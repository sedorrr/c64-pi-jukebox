"""The smart plug the Pi hangs on (Tuya, e.g. Antela - app "Smart Life"): before the Pi shuts down, the plug's own
switch-off timer is set, so the power goes some seconds after the Pi is down; it comes back by voice (Alexa) or the
app, and the Pi starts. tinytuya talks to the plug in the network (TCP 6668); it needs the device id and the plug's
local key (from the Tuya developer platform). Every call is short and runs in a thread - tinytuya blocks."""
import asyncio

SWITCH_DP = "1"
COUNTDOWN_DP = "9"          # countdown_1, seconds, on Tuya plugs
POWER_DP = "19"             # cur_power, 0.1 W (plugs with power metering)
VERSIONS = ("3.1", "3.3", "3.4", "3.5")
TIMEOUT_S = 4


def configured(cfg):
    return bool(cfg.get("id") and cfg.get("key"))


def _lib():
    try:
        import tinytuya
    except ImportError:
        raise ValueError("Das Python-Paket tinytuya fehlt – Installationsskript noch einmal ausführen")
    return tinytuya


class Plug:
    def __init__(self, lib=None):
        self.lib = lib          # tinytuya, or a fake in the tests

    def _tt(self):
        return self.lib or _lib()

    def _find(self, cfg):
        """{"ip", "version"} of the plug by its device id: it announces itself by UDP broadcast every few seconds"""
        r = self._tt().find_device(cfg["id"]) or {}
        if not r.get("ip"):
            raise ValueError("Steckdose nicht im Netz gefunden – eingeschaltet und im selben Netz? Sonst Adresse eintragen")
        return {"ip": r["ip"], "ver": str(r.get("version") or cfg.get("ver") or "3.5")}

    def _device(self, cfg, ip, ver):
        d = self._tt().OutletDevice(cfg["id"], address=ip, local_key=cfg["key"], version=float(ver),
                                    connection_timeout=TIMEOUT_S, connection_retry_limit=1)
        d.set_socketTimeout(TIMEOUT_S)
        d.set_socketRetryLimit(1)
        return d

    @staticmethod
    def _check(r):
        if not isinstance(r, dict):
            raise ValueError("keine Antwort")
        if r.get("Error") or r.get("Err"):
            err = str(r.get("Error") or r.get("Err"))
            if "key" in err.lower() or "decrypt" in err.lower() or str(r.get("Err")) == "914":
                err += " – Geräte-ID, Schlüssel und Version prüfen"
            raise ValueError(err)
        return r

    def _status(self, cfg):
        where = {"ip": cfg.get("ip", ""), "ver": cfg.get("ver") or "3.5"}
        if not where["ip"]:
            where = self._find(cfg)
        dps = (self._check(self._device(cfg, where["ip"], where["ver"]).status()).get("dps") or {})
        dps = {str(k): v for k, v in dps.items()}
        out = dict(where, on=bool(dps.get(SWITCH_DP)), timer=COUNTDOWN_DP in dps, secs=int(dps.get(COUNTDOWN_DP) or 0))
        if POWER_DP in dps:
            out["watt"] = round(float(dps[POWER_DP]) / 10, 1)
        return out

    def _countdown(self, cfg, secs):
        where = {"ip": cfg.get("ip", ""), "ver": cfg.get("ver") or "3.5"}
        if not where["ip"]:
            where = self._find(cfg)
        self._check(self._device(cfg, where["ip"], where["ver"]).set_value(int(COUNTDOWN_DP), int(secs)))

    async def status(self, cfg):
        """{"ip", "ver", "on", "timer" (has a switch-off timer), "secs" (running), "watt"?} - ValueError if not"""
        if not configured(cfg):
            raise ValueError("Geräte-ID und Schlüssel der Steckdose fehlen")
        return await asyncio.to_thread(self._status, cfg)

    async def countdown(self, cfg, secs):
        """power off in secs seconds (0 = cancel the timer)"""
        if not configured(cfg):
            raise ValueError("Geräte-ID und Schlüssel der Steckdose fehlen")
        await asyncio.to_thread(self._countdown, cfg, secs)
