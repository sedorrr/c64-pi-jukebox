"""Small OLED on the Pi (128 x 64, I2C address 0x3C/0x3D on /dev/i2c-1): SSD1306 (the common 0.96" boards) or SH1106
(1.3"). Four wires: VCC to 3V3 (pin 1), GND (pin 6), SDA GPIO2 (pin 3), SCL GPIO3 (pin 5).

Two pages, every 8 s in turn while a tune plays: what plays (title, author, time, progress, stream) and the network
(cable / WLAN / own access point with name, password and address). In the access point the network page stays, it is
what you need then. Against burn-in the picture moves by a pixel every minute; after "off_min" minutes without a tune
the display goes dark (a new tune or a change of network wakes it).

Talks to the kernel's i2c-dev directly (ioctl I2C_SLAVE + write) - no extra library; drawing with Pillow.

Display (below) also drives the 2.8" colour display with touch (tft.py): there the pages change by a tap, the
buttons control the player, and the first start asks for a calibration of the touch (three crosses)."""
import fcntl
import os
import threading
import time

I2C_SLAVE = 0x0703
W, H = 128, 64

INIT = {
    "ssd1306": [0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12,
                0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF],
    "sh1106": [0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0xAD, 0x8B, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0x80,
               0xD9, 0x22, 0xDB, 0x35, 0xA4, 0xA6, 0xAF],
}


class I2CBus:
    def __init__(self, path="/dev/i2c-1"):
        self.fd = os.open(path, os.O_RDWR)
        self.addr = None

    def write(self, addr, data):
        if addr != self.addr:
            fcntl.ioctl(self.fd, I2C_SLAVE, addr)
            self.addr = addr
        os.write(self.fd, bytes(data))

    def close(self):
        os.close(self.fd)


class Oled:
    def __init__(self, bus, kind="ssd1306", addr=None):
        self.bus, self.kind = bus, kind
        self.addr = addr or self.probe()
        self.on = False
        self.cmd(INIT[kind])
        self.on = True

    def probe(self):
        for a in (0x3C, 0x3D):
            try:
                self.bus.write(a, [0x00, 0xE3])        # NOP command: answers only when a display is there
                return a
            except OSError:
                continue
        raise OSError("kein Display an 0x3C/0x3D")

    def cmd(self, cmds):
        for k in range(0, len(cmds), 16):
            self.bus.write(self.addr, [0x00] + list(cmds[k:k + 16]))

    def power(self, on):
        if on != self.on:
            self.cmd([0xAF if on else 0xAE])
            self.on = on

    def close(self):
        self.power(False)
        self.bus.close()

    def show(self, img):
        """img: Pillow image, mode "1", 128 x 64"""
        px = img.load()
        pages = []
        for page in range(8):
            row = bytearray(W)
            for x in range(W):
                b = 0
                for bit in range(8):
                    if px[x, page * 8 + bit]:
                        b |= 1 << bit
                row[x] = b
            pages.append(row)
        if self.kind == "ssd1306":
            self.cmd([0x21, 0, W - 1, 0x22, 0, 7])
            data = b"".join(pages)
            for k in range(0, len(data), 255):
                self.bus.write(self.addr, b"\x40" + data[k:k + 255])
        else:                                          # SH1106: 132 columns, page addressing, picture at column 2
            for page, row in enumerate(pages):
                self.cmd([0xB0 + page, 0x02, 0x10])
                for k in range(0, W, 64):
                    self.bus.write(self.addr, b"\x40" + bytes(row[k:k + 64]))


def fmt(s):
    s = max(0, int(s or 0))
    return "%d:%02d" % (s // 60, s % 60)


FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",          # Raspberry Pi OS: fonts-dejavu-core
         "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial Unicode.ttf")


def font(size):
    """a font with umlauts (Pillow's built-in one has none)"""
    from PIL import ImageFont
    for p in FONTS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


class Screen:
    """what the display shows - drawing only, testable without hardware"""

    def __init__(self):
        self.big = font(13)
        self.small = font(10)

    def _fit(self, d, text, font, width):
        if d.textlength(text, font=font) <= width:
            return text
        while text and d.textlength(text + "…", font=font) > width:
            text = text[:-1]
        return text + "…"

    def render(self, st, page, shift=0):
        from PIL import Image, ImageDraw
        img = Image.new("1", (W, H), 0)
        d = ImageDraw.Draw(img)
        ox, oy = shift % 2, (shift // 2) % 2
        if page == "net":
            self._net(d, st.get("net") or {}, st, ox, oy)
        else:
            self._play(d, st, ox, oy)
        return img

    def _net(self, d, n, st, ox, oy):
        mode = n.get("mode", "unknown")
        name = st.get("name") or "c64pi"
        if mode == "ap" and n.get("ap"):
            ap = n["ap"]
            d.rectangle((0, 0, W - 1, 12), fill=1)
            d.text((2 + ox, 0), "Eigenes WLAN des Pi", font=self.small, fill=0)
            d.text((ox, 14 + oy), self._fit(d, "Name: " + ap.get("ssid", ""), self.small, W), font=self.small, fill=1)
            d.text((ox, 26 + oy), self._fit(d, "Passwort: " + ap.get("pw", ""), self.small, W), font=self.small, fill=1)
            d.text((ox, 38 + oy), self._fit(d, "http://" + ap.get("ip", ""), self.big, W), font=self.big, fill=1)
            d.text((ox, 53 + oy), "kein Kabel, kein WLAN", font=self.small, fill=1)
            return
        d.text((ox, oy), name + ".local", font=self.big, fill=1)
        if mode == "lan":
            lines = ["Kabel", n.get("eth_ip", "")]
        elif mode == "wlan":
            lines = ["WLAN " + n.get("wlan_ssid", ""), n.get("wlan_ip", "")]
        elif mode == "party":
            lines = ["Party " + (n.get("ap") or {}).get("ssid", ""), (n.get("ap") or {}).get("ip", "")]
        elif mode == "none":
            lines = ["kein Netz", "suche …"]
        else:
            lines = ["Netz unbekannt", st.get("ip", "")]
        d.text((ox, 17 + oy), self._fit(d, lines[0], self.big, W), font=self.big, fill=1)
        d.text((ox, 33 + oy), lines[1], font=self.big, fill=1)
        s = st.get("stream") or {}
        d.text((ox, 52 + oy), self._fit(d, "Stream %d/s an %d Picos" % (s.get("pps", 0), len(s.get("targets", []))) if s.get("on")
                                        else "Stream-Verteiler aus", self.small, W), font=self.small, fill=1)

    def _play(self, d, st, ox, oy):
        p = st.get("player") or {}
        now = p.get("now") or {}
        state = p.get("state")
        if state in ("play", "load"):                                   # icons drawn: fonts lack the glyphs
            d.polygon([(ox, oy + 1), (ox, oy + 9), (ox + 6, oy + 5)], fill=1)
        elif state == "pause":
            d.rectangle((ox, oy + 1, ox + 1, oy + 9), fill=1)
            d.rectangle((ox + 4, oy + 1, ox + 5, oy + 9), fill=1)
        else:
            d.rectangle((ox, oy + 2, ox + 6, oy + 8), fill=1)
        secs = now.get("secs") or 0
        el = p.get("el") or 0
        head = fmt(el) + (" / " + fmt(secs) if secs else "")
        d.text((ox + 10, oy), head, font=self.small, fill=1)
        if now.get("songs", 1) > 1:
            t = "%d/%d" % (now.get("song", 1), now["songs"])
            d.text((W - d.textlength(t, font=self.small) - 1 + ox, oy), t, font=self.small, fill=1)
        d.text((ox, 13 + oy), self._fit(d, now.get("title") or now.get("name") or "Nichts läuft", self.big, W), font=self.big, fill=1)
        d.text((ox, 29 + oy), self._fit(d, now.get("author") or "", self.small, W), font=self.small, fill=1)
        if secs:
            d.rectangle((ox, 42 + oy, W - 1, 46 + oy), outline=1)
            d.rectangle((ox, 42 + oy, ox + int((W - 1 - ox) * min(1, el / secs)), 46 + oy), fill=1)
        s = st.get("stream") or {}
        foot = ("Stream %d/s → %d Picos" % (s.get("pps", 0), len(s.get("targets", [])))) if s.get("on") else \
            "%d Titel in der Liste" % p.get("total", 0)
        d.text((ox, 52 + oy), self._fit(d, foot, self.small, W), font=self.small, fill=1)


class Display:
    """the jukebox's side: finds the display (OLED on I2C or the 2.8" TFT on SPI), chooses the page, sends only changed
    pictures; on the TFT also the touch (buttons, page change, calibration). tick() runs in a worker thread about once a
    second, the touch in its own thread - both draw under self.lock."""
    TFT_MSG = {"own": "2,8″-Display (ILI9341) an SPI 0.0, Touch an SPI 1.0", "shared": "2,8″-Display (ILI9341) an SPI 0.0, Touch an SPI 0.1"}

    def __init__(self, settings, bus_factory=I2CBus, clock=time.monotonic, hw=None, on_touch=None, save=None,
                 touch_thread=True):
        self.settings, self.bus_factory, self.clock = settings, bus_factory, clock
        self.hw = hw                                   # tft.Hardware (the tests pass a fake)
        self.on_touch = on_touch or (lambda what: None)
        self.save = save or (lambda: None)
        self.touch_thread = touch_thread
        self.dev = None
        self.tft = False
        self.screen = None
        self.reader = None
        self.msg = ""
        self.last_img = None
        self.next_try = 0.0
        self.last_active = clock()
        self.last_key = None
        self.t0 = clock()
        self.reopen = False
        self.lock = threading.RLock()
        self.last_st = None
        self.page = None
        self.dark = False
        self.override = None                           # (page, until): chosen by a tap
        self.cal_step = None                           # 0..2 while the crosses are shown
        self.cal_raw = []
        self.cal_note = ""

    def close(self):
        if self.reader:
            self.reader.stop.set()
            self.reader = None
        if self.dev:
            try:
                self.dev.close()
            except OSError:
                pass
        self.dev = None
        self.screen = None

    def _open(self):
        st = self.settings()
        kind = st.get("type", "auto")
        if kind == "off":
            self.close()
            self.msg = "aus"
            return False
        if self.dev:
            return True
        if self.clock() < self.next_try:
            return False
        self.next_try = self.clock() + 30
        try:
            if kind == "tft":
                from .tft import Hardware, Ili9341, TftScreen, TouchReader
                self.hw = self.hw or Hardware()
                self.screen = TftScreen()
                touch = "shared" if st.get("touch") == "shared" else "own"
                self.dev = Ili9341(self.hw, flip=bool(st.get("flip")), touch=touch, dc=int(st.get("dc") or 24))
                self.tft = True
                self.msg = self.TFT_MSG[touch]
                if self.touch_thread:
                    self.reader = TouchReader(self.dev.touch, self.touch_raw)
                    self.reader.start()
                if not st.get("cal"):
                    self.calibrate()
            else:
                self.screen = Screen()
                self.dev = Oled(self.bus_factory(), "sh1106" if kind == "sh1106" else "ssd1306")
                self.tft = False
                self.msg = "%s an 0x%02X" % (self.dev.kind.upper(), self.dev.addr)
            self.last_img = None
            return True
        except (OSError, ImportError) as e:
            self.close()
            self.msg = "nicht gefunden (%s)" % e
            if "spidev1.0" in str(e):                    # the second SPI bus comes with install.sh + one restart
                self.msg = "zweiter SPI-Bus für den Touch fehlt – Pi einmal neu starten (sudo reboot)"
            return False

    def page_for(self, st):
        n = st.get("net") or {}
        p = st.get("player") or {}
        if self.tft:
            if self.override and self.clock() < self.override[1]:
                return self.override[0]
            if n.get("mode") in ("ap", "none"):
                return "net"
            return "play" if p.get("state") in ("play", "pause", "load") or p.get("total") else "net"
        if n.get("mode") in ("ap", "none") or p.get("state") not in ("play", "pause", "load"):
            return "net"
        return "play" if int((self.clock() - self.t0) / 8) % 2 == 0 else "net"

    def frame(self, st):
        """-> (picture, page) or None while the display sleeps"""
        p = st.get("player") or {}
        n = st.get("net") or {}
        key = (p.get("state"), (p.get("now") or {}).get("md5"), n.get("mode"), (n.get("ap") or {}).get("ssid"))
        now = self.clock()
        if p.get("state") in ("play", "load") or key != self.last_key or self.cal_step is not None:
            self.last_active = now
        self.last_key = key
        if self.tft and self.cal_step is not None:
            return self.screen.render(st, "cal", self.cal_step, self.cal_note), "cal"
        off = float(self.settings().get("off_min", 10) or 0) * 60
        if off and now - self.last_active > off and n.get("mode") != "ap":
            return None
        page = self.page_for(st)
        if self.tft:
            return self.screen.render(st, page), page
        return self.screen.render(st, page, shift=int((now - self.t0) / 60)), page

    def _draw(self, st):
        fr = self.frame(st)
        if fr is None:
            self.dev.power(False)
            self.dark = True
            return
        img, self.page = fr
        data = img.tobytes()
        if data != self.last_img:
            self.dev.show(img)
            self.last_img = data
        self.dev.power(True)
        self.dark = False

    def tick(self, st):
        """called about once a second (in a worker thread: an I2C/SPI write takes up to 0.1 s)"""
        if self.reopen:
            self.reopen = False
            self.close()
            self.next_try = 0.0
        if not self._open():
            return
        with self.lock:
            self.last_st = st
            try:
                self._draw(st)
            except OSError as e:
                self.msg = "Fehler: %s" % e
                self.close()

    def redraw(self):
        """after a tap: draw at once with the last known state (not only at the next tick)"""
        with self.lock:
            if self.dev and self.last_st is not None:
                try:
                    self._draw(self.last_st)
                except OSError as e:
                    self.msg = "Fehler: %s" % e

    # ---- touch (TFT only) ----
    def calibrate(self):
        """show the three crosses; -> False without a touch display"""
        if not self.tft or not self.dev:
            return False
        self.cal_step, self.cal_raw, self.cal_note = 0, [], ""
        self.last_active = self.clock()
        return True

    def touch_raw(self, rx, ry):
        """a tap with the controller's raw values (from the touch thread)"""
        from .tft import calibrate, map_touch
        st = self.settings()
        self.last_active = self.clock()
        if self.dark:                                  # the first tap only wakes the display
            self.redraw()
            return "wake"
        if self.cal_step is not None:
            self.cal_raw.append((rx, ry))
            self.cal_step += 1
            if self.cal_step == 3:
                cal = calibrate(self.cal_raw)
                if cal:
                    cal["flip"] = bool(st.get("flip"))
                    st["cal"] = cal
                    self.save()
                    self.cal_step, self.cal_note = None, ""
                else:
                    self.cal_step, self.cal_raw, self.cal_note = 0, [], "Nicht erkannt – bitte noch einmal"
            self.redraw()
            return "cal"
        cal = st.get("cal")
        if not cal:
            return None
        return self.tap(*map_touch(cal, (rx, ry), bool(st.get("flip")) != bool(cal.get("flip"))))

    def tap(self, x, y):
        """a tap at screen coordinates: a button -> on_touch(what), elsewhere the other page for 30 s"""
        if not self.screen:
            return None
        for (x0, y0, x1, y1), what in self.screen.buttons(self.page):
            if x0 <= x <= x1 and y0 <= y <= y1:
                self._flash((x0, y0, x1 + 1, y1 + 1))
                self.on_touch(what)
                return what
        order = ["play", "level", "net"]                  # a tap elsewhere: the next page, 30 s long
        other = order[(order.index(self.page) + 1) % len(order)] if self.page in order else "play"
        self.override = (other, self.clock() + 30)
        self.redraw()
        return "page"

    def _flash(self, box):
        """the pressed button lights up until the next picture"""
        from PIL import ImageOps
        with self.lock:
            prev = getattr(self.dev, "prev", None)
            if prev is None:
                return
            img = prev.copy()
            img.paste(ImageOps.invert(img.crop(box)), box[:2])
            try:
                self.dev.show(img)
                self.last_img = None
            except OSError:
                pass
