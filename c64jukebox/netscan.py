"""Search the home network (the /24 of the Pi's own address) for computers with shares (SMB 445, FTP 21) and for
Ultimates (HTTP + GET /v1/info, "product" contains "Ultimate"). An Ultimate answers on its Ethernet and its WLAN
address; it is listed once, with the Ethernet address (the Ultimates stream over Ethernet only), the other one as
"alt" - told apart by the MAC in the ARP table: equal to "wifi_mac" of /v1/info = WLAN, otherwise Ethernet."""
import asyncio
import socket

import aiohttp

PORTS = {"smb": 445, "ftp": 21, "http": 80}


def arp_table(path="/proc/net/arp"):
    out = {}
    try:
        with open(path) as f:
            next(f, None)
            for line in f:
                p = line.split()
                if len(p) >= 4 and p[3] != "00:00:00:00:00:00":
                    out[p[0]] = p[3].lower()
    except OSError:
        pass
    return out


async def _open(host, port, timeout):
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        w.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def _rdns(ip):
    loop = asyncio.get_running_loop()
    try:
        name, _ = await asyncio.wait_for(loop.getnameinfo((ip, 0), socket.NI_NAMEREQD), 1.5)
        return "" if name == ip else name
    except (OSError, asyncio.TimeoutError):
        return ""


def _netbios(ip):
    try:
        from nmb.NetBIOS import NetBIOS
        nb = NetBIOS(broadcast=False)
        try:
            names = nb.queryIPForName(ip, timeout=1)
        finally:
            nb.close()
        return names[0] if names else ""
    except Exception:
        return ""


async def u64_info(session, host, port=80, timeout=2.5, passwords=("",)):
    """/v1/info of an Ultimate or None; an Ultimate with a network password answers only with it (403 without),
    so the passwords of the Ultimates already entered are tried as well"""
    for pw in passwords:
        try:
            async with session.get("http://%s:%d/v1/info" % (host, port), headers={"X-Password": pw} if pw else {},
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status in (401, 403):
                    continue
                if r.status != 200:
                    return None
                d = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
            return None
        if not isinstance(d, dict) or "ultimate" not in str(d.get("product", "")).lower():
            return None
        return d
    return None


def subnet_hosts(ip):
    base = ip.rsplit(".", 1)[0]
    return ["%s.%d" % (base, i) for i in range(1, 255) if "%s.%d" % (base, i) != ip]


def ip_key(ip):
    return tuple(int(x) if x.isdigit() else 0 for x in ip.split("."))


def label(e):
    """short text for a found host while the search runs"""
    what = [w for w, on in (("SMB", e["smb"]), ("FTP", e["ftp"])) if on]
    if e["u64"]:
        what.insert(0, str(e["u64"].get("product") or "Ultimate"))
    return "%s (%s)" % (e["ip"], ", ".join(what))


async def scan(session, hosts, ports=None, timeout=0.7, parallel=64, progress=None, arp=arp_table, passwords=()):
    """-> list of {"ip", "host" (DNS name or IP), "name" (for the eye), "smb", "ftp", "u64": {product, ...} or None,
    "alt": the other address of an Ultimate}

    progress(state) is called whenever something changes: {"pct": 0-100, "busy": addresses being checked right now
    (sorted), "found": short texts of what was found so far, "phase": "ports" or "names"}"""
    ports = ports or PORTS
    sem = asyncio.Semaphore(parallel)
    found = []
    busy = set()
    done = [0]
    total = max(1, len(hosts))

    def report(phase="ports", pct=None, now=None):
        if progress:
            progress({"pct": int(pct if pct is not None else 90 * done[0] / total), "phase": phase,
                      "busy": now if now is not None else sorted(busy, key=ip_key),
                      "found": [label(e) for e in sorted(found, key=lambda e: ip_key(e["ip"]))]})

    async def one(h):
        async with sem:
            busy.add(h)
            report()
            try:
                res = await asyncio.gather(*(_open(h, p, timeout) for p in ports.values()))
                got = dict(zip(ports.keys(), res))
                entry = None
                if any(got.values()):
                    entry = {"ip": h, "smb": got.get("smb", False), "ftp": got.get("ftp", False), "u64": None, "alt": ""}
                    if got.get("http"):
                        entry["u64"] = await u64_info(session, h, ports["http"], passwords=("",) + tuple(passwords))
                    if not (entry["smb"] or entry["ftp"] or entry["u64"]):
                        entry = None
                if entry:
                    found.append(entry)
            finally:
                busy.discard(h)
                done[0] += 1
                report()

    await asyncio.gather(*(one(h) for h in hosts))
    loop = asyncio.get_running_loop()
    for i, e in enumerate(found):
        report("names", 90 + 10 * i / max(1, len(found)), [e["ip"]])
        dns = await _rdns(e["ip"])
        e["host"] = dns or e["ip"]          # what goes into the settings: a name only when DNS knows it
        e["name"] = dns
        if not dns and e["smb"]:
            e["name"] = await loop.run_in_executor(None, _netbios, e["ip"])
        if e["u64"]:
            e["name"] = e["u64"].get("hostname") or e["name"]
    report("names", 100, [])
    # one entry per Ultimate, preferably the Ethernet address
    macs = arp()
    by_id = {}
    for e in found:
        u = e["u64"]
        if not u:
            continue
        uid = u.get("unique_id") or e["ip"]
        mac, wmac = macs.get(e["ip"], ""), str(u.get("wifi_mac", "")).lower()
        e["link"] = "wlan" if mac and wmac and mac == wmac else ("eth" if mac else "")
        by_id.setdefault(uid, []).append(e)
    drop = set()
    for group in by_id.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda e: 0 if e.get("link") == "eth" else 1)
        keep = group[0]
        keep["alt"] = ", ".join(g["ip"] for g in group[1:])
        for g in group[1:]:
            keep["smb"] = keep["smb"] or g["smb"]
            drop.add(g["ip"])
    found = [e for e in found if e["ip"] not in drop]
    found.sort(key=lambda e: ip_key(e["ip"]))
    return found
