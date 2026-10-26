"""Audio (forwarded by the jukebox) and video (from the Ultimate) over UDP, each in a thread of its own.

Video: 50 pictures/s of 384 x 272 pixels, 16 colours, in packets of 4 lines (12 bytes header + 768 bytes, ~3400 packets
a second). Handling every packet in Python would cost the Pi 3B half a core, so the thread only receives into a
preallocated array (recv_into) and the picture is decoded in one go, with numpy, when the screen wants it."""
import socket
import threading
import time

import numpy as np

from .sidtrace import SidTrace
from .modes import AUDIO_PORT, SID_PORT, VIDEO_PORT  # noqa: F401
VIDEO_W, VIDEO_H = 384, 272                # PAL; NTSC sends 240 lines
VIDEO_PKT = 780                            # 12 header + 4 lines * 192 bytes
AUDIO_PKT = 770                            # 2 sequence + 192 stereo frames int16
SAMPLE_RATE = 47983

# the "Pepto" VIC-II palette, as in the PC jukebox
VIC_PALETTE = [
    (0x00, 0x00, 0x00), (0xFF, 0xFF, 0xFF), (0x68, 0x37, 0x2B), (0x70, 0xA4, 0xB2),
    (0x6F, 0x3D, 0x86), (0x58, 0x8D, 0x43), (0x35, 0x28, 0x79), (0xB8, 0xC7, 0x6F),
    (0x6F, 0x4F, 0x25), (0x43, 0x39, 0x00), (0x9A, 0x67, 0x59), (0x44, 0x44, 0x44),
    (0x6C, 0x6C, 0x6C), (0x9A, 0xD2, 0x84), (0x6C, 0x5E, 0xB5), (0x95, 0x95, 0x95),
]


def decode_packets(packets, img):
    """packets: uint8 array (n, 780) of one picture -> lines written into img (272 x 384 colour indices);
    returns the number of lines seen (240 for NTSC). Lines of lost packets keep the last picture's."""
    if not len(packets):
        return 0
    p = packets
    line = (p[:, 4].astype(np.int32) | (p[:, 5].astype(np.int32) << 8)) & 0x7FFF
    width = p[:, 6].astype(np.int32) | (p[:, 7].astype(np.int32) << 8)
    lp, bp = p[:, 8], p[:, 9]
    enc = p[:, 10].astype(np.int32) | (p[:, 11].astype(np.int32) << 8)
    ok = (enc == 0) & (bp == 4) & (width == VIDEO_W) & (lp == 4)
    if not ok.any():
        return 0
    px = p[ok, 12:12 + 4 * VIDEO_W // 2]
    rows = np.empty((len(px), 4 * VIDEO_W), dtype=np.uint8)
    rows[:, 0::2] = px & 0x0F                 # low nibble = first pixel
    rows[:, 1::2] = px >> 4
    rows = rows.reshape(-1, VIDEO_W)
    ys = (line[ok][:, None] + np.arange(4)[None, :]).reshape(-1)
    keep = ys < VIDEO_H
    img[ys[keep]] = rows[keep]
    return int(ys[keep].max()) + 1 if keep.any() else 0


class VideoReceiver(threading.Thread):
    MAX_PKTS = 96                          # 68 per PAL picture

    def __init__(self, port=VIDEO_PORT, host="0.0.0.0"):
        super().__init__(daemon=True, name="video")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
        except OSError:
            pass
        self.sock.bind((host, port))
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        # one being filled, one complete and waiting, one being decoded, one spare
        self.bufs = [np.zeros((self.MAX_PKTS, VIDEO_PKT), dtype=np.uint8) for _ in range(4)]
        self.lock = threading.Lock()
        self.ready = None                  # (buffer index, packet count) of the newest complete picture
        self.reading = -1
        self.img = np.zeros((VIDEO_H, VIDEO_W), dtype=np.uint8)
        self.lines = VIDEO_H
        self.stop = threading.Event()
        self.pkts = 0
        self.frames = 0
        self.last = 0.0
        self.allow = set()                 # senders taken (the Ultimates' Ethernet addresses); empty = any
        self.foreign = 0

    def run(self):
        cur, k = 0, 0
        while not self.stop.is_set():
            buf = self.bufs[cur]
            try:
                n, addr = self.sock.recvfrom_into(memoryview(buf[k]))
            except socket.timeout:
                continue
            except OSError:
                break
            if self.allow and addr[0] not in self.allow:
                self.foreign += 1
                continue
            if n != VIDEO_PKT:
                continue
            self.pkts += 1
            self.last = time.monotonic()
            last = buf[k, 5] & 0x80
            k += 1
            if last:
                with self.lock:
                    busy = {cur, self.reading, self.ready[0] if self.ready else -1}
                    self.ready = (cur, k)
                    cur = next(i for i in range(4) if i not in busy)
                self.frames += 1
                k = 0
            elif k >= self.MAX_PKTS:
                k = 0                              # no end marker: throw away

    def picture(self):
        """-> colour indices (lines x 384) of the newest picture, or None if nothing new came"""
        with self.lock:
            r, self.ready = self.ready, None
            if r is None:
                return None
            self.reading = r[0]
        try:
            n = decode_packets(self.bufs[r[0]][:r[1]], self.img)
        finally:
            self.reading = -1
        if n:
            self.lines = 240 if n <= 240 else VIDEO_H
        return self.img[:self.lines]

    def age(self):
        return time.monotonic() - self.last if self.last else None

    def close(self):
        self.stop.set()
        self.sock.close()


class AudioReceiver(threading.Thread):
    """keeps the last 8256 stereo frames (43 packets)"""
    SIZE = 192 * 43

    def __init__(self, port=AUDIO_PORT, host="127.0.0.1"):
        super().__init__(daemon=True, name="audio")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self.ring = np.zeros((self.SIZE, 2), dtype=np.int16)
        self.pos = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.pkts = 0
        self.last = 0.0
        self.on_packet = None                      # gets the 192 stereo frames as bytes (sound over HDMI)

    def feed(self, data):
        if len(data) != AUDIO_PKT:
            return                                   # "C64NP1 ..." titles and other things
        fr = np.frombuffer(data, dtype="<i2", count=384, offset=2).reshape(192, 2)
        with self.lock:
            p = self.pos
            self.ring[p:p + 192] = fr                # SIZE is a multiple of 192: never wraps inside a packet
            self.pos = (p + 192) % self.SIZE
        self.pkts += 1
        self.last = time.monotonic()
        cb = self.on_packet
        if cb:
            cb(data[2:])

    def run(self):
        while not self.stop.is_set():
            try:
                data = self.sock.recv(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            self.feed(data)

    def snapshot(self, n=4096):
        """the last n stereo frames, oldest first (float32)"""
        with self.lock:
            r = np.roll(self.ring, -self.pos, axis=0)
        return r[-n:].astype(np.float32)

    def age(self):
        return time.monotonic() - self.last if self.last else None

    def close(self):
        self.stop.set()
        self.sock.close()


class SidReceiver(threading.Thread):
    """the Ultimate's debug stream (~2600 packets/s): received in batches of up to 64 packets (recv_into, no copies),
    each batch handed to the SidTrace at once - the numpy part then costs about as much as one packet"""
    BATCH = 64

    def __init__(self, port=SID_PORT, host="0.0.0.0"):
        super().__init__(daemon=True, name="sid")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 22)
        except OSError:
            pass
        self.sock.bind((host, port))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.buf = np.zeros((self.BATCH, 1504), dtype=np.uint8)
        self.trace = SidTrace()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.last = 0.0
        self.allow = set()                 # senders taken (the Ultimates' Ethernet addresses); empty = any
        self.foreign = 0

    def run(self):
        k, lens = 0, [0] * self.BATCH
        while not self.stop.is_set():
            try:
                n, addr = self.sock.recvfrom_into(memoryview(self.buf[k]))
                if self.allow and addr[0] not in self.allow:
                    self.foreign += 1
                    continue
                lens[k] = n
                k += 1
                if k < self.BATCH:
                    continue
            except socket.timeout:                     # 50 ms nothing more: hand over what came
                if not k:
                    continue
            except OSError:
                break
            self._flush(k, lens)
            k = 0

    def _flush(self, k, lens):
        with self.lock:
            self.trace.feed_rows(self.buf, lens[:k])
        self.last = time.monotonic()

    def frames(self, bases=None):
        """the last 6 s: [(frame number, {base: (volume, cutoff, filtered, voices)})], oldest first"""
        with self.lock:
            if bases is not None:
                self.trace.limit(bases)
            return list(self.trace.frames)

    def stats(self):
        t = self.trace
        return {"pkts": t.pkts, "lost": t.lost, "writes": t.writes, "chips": ["$%04X" % b for b in sorted(t.chips)],
                "foreign": self.foreign}

    def age(self):
        return time.monotonic() - self.last if self.last else None

    def close(self):
        self.stop.set()
        self.sock.close()
