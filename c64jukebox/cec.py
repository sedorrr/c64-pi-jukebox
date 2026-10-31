"""The TV's remote control over HDMI-CEC: the Pi announces itself as a playback device ("C64-Jukebox") on the HDMI
cable, the TV sends the keys of its remote to it (play, pause, stop, forward/back, arrows), and the jukebox can switch
the TV on and to its input when a tune starts (and to standby on stop, if wanted).

Straight through the kernel's CEC interface (/dev/cec0, linux/cec.h ioctls), no package needed - the Pi 3B's vc4 HDMI
has a CEC adapter. CecProtocol is the part without the device (what a message means, what to answer), CecLink talks
to the device. Most TVs only send keys to the active source: the Pi becomes it when the TV switches to its input
(Set Stream Path / Routing Change), when it switches the TV on itself, or on "Fernseher auf den Pi umschalten"."""
import errno
import fcntl
from collections import deque
import os
import struct
import time

from .i18n import tr


def _ioc(d, nr, size):
    return (d << 30) | (size << 16) | (ord("a") << 8) | nr


MSG = struct.Struct("<QQIIII16sBBBBBBBx")               # struct cec_msg (56 bytes)
LOG_ADDRS = struct.Struct("<4sHBBII15s4s4s4s48sx")      # struct cec_log_addrs (92 bytes)
CAPS = struct.Struct("<32s32sIII")                       # struct cec_caps (76 bytes)
R, W = 2, 1
CEC_ADAP_G_CAPS = _ioc(R | W, 0, CAPS.size)
CEC_ADAP_G_PHYS_ADDR = _ioc(R, 1, 2)
CEC_ADAP_G_LOG_ADDRS = _ioc(R, 3, LOG_ADDRS.size)
CEC_ADAP_S_LOG_ADDRS = _ioc(R | W, 4, LOG_ADDRS.size)
CEC_TRANSMIT = _ioc(R | W, 5, MSG.size)
CEC_RECEIVE = _ioc(R | W, 6, MSG.size)
CEC_S_MODE = _ioc(W, 9, 4)
MODE_INITIATOR, MODE_FOLLOWER = 0x01, 0x10
# a playback device: CEC_OP_PRIM_DEVTYPE_PLAYBACK, CEC_LOG_ADDR_TYPE_PLAYBACK (2 would be a tuner), CEC_OP_ALL_DEVTYPE_PLAYBACK
PRIM_DEVTYPE_PLAYBACK, LOG_ADDR_TYPE_PLAYBACK, ALL_DEVTYPE_PLAYBACK = 4, 3, 0x10

TV, BROADCAST = 0, 15
# opcodes
FEATURE_ABORT, IMAGE_VIEW_ON, STANDBY = 0x00, 0x04, 0x36
DECK_CONTROL, PLAY, GIVE_DECK_STATUS, DECK_STATUS = 0x42, 0x41, 0x1A, 0x1B
USER_CONTROL_PRESSED, USER_CONTROL_RELEASED = 0x44, 0x45
GIVE_OSD_NAME, SET_OSD_NAME = 0x46, 0x47
ROUTING_CHANGE, ACTIVE_SOURCE, REQUEST_ACTIVE_SOURCE, SET_STREAM_PATH = 0x80, 0x82, 0x85, 0x86
MENU_REQUEST, MENU_STATUS = 0x8D, 0x8E
GIVE_DEVICE_POWER_STATUS, REPORT_POWER_STATUS = 0x8F, 0x90
INACTIVE_SOURCE = 0x9D

# remote keys (UI command codes) -> what the jukebox does
KEYS = {
    0x44: "play", 0x46: "pause", 0x61: "toggle", 0x45: "stop",
    0x4B: "next", 0x49: "next",                               # forward, fast forward
    0x4C: "prev", 0x48: "prev",                               # backward, rewind
    # the arrows and OK: the TV menu (tvmenu.py) when it is open, else next/previous tune and effect, OK opens it
    0x01: "up", 0x02: "down", 0x03: "left", 0x04: "right", 0x00: "select",
    0x09: "menu", 0x0A: "menu", 0x0B: "menu", 0x0C: "menu", 0x10: "menu", 0x11: "menu",   # root/setup/contents/... menu
    0x0D: "back",                                             # exit / back
    0x30: "song_next", 0x31: "song_prev",                     # channel up/down: the next/previous sub-tune
}
# German; tr() here only marks them for tools/i18n_check.py (German at import) - shown as tr(KEY_NAMES[k])
KEY_NAMES = {0x00: "OK", 0x01: tr("hoch"), 0x02: tr("runter"), 0x03: tr("links"), 0x04: tr("rechts"),
             0x09: tr("Menü"), 0x0A: "Setup", 0x0B: tr("Inhalt"), 0x0C: tr("Favoriten"), 0x0D: tr("Zurück"),
             0x10: tr("Hauptmenü"), 0x11: tr("Kontextmenü"), 0x30: tr("Kanal +"), 0x31: tr("Kanal –"),
             0x44: "Play", 0x45: "Stop", 0x46: "Pause", 0x48: tr("Rücklauf"), 0x49: tr("Vorlauf"), 0x4B: tr("vor"),
             0x4C: tr("zurück (Titel)"), 0x61: "Play/Pause"}
DECK = {1: "next", 2: "prev", 3: "stop"}                       # Deck Control: skip forward, skip back, stop
REPEAT_S = 0.35                                                # a held key repeats: once per 0.35 s at most


class CecProtocol:
    """messages in -> (command for the jukebox or None, answers to send); answers are (destination, bytes)"""

    def __init__(self, name="C64-Jukebox", clock=time.monotonic):
        self.name = name[:14]
        self.clock = clock
        self.la = 4                   # our logical address (playback device 1); the link sets the real one
        self.phys = 0xFFFF            # our physical address (from the TV's EDID), 0xFFFF = not known
        self.active = False           # we are the active source (the TV shows the Pi)
        self.playing = False
        self.last_key = None          # (code, time) - against a held key's repeats
        self.last = ""                # the last command, for the page
        self.recent = deque(maxlen=8)   # the last commands (finding out what a remote sends)
        self.on_key = None              # callback(code, command or None) for every accepted key press
        self.tv_power = None            # what the TV said last: "on", "standby" or None (not heard yet)

    def _addr(self):
        return bytes([self.phys >> 8, self.phys & 0xFF])

    def active_source(self):
        self.active = True
        return (BROADCAST, bytes([ACTIVE_SOURCE]) + self._addr())

    def tv_on(self):
        """switch the TV on and to the Pi"""
        return [(TV, bytes([IMAGE_VIEW_ON])), self.active_source()]

    def tv_standby(self):
        self.active = False
        return [(TV, bytes([STANDBY]))]

    def ask_tv_power(self):
        """the TV answers with Report Power Status - not every TV announces its standby by itself"""
        return [(TV, bytes([GIVE_DEVICE_POWER_STATUS]))]

    def handle(self, frm, to, data):
        if not data:
            return None, []
        op, arg = data[0], data[1:]
        cmd, out = None, []
        if frm == TV:                   # the TV's power: its Standby (mostly to all), its answer, else it talks: on
            if op == STANDBY:
                self.tv_power, self.active = "standby", False
                return None, []
            if op == REPORT_POWER_STATUS and arg:
                self.tv_power = "on" if arg[0] in (0x00, 0x02) else "standby"   # 2 = going on, 3 = going to standby
                return None, []
            if op != FEATURE_ABORT:
                self.tv_power = "on"
        if op == USER_CONTROL_PRESSED and arg:
            now = self.clock()
            k = arg[0]
            if self.last_key and self.last_key[0] == k and now - self.last_key[1] < REPEAT_S:
                self.last_key = (k, now)
                return None, []
            self.last_key = (k, now)
            cmd = KEYS.get(k)
            if self.on_key:
                self.on_key(k, cmd)
        elif op == USER_CONTROL_RELEASED:
            self.last_key = None
        elif op == DECK_CONTROL and arg:
            cmd = DECK.get(arg[0])
        elif op == PLAY and arg:
            cmd = "play" if arg[0] == 0x24 else ("pause" if arg[0] == 0x25 else None)
        elif op == GIVE_OSD_NAME:
            out.append((frm, bytes([SET_OSD_NAME]) + self.name.encode("ascii", "replace")))
        elif op == GIVE_DEVICE_POWER_STATUS:
            out.append((frm, bytes([REPORT_POWER_STATUS, 0x00])))          # on
        elif op == GIVE_DECK_STATUS:
            out.append((frm, bytes([DECK_STATUS, 0x11 if self.playing else 0x1A])))   # play / stop
        elif op == MENU_REQUEST:
            out.append((frm, bytes([MENU_STATUS, 0x00])))                  # "activated": some TVs send keys only then
        elif op in (SET_STREAM_PATH, ROUTING_CHANGE) and len(arg) >= 2:
            path = arg[-2:]                                                # Routing Change: new address last
            if self.phys != 0xFFFF and path == self._addr():
                out.append(self.active_source())                           # the TV switched to the Pi
            else:
                self.active = False
        elif op == ACTIVE_SOURCE and frm != self.la:
            self.active = False                                            # another device took over
        elif op == REQUEST_ACTIVE_SOURCE and self.active:
            out.append((BROADCAST, bytes([ACTIVE_SOURCE]) + self._addr()))
        if cmd:
            self.last = cmd
            self.recent.append(cmd)
        return cmd, out


class CecLink:
    """the device /dev/cec0: claim a playback address, receive messages (non-blocking, on the asyncio loop), send"""

    def __init__(self, proto, dev="/dev/cec0", ioctl=fcntl.ioctl, opener=os.open):
        self.proto = proto
        self.dev = dev
        self.ioctl = ioctl
        self.opener = opener
        self.fd = None
        self.err = ""
        self.adapter = ""
        self.broken = False           # receiving failed for good (not just "nothing there")

    def open(self):
        """-> True when the adapter is there; the logical address comes a moment later (configured())"""
        try:
            self.fd = self.opener(self.dev, os.O_RDWR | os.O_NONBLOCK)
        except OSError as e:
            self.err = tr("kein CEC-Anschluss (%s)") % (e.strerror or e)
            return False
        try:
            caps = bytearray(CAPS.size)
            self.ioctl(self.fd, CEC_ADAP_G_CAPS, caps)
            drv, name = CAPS.unpack(bytes(caps))[:2]
            self.adapter = "%s %s" % (drv.split(b"\0")[0].decode(errors="replace"),
                                      name.split(b"\0")[0].decode(errors="replace"))
            self.ioctl(self.fd, CEC_S_MODE, struct.pack("<I", MODE_INITIATOR | MODE_FOLLOWER))
            self._claim()
        except OSError as e:
            self.err = "CEC: %s" % (e.strerror or e)
            self.close()
            return False
        self.err = ""
        return True

    def _claim(self):
        cur = bytearray(LOG_ADDRS.size)
        self.ioctl(self.fd, CEC_ADAP_G_LOG_ADDRS, cur)
        if LOG_ADDRS.unpack(bytes(cur))[3]:                                # set already (by us before, or a tool)
            self.ioctl(self.fd, CEC_ADAP_S_LOG_ADDRS, bytearray(LOG_ADDRS.size))     # free it first
        la = LOG_ADDRS.pack(b"\0" * 4, 0, 5, 1, 0xFFFFFFFF, 1,               # CEC 1.4, one address, no vendor,
                            self.proto.name.encode("ascii", "replace"),      # unregistered as fallback
                            bytes([PRIM_DEVTYPE_PLAYBACK, 0, 0, 0]), bytes([LOG_ADDR_TYPE_PLAYBACK, 0, 0, 0]),
                            bytes([ALL_DEVTYPE_PLAYBACK, 0, 0, 0]), b"\0" * 48)
        try:
            self.ioctl(self.fd, CEC_ADAP_S_LOG_ADDRS, bytearray(la))
        except OSError as e:
            if e.errno != errno.EBUSY:                                     # EBUSY: still configuring - fine
                raise

    def configured(self):
        """read our logical and physical address -> True when the Pi has a logical address on the bus"""
        if self.fd is None:
            return False
        try:
            cur = bytearray(LOG_ADDRS.size)
            self.ioctl(self.fd, CEC_ADAP_G_LOG_ADDRS, cur)
            f = LOG_ADDRS.unpack(bytes(cur))
            pa = bytearray(2)
            self.ioctl(self.fd, CEC_ADAP_G_PHYS_ADDR, pa)
        except OSError as e:
            self.err = "CEC: %s" % (e.strerror or e)
            return False
        self.proto.phys = struct.unpack("<H", bytes(pa))[0]
        if f[1] and f[0][0] != 0xFF:                                       # log_addr_mask, log_addr[0]
            self.proto.la = f[0][0]
            return True
        return False

    def receive(self):
        """-> list of (from, to, data) waiting on the device"""
        out = []
        while self.fd is not None:
            buf = bytearray(MSG.pack(0, 0, 0, 0, 0, 0, b"\0" * 16, 0, 0, 0, 0, 0, 0, 0))
            try:
                self.ioctl(self.fd, CEC_RECEIVE, buf)
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.ETIMEDOUT):
                    self.err = "CEC: %s" % (e.strerror or e)
                    self.broken = True
                break
            f = MSG.unpack(bytes(buf))
            n, raw = f[2], f[6]
            if 1 <= n <= 16:
                out.append((raw[0] >> 4, raw[0] & 15, raw[1:n]))
        return out

    def send(self, to, data):
        if self.fd is None:
            return False
        raw = bytes([(self.proto.la << 4) | to]) + data
        buf = bytearray(MSG.pack(0, 0, len(raw), 0, 0, 0, raw.ljust(16, b"\0"), 0, 0, 0, 0, 0, 0, 0))
        try:
            self.ioctl(self.fd, CEC_TRANSMIT, buf)          # timeout 0: queued, not waited for
            return True
        except OSError as e:
            self.err = tr("CEC senden: %s") % (e.strerror or e)
            return False

    def close(self):
        if self.fd is not None:
            try:                                          # off the bus: the TV no longer lists "C64-Jukebox"
                self.ioctl(self.fd, CEC_ADAP_S_LOG_ADDRS, bytearray(LOG_ADDRS.size))
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
