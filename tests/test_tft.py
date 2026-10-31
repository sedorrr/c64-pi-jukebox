"""2.8" touch display: ILI9341 commands decoded by a small emulator (picture memory), XPT2046 with given raw values,
calibration, buttons, page change, wake-up; previews as PNG (tests/web/tft_*.png)."""
import itertools
import os

from PIL import Image

from c64jukebox import tft
from c64jukebox.display import Display
from c64jukebox.tft import (CAL_POINTS, PIN_DC, PIN_IRQ, PIN_LED, PIN_RESET, Ili9341, TftScreen, TouchReader,
                            calibrate, map_touch, rgb565)

from test_display import AP, PLAY

HERE = os.path.dirname(os.path.abspath(__file__))


class FakeGpio:
    def __init__(self, outputs, inputs):
        self.v = dict(outputs)
        for n in inputs:
            self.v[n] = 1                       # pull-up: not touched
        self.log = []

    def set(self, line, value):
        self.v[line] = value
        self.log.append((line, value))

    def get(self, line):
        return bool(self.v[line])

    def close(self):
        pass


class Emu:
    """the display end of the SPI bus: commands with DC low, parameters/pixels with DC high"""

    def __init__(self, hw):
        self.hw = hw
        self.cmds = []
        self.cmd = None
        self.args = bytearray()
        self.fb = Image.new("RGB", (tft.W, tft.H))
        self.win = (0, 0, tft.W - 1, tft.H - 1)
        self.pos = 0
        self.pixels = 0

    def write(self, data):
        if not self.hw.gpio_.v[self.hw.dc]:
            self._end()
            self.cmd, self.args, self.pos = data[0], bytearray(), 0
            self.cmds.append(data[0])
            return
        if self.cmd == 0x2C:
            x0, y0, x1, y1 = self.win
            w = x1 - x0 + 1
            buf = self.args + data
            n = len(buf) // 2
            for k in range(n):
                v = buf[2 * k] << 8 | buf[2 * k + 1]
                i = self.pos + k
                self.fb.putpixel((x0 + i % w, y0 + i // w), ((v >> 8) & 0xF8, (v >> 3) & 0xFC, (v << 3) & 0xF8))
            self.pos += n
            self.pixels += n
            self.args = bytearray(buf[2 * n:])
        else:
            self.args += data

    def _end(self):
        a = self.args
        if self.cmd in (0x2A, 0x2B) and len(a) == 4:
            lo, hi = a[0] << 8 | a[1], a[2] << 8 | a[3]
            x0, y0, x1, y1 = self.win
            self.win = (lo, y0, hi, y1) if self.cmd == 0x2A else (x0, lo, x1, hi)
        if self.cmd == 0x36:
            self.madctl = a[0]

    def close(self):
        pass


class TouchSpi:
    def __init__(self, hw):
        self.hw = hw
        self.at = None                           # (raw_x, raw_y, z1) while touched

    def xfer(self, data):
        v = {0xB0: self.at[2], 0xD0: self.at[0], 0x90: self.at[1]}.get(data[0], 0) if self.at else 0
        return bytes([0, (v << 3) >> 8 & 0xFF, (v << 3) & 0xFF])

    def close(self):
        pass


class FakeHw:
    def __init__(self):
        self.gpio_ = None
        self.emu = self.touch = None
        self.slept = 0.0
        self.touch_path = None

    def spi(self, path, speed):
        if path == tft.SPI_DISPLAY:
            self.emu = Emu(self)
            return self.emu
        self.touch_path = path
        self.touch = TouchSpi(self)
        return self.touch

    def gpio(self, outputs, inputs):
        self.dc = next((p for p in (23, 6) if p in outputs), PIN_DC)  # the D/C line the display was opened with
        self.gpio_ = FakeGpio(outputs, inputs)
        return self.gpio_

    def sleep(self, s):
        self.slept += s

    def press(self, rx, ry, z=400):
        self.touch.at = (rx, ry, z)
        self.gpio_.v[PIN_IRQ] = 0

    def release(self):
        self.touch.at = None
        self.gpio_.v[PIN_IRQ] = 1


def quant(img):
    return Image.frombytes("RGB", img.size, bytes(b & m for b, m in zip(img.tobytes(), itertools.cycle((0xF8, 0xFC, 0xF8)))))


def test_rgb565():
    img = Image.new("RGB", (4, 1))
    for i, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]):
        img.putpixel((i, 0), c)
    assert rgb565(img) == bytes([0xF8, 0x00, 0x07, 0xE0, 0x00, 0x1F, 0xFF, 0xFF])


def test_init_reset_and_backlight():
    hw = FakeHw()
    d = Ili9341(hw)
    assert hw.gpio_.log[:2] == [(PIN_RESET, 0), (PIN_RESET, 1)]
    assert hw.emu.cmds[0] == 0x01 and hw.emu.cmds[-1] == 0x29 and 0x11 in hw.emu.cmds
    assert hw.emu.madctl == tft.MADCTL_LANDSCAPE
    assert hw.gpio_.v[PIN_LED] == 0                   # dark until the first picture
    d.power(True)
    assert hw.gpio_.v[PIN_LED] == 1
    hw2 = FakeHw()
    Ili9341(hw2, flip=True)
    hw2.emu._end()
    assert hw2.emu.madctl == tft.MADCTL_FLIPPED


def test_show_whole_then_only_the_change():
    hw = FakeHw()
    d = Ili9341(hw)
    img = TftScreen().render(PLAY, "play")
    assert d.show(img)
    hw.emu._end()
    assert hw.emu.pixels == tft.W * tft.H and hw.emu.fb.tobytes() == quant(img).tobytes()
    st = dict(PLAY, player=dict(PLAY["player"], el=84))           # one second later: the clock and the bar
    img2 = TftScreen().render(st, "play")
    hw.emu.pixels = 0
    assert d.show(img2)
    hw.emu._end()
    assert 0 < hw.emu.pixels < tft.W * tft.H / 3
    assert hw.emu.fb.tobytes() == quant(img2).tobytes()
    assert not d.show(img2)                                       # nothing changed: nothing sent


def test_touch_controller():
    hw = FakeHw()
    d = Ili9341(hw)
    t = d.touch
    assert t.read() is None
    hw.press(1200, 3000)
    assert t.read() == (1200, 3000)
    hw.press(1200, 3000, z=10)                                    # too light: noise
    assert t.read() is None
    hw.release()
    assert t.read() is None


def test_touch_reader_taps_on_release():
    class Seq:
        def __init__(self, seq):
            self.seq = list(seq)

        def read(self):
            return self.seq.pop(0) if self.seq else None

    taps = []
    r = TouchReader(Seq([(100, 900), (110, 905), (120, 910), (115, 3000), None, (500, 500), None]),
                    lambda x, y: taps.append((x, y)))
    s = []
    for _ in range(8):
        s = r.step(s)
    assert taps == [(115, 910)]                                   # median without the first sample; the spike alone: no tap


def raw_for(x, y, swap=True):
    """how a typical board reports a screen point: axes swapped, x inverted"""
    rx = 3800 - (x / tft.W) * 3500
    ry = 300 + (y / tft.H) * 3400
    return (int(ry), int(rx)) if swap else (int(rx), int(ry))


def test_calibration_and_mapping():
    for swap in (True, False):
        cal = calibrate([raw_for(*p, swap=swap) for p in CAL_POINTS])
        assert cal and cal["ax"] == (1 if swap else 0)
        for x, y in ((10, 10), (160, 120), (300, 230)):
            mx, my = map_touch(cal, raw_for(x, y, swap))
            assert abs(mx - x) <= 2 and abs(my - y) <= 2
        mx, my = map_touch(cal, raw_for(10, 10, swap), flipped=True)
        assert abs(mx - (tft.W - 11)) <= 2 and abs(my - (tft.H - 11)) <= 2
    assert calibrate([(2000, 2000), (2010, 2000), (2000, 2005)]) is None     # three taps on one spot


def test_display_with_touch():
    cfg = {"type": "tft", "off_min": 10, "flip": False, "cal": None}
    t = [0.0]
    saved, cmds = [], []
    hw = FakeHw()
    d = Display(lambda: cfg, clock=lambda: t[0], hw=hw, on_touch=cmds.append, save=lambda: saved.append(1),
                touch_thread=False)
    d.tick(PLAY)
    assert d.msg == Display.TFT_MSG["own"] and d.page == "cal"    # no calibration yet: the crosses come first
    assert hw.touch_path == "/dev/spidev1.0"                      # the touch on its own bus: no Y cables
    preview(hw, "tft_cal.png")
    for p in CAL_POINTS:
        assert d.touch_raw(*raw_for(*p)) == "cal"
    assert saved and cfg["cal"] and d.cal_step is None
    assert d.page == "play"
    preview(hw, "tft_play.png")
    hw.emu._end()
    assert d.touch_raw(*raw_for(120, 200)) == "stop" and cmds == ["stop"]         # second button
    assert d.touch_raw(*raw_for(200, 200)) == "next"
    assert d.touch_raw(*raw_for(20, 200)) == "prev"
    # the power button: a page with TV on / off and "Jukebox ausschalten" (a second tap within 5 s)
    assert d.touch_raw(*raw_for(280, 200)) == "power" and d.page == "power" and cmds == ["stop", "next", "prev"]
    d.tick(dict(PLAY, tvctl={"ready": True, "tv": "on"}))
    preview(hw, "tft_power.png")
    assert d.touch_raw(*raw_for(240, 80)) == "tvoff" and cmds[-1] == "tvoff" and d.page == "power"
    assert d.touch_raw(*raw_for(160, 40)) is None and d.page == "power"       # beside the buttons: stays
    assert d.touch_raw(*raw_for(160, 140)) == "arm" and cmds[-1] == "tvoff"
    t[0] += 6                                                                   # too late: asks again
    assert d.touch_raw(*raw_for(160, 140)) == "arm"
    t[0] += 1
    assert d.touch_raw(*raw_for(160, 140)) == "pioff" and cmds[-1] == "pioff"
    assert d.touch_raw(*raw_for(160, 205)) == "back" and d.page == "play"
    del cmds[3:]
    assert d.touch_raw(*raw_for(160, 60)) == "page" and d.page == "level"         # elsewhere: the next page
    d.tick(dict(PLAY, level={"now": [0.55, 0.83], "peak": [0.7, 0.95],
                             "hist": [abs(((i * 7) % 23) - 11) / 11 for i in range(60)]}))
    assert d.page == "level"
    preview(hw, "tft_level.png")
    assert d.touch_raw(*raw_for(160, 60)) == "page" and d.page == "net"
    preview(hw, "tft_net.png")
    assert d.touch_raw(*raw_for(160, 60)) == "page" and d.page == "play"
    t[0] = 40
    d.override = None
    d.tick(AP)
    assert d.page == "net"                                        # own access point: its credentials
    preview(hw, "tft_ap.png")
    stopped = {"name": "c64pi", "player": {"state": "stop", "total": 0}, "net": {"mode": "lan", "eth_ip": "1.2.3.4"}}
    d.tick(stopped)
    t[0] = 40 + 601
    d.tick(stopped)
    assert d.dark and hw.gpio_.v[PIN_LED] == 0                    # 10 min nothing: backlight off
    assert d.touch_raw(*raw_for(160, 200)) == "wake" and hw.gpio_.v[PIN_LED] == 1 and cmds == ["stop", "next", "prev"]
    assert d.calibrate() and d.touch_raw(1, 1) == "cal"           # again from the web page
    d.touch_raw(1, 2)
    d.touch_raw(2, 1)
    assert d.cal_step == 0 and "noch einmal" in d.cal_note        # nonsense taps: start over, old calibration stays
    cfg["type"] = "off"
    d.tick(PLAY)
    assert d.dev is None and d.msg == "aus"


def test_no_spi():
    class NoSpi(FakeHw):
        def spi(self, path, speed):
            raise FileNotFoundError(2, "No such file or directory", path)

    d = Display(lambda: {"type": "tft"}, hw=NoSpi(), touch_thread=False)
    d.tick(PLAY)
    assert d.dev is None and d.msg.startswith("nicht gefunden") and "spidev0.0" in d.msg


def preview(hw, name):
    hw.emu._end()
    hw.emu.fb.resize((640, 480), 0).save(os.path.join(HERE, "web", name))


def test_touch_bus_choice():
    """with Y cables the touch shares the display's bus (CE1); without, it has SPI1 - which needs a restart first"""
    hw = FakeHw()
    d = Display(lambda: {"type": "tft", "touch": "shared", "cal": [1, 0, 0, 0, 1, 0]}, hw=hw, touch_thread=False)
    d.tick(PLAY)
    assert hw.touch_path == "/dev/spidev0.1" and d.msg == Display.TFT_MSG["shared"]

    class NoSpi1(FakeHw):
        def spi(self, path, speed):
            if path == "/dev/spidev1.0":
                raise FileNotFoundError(2, "No such file or directory", path)
            return super().spi(path, speed)
    d = Display(lambda: {"type": "tft"}, hw=NoSpi1(), touch_thread=False)
    d.tick(PLAY)
    assert d.dev is None and "neu starten" in d.msg


def test_dc_on_pin_16():
    """a Pi whose GPIO24 (pin 18) is damaged: D/C on GPIO23 (pin 16) - the picture arrives the same way"""
    hw = FakeHw()
    d = Display(lambda: {"type": "tft", "dc": 23, "cal": [1, 0, 0, 0, 1, 0]}, hw=hw, touch_thread=False)
    d.tick(PLAY)
    assert hw.dc == 23 and 24 not in hw.gpio_.v and d.dev.dc == 23
    assert 0x2C in hw.emu.cmds and hw.emu.pixels > 0                 # pixels written as data, not as commands


def test_middle_button_stops_and_plays(tmp_path):
    """the middle button: stop while a tune plays or pauses, play when nothing plays"""
    import asyncio
    from c64jukebox.core import Jukebox
    from fakes import FakeUltimate, make_sid

    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        (d / "a.sid").write_bytes(make_sid("Alpha", "Ann"))
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        await jb.start()
        try:
            await jb.player.set_items([{"src": "pi", "path": "/a.sid", "name": "a.sid"}], 0, play=True, source="t")
            assert jb.player.state == "play"
            await jb.touch_cmd("stop")
            assert jb.player.state == "stop"
            await jb.touch_cmd("stop")
            assert jb.player.state == "play"
            await jb.player.pause()
            await jb.touch_cmd("stop")
            assert jb.player.state == "stop"
        finally:
            await jb.close()
            await u64.stop()
    asyncio.run(t())


def test_closed_gpio_is_an_oserror():
    """the display closed while the touch thread reads: an OSError (caught there), not a KeyError that ends the thread"""
    import pytest
    g = tft.Gpio.__new__(tft.Gpio)
    g.fds, g.index = {}, {17: 0}
    with pytest.raises(OSError):
        g.get(17)
    with pytest.raises(OSError):
        g.set(17, 1)


def test_dc_on_pin_31():
    hw = FakeHw()
    d = Display(lambda: {"type": "tft", "dc": 6, "cal": [1, 0, 0, 0, 1, 0]}, hw=hw, touch_thread=False)
    d.tick(PLAY)
    assert hw.dc == 6 and d.dev.dc == 6 and hw.emu.pixels > 0


def test_level_page_without_data():
    img = TftScreen().render({"name": "c64pi", "player": {"state": "stop"}}, "level")
    assert img.size == (320, 240)                                 # no levels yet: empty meters, no error
