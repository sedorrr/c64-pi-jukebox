"""Network watcher for the Pi (runs as root, service c64pi-net, only the standard library + nmcli of NetworkManager).

- Cable or a known WLAN: nothing to do.
- Neither for 60 s (90 s after boot): scan; a saved WLAN in range -> connect; otherwise open an own access point
  "C64-Jukebox[-<name>]" (WPA2, password from the settings, default "commodore64"), the page then at http://<ip>/.
- Before opening it: which C64 access points are already in the air? The Picos' own access points ("C64-Visualizer...",
  "C64-Audio...") use 192.168.4.1. The Pi takes the first of 192.168.4/5/6/... that none of them uses, and a different
  SSID when its own name is already taken - so a phone never ends up in a second network with the same addresses.
- In the access point: every 5 minutes (not while somebody used the page in the last 5 minutes) look for a saved WLAN
  again; cable plugged in -> access point off at once (and the radio off again if it was off before).

Party mode (settings "party": on, ssid, pw - pw empty = from the saved connection of that WLAN): away from home the Pi
opens its access point under the name and password of the home WLAN, so the Picos and phones join by themselves, and
hands out ONE address on the cable (10.64.64.2, for the Ultimate). It stays quiet while the home WLAN is in range or
the cable got an address from a router (at home), and only serves the cable after its own DHCP request found no server
for PARTY_DHCP_WAIT_S since the cable was plugged in; pulling the cable stops it at once.

State for the jukebox (display, web page): /run/c64pi/net.json. The jukebox asks for things (scan, connect to a WLAN,
forget one) by writing /run/c64pi/request.json; the answer lands in net.json "last"."""
import json
import os
import subprocess
import sys
import time

from .i18n import set_lang, tr

RUN_DIR = "/run/c64pi"
CONFIG = "/var/lib/c64jukebox/config.json"
CON_AP = "c64pi-ap"
SUBNETS = [4, 5, 6, 7, 8, 9]          # 192.168.<n>.1
PICO_AP_PREFIXES = ("C64-Visualizer", "C64-Audio")
OUR_PREFIX = "C64-Jukebox"
NO_NET_S = 60
BOOT_GRACE_S = 90
AP_RETRY_S = 300
WEB_RECENT_S = 300
WAIT_S = "40"                         # nmcli -w: below the 60 s the subprocess may take
CON_PARTY_ETH = "c64pi-party-eth"
PARTY_ETH_IP = "10.64.64.1"
PARTY_U64_IP = "10.64.64.2"           # the one address on the cable: the Ultimate
PARTY_DHCP_WAIT_S = 40                # no router answered on the cable for so long -> we hand out the address
SAVED_EVERY_S = 60


def run(cmd, timeout=30):
    """nmcli & co.: (returncode, stdout)"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + (p.stderr if p.returncode else "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def split_terse(line):
    """nmcli -t line: fields separated by ':', '\\:' is a colon inside a field"""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def unesc(s):
    """values of `nmcli -g` keep the terse escaping: a colon comes as backslash-colon"""
    out, esc = "", False
    for ch in s or "":
        if esc:
            out += ch
            esc = False
        elif ch == "\\":
            esc = True
        else:
            out += ch
    return out


def choose_ap(visible, base_ssid):
    """-> (ssid, subnet n) for our access point, given the SSIDs in the air"""
    used = set()
    pico = any(s.startswith(PICO_AP_PREFIXES) for s in visible)
    if pico:
        used.add(4)
    others = sorted(s for s in visible if s.startswith(OUR_PREFIX))
    n_free = [n for n in SUBNETS if n not in used]
    # every other Pi already in the air took one subnet (the first free ones, in the same order)
    taken = len(others)
    subnet = n_free[min(taken, len(n_free) - 1)]
    ssid = base_ssid
    k = 2
    while ssid in visible:
        ssid = "%s-%d" % (base_ssid, k)
        k += 1
    return ssid, subnet


class NetWatch:
    def __init__(self, runner=run, clock=time.monotonic, run_dir=RUN_DIR, config=CONFIG):
        self.run, self.clock, self.dir, self.config_path = runner, clock, run_dir, config
        self.sleep = time.sleep
        self.start = clock()
        self.no_net_since = None
        self.mode = "none"
        self.ap = None                    # {"ssid", "pw", "ip"} while our access point is up
        self.radio_was_off = False
        self.next_try = 0.0
        self.last = None
        self.scan_list = []
        self.info = {}
        self.carrier_since = None         # since when the cable has a link (party mode)
        self.party_eth = False            # our DHCP on the cable is up
        self.party = {"state": "aus"}
        self.saved_at = -1e9

    # ------------------------------------------------------------ settings and files
    def settings(self):
        try:
            with open(self.config_path, encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, ValueError):
            c = {}
        set_lang(c.get("lang") or "de")         # the texts for the page and the display (net.json) in its language
        w = c.get("wlan") or {}
        name = c.get("name") or "c64pi"
        base = OUR_PREFIX if name == "c64pi" else "%s-%s" % (OUR_PREFIX, name)
        pw = w.get("ap_pw") or "commodore64"
        p = c.get("party") or {}
        return {"ap": w.get("ap", True), "ssid": (w.get("ap_ssid") or base)[:32], "pw": pw if len(pw) >= 8 else "commodore64",
                "party": {"on": bool(p.get("on")), "ssid": str(p.get("ssid") or "")[:32], "pw": str(p.get("pw") or "")}}

    def write_state(self):
        os.makedirs(self.dir, exist_ok=True)
        d = dict(self.info, mode=self.mode, ap=self.ap, last=self.last, scan=self.scan_list, party=self.party, t=time.time())
        tmp = os.path.join(self.dir, "net.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(self.dir, "net.json"))

    def web_recent(self):
        """the jukebox touches /run/c64pi/web whenever the page is used"""
        try:
            return time.time() - os.path.getmtime(os.path.join(self.dir, "web")) < WEB_RECENT_S
        except OSError:
            return False

    # ------------------------------------------------------------ what NetworkManager says
    def devices(self):
        """{"eth0": {"state", "con"}, "wlan0": {...}}"""
        rc, out = self.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
        devs = {}
        for line in out.splitlines() if rc == 0 else []:
            f = split_terse(line)
            if len(f) >= 4 and f[1] in ("ethernet", "wifi"):
                devs[f[0]] = {"type": f[1], "state": f[2], "con": f[3]}
        return devs

    def ip_of(self, dev):
        rc, out = self.run(["nmcli", "-t", "-g", "IP4.ADDRESS", "device", "show", dev])
        if rc:
            return ""
        a = out.strip().split("|")[0].strip()
        return a.split("/")[0]

    def radio_on(self):
        rc, out = self.run(["nmcli", "radio", "wifi"])
        return rc == 0 and out.strip() == "enabled"

    def saved_wifi(self):
        """SSIDs of the saved WLAN connections (not our access point)"""
        rc, out = self.run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
        names = []
        for line in out.splitlines() if rc == 0 else []:
            f = split_terse(line)
            if len(f) >= 2 and f[1] in ("802-11-wireless", "wifi") and f[0] != CON_AP:
                names.append(f[0])
        ssids = {}
        for n in names:
            rc, s = self.run(["nmcli", "-t", "-g", "802-11-wireless.ssid,802-11-wireless.mode", "connection", "show", n])
            parts = [unesc(x) for x in s.strip().splitlines()]
            if rc == 0 and parts and (len(parts) < 2 or parts[1] != "ap"):
                ssids[parts[0]] = n
        return ssids

    def scan(self):
        """[{"ssid", "signal", "sec"}], strongest first. NetworkManager refuses to scan while our access point runs:
        callers take it down first (look_around)."""
        rc, out = self.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
                           timeout=30)
        best = {}
        for line in out.splitlines() if rc == 0 else []:
            f = split_terse(line)
            if len(f) >= 3 and f[0]:
                sig = int(f[1]) if f[1].isdigit() else 0
                if f[0] not in best or sig > best[f[0]]["signal"]:
                    best[f[0]] = {"ssid": f[0], "signal": sig, "sec": f[2]}
        return sorted(best.values(), key=lambda x: -x["signal"])

    # ------------------------------------------------------------ actions
    def ensure_radio(self):
        if not self.radio_on():
            self.radio_was_off = True
            self.run(["nmcli", "radio", "wifi", "on"])
            self.sleep(3)

    def carrier(self, dev):
        rc, out = self.run(["nmcli", "-g", "WIRED-PROPERTIES.CARRIER", "device", "show", dev])
        return rc == 0 and out.strip() == "on"

    def saved_psk(self, ssid):
        """the password of the saved WLAN with this name (we run as root; it never goes to the page)"""
        con = self.saved_wifi().get(ssid)
        if not con:
            return ""
        rc, out = self.run(["nmcli", "-s", "-g", "802-11-wireless-security.psk", "connection", "show", con])
        return unesc(out.strip()) if rc == 0 else ""

    def start_ap(self, visible, party=None):
        s = self.settings()
        if party:                                      # the home WLAN's name and password, exactly
            ssid, n = choose_ap([], party["ssid"])
            n = choose_ap([v["ssid"] for v in visible], "x")[1]
            s = dict(s, pw=party["pw"])
        else:
            ssid, n = choose_ap([v["ssid"] for v in visible], s["ssid"])
        ip = "192.168.%d.1" % n
        self.run(["nmcli", "connection", "delete", CON_AP])
        rc, out = self.run(["nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0", "con-name", CON_AP,
                            "autoconnect", "no", "ssid", ssid, "mode", "ap", "802-11-wireless.band", "bg",
                            "ipv4.method", "shared", "ipv4.addresses", ip + "/24", "ipv6.method", "disabled",
                            "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", s["pw"]])
        if rc == 0:
            rc, out = self.run(["nmcli", "-w", WAIT_S, "connection", "up", CON_AP], timeout=60)
        if rc == 0:
            self.ap = {"ssid": ssid, "pw": s["pw"], "ip": ip}
            self.mode = "ap"
            self.log("Zugangspunkt %s an (%s)" % (ssid, ip))
        else:
            self.log("Zugangspunkt ging nicht: " + out.strip()[:200])
        return rc == 0

    def stop_ap(self, why):
        if self.ap:
            self.run(["nmcli", "connection", "down", CON_AP])
            self.log("Zugangspunkt aus (%s)" % why)
            self.ap = None
            if self.radio_was_off and why == "Kabel":
                self.run(["nmcli", "radio", "wifi", "off"])
                self.radio_was_off = False

    def adopt_ap(self, wifi):
        """the watcher was restarted while its access point runs: take it over again"""
        if self.ap or wifi.get("con") != CON_AP:
            return
        rc, out = self.run(["nmcli", "-t", "-g", "802-11-wireless.ssid,ipv4.addresses", "connection", "show", CON_AP])
        parts = [unesc(x) for x in out.strip().splitlines()] if rc == 0 else []
        if len(parts) >= 2:
            s = self.settings()
            party = s["party"]["on"] and parts[0] == s["party"]["ssid"]
            self.ap = {"ssid": parts[0], "pw": tr("wie zu Hause") if party else s["pw"], "ip": parts[1].split("/")[0]}
            if party:
                self.ap["party"] = True
            self.next_try = self.clock() + AP_RETRY_S
            self.log("Zugangspunkt %s übernommen" % parts[0])
        else:
            self.run(["nmcli", "connection", "down", CON_AP])

    def try_known(self, visible):
        """a saved WLAN in range? -> connect (the access point must be down already)"""
        saved = self.saved_wifi()
        for v in visible:
            con = saved.get(v["ssid"])
            if con:
                rc, out = self.run(["nmcli", "-w", WAIT_S, "connection", "up", con], timeout=60)
                if rc == 0:
                    self.log("verbunden mit " + v["ssid"])
                    return True
                self.log("Verbinden mit %s ging nicht: %s" % (v["ssid"], out.strip()[:120]))
        return False

    def look_around(self, connect=True):
        """scan (and connect to a known WLAN); our access point goes down for it - NetworkManager does not scan
        while it runs - and comes back when nothing better was found"""
        had_ap = self.ap is not None
        if had_ap:
            self.run(["nmcli", "connection", "down", CON_AP])
            self.sleep(2)
        visible = self.scan()
        self.scan_list = visible
        if connect and self.try_known(visible):
            if had_ap:
                self.log("Zugangspunkt aus (bekanntes WLAN)")
            self.ap = None
            return visible, True
        if had_ap:
            self.ap = None
            self.start_ap(visible)
        return visible, False

    # ------------------------------------------------------------ party mode
    def party_eth_up(self):
        self.run(["nmcli", "connection", "delete", CON_PARTY_ETH])
        rc, out = self.run(["nmcli", "connection", "add", "type", "ethernet", "ifname", "eth0", "con-name", CON_PARTY_ETH,
                            "autoconnect", "no", "ipv4.method", "shared", "ipv4.addresses", PARTY_ETH_IP + "/24",
                            "ipv4.shared-dhcp-range", "%s,%s" % (PARTY_U64_IP, PARTY_U64_IP), "ipv6.method", "disabled"])
        if rc == 0:
            rc, out = self.run(["nmcli", "-w", WAIT_S, "connection", "up", CON_PARTY_ETH], timeout=60)
        self.party_eth = rc == 0
        self.log("Party: Kabel gibt %s aus" % PARTY_U64_IP if rc == 0 else "Party: Kabel ging nicht: " + out.strip()[:160])

    def party_eth_down(self, why):
        if self.party_eth:
            self.run(["nmcli", "connection", "down", CON_PARTY_ETH])
            self.party_eth = False
            self.log("Party: Kabel aus (%s)" % why)

    def party_tick(self, now, devs, eth_name, wifi):
        """-> True while party mode runs the network, False at home (the normal rules apply)"""
        p = self.settings()["party"]
        eth = devs.get(eth_name, {})
        if eth.get("state") == "connected" and eth.get("con") != CON_PARTY_ETH:
            self.party_eth_down("Heimnetz am Kabel")
            self.stop_ap("Heimnetz am Kabel") if self.ap and self.ap.get("party") else None
            self.party = {"state": "wartet", "why": tr("Kabel-Netz eines Routers")}
            return False
        if wifi.get("state") == "connected" and wifi.get("con") not in ("", CON_AP):
            self.party = {"state": "wartet", "why": tr("mit dem WLAN verbunden")}
            return False
        if not p["ssid"]:
            self.party = {"state": "wartet", "why": tr("kein WLAN-Name eingestellt")}
            return False
        # the cable: hand out the one address only when no router answered for a while since it was plugged in
        if self.carrier(eth_name):
            if self.carrier_since is None:
                self.carrier_since = now
            if not self.party_eth and now - self.carrier_since >= PARTY_DHCP_WAIT_S:
                self.party_eth_up()
        else:
            self.carrier_since = None
            self.party_eth_down("Kabel gezogen")
        # the access point under the home WLAN's name (scan once before: is the home WLAN here after all?)
        if not self.ap and now >= self.next_try and now - self.start >= 15:
            self.next_try = now + 60
            self.ensure_radio()
            visible, _ = self.look_around(connect=False)
            if any(v["ssid"] == p["ssid"] for v in visible):
                self.party = {"state": "wartet", "why": tr("Heim-WLAN in Reichweite")}
                return False
            pw = p["pw"] or self.saved_psk(p["ssid"])
            if len(pw) < 8:
                self.party = {"state": "fehler", "why": tr("kein Passwort für %s gespeichert") % p["ssid"]}
                return True
            if self.start_ap(visible, {"ssid": p["ssid"], "pw": pw}):
                self.ap.update(party=True, pw=tr("wie zu Hause"))   # the home password never goes to the page/display
        self.mode = "party"
        self.party = {"state": "aktiv" if self.ap else "startet", "ssid": p["ssid"], "ap_ip": (self.ap or {}).get("ip", ""),
                      "eth": self.party_eth, "u64": PARTY_U64_IP if self.party_eth else ""}
        return True

    def log(self, msg):
        print(msg, flush=True)
        self.info["log"] = (self.info.get("log", []) + [time.strftime("%H:%M:%S ") + msg])[-20:]

    # ------------------------------------------------------------ requests from the page
    def handle_request(self):
        p = os.path.join(self.dir, "request.json")
        try:
            with open(p, encoding="utf-8") as f:
                req = json.load(f)
            os.remove(p)
        except (OSError, ValueError):
            return
        act, rid = req.get("action"), req.get("id")
        ok, msg = False, ""
        if act == "scan":
            self.ensure_radio()
            self.look_around(connect=False)
            ok, msg = True, tr("%d WLANs gefunden") % len(self.scan_list)
        elif act == "connect" and req.get("ssid"):
            self.ensure_radio()
            had_ap = self.ap is not None
            if had_ap:
                self.run(["nmcli", "connection", "down", CON_AP])
                self.sleep(2)
            cmd = ["nmcli", "-w", WAIT_S, "device", "wifi", "connect", req["ssid"], "ifname", "wlan0"]
            if req.get("pw"):
                cmd += ["password", req["pw"]]
            rc, out = self.run(cmd, timeout=60)
            ok = rc == 0
            msg = tr("verbunden mit %s") % req["ssid"] if ok else tr("Verbinden ging nicht: %s") % out.strip()[:200]
            if ok:
                self.ap = None
                self.radio_was_off = False
            elif had_ap:                                   # back to the access point at once
                self.ap = None
                self.start_ap(self.scan_list)
        elif act == "forget" and req.get("ssid"):
            con = self.saved_wifi().get(req["ssid"])
            if con:
                rc, out = self.run(["nmcli", "connection", "delete", con])
                ok, msg = rc == 0, tr("vergessen") if rc == 0 else out.strip()[:200]
            else:
                msg = tr("nicht gespeichert")
        else:
            msg = tr("unbekannte Anfrage")
        self.last = {"id": rid, "ok": ok, "msg": msg}
        self.log(msg)

    # ------------------------------------------------------------ one look around (every few seconds)
    def tick(self):
        self.settings()                          # first: the language of the answer to a request (set_lang)
        self.handle_request()
        now = self.clock()
        devs = self.devices()
        eth = next((d for n, d in devs.items() if d["type"] == "ethernet" and d["state"] == "connected"), None)
        wifi_name = next((n for n, d in devs.items() if d["type"] == "wifi"), "wlan0")
        wifi = devs.get(wifi_name, {})
        self.adopt_ap(wifi)
        eth_name = next((n for n, d in devs.items() if d["type"] == "ethernet"), "eth0")
        self.info.update({"eth": bool(eth), "eth_ip": self.ip_of(eth_name) if eth else "",
                          "wlan_ssid": "", "wlan_ip": "", "radio": self.radio_on()})
        if now - self.saved_at >= SAVED_EVERY_S:            # the saved WLANs, for the party mode's choice
            self.saved_at = now
            self.info["saved"] = sorted(self.saved_wifi())
        if self.settings()["party"]["on"]:
            if self.party_tick(now, devs, eth_name, wifi):
                self.write_state()
                return
        else:
            self.party = {"state": "aus"}
            self.party_eth_down("Party-Modus aus")
            if self.ap and self.ap.get("party"):
                self.stop_ap("Party-Modus aus")
        if eth and eth.get("con") == CON_PARTY_ETH:
            eth = None                                         # our own party cable is no home network
        if eth:
            self.no_net_since = None
            self.stop_ap("Kabel")
            self.mode = "lan"
        elif wifi.get("state") == "connected" and wifi.get("con") and wifi.get("con") != CON_AP:
            self.no_net_since = None
            self.mode = "wlan"
            self.info["wlan_ip"] = self.ip_of(wifi_name)
            rc, out = self.run(["nmcli", "-t", "-g", "802-11-wireless.ssid", "connection", "show", wifi["con"]])
            self.info["wlan_ssid"] = unesc(out.strip()) if rc == 0 else wifi["con"]
        elif self.ap:
            self.mode = "ap"
            if now >= self.next_try and not self.web_recent():
                self.next_try = now + AP_RETRY_S
                self.look_around()
        else:
            self.mode = "none"
            if self.no_net_since is None:
                self.no_net_since = now
            waited = now - self.no_net_since
            if waited >= NO_NET_S and now - self.start >= BOOT_GRACE_S and now >= self.next_try:
                self.next_try = now + 30
                if not self.settings()["ap"]:
                    pass
                else:
                    self.ensure_radio()
                    visible, connected = self.look_around()
                    if not connected and self.start_ap(visible):
                        self.next_try = now + AP_RETRY_S
        self.write_state()


def main():
    w = NetWatch()
    while True:
        try:
            w.tick()
        except Exception as e:                  # never stop watching
            print("Fehler:", e, file=sys.stderr, flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
