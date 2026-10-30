"""The TV's remote control over HDMI-CEC: the kernel structures and ioctl numbers (as in linux/cec.h), what the
remote's keys do, the answers a TV expects, and the jukebox side with a pretend /dev/cec0."""
import asyncio
import errno
import os
import struct

from c64jukebox import cec, events
from c64jukebox.cec import CecLink, CecProtocol
from c64jukebox.core import Jukebox
from fakes import FakeUltimate, make_sid


def test_kernel_layout():
    assert (cec.MSG.size, cec.LOG_ADDRS.size, cec.CAPS.size) == (56, 92, 76)
    # the numbers v4l-utils' cec-ctl uses
    assert cec.CEC_ADAP_G_CAPS == 0xC04C6100 and cec.CEC_ADAP_G_PHYS_ADDR == 0x80026101
    assert cec.CEC_ADAP_G_LOG_ADDRS == 0x805C6103 and cec.CEC_ADAP_S_LOG_ADDRS == 0xC05C6104
    assert cec.CEC_TRANSMIT == 0xC0386105 and cec.CEC_RECEIVE == 0xC0386106 and cec.CEC_S_MODE == 0x40046109


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def test_protocol_keys_and_answers():
    clk = Clock()
    p = CecProtocol(clock=clk)
    p.phys = 0x1000
    key = lambda k: p.handle(0, 4, bytes([cec.USER_CONTROL_PRESSED, k]))[0]     # noqa: E731
    assert key(0x44) == "play" and p.last == "play"
    assert key(0x44) is None                                       # held: the repeat is ignored
    p.handle(0, 4, bytes([cec.USER_CONTROL_RELEASED]))
    assert key(0x44) == "play"                                     # pressed again
    clk.t += 1
    assert [key(k) for k in (0x46, 0x45, 0x4B, 0x4C, 0x01, 0x30, 0x61)] == \
        ["pause", "stop", "next", "prev", "up", "song_next", "toggle"]
    assert key(0x99) is None
    assert p.handle(0, 4, bytes([cec.DECK_CONTROL, 1]))[0] == "next"
    assert p.handle(0, 4, bytes([cec.PLAY, 0x25]))[0] == "pause"
    assert p.handle(0, 4, bytes([cec.GIVE_OSD_NAME]))[1] == [(0, bytes([cec.SET_OSD_NAME]) + b"C64-Jukebox")]
    assert p.handle(0, 4, bytes([cec.MENU_REQUEST, 2]))[1] == [(0, bytes([cec.MENU_STATUS, 0]))]
    assert p.handle(0, 4, bytes([cec.GIVE_DEVICE_POWER_STATUS]))[1] == [(0, bytes([cec.REPORT_POWER_STATUS, 0]))]
    # the TV switches to the Pi's input -> we are the active source; to another input -> not any more
    assert p.handle(0, 15, bytes([cec.SET_STREAM_PATH, 0x10, 0x00]))[1] == [(15, bytes([cec.ACTIVE_SOURCE, 0x10, 0]))]
    assert p.active
    assert p.handle(0, 15, bytes([cec.REQUEST_ACTIVE_SOURCE]))[1] == [(15, bytes([cec.ACTIVE_SOURCE, 0x10, 0]))]
    p.handle(0, 15, bytes([cec.ROUTING_CHANGE, 0x10, 0x00, 0x20, 0x00]))
    assert not p.active and p.handle(0, 15, bytes([cec.REQUEST_ACTIVE_SOURCE]))[1] == []
    assert p.tv_on() == [(0, bytes([cec.IMAGE_VIEW_ON])), (15, bytes([cec.ACTIVE_SOURCE, 0x10, 0]))] and p.active


class FakeCecDevice:
    """what the kernel does for our ioctls; a pipe makes the fd readable when a message waits"""

    def __init__(self):
        self.r = self.w = None
        self.la, self.phys, self.cleared, self.fail = None, 0x1000, 0, None
        self.inbox, self.sent, self.mode = [], [], None

    def open(self, path, flags):
        self.r, self.w = os.pipe()                       # a fresh device file each time it is opened
        os.set_blocking(self.r, False)
        return self.r

    def put(self, frm, to, data):
        self.inbox.append(bytes([(frm << 4) | to]) + data)
        os.write(self.w, b"x")

    def ioctl(self, fd, req, buf):
        if req == cec.CEC_ADAP_G_CAPS:
            buf[:] = cec.CAPS.pack(b"vc4", b"vc4-hdmi", 1, 0x7E, 0)
        elif req == cec.CEC_S_MODE:
            self.mode = struct.unpack("<I", buf)[0]
        elif req == cec.CEC_ADAP_G_LOG_ADDRS:
            la = self.la
            buf[:] = cec.LOG_ADDRS.pack(bytes([la if la is not None else 0xFF, 0, 0, 0]), (1 << la) if la is not None else 0,
                                        5, 1 if la is not None else 0, 0, 0, b"", b"", b"", b"", b"")
        elif req == cec.CEC_ADAP_S_LOG_ADDRS:
            f = cec.LOG_ADDRS.unpack(bytes(buf))
            if f[3] == 0:                                    # cleared: off the bus
                self.la, self.cleared = None, self.cleared + 1
                return 0
            assert f[3] == 1 and f[8][0] == 3 and f[7][0] == 4 and f[9][0] == 0x10 and f[6].rstrip(b"\0") == b"C64-Jukebox"     # one playback address
            self.la = 4
        elif req == cec.CEC_ADAP_G_PHYS_ADDR:
            buf[:] = struct.pack("<H", self.phys)
        elif req == cec.CEC_RECEIVE:
            if self.fail:
                raise OSError(self.fail, "No such device")
            if not self.inbox:
                raise OSError(errno.EAGAIN, "Resource temporarily unavailable")
            raw = self.inbox.pop(0)
            try:
                os.read(self.r, 1)
            except BlockingIOError:
                pass
            buf[:] = cec.MSG.pack(0, 0, len(raw), 0, 0, 0, raw.ljust(16, b"\0"), 0, 1, 0, 0, 0, 0, 0)
        elif req == cec.CEC_TRANSMIT:
            f = cec.MSG.unpack(bytes(buf))
            self.sent.append(f[6][:f[2]])
        return 0


def test_link_and_jukebox(tmp_path, monkeypatch):
    dev = FakeCecDevice()
    monkeypatch.setattr("c64jukebox.core.CecLink", lambda proto: CecLink(proto, ioctl=dev.ioctl, opener=dev.open))

    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        for n in ("a.sid", "b.sid"):
            (d / n).write_bytes(make_sid(n, "Ann"))
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        await jb.start()
        try:
            assert jb.cec is None and jb.cec_status() == {"on": False}             # off by default
            jb.cec_set({"on": True, "tv_on": True, "tv_off_min": 1})
            assert dev.mode == cec.MODE_INITIATOR | cec.MODE_FOLLOWER
            jb._cec_tick()
            st = jb.cec_status()
            assert st["ready"] and st["la"] == 4 and st["phys"] == "1.0.0.0" and "vc4" in st["adapter"]
            await jb.player.set_items([{"src": "pi", "path": "/" + n, "name": n} for n in ("a.sid", "b.sid")], 0,
                                      play=True, source="t")
            jb._cec_tick()                                                         # playing: TV on, to the Pi
            assert dev.sent[-2:] == [bytes([0x40, cec.IMAGE_VIEW_ON]), bytes([0x4F, cec.ACTIVE_SOURCE, 0x10, 0])]
            dev.put(0, 4, bytes([cec.USER_CONTROL_PRESSED, 0x4B]))                 # the remote: forward
            for _ in range(50):
                await asyncio.sleep(0.02)
                if jb.player.cur and jb.player.cur["item"]["name"] == "b.sid":
                    break
            assert jb.player.cur["item"]["name"] == "b.sid" and jb.cec_status()["last"] == "next"
            dev.put(0, 4, bytes([cec.USER_CONTROL_PRESSED, 0x01]))                 # up: the next effect on the TV
            mode = jb.config["hdmi"]["mode"]
            for _ in range(50):
                await asyncio.sleep(0.02)
                if jb.config["hdmi"]["mode"] != mode:
                    break
            assert jb.config["hdmi"]["mode"] != mode
            # one play/pause key that always sends "play": stops while playing, plays when stopped
            dev.put(0, 4, bytes([cec.USER_CONTROL_PRESSED, 0x44]))
            for _ in range(50):
                await asyncio.sleep(0.02)
                if jb.player.state == "stop":
                    break
            assert jb.player.state == "stop"
            dev.put(0, 4, bytes([cec.USER_CONTROL_RELEASED]))
            dev.put(0, 4, bytes([cec.USER_CONTROL_PRESSED, 0x44]))
            for _ in range(50):
                await asyncio.sleep(0.02)
                if jb.player.state == "play":
                    break
            assert jb.player.state == "play" and jb.cec_status()["recent"][-2:] == ["play", "play"]
            dev.put(0, 4, bytes([cec.GIVE_OSD_NAME]))
            await asyncio.sleep(0.1)
            assert dev.sent[-1] == bytes([0x40, cec.SET_OSD_NAME]) + b"C64-Jukebox"
            dev.put(0, 4, bytes([cec.USER_CONTROL_PRESSED, 0x45]))                 # stop
            for _ in range(50):
                await asyncio.sleep(0.02)
                if jb.player.state == "stop":
                    break
            assert jb.player.state == "stop"
            jb._cec_tick()
            n = len(dev.sent)
            jb.clock = lambda: 1e12                                                # a long time later
            jb._cec_tick()
            assert dev.sent[n:] == [bytes([0x40, cec.STANDBY])]                    # TV to standby, once
            jb._cec_tick()
            assert len(dev.sent) == n + 1
            # "claim" (on by default): without tv_on, a start of playing only announces the Pi as the active source
            jb.cec_set({"tv_on": False})
            await jb.player.stop()
            jb._cec_tick()
            jb.cec.proto.active = False
            n = len(dev.sent)
            await jb.player.play_pos(0)
            jb._cec_tick()
            assert dev.sent[n:] == [bytes([0x4F, cec.ACTIVE_SOURCE, 0x10, 0])]
            jb.cec_set({"claim": False})
            await jb.player.stop()
            jb._cec_tick()
            jb.cec.proto.active = False
            n = len(dev.sent)
            await jb.player.play_pos(0)
            jb._cec_tick()
            assert dev.sent[n:] == []
            jb.cec_set({"claim": True, "tv_on": True})
            # the TV moves the Pi to another input address: read every second
            dev.phys = 0x2000
            jb._cec_tick()
            assert jb.cec_status()["phys"] == "2.0.0.0"
            dev.put(0, 15, bytes([cec.SET_STREAM_PATH, 0x20, 0x00]))
            await asyncio.sleep(0.1)
            assert dev.sent[-1] == bytes([0x4F, cec.ACTIVE_SOURCE, 0x20, 0])
            # music starts while the TV gives no address; when it comes later, the TV is NOT switched on then
            dev.la = None
            jb._cec_tick()
            assert not jb.cec_status()["ready"]
            await jb.player.play_pos(0)
            jb._cec_tick()
            n = len(dev.sent)
            dev.la = 4
            jb._cec_tick()
            assert jb.cec_status()["ready"] and dev.sent[n:] == []
            # the adapter goes away: no reader firing for ever, opened again later
            dev.fail = errno.ENODEV
            dev.put(0, 4, bytes([cec.GIVE_OSD_NAME]))
            await asyncio.sleep(0.1)
            assert jb.cec.fd is None and "No such device" in jb.cec_status()["err"]
            dev.fail = None
            jb.clock = lambda: 2e12
            jb._cec_tick()
            assert jb.cec and jb.cec.fd is not None
            cleared = dev.cleared
            jb.cec_set({"on": False})
            assert jb.cec is None and dev.cleared == cleared + 1          # off the bus
        finally:
            await jb.close()
            await u64.stop()
    asyncio.run(t())


def test_protocol_tv_power():
    p = CecProtocol()
    assert p.tv_power is None
    assert p.handle(0, 15, bytes([cec.ROUTING_CHANGE, 0x10, 0, 0x20, 0]))[0] is None and p.tv_power == "on"
    assert p.handle(0, 15, bytes([cec.STANDBY])) == (None, []) and p.tv_power == "standby" and not p.active
    p.handle(0, 4, bytes([cec.REPORT_POWER_STATUS, 0x02]))                 # going on
    assert p.tv_power == "on"
    p.handle(0, 4, bytes([cec.REPORT_POWER_STATUS, 0x01]))
    assert p.tv_power == "standby"
    p.handle(5, 15, bytes([cec.ACTIVE_SOURCE, 0x30, 0]))                    # another device: says nothing about the TV
    assert p.tv_power == "standby"
    assert p.ask_tv_power() == [(cec.TV, bytes([cec.GIVE_DEVICE_POWER_STATUS]))]


def test_pi_off_when_the_tv_goes_off(tmp_path, monkeypatch):
    """the TV on, then standby: a minute later the Pi goes off (the plug's timer first); on again in between keeps it;
    a Pi that never saw the TV on stays on (started by the plug for music without the TV); headphones keep it on"""
    from test_plug import ID, setup
    dev = FakeCecDevice()
    monkeypatch.setattr("c64jukebox.core.CecLink", lambda proto: CecLink(proto, ioctl=dev.ioctl, opener=dev.open))

    async def t():
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        fake, mark = setup(jb, tmp_path)
        jb.config.data["plug"].update(ip=fake.ip, id=ID, key=fake.key)
        await jb.start()
        now = [1000.0]
        jb.clock = lambda: now[0]
        try:
            jb.cec_set({"on": True, "pi_off": True})
            jb._cec_tick()
            assert dev.sent[-1] == bytes([0x40, cec.GIVE_DEVICE_POWER_STATUS])     # asked at once, then every 30 s

            async def tv(power):
                dev.put(0, 15 if power == "standby" else 4,
                        bytes([cec.STANDBY]) if power == "standby" else bytes([cec.REPORT_POWER_STATUS, 0]))
                await asyncio.sleep(0.05)
                jb._cec_tick()

            await tv("standby")                         # off from the start: never seen on -> nothing
            now[0] += 120
            jb._cec_tick()
            assert jb.tv_off_at is None and not jb.powering_off
            await tv("on")
            await tv("standby")
            assert jb.cec_status()["pi_off_in"] == 60
            now[0] += 30
            await tv("on")                              # on again within the minute: stays on
            now[0] += 60
            jb._cec_tick()
            assert not jb.powering_off and any("wieder an" in x[1] for x in events._log)
            # headphones connected: stays on
            jb.bt_conn = True
            jb.config.data["bt"].update(on=True, mac="12:34:56:78:9A:BC")
            await tv("standby")
            now[0] += 61
            jb._cec_tick()
            assert not jb.powering_off and any("Kopfhörer verbunden" in x[1] for x in events._log)
            jb.bt_conn = False
            await tv("on")
            await tv("standby")
            now[0] += 61
            jb._cec_tick()
            for _ in range(40):
                if jb.powering_off:
                    break
                await asyncio.sleep(0.05)
            assert jb.powering_off and fake.dps["9"] == 30
        finally:
            jb.powering_off = True                      # no real shutdown command left pending
            await jb.close()
    asyncio.run(t())


def test_tv_on_when_the_pi_starts(tmp_path, monkeypatch):
    """tv_on_boot: the first time the Pi is ready on the HDMI cable after its start -> TV on + to the Pi, once;
    ready only after TV_BOOT_S (the TV was off and is switched on by someone later): not pulled to the Pi"""
    from c64jukebox import core as core_mod

    async def run_start(ready_after):
        dev = FakeCecDevice()
        monkeypatch.setattr("c64jukebox.core.CecLink", lambda proto: CecLink(proto, ioctl=dev.ioctl, opener=dev.open))
        jb = Jukebox(str(tmp_path / ("data%d" % ready_after)), stream_port=0, dev_port=0, bcast="127.0.0.1",
                     run_dir=str(tmp_path))
        jb.config.data["cec"].update(on=True, tv_on_boot=True, claim=False)
        now = [500.0]
        jb.clock = lambda: now[0]
        await jb.start()
        try:
            dev.la = None                               # the TV is off: no address on the bus yet
            jb._cec_tick()
            assert not jb.cec_ready
            now[0] += ready_after
            dev.la = 4                                  # the TV gives the Pi its address
            jb._cec_tick()
            jb._cec_tick()
            return [m for m in dev.sent if m[1:2] == bytes([cec.IMAGE_VIEW_ON])]
        finally:
            await jb.close()

    assert len(asyncio.run(run_start(5))) == 1                          # once
    assert asyncio.run(run_start(core_mod.TV_BOOT_S + 10)) == []        # too late after the start
