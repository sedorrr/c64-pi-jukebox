"""The network watcher against a fake nmcli: cable, known WLAN, own access point (subnet away from the Picos'),
requests from the page."""
import json
import os

from c64jukebox import netwatch
from c64jukebox.netwatch import NetWatch, choose_ap, split_terse


class FakeNM:
    def __init__(self):
        self.eth = False
        self.wifi_con = ""             # active WLAN connection name
        self.radio = False
        self.air = []                  # (ssid, signal)
        self.saved = {"Heim": "MeinWLAN"}  # connection name -> ssid
        self.ap = None
        self.calls = []
        self.connect_ok = True
        self.carrier = False           # a cable with link (party mode)
        self.party_eth = None          # the party cable connection that was added / brought up
        self.psk = {"Heim": "heimgeheim"}   # saved WLAN passwords (nmcli -s)

    def __call__(self, cmd, timeout=30):
        self.calls.append(cmd)
        a = cmd[1:]
        if a[:1] == ["-w"]:                       # nmcli -w <seconds> ...
            a = a[2:]
        if a[:4] == ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]:
            w_state = "connected" if (self.wifi_con or self.ap) else ("disconnected" if self.radio else "unavailable")
            con = self.wifi_con or ("c64pi-ap" if self.ap else "")
            e_state, e_con = ("connected", "Wired") if self.eth else (("connected", "c64pi-party-eth") if self.party_eth == "up"
                                                                     else ("connecting" if self.carrier else "unavailable", ""))
            return 0, "eth0:ethernet:%s:%s\nwlan0:wifi:%s:%s\nlo:loopback:connected (externally):lo\n" % (
                e_state, e_con, w_state, con)
        if a[:3] == ["-t", "-g", "IP4.ADDRESS"]:
            return 0, ("192.168.1.78/24" if a[-1] == "eth0" else "192.168.1.77/24") + "\n"
        if a[:2] == ["-g", "WIRED-PROPERTIES.CARRIER"]:
            return 0, "on\n" if (self.carrier or self.eth) else "off\n"
        if a[:3] == ["-s", "-g", "802-11-wireless-security.psk"]:
            return 0, self.psk.get(a[-1], "") + "\n"
        if a == ["radio", "wifi"]:
            return 0, "enabled\n" if self.radio else "disabled\n"
        if a[:2] == ["radio", "wifi"]:
            self.radio = a[2] == "on"
            return 0, ""
        if a[:4] == ["-t", "-f", "NAME,TYPE", "connection"]:
            lines = ["Wired:802-3-ethernet"] + ["%s:802-11-wireless" % n.replace(":", "\\:") for n in self.saved]
            if self.ap:
                lines.append("c64pi-ap:802-11-wireless")
            return 0, "\n".join(lines) + "\n"
        if a[:3] == ["-t", "-g", "802-11-wireless.ssid,802-11-wireless.mode"]:
            return 0, self.saved.get(a[-1], "").replace(":", "\\:") + "\ninfrastructure\n"
        if a[:3] == ["-t", "-g", "802-11-wireless.ssid"]:
            return 0, self.saved.get(a[-1], a[-1]).replace(":", "\\:") + "\n"
        if a[:5] == ["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi"]:
            if self.ap:                           # NetworkManager does not scan while an access point runs
                return 0, ""
            return 0, "".join("%s:%d:WPA2\n" % (s.replace(":", "\\:"), sig) for s, sig in self.air)
        if a[:3] == ["-t", "-g", "802-11-wireless.ssid,ipv4.addresses"]:
            return (0, "%s\n%s\n" % (self.ap["ssid"], self.ap["ip"])) if self.ap else (10, "no such connection")
        if a[:2] == ["connection", "up"]:
            if a[2] == "c64pi-party-eth":
                self.party_eth = "up"
                return 0, ""
            if a[2] == "c64pi-ap":
                self.ap = self.ap_pending
                return 0, ""
            if self.connect_ok and self.saved.get(a[2]) in [s for s, _ in self.air] and not self.ap:
                self.wifi_con = a[2]
                return 0, ""
            return 4, "Error: Connection activation failed"
        if a[:2] == ["connection", "down"]:
            if a[2] == "c64pi-party-eth":
                self.party_eth = "added"
            if a[2] == "c64pi-ap":
                self.ap = None
            return 0, ""
        if a[:2] == ["connection", "delete"]:
            self.saved.pop(a[2], None)
            return 0, ""
        if a[:2] == ["connection", "add"] and "ethernet" in a:
            self.party_eth = "added"
            self.party_add = a
            return 0, ""
        if a[:2] == ["connection", "add"]:
            self.ap_pending = {"ssid": a[a.index("ssid") + 1], "ip": a[a.index("ipv4.addresses") + 1], "pw": a[-1]}
            return 0, ""
        if a[:3] == ["device", "wifi", "connect"]:
            ssid = a[3]
            if "password" in a and a[a.index("password") + 1] == "falsch":
                return 4, "Error: Secrets were required, but not provided."
            self.saved[ssid] = ssid
            self.wifi_con = ssid
            return 0, ""
        return 1, "unknown " + " ".join(cmd)


def make(tmp_path, nm, cfg=None):
    t = [1000.0]
    conf = tmp_path / "config.json"
    conf.write_text(json.dumps(cfg or {"name": "c64pi"}))
    w = NetWatch(runner=nm, clock=lambda: t[0], run_dir=str(tmp_path / "run"), config=str(conf))
    w.sleep = lambda s: None
    return w, t


def state(tmp_path):
    return json.loads((tmp_path / "run" / "net.json").read_text())


def test_terse_and_choice():
    assert split_terse("Paul\\:a:80:WPA2") == ["Paul:a", "80", "WPA2"]
    assert choose_ap([], "C64-Jukebox") == ("C64-Jukebox", 4)
    assert choose_ap(["C64-Visualizer", "Heim"], "C64-Jukebox") == ("C64-Jukebox", 5)       # a Pico AP uses .4
    assert choose_ap(["C64-Audio-wohnzimmer", "C64-Jukebox"], "C64-Jukebox") == ("C64-Jukebox-2", 6)


def test_cable_and_wlan(tmp_path):
    nm = FakeNM()
    nm.eth = True
    w, t = make(tmp_path, nm)
    w.tick()
    s = state(tmp_path)
    assert s["mode"] == "lan" and s["eth_ip"] == "192.168.1.78" and s["ap"] is None
    nm.eth, nm.radio, nm.wifi_con = False, True, "Heim"
    w.tick()
    s = state(tmp_path)
    assert s["mode"] == "wlan" and s["wlan_ssid"] == "MeinWLAN" and s["wlan_ip"] == "192.168.1.77"


def test_access_point_and_back(tmp_path):
    nm = FakeNM()
    nm.air = [("C64-Visualizer", 60), ("Nachbar", 40)]
    w, t = make(tmp_path, nm, {"name": "c64pi", "wlan": {"ap_pw": "geheim123"}})
    w.tick()
    assert state(tmp_path)["mode"] == "none" and not nm.ap               # no access point right after the start
    t[0] += 100
    w.tick()
    s = state(tmp_path)
    assert nm.radio and s["mode"] == "ap"
    assert s["ap"] == {"ssid": "C64-Jukebox", "pw": "geheim123", "ip": "192.168.5.1"}   # .4 is the Pico's
    assert nm.ap["ip"] == "192.168.5.1/24"
    # every 5 minutes it looks for the home WLAN - not while the page is used
    nm.air.append(("MeinWLAN", 70))
    os.utime(str(tmp_path / "run"), None)
    (tmp_path / "run" / "web").write_text("")
    t[0] += 301
    w.tick()
    assert state(tmp_path)["mode"] == "ap"
    os.utime(str(tmp_path / "run" / "web"), (0, 0))
    t[0] += 301
    w.tick()                                                              # finds MeinWLAN, AP goes down, connects
    w.tick()
    s = state(tmp_path)
    assert s["mode"] == "wlan" and s["ap"] is None and nm.wifi_con == "Heim"


def test_cable_ends_access_point_and_restores_radio(tmp_path):
    nm = FakeNM()
    w, t = make(tmp_path, nm)
    w.tick()
    t[0] += 100
    w.tick()
    assert state(tmp_path)["mode"] == "ap" and nm.radio
    nm.eth = True
    w.tick()
    s = state(tmp_path)
    assert s["mode"] == "lan" and nm.ap is None and not nm.radio          # the radio was off before: off again


def test_switched_off_access_point(tmp_path):
    nm = FakeNM()
    w, t = make(tmp_path, nm, {"wlan": {"ap": False}})
    t[0] += 100
    w.tick()
    assert state(tmp_path)["mode"] == "none" and not nm.ap and not nm.radio


def test_requests_from_the_page(tmp_path):
    nm = FakeNM()
    nm.eth = True
    nm.air = [("MeinWLAN", 70), ("Gast:WLAN", 30)]
    w, t = make(tmp_path, nm)
    w.tick()
    run = tmp_path / "run"
    (run / "request.json").write_text(json.dumps({"id": "a1", "action": "scan"}))
    w.tick()
    s = state(tmp_path)
    assert s["last"] == {"id": "a1", "ok": True, "msg": "2 WLANs gefunden"}
    assert [x["ssid"] for x in s["scan"]] == ["MeinWLAN", "Gast:WLAN"] and not (run / "request.json").exists()
    (run / "request.json").write_text(json.dumps({"id": "a2", "action": "connect", "ssid": "Gast:WLAN", "pw": "falsch"}))
    w.tick()
    assert state(tmp_path)["last"]["ok"] is False and "Secrets" in state(tmp_path)["last"]["msg"]
    (run / "request.json").write_text(json.dumps({"id": "a3", "action": "connect", "ssid": "Gast:WLAN", "pw": "richtig1"}))
    w.tick()
    assert state(tmp_path)["last"] == {"id": "a3", "ok": True, "msg": "verbunden mit Gast:WLAN"}
    (run / "request.json").write_text(json.dumps({"id": "a4", "action": "forget", "ssid": "Gast:WLAN"}))
    w.tick()
    assert state(tmp_path)["last"]["ok"] and "Gast:WLAN" not in nm.saved


def test_settings_defaults(tmp_path):
    w, _ = make(tmp_path, FakeNM(), {"name": "wohnzimmer", "wlan": {"ap_pw": "kurz"}})
    assert w.settings() == {"ap": True, "ssid": "C64-Jukebox-wohnzimmer", "pw": "commodore64",    # WPA2 needs 8+
                            "party": {"on": False, "ssid": "", "pw": ""}}
    assert netwatch.SUBNETS[0] == 4


def test_ap_is_down_for_the_scan_and_comes_back(tmp_path):
    """NetworkManager does not scan while the access point runs: it goes down, and up again if nothing is found"""
    nm = FakeNM()
    w, t = make(tmp_path, nm)
    w.tick()
    t[0] += 100
    w.tick()
    assert nm.ap
    os.makedirs(str(tmp_path / "run"), exist_ok=True)
    t[0] += 301
    w.tick()                                           # nothing known in the air: access point again
    assert nm.ap and state(tmp_path)["mode"] == "ap"
    downs = [c for c in nm.calls if c[1:3] == ["connection", "down"]]
    assert downs                                        # it was taken down for the scan
    nm.air.append(("MeinWLAN", 70))
    t[0] += 301
    w.tick()
    w.tick()
    assert state(tmp_path)["mode"] == "wlan" and not nm.ap


def test_failed_connect_from_the_ap_brings_it_back(tmp_path):
    nm = FakeNM()
    w, t = make(tmp_path, nm)
    w.tick()
    t[0] += 100
    w.tick()
    assert nm.ap
    (tmp_path / "run" / "request.json").write_text(json.dumps({"id": "x", "action": "connect", "ssid": "Fremd", "pw": "falsch"}))
    w.tick()
    s = state(tmp_path)
    assert s["last"]["ok"] is False and nm.ap and s["mode"] == "ap"


def test_restart_adopts_the_running_ap(tmp_path):
    nm = FakeNM()
    nm.radio = True
    nm.ap = {"ssid": "C64-Jukebox", "ip": "192.168.5.1/24", "pw": "commodore64"}
    w, t = make(tmp_path, nm)
    w.tick()
    s = state(tmp_path)
    assert s["mode"] == "ap" and s["ap"]["ip"] == "192.168.5.1" and s["ap"]["ssid"] == "C64-Jukebox"
    nm.eth = True
    w.tick()
    assert nm.ap is None and state(tmp_path)["mode"] == "lan"            # the cable ends it


def test_ssid_with_colon_connects(tmp_path):
    nm = FakeNM()
    nm.saved = {"Gast": "Gast:WLAN"}
    nm.air = [("Gast:WLAN", 50)]
    w, t = make(tmp_path, nm)
    w.tick()
    t[0] += 100
    w.tick()
    assert nm.wifi_con == "Gast" and not nm.ap


PARTY = {"name": "c64pi", "party": {"on": True, "ssid": "MeinWLAN", "pw": ""}}


def test_party_away_from_home(tmp_path):
    """away: AP under the home WLAN's name with its saved password (never shown), the cable hands out the one address
    for the Ultimate only after no router answered for 40 s"""
    nm = FakeNM()
    nm.carrier = True                                         # the Ultimate on the cable, no router
    w, t = make(tmp_path, nm, PARTY)
    t[0] += 16
    w.tick()
    s = state(tmp_path)
    assert s["mode"] == "party" and s["party"]["state"] == "aktiv" and s["party"]["ssid"] == "MeinWLAN"
    assert nm.ap["ssid"] == "MeinWLAN" and nm.ap["pw"] == "heimgeheim"         # the saved password of "Heim"
    assert s["ap"]["pw"] == "wie zu Hause" and "heimgeheim" not in json.dumps(s)
    assert nm.party_eth is None                                # the cable: not yet (a router may still answer)
    t[0] += 41
    w.tick()
    s = state(tmp_path)
    assert nm.party_eth == "up" and s["party"]["u64"] == "10.64.64.2" and s["party"]["eth"]
    add = nm.party_add
    assert add[add.index("ipv4.shared-dhcp-range") + 1] == "10.64.64.2,10.64.64.2"   # exactly one address
    assert add[add.index("ipv4.method") + 1] == "shared"
    # the cable is pulled: our DHCP stops at once; plugged in again: the 40 s start anew
    nm.carrier = False
    w.tick()
    assert nm.party_eth == "added" and not state(tmp_path)["party"]["eth"]
    nm.carrier = True
    t[0] += 5
    w.tick()
    assert nm.party_eth == "added"
    t[0] += 41
    w.tick()
    assert nm.party_eth == "up"


def test_party_stays_quiet_at_home(tmp_path):
    """at home the party mode never hands out addresses: cable with a router's address, or the home WLAN in range"""
    nm = FakeNM()
    nm.eth = True                                              # the home router gave the cable an address
    w, t = make(tmp_path, nm, PARTY)
    t[0] += 100
    w.tick()
    s = state(tmp_path)
    assert s["mode"] == "lan" and s["party"]["state"] == "wartet" and nm.party_eth is None and not nm.ap
    nm.eth = False                                             # no cable, but the home WLAN is in the air
    nm.air = [("MeinWLAN", 70)]
    t[0] += 100
    w.tick()
    s = state(tmp_path)
    assert s["party"]["why"] == "Heim-WLAN in Reichweite" and (nm.ap is None or nm.ap["ssid"] != "MeinWLAN")
    # switched off: the party connections go down
    w2, t2 = make(tmp_path, nm, {"name": "c64pi"})
    w2.party_eth = True
    t2[0] += 1
    w2.tick()
    assert state(tmp_path)["party"]["state"] == "aus" and nm.party_eth != "up"
