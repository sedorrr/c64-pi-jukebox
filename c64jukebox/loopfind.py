"""Find where a tune starts again: most SID tunes loop for ever, and the song length databases give the time of the
first repeat. A tune without a known length plays until the time limit; this finds the repeat in the stream itself.

Every ~43 ms a fingerprint of the sound is kept: the notes (12 pitch classes, "chroma") and the tone colour (12
log-spaced bands, loudness taken out). Each new one is compared with all earlier ones; per lag (distance in time) a
running mean of the similarity (~4 s) is kept. When at one lag that mean stays high, and clearly above the other lags,
for long enough, what plays now is what played L seconds ago: the tune has looped. Where the matching began is the
tune's length (HVSC convention); found by walking back along that lag.

Needs numpy (the system's python3-numpy) - it runs in its own process (loopwatch.py), the jukebox only reads the
results. Fed with mono samples at 48 kHz (the Ultimate's stream, mixed)."""
import math

import numpy as np

RATE = 48000
DECIM = 4                       # 48 kHz -> 12 kHz
SR = RATE // DECIM
HOP = 512                       # 42.7 ms per fingerprint
WIN = 2048                      # 170 ms window: 5.9 Hz per bin, enough for notes from ~100 Hz
FPS = SR / HOP                  # 23.4 fingerprints per second
TAU_S = 4.0                     # running mean of the similarity per lag
ON = 0.80                       # running mean at least this ...
CONTRAST = 0.25                 # ... and this much above the mean of all lags
MIN_LAG_S = 20.0                # shorter repeats are patterns inside the tune, not the tune
MATCH_S = 15.0                  # a repeat must hold this long, and for half a round (up to MATCH_MAX_S)
MATCH_MAX_S = 40.0
BACK_START_S = 3.0              # a repeat that goes back to the first 3 s: the tune starts again
SUB_GAP = 0.08                  # a pattern: matches at a fraction of the lag within this of the lag itself
CHECK_EVERY = 12                # look at the candidates every 12 fingerprints (0.5 s)
MAX_S = 20 * 60                 # longest tune looked at
QUIET = 1e5                     # band energy below this: a pause, matches nothing


def _bins():
    f = np.fft.rfftfreq(WIN, 1.0 / SR)
    pc = np.full(len(f), -1)
    ok = (f >= 100) & (f <= 3000)
    pc[ok] = np.round(12 * np.log2(f[ok] / 440.0)).astype(int) % 12
    edges = np.geomspace(80, 5500, 13)
    bands = [(int(np.searchsorted(f, a)), max(int(np.searchsorted(f, b)), int(np.searchsorted(f, a)) + 1))
             for a, b in zip(edges[:-1], edges[1:])]
    return pc, bands


class LoopFinder:
    def __init__(self, max_s=MAX_S):
        self.n_max = int(max_s * FPS)
        self.raw = np.zeros((self.n_max, 24), np.float32)   # fingerprints
        self.fp = np.zeros((self.n_max, 24), np.float32)    # smoothed over 4 (170 ms), compared
        self.n = 0
        self.buf = np.zeros(0, np.float32)
        self.rest = np.zeros(0, np.float32)
        self.win = np.hanning(WIN).astype(np.float32)
        self.pc, self.bands = _bins()
        self.pc_onehot = np.zeros((len(self.pc), 12), np.float32)
        for k, p in enumerate(self.pc):
            if p >= 0:
                self.pc_onehot[k, p] = 1.0
        self.a = math.exp(-1.0 / (TAU_S * FPS))
        self.min_lag = int(MIN_LAG_S * FPS)
        self.S = np.zeros(self.n_max, np.float32)            # by lag: running mean of the similarity
        self.on = np.zeros(self.n_max, np.int32)             # by lag: fingerprints in a row above ON / CONTRAST
        self.found = None

    # ---- input
    def feed(self, pcm):
        """mono samples (int16 or float) at 48 kHz -> the result once one is found (see result())"""
        x = np.concatenate([self.rest, np.asarray(pcm, np.float32)])
        k = len(x) // DECIM * DECIM
        self.rest = x[k:]
        self.buf = np.concatenate([self.buf, x[:k].reshape(-1, DECIM).mean(axis=1)])
        while len(self.buf) >= WIN and self.n < self.n_max and self.found is None:
            self._frame(self.buf[:WIN])
            self.buf = self.buf[HOP:]
        return self.found

    def seconds(self):
        return self.n / FPS

    def _frame(self, w):
        mag = np.abs(np.fft.rfft(w * self.win))
        pw = mag * mag
        e = np.array([pw[a:b].sum() for a, b in self.bands], np.float32)
        t = self.n
        if e.sum() > QUIET:
            chroma = np.log1p(mag / (mag.mean() + 1e-9)) @ self.pc_onehot
            chroma -= chroma.mean()
            col = np.log(e + 1e-3 * e.sum() + 1.0)
            col -= col.mean()
            v = np.concatenate([chroma / (np.linalg.norm(chroma) + 1e-9), col / (np.linalg.norm(col) + 1e-9)])
            self.raw[t] = v / math.sqrt(2)
        g = self.raw[max(0, t - 3):t + 1].sum(axis=0)
        nrm = float(np.linalg.norm(g))
        self.fp[t] = g / nrm if nrm > 1e-6 else 0.0
        self.n += 1
        self._match(t)

    def _match(self, t):
        if t <= self.min_lag:
            return
        sims = self.fp[:t - self.min_lag + 1] @ self.fp[t]           # index j: earlier fingerprint, lag t - j
        lags = t - np.arange(len(sims))
        S = self.S[lags] * self.a + sims * (1 - self.a)
        self.S[lags] = S
        on = (S >= ON) & (S - S.mean() >= CONTRAST)
        o = np.where(on, self.on[lags] + 1, 0)
        self.on[lags] = o
        if t % CHECK_EVERY:
            return
        fast = FPS * np.maximum(MATCH_S, np.minimum(lags / FPS / 2, MATCH_MAX_S))
        ready = o >= fast
        for b in np.flatnonzero(ready)[::-1]:                         # shortest lag first
            lag = int(lags[b])
            if self._periodic(t, lag, int(o[b])):
                continue
            start = self._onset(t, lag, float(S.mean()))
            back = (start - lag) / FPS
            # only back to the very start: the tune begins again. A repeat back into the middle is as often a part
            # played twice inside the tune as an intro followed by the loop (measured: wrong more often than right)
            if back <= BACK_START_S:
                self.found = {"len": round(start / FPS, 1), "lag": round(lag / FPS, 1),
                              "from": round(back, 1), "at": round(t / FPS, 1)}
                return

    def _periodic(self, t, lag, n):
        """the matching stretch also matches itself at a whole fraction of the lag (a half, a third ... a twelfth): a
        short pattern played over and over (which matches at every multiple of its length), not the tune coming round.
        Only when it matches there about as well as at the lag itself: inside a real loop a bar may resemble one a
        fraction earlier by chance (measured: 0.82 against 1.00)"""
        a = t - n + 1

        def sim(d):
            return float((self.fp[a:t + 1] * self.fp[a - d:t + 1 - d]).sum(axis=1).mean())
        need = max(ON, sim(lag) - SUB_GAP)
        for k in range(2, 13):
            for sub in {int(lag / k), int(lag / k + 0.5), int(lag / k) + 1}:
                if sub >= FPS and a - sub >= 0 and sim(sub) >= need:
                    return True
        return False

    def _onset(self, t, lag, base):
        """walk back along the lag: the earliest point from which on the sound matches (1 s mean of the similarity
        above half way between the other lags - base - and this one)"""
        s = (self.fp[lag:t + 1] * self.fp[:t + 1 - lag]).sum(axis=1)       # index i: time i + lag
        k = int(FPS)
        c = np.concatenate([[0.0], np.cumsum(s)])
        m = (c[k:] - c[:-k]) / k                                            # m[i]: mean of s[i .. i+k-1]
        plateau = float(np.median(m[-int(MATCH_S * FPS):]))
        thr = (plateau + base) / 2
        i = len(m) - 1
        while i > 0 and m[i - 1] >= thr:
            i -= 1
        return i + lag

    def result(self):
        """None, or {"len": s (where the repeat began = the tune's length), "lag": s (one round of the loop),
        "from": s (where in the tune the repeat goes back to; ~0 = to the very start), "at": s (when found)}"""
        return self.found
