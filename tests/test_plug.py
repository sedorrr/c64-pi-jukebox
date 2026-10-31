"""Switching the Pi off with the smart plug: a fake tinytuya (the plug's data points in a dict), fake logind commands
(true / false) - the timer is set before the shutdown, taken back when the shutdown fails, and without an answering
plug the Pi stays on unless the page insists."""
import asyncio
import sys

from c64jukebox import plug
from c64jukebox.config import MASK
from test_web import get, job, login, post, run

ID = "bf00112233445566778899"


class FakeTuya:
    """tinytuya's find_device + OutletDevice; dps of the one plug, calls written down"""
    def __init__(self, key="0123456789abcdef", ip="192.168.1.50", ver="3.5", timer=True):
        self.key, self.ip, self.ver = key, ip, ver
        self.dps = {"1": True, "19": 123, **({"9": 0} if timer else {})}
        self.calls, self.down = [], False
        fake = self

        class OutletDevice:
            def __init__(self, dev_id, address=None, local_key="", version=3.1, **kw):
                self.ok = dev_id == ID and local_key == fake.key and address == fake.ip and version == float(fake.ver)

            def set_socketTimeout(self, s):
                pass

            def set_socketRetryLimit(self, n):
                pass

            def _err(self):
                if fake.down:
                    return {"Error": "Network Error: Device Unreachable", "Err": "905"}
                if not self.ok:
                    return {"Error": "Check device key or version", "Err": "914"}

            def status(self):
                return self._err() or {"dps": dict(fake.dps)}

            def set_value(self, index, value):
                fake.calls.append((index, value))
                if self._err():
                    return self._err()
                fake.dps[str(index)] = value
                return {"dps": {str(index): value}}
        self.OutletDevice = OutletDevice

    def find_device(self, dev_id):
        self.calls.append(("find", dev_id))
        return {"ip": self.ip, "version": self.ver, "id": ID} if dev_id == ID and not self.down else {"ip": None}


def setup(jb, tmp_path, can=True, off_ok=True, **kw):
    fake = FakeTuya(**kw)
    jb.plug = plug.Plug(lib=fake)
    jb.power_can_cmd = [sys.executable, "-c", "print('s \"%s\"')" % ("yes" if can else "no")]
    mark = tmp_path / "poweroff"
    jb.power_cmd = [sys.executable, "-c", "open(%r, 'w').write('x'); raise SystemExit(%d)" % (str(mark), 0 if off_ok else 1)]
    return fake, mark


def test_switch_off_sets_the_plug_timer_first(tmp_path):
    async def t(c, jb, u64):
        fake, mark = setup(jb, tmp_path)
        await login(c)
        s, r = await get(c, "/api/power")
        assert r["can"] and not r["plug"]
        s, r = await post(c, "/api/plug/check", {})
        assert not r["ok"] and "fehlen" in r["msg"]
        # the key leaves the Pi only masked, saving the mask back keeps it
        s, r = await post(c, "/api/config", {"plug": {"ip": "", "id": ID, "key": fake.key, "ver": "3.5", "off_s": 5}})
        assert r["config"]["plug"]["key"] == MASK and r["config"]["plug"]["off_s"] == 20     # at least 20 s
        await post(c, "/api/config", {"plug": {"key": MASK, "off_s": 40}})
        assert jb.config["plug"]["key"] == fake.key and jb.config["plug"]["off_s"] == 40
        # no address: found by its id, address and version kept
        s, r = await post(c, "/api/plug/check", {})
        res = (await job(c, r["job"]))["result"]
        assert res == {"ip": fake.ip, "ver": "3.5", "on": True, "timer": True, "secs": 0, "watt": 12.3}
        assert jb.config["plug"]["ip"] == fake.ip and ("find", ID) in fake.calls
        s, r = await post(c, "/api/power/off", {})
        assert r["ok"] and r["timer"] and r["secs"] == 40
        assert fake.dps["9"] == 40 and not mark.exists()              # timer now, shutdown a moment later
        s, r = await post(c, "/api/power/off", {})
        assert not r["ok"] and "schon" in r["msg"]
        for _ in range(40):
            if mark.exists():
                break
            await asyncio.sleep(0.1)
        assert mark.exists() and fake.dps["9"] == 40
    run(tmp_path, t)


def test_failed_shutdown_takes_the_timer_back(tmp_path):
    async def t(c, jb, u64):
        fake, mark = setup(jb, tmp_path, off_ok=False)
        jb.config["plug"].update(ip=fake.ip, id=ID, key=fake.key)
        await login(c)
        s, r = await post(c, "/api/power/off", {})
        assert r["ok"] and fake.dps["9"] == 30
        for _ in range(40):
            if not jb.powering_off:
                break
            await asyncio.sleep(0.1)
        assert mark.exists() and not jb.powering_off and fake.dps["9"] == 0     # the Pi stays on with its power
    run(tmp_path, t)


def test_plug_not_answering_keeps_the_pi_on(tmp_path):
    async def t(c, jb, u64):
        fake, mark = setup(jb, tmp_path)
        jb.config["plug"].update(ip=fake.ip, id=ID, key="falsch")
        await login(c)
        s, r = await post(c, "/api/plug/check", {})
        assert "Schlüssel" in (await job(c, r["job"]))["error"]
        s, r = await post(c, "/api/power/off", {})
        assert not r["ok"] and "bleibt an" in r["msg"] and not jb.powering_off
        assert r["plug"] is True                     # the page offers "anyway" by this flag, whatever the language
        s, r = await post(c, "/api/power/off", {"force": True})                # the page asked: shut down anyway
        assert r["ok"] and not r["timer"]
    run(tmp_path, t)


def test_not_allowed_to_switch_off(tmp_path):
    async def t(c, jb, u64):
        setup(jb, tmp_path, can=False)
        await login(c)
        assert (await get(c, "/api/power"))[1]["can"] is False
        s, r = await post(c, "/api/power/off", {})
        assert not r["ok"] and "Installationsskript" in r["msg"] and not r["plug"]
    run(tmp_path, t)


def test_switch_off_from_the_tv(tmp_path):
    async def t(c, jb, u64):
        fake, mark = setup(jb, tmp_path, timer=True)
        jb.config["plug"].update(ip=fake.ip, id=ID, key=fake.key)
        entry = next(e for e in jb.menu.entries_of("power") if e[0] == "Jukebox ausschalten")
        assert "Steckdose" in entry[2][1]
        await jb.menu._do(entry[2])                     # the question first ...
        await jb.menu._do(entry[2][3])                  # ... then "Ja, ausschalten"
        assert "Strom aus in 30 s" in jb.menu.note and fake.dps["9"] == 30
    run(tmp_path, t)


def test_switch_off_from_the_touch_display(tmp_path):
    async def t(c, jb, u64):
        fake, mark = setup(jb, tmp_path)
        jb.config["plug"].update(ip=fake.ip, id=ID, key=fake.key)
        await jb.touch_cmd("tvoff")                     # no HDMI-CEC here: the reason on the page "Ein / Aus"
        jb.display.page = "power"
        assert "HDMI-CEC" in jb.display_state()["pnote"] and jb.display_state()["tvctl"]["ready"] is False
        await jb.touch_cmd("pioff")
        assert jb.powering_off and fake.dps["9"] == 30 and "Strom aus in 30 s" in jb.display_state()["pnote"]
    run(tmp_path, t)
