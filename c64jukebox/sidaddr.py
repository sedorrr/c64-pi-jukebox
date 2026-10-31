"""SID addresses on the Ultimate, like "Auto-adjust SID addresses" of the PC jukebox (and the Pico's jukebox):
before a tune starts, its header says which SID addresses it needs ($D400, maybe $D420/$D500 ...). If exactly one of
them is missing on the Ultimate and exactly one SID *socket* is free (its address not needed by the tune), that
socket is switched to the missing address - only in the Ultimate's RAM (not saved there), and only the clear case.

Never an UltiSID (wish of the user); an address an UltiSID already provides counts as present. The original address
is written to a file *before* switching and restored when the next tune does not need it, on stop, when another
Ultimate is chosen and when the jukebox starts (after a power cut in the middle of a tune)."""
import json
import os
import re
import time
from urllib.parse import quote

from .i18n import tr
from .ultimate import UltimateError

CATEGORY = "SID Addressing"
SOCKET_RE = re.compile(r"^SID Socket (\d) Address$")
ADDR_RE = re.compile(r"^\$?([0-9A-Fa-f]{4})$")


def norm(a):
    """'d420', '$D420', 'D420' -> '$D420'; anything else (Unmapped, Disabled ...) -> None"""
    m = ADDR_RE.match(str(a or "").strip())
    return "$" + m.group(1).upper() if m else None


def plan(cfg, needed):
    """cfg: the "SID Addressing" items, needed: addresses of the tune -> (socket number, address) to switch, or None,
    and a reason for the page"""
    need = {norm(a) for a in needed} - {None}
    sockets = {int(SOCKET_RE.match(k).group(1)): norm(v) for k, v in cfg.items() if SOCKET_RE.match(k)}
    present = {norm(v) for v in cfg.values()} - {None}               # sockets and UltiSIDs
    missing = sorted(need - present)
    if not missing:
        return None, ""
    spare = [n for n, a in sorted(sockets.items()) if a and a not in need]
    if len(missing) > 1 or len(spare) != 1:
        return None, tr("SID-Adressen nicht eindeutig (fehlt %s) – nicht umgestellt") % ", ".join(missing)
    return (spare[0], missing[0]), ""


class SidAddressing:
    """pending: {Ultimate address: {"addr", "sock", "orig", "new"}} - one switched socket per Ultimate, kept in a file
    so a restore survives a restart. A record for an Ultimate that cannot be reached stays (and is tried again on
    stop and at the start), but never blocks switching on another one."""

    def __init__(self, path):
        self.path = path
        self.pending = self._load()
        self.msg = ""
        self.known = {}                      # the last read configuration (page: "SID-Adressen am Ultimate")
        self.known_addr = ""                 # ... of this Ultimate
        self.gen = 0                         # +1 on every switch/restore: a read that was running meanwhile is stale
        self.failed_at = {}                  # address -> when restoring there failed (not retried at once)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return {}
        if isinstance(d, dict) and d.get("sock"):                     # the first format: one record
            d = [d]
        recs = d.values() if isinstance(d, dict) else d if isinstance(d, list) else []
        return {r["addr"]: r for r in recs if isinstance(r, dict) and r.get("sock") and r.get("addr")}

    def _write(self, pending):
        """the file first, then the RAM copy (OSError: nothing changed)"""
        if pending:
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(list(pending.values()), f)
            os.replace(self.path + ".tmp", self.path)
            os.chmod(self.path, 0o600)                                # holds the network password
        else:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass
        self.pending = pending
        self.gen += 1

    def _forget(self, addr):
        try:
            self._write({a: r for a, r in self.pending.items() if a != addr})
        except OSError:
            self.pending.pop(addr, None)

    @staticmethod
    def _put(sock, value):
        """the path of one socket's address with its new value ("$" sent as %24, as the Pico does it)"""
        return "/v1/configs/SID%%20Addressing/SID%%20Socket%%20%d%%20Address?value=%s" % (sock, quote(value, safe=""))

    async def read(self, u, keep=True):
        d = await u.request("GET", "/v1/configs/SID%20Addressing", timeout=6, want_json=True)
        cfg = d.get(CATEGORY, d) if isinstance(d, dict) else {}
        cfg = {k: v for k, v in cfg.items() if k != "errors" and isinstance(v, str)}
        if keep:
            self.known, self.known_addr = cfg, u.addr
        return cfg

    def base(self):
        """the configuration as it is without our switch (what the list marks against)"""
        cfg = dict(self.known)
        p = self.pending.get(self.known_addr)
        if p and p.get("orig"):
            cfg["SID Socket %d Address" % p["sock"]] = p["orig"]
        return cfg

    def fit(self, needed, cfg=None):
        """like the PC jukebox's purple marking: None (configuration unknown), "ok", "fix" (one socket will be
        switched for it) or "no" (the Ultimate lacks an address and there is no clear fix)"""
        cfg = self.base() if cfg is None else cfg
        if not any(SOCKET_RE.match(k) for k in cfg):
            return None
        need = {norm(a) for a in needed or []} - {None}
        if not need - ({norm(v) for v in cfg.values()} - {None}):
            return "ok"
        return "fix" if plan(cfg, needed)[0] else "no"

    async def release(self, u_for, addr=None, others_of=None, wait_s=0):
        """restore switched sockets - of one Ultimate (addr), or of all except others_of; u_for(addr, pw) -> client
        (the password the switch was made with, so an edited entry does not matter). An Ultimate where restoring
        failed less than wait_s ago is left for later. -> True when nothing is left switched at addr"""
        todo = [addr] if addr is not None else [a for a in self.pending if a != others_of]
        for a in todo:
            p = self.pending.get(a)
            if not p:
                continue
            if not p.get("orig"):
                self._forget(a)
                continue
            if wait_s and time.monotonic() - self.failed_at.get(a, -1e9) < wait_s:
                continue
            try:
                await u_for(a, p.get("pw")).request("PUT", self._put(p["sock"], p["orig"]), timeout=6)
                self.msg = tr("Sockel %d zurück auf %s") % (p["sock"], p["orig"])
                if self.known_addr == a:
                    self.known["SID Socket %d Address" % p["sock"]] = p["orig"]
                self.failed_at.pop(a, None)
                self._forget(a)
            except UltimateError as e:
                self.failed_at[a] = time.monotonic()
                self.msg = tr("Zurückstellen fehlgeschlagen: %s") % e
        return addr is None or addr not in self.pending

    def rekey(self, old, new, pw):
        """an entry's address was changed on the page (same device): its record moves along"""
        p = self.pending.get(old)
        if p and new and new != old and new not in self.pending:
            rest = {a: r for a, r in self.pending.items() if a != old}
            rest[new] = dict(p, addr=new, pw=pw)
            try:
                self._write(rest)
            except OSError:
                self.pending = rest

    def drop_unknown(self, addrs):
        """forget records of Ultimates no longer entered (after a power cycle their RAM setting is gone anyway)"""
        for a in [a for a in self.pending if a not in addrs]:
            self._forget(a)

    async def prepare(self, u, needed, enabled, u_for):
        """before a tune on u: restore what the last one needed (unless this one needs it too), then switch if needed"""
        need = {norm(a) for a in needed}
        p = self.pending.get(u.addr)
        if p and not (enabled and norm(p["new"]) in need):
            if not await self.release(u_for, u.addr):
                return                        # the socket's state is unknown: better not switch another one
            p = None
        if not enabled:
            self.msg = ""
            return
        try:
            cfg = await self.read(u)
        except UltimateError as e:
            self.msg = tr("SID-Konfiguration nicht lesbar: %s") % e
            return
        key = lambda n: "SID Socket %d Address" % n                   # noqa: E731
        if p:                                 # kept for this tune too - unless the Ultimate was switched off meanwhile
            if norm(cfg.get(key(p["sock"]))) == norm(p["new"]):
                self.msg = tr("Sockel %d für dieses Stück auf %s (sonst %s)") % (p["sock"], p["new"], p["orig"])
                return
            switch = (p["sock"], p["new"])
            orig = p["orig"]
        else:
            switch, why = plan(cfg, needed)
            self.msg = why
            if not switch:
                return
            orig = norm(cfg.get(key(switch[0])))
        sock, new = switch
        try:                                  # remembered before switching
            self._write(dict(self.pending, **{u.addr: {"addr": u.addr, "pw": u.pw, "sock": sock, "orig": orig, "new": new}}))
        except OSError as e:
            self.msg = tr("Nicht umgestellt – Rückstellung nicht speicherbar: %s") % e
            return
        try:
            await u.request("PUT", self._put(sock, new), timeout=6)
            self.gen += 1
            self.known[key(sock)] = new
            self.msg = tr("Sockel %d für dieses Stück auf %s (sonst %s)") % (sock, new, orig)
        except UltimateError as e:            # it may have happened anyway: the record stays, a restore is harmless
            self.msg = tr("Umstellen fehlgeschlagen: %s") % e
