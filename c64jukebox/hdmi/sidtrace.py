"""The real SID voices, from the Ultimate's debug stream ("6510 Only"): every bus cycle of the C64's processor comes
over UDP (packets of 2 bytes sequence, 2 bytes reserved, up to 360 entries of 32 bits: address 15..0, data 23..16,
R/W# 24), about 985 000 entries a second (32 Mbit/s). The writes to the SID registers ($D400-$D7FF; $DE00-$DFFF only
for a tune with a SID there) are picked out with numpy, a copy of each chip's 32 registers follows them, and once per
PAL frame (19656 cycles) the voices are taken down: pitch, waveform, gate and a simulated ADSR envelope. Part of the
HDMI service (numpy only). Measured on the Elite II (2026-10-22): ~2600 packets/s, none lost, now and then a shorter
packet; a 2SID tune writes its registers about 100 times a second; on the Pi 3B this costs ~11 % of one core."""
import math
from collections import deque

import numpy as np

from ..i18n import tr

PAL_HZ = 985248
FRAME = 19656                          # cycles of one PAL frame (312 lines x 63)
PKT_HEAD = 4
ENTRIES = 360                          # a full packet: 4 + 360 x 4 = 1444 bytes
KEEP = 300                             # frames kept: 6 seconds
FORGET = 3 * 50                        # a chip without writes for 3 s is no longer shown

# envelope times of the SID (ms) for the rate values 0..15; decay and release take three times as long
ATTACK_MS = (2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000)
NOTE_NAMES = ("C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "H-")
WAVES = ((0x80, tr("Rauschen")), (0x40, tr("Puls")), (0x20, tr("Säge")), (0x10, tr("Dreieck")))   # tr: marks only
# (German at import), translated in wave_name


def sid_writes(words, io2=False):
    """uint32 entries -> (indices, addresses, data) of the processor's writes (PHI2 high, R/W# low) to $D400-$D7FF,
    with io2 also $DE00-$DFFF (only for tunes with a SID there - else e.g. a REU's registers). One pass over the ~1
    million entries a second (the Pi 3B feels each one): all writes to $D000-$D7FF, the few VIC ones dropped after."""
    idx = np.flatnonzero((words & 0x8100F800) == 0x8000D000)
    if io2:
        idx = np.union1d(idx, np.flatnonzero((words & 0x8100FE00) == 0x8000DE00))
    w = words[idx]
    keep = (w & 0xFC00) != 0xD000
    idx, w = idx[keep], w[keep]
    return idx, w & 0xFFFF, (w >> 16) & 0xFF


def note_name(midi):
    """69.0 -> "A-4" (C64 style, German H for B - B in English)"""
    n = int(round(midi))
    return "%s%d" % (tr("H-") if n % 12 == 11 else NOTE_NAMES[n % 12], n // 12 - 1)


def wave_name(ctrl):
    names = [tr(n) for bit, n in WAVES if ctrl & bit]
    return "+".join(names) if names else "–"


class Envelope:
    """a rough copy of the SID's ADSR: attack straight up, decay and release falling exponentially"""
    __slots__ = ("level", "phase")

    def __init__(self):
        self.level, self.phase = 0.0, "release"

    def step(self, dt, gate, trig, ad, sr):
        if trig:
            self.phase = "attack"
        elif not gate:
            self.phase = "release"
        if self.phase == "attack":
            self.level += dt * 1000.0 / ATTACK_MS[ad >> 4]
            if self.level >= 1.0:
                self.level, self.phase = 1.0, "decay"
        elif self.phase == "decay":
            sus = (sr >> 4) / 15.0
            self.level = sus + (self.level - sus) * math.exp(-dt * 1000.0 * 4 / (3 * ATTACK_MS[ad & 15]))
        else:
            self.level *= math.exp(-dt * 1000.0 * 4 / (3 * ATTACK_MS[sr & 15]))
        return self.level


class Chip:
    def __init__(self, base):
        self.base = base
        self.regs = bytearray(32)
        self.known = bytearray(32)           # written since the stream began (the volume is often set only once)
        self.env = [Envelope() for _ in range(3)]
        self.trig = [False] * 3              # gate went on since the last frame (also off and on again)
        self.last = 0                        # frame number of the last write

    def write(self, reg, val):
        if reg in (4, 11, 18):
            v = reg // 7
            if val & 1 and not (self.regs[reg] & 1):
                self.trig[v] = True
        self.regs[reg] = val
        self.known[reg] = 1

    def frame(self, dt, clock):
        """-> (volume 0..15, filter cutoff 0..1, filtered voices bits, [(midi or None, level, ctrl, pw) x 3])"""
        r = self.regs
        out = []
        for v in range(3):
            o = v * 7
            ctrl, freq = r[o + 4], r[o] | r[o + 1] << 8
            lvl = self.env[v].step(dt, ctrl & 1, self.trig[v], r[o + 5], r[o + 6])
            self.trig[v] = False
            if ctrl & 0x08 or not ctrl & 0xF0 or (v == 2 and r[24] & 0x80):      # test bit, no waveform, voice 3 off
                lvl = 0.0
            hz = freq * clock / 16777216.0
            midi = 69 + 12 * math.log2(hz / 440.0) if hz > 8 else None
            out.append((midi, lvl, ctrl, (r[o + 2] | (r[o + 3] & 15) << 8) / 4095.0))
        return (r[24] & 15) if self.known[24] else 15, ((r[21] & 7) | r[22] << 3) / 2047.0, r[23] & 15, out


class SidTrace:
    """feed() the debug stream's packets; frames holds (frame number, {base: Chip.frame()}) of the last 6 s"""

    def __init__(self, clock=PAL_HZ, keep=KEEP):
        self.clock = clock
        self.chips = {}
        self.only = None                     # set of bases (from the tune's SID addresses) or None = all seen
        self.io2 = False                     # a SID at $DE00-$DFFF wanted
        self.cycle = 0
        self.next_frame = FRAME
        self.nframe = 0
        self.frames = deque(maxlen=keep)
        self.seq = None
        self.pkts = self.lost = self.writes = 0

    def feed_rows(self, buf, lens):
        """the receiver's batch: buf uint8 (rows, >= 1444), lens = bytes per row. Without lost packets in one go -
        also with the shorter packets the Ultimate sends now and then (216 entries, about every 50th)"""
        k = len(lens)
        n = [(x - PKT_HEAD) // 4 for x in lens]
        if k and min(n) > 0 and max(n) <= ENTRIES:
            seq = (buf[:k, 0].astype(np.int64) | buf[:k, 1].astype(np.int64) << 8).tolist()
            first = self.seq is None or (seq[0] - self.seq) & 0xFFFF == 1
            if first and all((b - a) & 0xFFFF == 1 for a, b in zip(seq, seq[1:])):
                self.seq = seq[-1]
                self.pkts += k
                w = buf[:k, PKT_HEAD:PKT_HEAD + 4 * ENTRIES].view("<u4")
                for i, x in enumerate(n):
                    if x < ENTRIES:
                        w[i, x:] = 0                     # the rest of a short packet: no cycles, no writes
                self.feed_words(w.reshape(-1), n if min(n) < ENTRIES else None)
                return
        self.feed([memoryview(buf[i])[:x] for i, x in enumerate(lens) if x])

    def feed(self, packets):
        """packets: list of bytes-like (one UDP packet each)"""
        parts = []
        for p in packets:
            n = (len(p) - PKT_HEAD) // 4
            if n <= 0:
                continue
            seq = p[0] | p[1] << 8
            if self.seq is not None:
                gap = (seq - self.seq - 1) & 0xFFFF
                if 0 < gap < 1000:                         # lost packets: their time still passed
                    self.lost += gap
                    parts.append(np.full(gap * ENTRIES, 0x81000000, dtype="<u4"))   # reads
            self.seq = seq
            self.pkts += 1
            parts.append(np.frombuffer(p, dtype="<u4", count=n, offset=PKT_HEAD))
        if parts:
            self.feed_words(np.concatenate(parts))

    def feed_words(self, words, rows=None):
        """rows: entries used in each row of 360 (short packets end in zeros) - None = all"""
        idx, addr, data = sid_writes(words, self.io2)
        if len(words) and words.view(np.int32).max() < 0:       # all PHI2 high ("6510 Only"): every entry a cycle
            n = len(words)
        else:                                       # "6510 & VIC" sends both halves; short packets end in zeros
            phi = words.view(np.int32) < 0
            n = int(np.count_nonzero(phi))
        if n == len(words) or not len(idx):
            pass
        elif rows is not None and n == sum(rows):     # only the ends of short packets are empty: shift by row
            miss = np.cumsum([0] + [ENTRIES - x for x in rows[:-1]])
            idx = idx - miss[idx // ENTRIES]
        else:                                       # count the processor's cycles only
            idx = np.cumsum(phi)[idx] - 1
        start = self.cycle
        for i, a, d in zip(idx.tolist(), addr.tolist(), data.tolist()):
            cyc = start + i
            while cyc >= self.next_frame:
                self._frame()
            base = a & 0xFFE0
            if self.only is not None and base not in self.only:
                continue
            c = self.chips.get(base)
            if c is None:
                c = self.chips[base] = Chip(base)
            c.write(a & 31, d)
            c.last = self.nframe
            self.writes += 1
        self.cycle = start + n
        while self.cycle >= self.next_frame:
            self._frame()

    def _frame(self):
        self.next_frame += FRAME
        self.nframe += 1
        dt = FRAME / self.clock
        for b in [b for b, c in self.chips.items() if self.nframe - c.last > FORGET]:
            del self.chips[b]
        self.frames.append((self.nframe, {b: c.frame(dt, self.clock) for b, c in sorted(self.chips.items())}))

    def limit(self, bases):
        """only these chips (the tune's SID addresses, e.g. ["$D400", "$D500"]); None or [] = every one written to"""
        want = set()
        for b in bases or []:
            try:
                want.add(int(str(b).lstrip("$"), 16) & 0xFFE0)
            except ValueError:
                pass
        self.only = want or None
        self.io2 = any(b >= 0xDE00 for b in want)
        if self.only:
            for b in [b for b in self.chips if b not in self.only]:
                del self.chips[b]
