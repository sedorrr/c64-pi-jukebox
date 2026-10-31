"""2.8" colour display with touch on the Pi: ILI9341 (320 x 240, SPI) + XPT2046 touch controller (the red 86 x 50 mm
boards, "MSP2807", ARCELI, AZDelivery ...). Talks to the kernel directly - /dev/spidev0.0 (display), the touch on its
own bus /dev/spidev1.0 (or, wired with Y cables, /dev/spidev0.1) and /dev/gpiochip0 (DC, RESET, backlight, touch
interrupt) - no extra library. The second bus needs "dtoverlay=spi1-1cs,cs0_pin=16" (install.sh; CE0 moved off
GPIO18, which is the backlight).

Wiring (Pi header pin -> module pin), one cable per pin:
    1  3V3      VCC            19 MOSI     SDI(MOSI)              24 CE0    CS
    6  GND      GND            23 SCLK     SCK                    12 GPIO18 LED (backlight)
   18  GPIO24   DC             22 GPIO25   RESET
   40  GPIO21   T_CLK          38 GPIO20   T_DIN      35 GPIO19   T_DO      36 GPIO16  T_CS     11 GPIO17  T_IRQ
With Y cables ("touch": "shared"): T_DIN on 19 and T_CLK on 23 too, T_DO on 21 (MISO), T_CS on 26 (CE1).
The display's SDO stays free: on many boards it does not let go of the line and would disturb the touch readings.

Drawing: Pillow pictures (RGB, 320 x 240); only the changed rectangle is sent. The touch is read ~50 times a second in
its own thread; a tap counts when the finger is lifted."""
import ctypes
import fcntl
import os
import threading
import time

from .i18n import tr

W, H = 320, 240
PIN_DC, PIN_RESET, PIN_LED, PIN_IRQ = 24, 25, 18, 17
# D/C: GPIO -> header pin. 23 (pin 16) and 6 (pin 31) for a Pi whose GPIO24 is damaged; pin 31 has only GPIOs as
# neighbours (pins 16 and 18 sit next to GND - a plug slipping there while the pin drives high can destroy it)
PINS_DC = {24: 18, 23: 16, 6: 31}
SPI_DISPLAY = "/dev/spidev0.0"
SPI_TOUCH = {"own": "/dev/spidev1.0", "shared": "/dev/spidev0.1"}       # own bus (no Y cables) / shared with the display
SPEED_DISPLAY, SPEED_TOUCH = 16_000_000, 1_000_000


def _iow(nr, size, t=0x6B):
    return (1 << 30) | (size << 16) | (t << 8) | nr


def _iowr(nr, size, t=0xB4):
    return (3 << 30) | (size << 16) | (t << 8) | nr


SPI_IOC_WR_MODE = _iow(1, 1)
SPI_IOC_WR_MAX_SPEED_HZ = _iow(4, 4)
SPI_IOC_MESSAGE_1 = _iow(0, 32)


class SpiXfer(ctypes.Structure):          # struct spi_ioc_transfer
    _fields_ = [("tx_buf", ctypes.c_uint64), ("rx_buf", ctypes.c_uint64), ("len", ctypes.c_uint32),
                ("speed_hz", ctypes.c_uint32), ("delay_usecs", ctypes.c_uint16), ("bits_per_word", ctypes.c_uint8),
                ("cs_change", ctypes.c_uint8), ("tx_nbits", ctypes.c_uint8), ("rx_nbits", ctypes.c_uint8),
                ("word_delay_usecs", ctypes.c_uint8), ("pad", ctypes.c_uint8)]


class Spi:
    """spidev: write() for the display, xfer() (full duplex) for the touch controller"""
    CHUNK = 4096                          # spidev's default bufsiz

    def __init__(self, path, speed):
        self.fd = os.open(path, os.O_RDWR)
        self.speed = speed
        fcntl.ioctl(self.fd, SPI_IOC_WR_MODE, bytes([0]))
        fcntl.ioctl(self.fd, SPI_IOC_WR_MAX_SPEED_HZ, speed.to_bytes(4, "little"))

    def write(self, data):
        for k in range(0, len(data), self.CHUNK):
            os.write(self.fd, data[k:k + self.CHUNK])

    def xfer(self, data):
        tx = ctypes.create_string_buffer(bytes(data), len(data))
        rx = ctypes.create_string_buffer(len(data))
        x = SpiXfer(tx_buf=ctypes.addressof(tx), rx_buf=ctypes.addressof(rx), len=len(data), speed_hz=self.speed,
                    bits_per_word=8)
        fcntl.ioctl(self.fd, SPI_IOC_MESSAGE_1, x)
        return rx.raw

    def close(self):
        os.close(self.fd)


# ---- GPIO character device, uAPI v2 (linux/gpio.h) ----
GPIO_V2_LINE_FLAG_INPUT, GPIO_V2_LINE_FLAG_OUTPUT, GPIO_V2_LINE_FLAG_BIAS_PULL_UP = 1 << 2, 1 << 3, 1 << 8
GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES = 2


class _Attr(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint32), ("padding", ctypes.c_uint32), ("values", ctypes.c_uint64)]


class _CfgAttr(ctypes.Structure):
    _fields_ = [("attr", _Attr), ("mask", ctypes.c_uint64)]


class _LineConfig(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("num_attrs", ctypes.c_uint32), ("padding", ctypes.c_uint32 * 5),
                ("attrs", _CfgAttr * 10)]


class _LineRequest(ctypes.Structure):
    _fields_ = [("offsets", ctypes.c_uint32 * 64), ("consumer", ctypes.c_char * 32), ("config", _LineConfig),
                ("num_lines", ctypes.c_uint32), ("event_buffer_size", ctypes.c_uint32),
                ("padding", ctypes.c_uint32 * 5), ("fd", ctypes.c_int32)]


class _LineValues(ctypes.Structure):
    _fields_ = [("bits", ctypes.c_uint64), ("mask", ctypes.c_uint64)]


GPIO_V2_GET_LINE_IOCTL = _iowr(0x07, ctypes.sizeof(_LineRequest))
GPIO_V2_LINE_GET_VALUES_IOCTL = _iowr(0x0E, ctypes.sizeof(_LineValues))
GPIO_V2_LINE_SET_VALUES_IOCTL = _iowr(0x0F, ctypes.sizeof(_LineValues))


class Gpio:
    """a few lines of /dev/gpiochip0 (offset = BCM number on the Pi 3): outputs with start values, inputs with pull-up"""

    def __init__(self, outputs, inputs=(), chip="/dev/gpiochip0"):
        self.fds = {}
        self.index = {}
        chip_fd = os.open(chip, os.O_RDWR)
        try:
            if outputs:
                self._request(chip_fd, list(outputs), GPIO_V2_LINE_FLAG_OUTPUT, outputs)
            if inputs:
                self._request(chip_fd, list(inputs), GPIO_V2_LINE_FLAG_INPUT | GPIO_V2_LINE_FLAG_BIAS_PULL_UP, None)
        finally:
            os.close(chip_fd)

    def _request(self, chip_fd, lines, flags, values):
        req = _LineRequest()
        for i, n in enumerate(lines):
            req.offsets[i] = n
        req.consumer = b"c64jukebox"
        req.num_lines = len(lines)
        req.config.flags = flags
        if values:
            bits = sum(1 << i for i, n in enumerate(lines) if values[n])
            req.config.num_attrs = 1
            req.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES
            req.config.attrs[0].attr.values = bits
            req.config.attrs[0].mask = (1 << len(lines)) - 1
        fcntl.ioctl(chip_fd, GPIO_V2_GET_LINE_IOCTL, req)
        for i, n in enumerate(lines):
            self.fds[n] = req.fd
            self.index[n] = i

    def _fd(self, line):
        fd = self.fds.get(line)
        if fd is None:                    # closed meanwhile (the touch thread may still be reading): an OSError
            raise OSError(9, "GPIO line %d closed" % line)
        return fd

    def set(self, line, value):
        v = _LineValues(bits=(1 << self.index[line]) if value else 0, mask=1 << self.index[line])
        fcntl.ioctl(self._fd(line), GPIO_V2_LINE_SET_VALUES_IOCTL, v)

    def get(self, line):
        v = _LineValues(mask=1 << self.index[line])
        fcntl.ioctl(self._fd(line), GPIO_V2_LINE_GET_VALUES_IOCTL, v)
        return bool(v.bits >> self.index[line] & 1)

    def close(self):
        for fd in set(self.fds.values()):
            os.close(fd)
        self.fds = {}


class Hardware:
    """what the TFT needs from the Pi; the tests replace it"""

    def spi(self, path, speed):
        return Spi(path, speed)

    def gpio(self, outputs, inputs):
        return Gpio(outputs, inputs)

    def sleep(self, s):
        time.sleep(s)


# ---- ILI9341 ----
GAMMA_P = bytes([0x0F, 0x31, 0x2B, 0x0C, 0x0E, 0x08, 0x4E, 0xF1, 0x37, 0x07, 0x10, 0x03, 0x0E, 0x09, 0x00])
GAMMA_N = bytes([0x00, 0x0E, 0x14, 0x03, 0x11, 0x07, 0x31, 0xC1, 0x48, 0x08, 0x0F, 0x0C, 0x31, 0x36, 0x0F])
MADCTL_LANDSCAPE, MADCTL_FLIPPED = 0x28, 0xE8        # MV|BGR, MY|MX|MV|BGR


def rgb565(img):
    """Pillow RGB picture -> big-endian RGB565 bytes, as the ILI9341 takes them"""
    from PIL import Image, ImageChops
    r, g, b = img.convert("RGB").split()
    hi = ImageChops.add(r.point(lambda v: v & 0xF8), g.point(lambda v: v >> 5))
    lo = ImageChops.add(g.point(lambda v: (v & 0x1C) << 3), b.point(lambda v: v >> 3))
    return Image.merge("LA", (hi, lo)).tobytes()


class Ili9341:
    kind = "ILI9341"

    def __init__(self, hw, flip=False, touch="own", dc=PIN_DC):
        self.hw = hw
        self.dc = dc if dc in PINS_DC else PIN_DC
        self.spi = hw.spi(SPI_DISPLAY, SPEED_DISPLAY)
        self.gpio = hw.gpio({self.dc: 0, PIN_RESET: 1, PIN_LED: 0}, [PIN_IRQ])
        self.touch = Xpt2046(hw.spi(SPI_TOUCH.get(touch, SPI_TOUCH["own"]), SPEED_TOUCH), self.gpio)
        self.lock = threading.Lock()
        self.prev = None
        self.on = False
        self.init(flip)

    def cmd(self, c, data=b""):
        self.gpio.set(self.dc, 0)
        self.spi.write(bytes([c]))
        if data:
            self.gpio.set(self.dc, 1)
            self.spi.write(bytes(data))

    def init(self, flip):
        self.gpio.set(PIN_RESET, 0)
        self.hw.sleep(0.02)
        self.gpio.set(PIN_RESET, 1)
        self.hw.sleep(0.15)
        self.cmd(0x01)                    # software reset
        self.hw.sleep(0.15)
        for c, d in ((0xEF, b"\x03\x80\x02"), (0xCF, b"\x00\xC1\x30"), (0xED, b"\x64\x03\x12\x81"),
                     (0xE8, b"\x85\x00\x78"), (0xCB, b"\x39\x2C\x00\x34\x02"), (0xF7, b"\x20"), (0xEA, b"\x00\x00"),
                     (0xC0, b"\x23"), (0xC1, b"\x10"), (0xC5, b"\x3E\x28"), (0xC7, b"\x86"),
                     (0x36, bytes([MADCTL_FLIPPED if flip else MADCTL_LANDSCAPE])), (0x37, b"\x00"),
                     (0x3A, b"\x55"), (0xB1, b"\x00\x18"), (0xB6, b"\x08\x82\x27"), (0xF2, b"\x00"), (0x26, b"\x01"),
                     (0xE0, GAMMA_P), (0xE1, GAMMA_N)):
            self.cmd(c, d)
        self.cmd(0x11)                    # sleep out
        self.hw.sleep(0.12)
        self.cmd(0x29)                    # display on (the backlight comes with power(True))

    def window(self, x0, y0, x1, y1):
        self.cmd(0x2A, bytes([x0 >> 8, x0 & 255, x1 >> 8, x1 & 255]))
        self.cmd(0x2B, bytes([y0 >> 8, y0 & 255, y1 >> 8, y1 & 255]))

    def power(self, on):
        if on != self.on:
            with self.lock:
                self.gpio.set(PIN_LED, 1 if on else 0)
            self.on = on

    def show(self, img):
        """sends the rectangle that differs from the last picture (all of it the first time)"""
        from PIL import ImageChops
        with self.lock:
            box = (0, 0, W, H) if self.prev is None else ImageChops.difference(img, self.prev).getbbox()
            if not box:
                return False
            x0, y0, x1, y1 = box
            self.window(x0, y0, x1 - 1, y1 - 1)
            self.cmd(0x2C, rgb565(img.crop(box)))
            self.prev = img.copy()
            return True

    def close(self):
        try:
            self.gpio.set(PIN_LED, 0)
        except OSError:
            pass
        for x in (self.spi, self.touch.spi, self.gpio):
            try:
                x.close()
            except OSError:
                pass


class Xpt2046:
    """resistive touch: raw 12-bit X/Y while T_IRQ is low"""
    Z_MIN = 80                            # pressure below this is no touch (noise at the edge of a light tap)

    def __init__(self, spi, gpio):
        self.spi, self.gpio = spi, gpio

    def _read(self, cmd):
        r = self.spi.xfer([cmd, 0, 0])
        return ((r[1] << 8) | r[2]) >> 3

    def read(self):
        """-> (raw_x, raw_y) or None when nothing touches"""
        if self.gpio.get(PIN_IRQ):
            return None
        if self._read(0xB0) < self.Z_MIN:             # Z1 = pressure
            return None
        xs = sorted(self._read(0xD0) for _ in range(5))
        ys = sorted(self._read(0x90) for _ in range(5))
        if self.gpio.get(PIN_IRQ):                    # let go while measuring: not trustworthy
            return None
        return xs[2], ys[2]


class TouchReader(threading.Thread):
    """polls the touch controller; a tap = touched and lifted again -> on_tap(raw_x, raw_y) (median of the samples)"""

    def __init__(self, touch, on_tap, period=0.02, sleep=time.sleep):
        super().__init__(daemon=True, name="touch")
        self.touch, self.on_tap, self.period, self.sleep = touch, on_tap, period, sleep
        self.stop = threading.Event()

    def step(self, samples):
        try:
            p = self.touch.read()
        except OSError:
            p = None
        if p:
            samples.append(p)
            return samples
        if len(samples) >= 2:                         # at least 40 ms: no single spike
            xs = sorted(s[0] for s in samples[1:] or samples)
            ys = sorted(s[1] for s in samples[1:] or samples)
            self.on_tap(xs[len(xs) // 2], ys[len(ys) // 2])
        return []

    def run(self):
        samples = []
        while not self.stop.is_set():
            self.sleep(self.period)
            samples = self.step(samples)


# ---- calibration: three crosses, from them which raw axis is x and how it scales ----
CAL_POINTS = [(24, 24), (W - 24, 24), (24, H - 24)]


def calibrate(raws):
    """raws: raw (x, y) at the three CAL_POINTS -> calibration dict, or None if the taps make no sense"""
    (a, b, c) = raws
    ax = 0 if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else 1
    ay = 1 - ax
    cal = {"ax": ax, "x0": a[ax], "x1": b[ax], "y0": a[ay], "y1": c[ay]}
    if abs(cal["x1"] - cal["x0"]) < 400 or abs(cal["y1"] - cal["y0"]) < 300:
        return None
    return cal


def map_touch(cal, raw, flipped=False):
    """raw (x, y) -> screen (x, y); flipped: the picture was turned by 180 degrees after calibrating"""
    (x0, y0), (x1, _), (_, y1) = CAL_POINTS
    ax = cal["ax"]
    x = x0 + (raw[ax] - cal["x0"]) * (x1 - x0) / (cal["x1"] - cal["x0"])
    y = y0 + (raw[1 - ax] - cal["y0"]) * (y1 - y0) / (cal["y1"] - cal["y0"])
    if flipped:
        x, y = W - 1 - x, H - 1 - y
    return max(0, min(W - 1, int(x))), max(0, min(H - 1, int(y)))


# ---- what the colour display shows ----
BLUE, LIGHT, WHITE, DARK = (64, 49, 141), (120, 105, 196), (255, 255, 255), (40, 30, 95)    # C64 blue / light blue
SOFT = (175, 165, 240)                    # secondary text: light blue, a little brighter for the small screen
BUTTONS = [((8, 166, 76, 232), "prev"), ((84, 166, 156, 232), "stop"), ((164, 166, 236, 232), "next"),
           ((244, 166, 312, 232), "power")]
POWER_BUTTONS = [((8, 50, 156, 108), "tvon"), ((164, 50, 312, 108), "tvoff"), ((8, 116, 312, 170), "pioff"),
                 ((8, 178, 312, 232), "back")]
RED = (136, 0, 0)                         # C64 red: the button that switches the jukebox off
BOLD = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def bold(size):
    from PIL import ImageFont
    for p in BOLD:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    from .display import font
    return font(size)


class TftScreen:
    """320 x 240 pages in C64 colours: "play" (with four touch buttons), "level" (meters), "net", "power" (TV on/off,
    jukebox off), "cal" (crosses)"""

    def __init__(self):
        from .display import font
        self.title = bold(22)
        self.mid = font(17)
        self.small = font(14)
        self.head = bold(15)

    @staticmethod
    def _fit(d, text, f, width):
        if d.textlength(text, font=f) <= width:
            return text
        while text and d.textlength(text + "…", font=f) > width:
            text = text[:-1]
        return text + "…"

    def _wrap(self, d, text, f, width, lines):
        words, out = text.split(), []
        while words and len(out) < lines:
            line = words.pop(0)
            while words and d.textlength(line + " " + words[0], font=f) <= width:
                line += " " + words.pop(0)
            out.append(line)
        if words:
            out[-1] = self._fit(d, out[-1] + " " + " ".join(words), f, width)
        return [self._fit(d, x, f, width) for x in out]

    def render(self, st, page, cal_step=0, note=""):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (W, H), BLUE)
        d = ImageDraw.Draw(img)
        if page == "cal":
            self._cal(d, cal_step, note)
        elif page == "net":
            self._net(d, st.get("net") or {}, st)
        elif page == "level":
            self._level(d, st)
        elif page == "power":
            self._power(d, st)
        else:
            self._play(d, st)
        return img

    def _level(self, d, st):
        """two meters (left / right, held peaks) and the last 15 s as columns - like the C64's colour bars"""
        p = st.get("player") or {}
        now = p.get("now") or {}
        lv = st.get("level") or {}
        self._bar(d, tr("Pegel"), self._fit(d, now.get("title") or now.get("name") or "", self.head, 200))
        cols = [(0, 204, 85), (238, 238, 119), (221, 136, 85), (136, 0, 0)]     # C64 green, yellow, orange, red
        x0, w = 34, W - 34 - 10
        for k, (label, y) in enumerate((("L", 40), ("R", 76))):
            d.text((10, y + 2), label, font=self.mid, fill=WHITE)
            d.rectangle((x0, y, x0 + w, y + 26), outline=LIGHT)
            segs = 24
            on = int(round(min(1.0, (lv.get("now") or [0, 0])[k]) * segs))
            for s_ in range(segs):
                c = cols[0] if s_ < segs * 0.6 else cols[1] if s_ < segs * 0.8 else cols[2] if s_ < segs * 0.92 else cols[3]
                sx = x0 + 2 + s_ * (w - 3) // segs
                if s_ < on:
                    d.rectangle((sx, y + 3, sx + (w - 3) // segs - 2, y + 23), fill=c)
            pk = min(1.0, (lv.get("peak") or [0, 0])[k])
            if pk > 0.02:
                px = x0 + 2 + int(pk * (w - 6))
                d.rectangle((px, y + 2, px + 2, y + 24), fill=WHITE)
        # the last seconds: one column per quarter second, newest on the right
        hist = lv.get("hist") or []
        top, bot = 118, 222
        d.rectangle((10, top - 4, W - 10, bot + 2), outline=DARK)
        n = 60
        cw = (W - 24) / n
        for i, v in enumerate(hist[-n:]):
            h_ = int(min(1.0, v) * (bot - top))
            x = 12 + (n - len(hist[-n:]) + i) * cw
            c = cols[0] if v < 0.6 else cols[1] if v < 0.8 else cols[2] if v < 0.92 else cols[3]
            if h_ > 0:
                d.rectangle((int(x), bot - h_, int(x + cw) - 1, bot), fill=c)
        from .display import fmt
        secs, el = now.get("secs") or 0, p.get("el") or 0
        if p.get("state") in ("play", "pause", "load"):
            d.text((10, 226), fmt(el) + (" / " + fmt(secs) if secs else ""), font=self.small, fill=WHITE)
        t = tr("Tippen: nächste Seite")
        d.text((W - 10 - d.textlength(t, font=self.small), 226), t, font=self.small, fill=SOFT)

    def buttons(self, page):
        return BUTTONS if page == "play" else POWER_BUTTONS if page == "power" else []

    def _power(self, d, st):
        """TV on / off (HDMI-CEC), the jukebox off - a second tap within a few seconds (st["armed"])"""
        tv = st.get("tvctl") or {}
        state = {"on": tr("Fernseher an"), "standby": tr("Fernseher aus")}.get(tv.get("tv"), "") if tv.get("ready") else ""
        self._bar(d, tr("Ein / Aus"), state)
        note = st.get("pnote") or ("" if tv.get("ready") else tr("TV-Fernbedienung (HDMI-CEC) ist aus"))
        d.text((8, 30), self._fit(d, note, self.small, W - 16), font=self.small, fill=SOFT)
        labels = {"tvon": tr("Fernseher an"), "tvoff": tr("Fernseher aus"), "back": tr("Zurück"),
                  "pioff": tr("Nochmal tippen: ausschalten") if st.get("armed") else tr("Jukebox ausschalten")}
        for (x0, y0, x1, y1), what in POWER_BUTTONS:
            off = what in ("tvon", "tvoff") and not tv.get("ready")
            fill = RED if what == "pioff" else (56, 44, 118) if off else LIGHT
            text = WHITE if what == "pioff" else (105, 92, 170) if off else DARK
            d.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=fill)
            t = self._fit(d, labels[what], self.head, x1 - x0 - 12)
            d.text(((x0 + x1 - d.textlength(t, font=self.head)) // 2, (y0 + y1) // 2 - 9), t, font=self.head, fill=text)

    def _bar(self, d, left, right=""):
        d.rectangle((0, 0, W - 1, 25), fill=LIGHT)
        d.text((8, 4), left, font=self.head, fill=BLUE)
        if right:
            d.text((W - 8 - d.textlength(right, font=self.head), 4), right, font=self.head, fill=BLUE)

    def _play(self, d, st):
        p = st.get("player") or {}
        now = p.get("now") or {}
        state = p.get("state")
        secs, el = now.get("secs") or 0, p.get("el") or 0
        from .display import fmt
        head = {"play": "", "load": tr("lädt … "), "pause": tr("Pause") + "  ", "stop": tr("Stopp") + "  "}.get(state, "") + \
            (fmt(el) + (" / " + fmt(secs) if secs else "") if state in ("play", "pause", "load") else "")
        self._bar(d, head.strip() or tr("Stopp"), tr("Lied %d/%d") % (now.get("song", 1), now["songs"])
                  if now.get("songs", 1) > 1 and state != "stop" else "")
        title = now.get("title") or now.get("name") or (tr("Nichts läuft") if state != "stop" or not p.get("total")
                                                         else tr("Bereit"))
        y = 32
        for line in self._wrap(d, title, self.title, W - 16, 2):
            d.text((8, y), line, font=self.title, fill=WHITE)
            y += 27
        y = max(y + 2, 62)
        d.text((8, y), self._fit(d, now.get("author") or "", self.mid, W - 16), font=self.mid, fill=SOFT)
        extra = now.get("released") or ""
        if (now.get("chips") or 1) > 1:
            extra += ("  ·  " if extra else "") + "%d SIDs" % now["chips"]
        if extra and y < 90:
            d.text((8, y + 22), self._fit(d, extra, self.small, W - 16), font=self.small, fill=SOFT)
        if secs and state in ("play", "pause", "load"):
            d.rectangle((8, 118, W - 9, 130), outline=LIGHT)
            d.rectangle((10, 120, 10 + int((W - 21) * min(1, el / secs)), 128), fill=WHITE)
        s = st.get("stream") or {}
        foot = (tr("Stream %d/s → %d Picos") % (s.get("pps", 0), len(s.get("targets", [])))) if s.get("on") else \
            tr("%d Titel in der Liste") % p.get("total", 0)
        d.text((8, 138), self._fit(d, foot, self.small, W - 16), font=self.small, fill=SOFT)
        for (x0, y0, x1, y1), what in BUTTONS:
            d.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=LIGHT)
            self._icon(d, what, (x0 + x1) // 2, (y0 + y1) // 2, state)

    @staticmethod
    def _icon(d, what, cx, cy, state):
        c = BLUE
        if what == "power":                           # the power sign: an open ring and a bar
            d.arc((cx - 15, cy - 13, cx + 15, cy + 17), 300, 240, fill=c, width=4)
            d.rectangle((cx - 2, cy - 18, cx + 2, cy + 2), fill=c)
            return
        if what == "stop":                            # stop while a tune plays (or pauses), else play
            if state in ("play", "load", "pause"):
                d.rectangle((cx - 14, cy - 14, cx + 14, cy + 14), fill=c)
            else:
                d.polygon([(cx - 11, cy - 17), (cx - 11, cy + 17), (cx + 16, cy)], fill=c)
            return
        s = -1 if what == "prev" else 1               # two triangles and a bar, mirrored for "prev"
        for base in (cx - 14 * s, cx):
            d.polygon([(base, cy - 14), (base, cy + 14), (base + 15 * s, cy)], fill=c)
        bx = cx + 15 * s
        d.rectangle((min(bx, bx + 4 * s), cy - 14, max(bx, bx + 4 * s), cy + 14), fill=c)

    def _net(self, d, n, st):
        mode = n.get("mode", "unknown")
        name = st.get("name") or "c64pi"
        if mode == "ap" and n.get("ap"):
            ap = n["ap"]
            self._bar(d, tr("Eigenes WLAN des Pi"))
            rows = [(tr("WLAN-Name"), ap.get("ssid", "")), (tr("Passwort"), ap.get("pw", "")),
                    (tr("Danach im Browser"), "http://" + ap.get("ip", ""))]
            y = 34
            for label, value in rows:
                d.text((8, y), label, font=self.small, fill=SOFT)
                d.text((8, y + 17), self._fit(d, value, self.title, W - 16), font=self.title, fill=WHITE)
                y += 52
            d.text((8, 214), self._fit(d, tr("kein Kabel, kein bekanntes WLAN"), self.small, W - 16), font=self.small, fill=SOFT)
            return
        self._bar(d, tr("Netzwerk"))
        d.text((8, 34), self._fit(d, name + ".local", self.title, W - 16), font=self.title, fill=WHITE)
        if mode == "lan":
            lines = [tr("Netzwerkkabel"), n.get("eth_ip", "")]
        elif mode == "wlan":
            lines = [tr("WLAN %s") % n.get("wlan_ssid", ""), n.get("wlan_ip", "")]
        elif mode == "party":
            lines = [tr("Party-WLAN %s") % (n.get("ap") or {}).get("ssid", ""), (n.get("ap") or {}).get("ip", "")]
        elif mode == "none":
            lines = [tr("kein Netz"), tr("suche …")]
        else:
            lines = [tr("Netz unbekannt"), st.get("ip", "")]
        d.text((8, 70), self._fit(d, lines[0], self.mid, W - 16), font=self.mid, fill=SOFT)
        d.text((8, 94), lines[1], font=self.title, fill=WHITE)
        s = st.get("stream") or {}
        if s.get("on"):
            txt = tr("Stream %d/s an %d Picos") % (s.get("pps", 0), len(s.get("targets", [])))
        else:
            txt = tr("Stream-Verteiler aus")
        d.text((8, 136), self._fit(d, txt, self.mid, W - 16), font=self.mid, fill=SOFT)
        u = st.get("ultimate") or ""
        if u:
            d.text((8, 160), self._fit(d, "Ultimate: " + u, self.mid, W - 16), font=self.mid, fill=SOFT)
        d.text((8, 214), self._fit(d, tr("Tippen: zurück zur Wiedergabe"), self.small, W - 16), font=self.small, fill=SOFT)

    def _cal(self, d, step, note):
        d.rectangle((0, 0, W - 1, H - 1), fill=DARK)
        x, y = CAL_POINTS[min(step, 2)]
        d.line((x - 14, y, x + 14, y), fill=WHITE, width=2)
        d.line((x, y - 14, x, y + 14), fill=WHITE, width=2)
        d.ellipse((x - 5, y - 5, x + 5, y + 5), outline=WHITE)
        d.text((60, 92), tr("Touch einrichten (%d/3)") % (min(step, 2) + 1), font=self.head, fill=WHITE)
        for k, line in enumerate(self._wrap(d, tr("Mit einem Stift oder dem Fingernagel genau auf das Kreuz tippen."),
                                            self.small, W - 70, 3)):
            d.text((60, 116 + 18 * k), line, font=self.small, fill=SOFT)
        if note:
            d.text((60, 178), note, font=self.small, fill=WHITE)
