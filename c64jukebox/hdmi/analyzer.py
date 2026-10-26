"""Spectrum like the PC jukebox's Spectrum Analyzer: FFT over 2048 samples, 28 bands logarithmic from 40 Hz to
16 kHz, dB with a noise floor of 30 dB, attack 0.45 / release 0.30, peak hold 6 frames then -0.035 per frame,
6 rows of history for "Net"; for songs with more than one SID a spectrum per channel (left/right) as well."""
from collections import deque

import numpy as np

from .receivers import SAMPLE_RATE

BANDS = 28
FFT_SIZE = 2048
MIN_FREQ, MAX_FREQ = 40, 16000
PEAK_HOLD_FRAMES = 6
PEAK_DECAY = 0.035
NET_HISTORY = 6


class Analyzer:
    def __init__(self):
        edges = np.logspace(np.log10(MIN_FREQ), np.log10(MAX_FREQ), BANDS + 1)
        freqs = np.fft.rfftfreq(FFT_SIZE, d=1.0 / SAMPLE_RATE)
        self.freqs = freqs
        self.window = np.hanning(FFT_SIZE).astype(np.float32)
        # per band: the FFT bins inside it, or (for the narrow low bands) an interpolation at its centre
        self.bands = []
        for i in range(BANDS):
            lo, hi = edges[i], edges[i + 1]
            idx = np.nonzero((freqs >= lo) & (freqs < hi))[0]
            self.bands.append((int(idx[0]), int(idx[-1]) + 1) if len(idx) else float(np.sqrt(lo * hi)))
        self.smoothed = np.zeros(BANDS, dtype=np.float32)
        self.smoothed_l = np.zeros(BANDS, dtype=np.float32)
        self.smoothed_r = np.zeros(BANDS, dtype=np.float32)
        self.peak = np.zeros(BANDS, dtype=np.float32)
        self.peak_hold = np.zeros(BANDS, dtype=np.int32)
        self.history = deque(maxlen=NET_HISTORY)
        self.samples = np.zeros(FFT_SIZE, dtype=np.float32)          # mono, newest last
        self.stereo = np.zeros((FFT_SIZE, 2), dtype=np.float32)
        self.lr_levels = (0.0, 0.0)

    def magnitudes(self, chunk):
        spec = np.abs(np.fft.rfft(chunk * self.window))
        out = np.empty(BANDS, dtype=np.float32)
        for i, b in enumerate(self.bands):
            out[i] = spec[b[0]:b[1]].mean() if isinstance(b, tuple) else np.interp(b, self.freqs, spec)
        return out

    @staticmethod
    def smooth(mags, prev):
        db = 20 * np.log10(mags + 1.0)
        db = np.clip(db - 30.0, 0, 95) / 95.0
        delta = db - prev
        return (prev + np.where(delta > 0, 0.45, 0.30) * delta).astype(np.float32)

    def update(self, stereo, chips=1):
        """stereo: float32 (n, 2), the newest frames last (n >= FFT_SIZE)"""
        st = stereo[-FFT_SIZE:]
        self.stereo = st
        mono = (st[:, 0] + st[:, 1]) * 0.5
        self.samples = mono
        last = st[-768:]
        rms = np.sqrt(np.mean(last ** 2, axis=0)) / 32768.0
        self.lr_levels = (min(1.0, float(rms[0]) * 4.0), min(1.0, float(rms[1]) * 4.0))
        self.smoothed = self.smooth(self.magnitudes(mono), self.smoothed)
        if chips > 1:
            self.smoothed_l = self.smooth(self.magnitudes(st[:, 0]), self.smoothed_l)
            self.smoothed_r = self.smooth(self.magnitudes(st[:, 1]), self.smoothed_r)
        new = self.smoothed > self.peak
        self.peak = np.where(new, self.smoothed, self.peak)
        self.peak_hold = np.where(new, PEAK_HOLD_FRAMES, self.peak_hold)
        holding = self.peak_hold > 0
        self.peak_hold = np.where(holding, self.peak_hold - 1, 0)
        falling = ~holding & ~new
        self.peak = np.where(falling, np.maximum(self.peak - PEAK_DECAY, self.smoothed), self.peak)
        self.history.appendleft(self.smoothed.copy())

    def calm(self):
        """no sound: let everything sink (as with silence in the stream)"""
        self.update(np.zeros((FFT_SIZE, 2), dtype=np.float32))
