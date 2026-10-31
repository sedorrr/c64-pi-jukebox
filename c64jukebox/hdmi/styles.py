"""The 17 styles of the PC jukebox's Spectrum Analyzer (SpectrumAnalyzerWindow._draw_*), drawn with pygame onto a
transparent layer (960 x 540, the graphics chip scales it to 1920 x 1080). Same constants, colours, drawing order
and effects as there; Tk's "stipple" (pseudo transparency) became real alpha. Text: DejaVu (fonts-dejavu-core)."""
import math
import os
import random
import time
from collections import deque

import numpy as np
import pygame

from ..i18n import tr
from .analyzer import BANDS, NET_HISTORY
from .sidtrace import note_name, wave_name
from .modes import MODES


def rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def lerp(c1, c2, t):
    t = max(0.0, min(1.0, float(t)))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def hsv(h, s, v):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def boost(value, power=0.85, gain=1.0):
    value = max(0.0, min(1.0, float(value)))
    return min(1.0, (value ** power) * gain)


def band_energy(values):
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return 0.0
    return float(0.65 * np.max(values) + 0.35 * np.mean(values))


FONT_DIRS = ("/usr/share/fonts/truetype/dejavu/", "/System/Library/Fonts/Supplemental/")
FONT_FILES = {
    (False, False): ("DejaVuSans.ttf", "Arial.ttf"),
    (True, False): ("DejaVuSans-Bold.ttf", "Arial Bold.ttf"),
    (True, True): ("DejaVuSansMono-Bold.ttf", "Courier New Bold.ttf"),
    (False, True): ("DejaVuSansMono.ttf", "Courier New.ttf"),
}
_fonts = {}


def font(size, bold=False, mono=False, italic=False):
    key = (size, bold, mono, italic)
    if key not in _fonts:
        if not pygame.font.get_init():
            pygame.font.init()
        path = None
        names = FONT_FILES[(bold, mono)]
        if italic and not mono:
            names = ("DejaVuSans-Oblique.ttf" if not bold else "DejaVuSans-BoldOblique.ttf",
                     "Arial Italic.ttf") + names
        for d in FONT_DIRS:
            for n in names:
                if os.path.exists(d + n):
                    path = d + n
                    break
            if path:
                break
        f = pygame.font.Font(path, size)
        if italic and path and "Oblique" not in path and "Italic" not in path:
            f.italic = True
        _fonts[key] = f
    return _fonts[key]


def R(x0, y0, x1, y1):
    """Tk rectangle coordinates -> pygame.Rect"""
    x0, x1 = sorted((round(x0), round(x1)))
    y0, y1 = sorted((round(y0), round(y1)))
    return pygame.Rect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))


SEGMENTS = 16
SEG_LIT = [rgb("#2ecc71")] * 9 + [rgb("#f4d03f")] * 4 + [rgb("#e74c3c")] * 3
SEG_DIM = [rgb("#123322")] * 9 + [rgb("#3a331a")] * 4 + [rgb("#3a1c18")] * 3
NET_COLORS = [rgb(c) for c in ("#4df1ff", "#33c8f2", "#2aa0e0", "#2178c8", "#1c56aa", "#173a8c")]
RAIN_TRAIL = [rgb(c) for c in ("#eaffef", "#8dffb0", "#39ff6a", "#20e055", "#1fcc50",
                                "#17a840", "#128a35", "#0d6a28", "#0a5522")]
C64_BG, C64_BORDER, C64_DIM = rgb("#4040E0"), rgb("#7869C4"), rgb("#2c2470")
C64_SEG = [rgb(c) for c in ("#40318D", "#40318D", "#67B6BD", "#67B6BD", "#55A049",
                             "#94E089", "#BFCE72", "#8B5429", "#B86962", "#FFFFFF")]
KALEIDO = [rgb(c) for c in ("#ff5f6d", "#ffc371", "#f7f172", "#7bed9f", "#70a1ff", "#a29bfe", "#ff85c0", "#ffffff")]
LABEL = rgb("#dddddd")


class Info:
    """what the styles need about the song"""

    def __init__(self, chips=1, addresses=None, title="", author="", sid=None, sid_note=""):
        self.chips = max(1, min(int(chips or 1), 3))
        self.addresses = addresses or ["$D400"]
        self.title, self.author = title or "", author or ""
        self.sid = sid or []                 # SidTrace frames (the debug stream), oldest first
        self.sid_note = sid_note             # why there are none


class Styles:
    CLOUD_PER_BAND = 3
    RAIN_DROPS, RAIN_LEN = 2, 9
    WAVE_LEN = 150
    MILK_POINTS = 64

    def __init__(self, size=(960, 540), seed=None):
        self.W, self.H = size
        self.k = self.H / 540                                  # text and line sizes were made for 540 lines
        self.rnd = random.Random(seed)
        rs = np.random.RandomState(seed)
        n = BANDS * self.CLOUD_PER_BAND
        self.cloud_band = np.tile(np.arange(BANDS), self.CLOUD_PER_BAND)
        self.cloud = [dict(angles=rs.uniform(0, 2 * np.pi, n), drift=rs.uniform(-0.02, 0.02, n),
                           phase=rs.uniform(0, 2 * np.pi, n), jitter=rs.uniform(0.8, 1.2, n)) for _ in range(2)]
        self.cloud_alpha = [self.rnd.choice([255, 255, 255, 64, 128]) for _ in range(n)]
        self.rs = rs
        self.rain_y = rs.uniform(0, 1, (BANDS, self.RAIN_DROPS))
        self.rain_ch = [[[self.rnd.choice("01") for _ in range(self.RAIN_LEN)] for _ in range(self.RAIN_DROPS)]
                        for _ in range(BANDS)]
        self._glyphs = {}
        self._tiles = {}
        self.vu = [0.0, 0.0]
        self.wave = [deque([0.0] * self.WAVE_LEN, maxlen=self.WAVE_LEN) for _ in range(2)]
        self.vinyl_angle = 0.0
        self._vinyl_key, self._vinyl_img = None, None
        self.neon_phase, self.neon_last = 0.0, None
        self.cyber = dict(glitch_until=0.0, prev=0.0, hex=[[0.0, None, (0, 0)] for _ in range(7)])
        self.sr = dict(glitch_until=0.0, prev=0.0, read=[[0.0, None, (0, 0)] for _ in range(6)])
        self.milk_hue = 0.0

    # ------------------------------------------------------------ entry
    def draw(self, mode, surf, a, info, bg=False, now=None):
        """mode: key of MODES; surf: transparent layer; a: Analyzer; bg: a background is shown (as in the PC
        jukebox some styles become see-through then)"""
        now = time.time() if now is None else now
        fn = getattr(self, "_" + mode, None) if mode in MODES else None
        (fn or self._bars)(surf, a, info, bg, now)

    def _tile(self, w, h, color, border=None):
        """a filled rectangle as a little surface (cached), for blits() of many equal segments"""
        key = (w, h, color, border)
        t = self._tiles.get(key)
        if t is None:
            opaque = len(color) == 3 or color[3] == 255         # no alpha channel: blitted by copying, not blending
            t = pygame.Surface((max(1, w), max(1, h)), 0 if opaque else pygame.SRCALPHA, 32 if not opaque else 24)
            t.fill(color)
            if border:
                pygame.draw.rect(t, border, t.get_rect(), 1)
            if len(self._tiles) > 400:
                self._tiles.clear()
            self._tiles[key] = t
        return t

    def _text(self, surf, txt, pos, f, color, anchor="nw"):
        img = f.render(txt, True, color)
        x, y = pos
        w, h = img.get_size()
        if "e" in anchor:
            x -= w
        elif "w" not in anchor:
            x -= w / 2
        if "s" in anchor:
            y -= h
        elif "n" not in anchor:
            y -= h / 2
        surf.blit(img, (round(x), round(y)))

    # ------------------------------------------------------------ styles
    def _none(self, surf, a, info, bg, now):
        pass

    def _bars(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        bw, sh = W / BANDS, H / SEGMENTS
        gap = sh * 0.18
        pm = max(sh * 0.35, 2)
        al = 128 if bg else 255
        if bg:                                               # see-through: fill() writes the alpha straight in
            for i in range(BANDS):
                lit = int(round(float(a.smoothed[i]) * SEGMENTS))
                x0, x1 = i * bw + 1, (i + 1) * bw - 1
                for s in range(SEGMENTS):
                    y1 = H - s * sh
                    surf.fill((SEG_LIT[s] if s < lit else SEG_DIM[s]) + (al,), R(x0, y1 - sh + gap, x1, y1))
                py = H - float(a.peak[i]) * H
                surf.fill((255, 255, 255, al), R(x0, py - pm, x1, py))
            return
        w = round(bw - 2)
        ys = [(round(H - s * sh - sh + gap), round(H - s * sh)) for s in range(SEGMENTS)]
        lit_t = [self._tile(w, y1 - y0, SEG_LIT[s] + (al,)) for s, (y0, y1) in enumerate(ys)]
        dim_t = [self._tile(w, y1 - y0, SEG_DIM[s] + (al,)) for s, (y0, y1) in enumerate(ys)]
        todo = []
        for i in range(BANDS):
            lit = int(round(float(a.smoothed[i]) * SEGMENTS))
            x0 = round(i * bw + 1)
            todo += [((lit_t if s < lit else dim_t)[s], (x0, ys[s][0])) for s in range(SEGMENTS)]
        surf.blits(todo, doreturn=False)
        for i in range(BANDS):
            py = H - float(a.peak[i]) * H
            surf.fill((255, 255, 255, al), R(i * bw + 1, py - pm, (i + 1) * bw - 1, py))

    def _net(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        bw, gap, mh = W / BANDS, H * 0.05, H * 0.75
        al = 128 if bg else 255
        rows = list(a.history)
        while len(rows) < NET_HISTORY:
            rows.append(np.zeros(BANDS, dtype=np.float32))
        pts = [[((i + 0.5) * bw, H - float(v[i]) * mh - r * gap) for i in range(BANDS)] for r, v in enumerate(rows)]
        for r in range(NET_HISTORY - 1):                        # vertical links first (created later in Tk, thin)
            for i in range(BANDS):
                pygame.draw.line(surf, NET_COLORS[r] + (al,), pts[r][i], pts[r + 1][i], 1)
        for r in range(NET_HISTORY - 1, -1, -1):
            pygame.draw.lines(surf, NET_COLORS[r] + (al,), False, pts[r], max(1, round((2 if r == 0 else 1.2) * self.k)))

    def _cloud_system(self, surf, st, values, cx, cy, side, quiet, loud, bg, now):
        st["drift"] += self.rs.uniform(-0.0015, 0.0015, len(st["drift"]))
        np.clip(st["drift"], -0.02, 0.02, out=st["drift"])
        st["angles"] += st["drift"]
        v = values[self.cloud_band]
        bob = np.sin(now * 1.3 + st["phase"]) * (side * 0.02)
        radius = (side * 0.10 + v * side * 0.58) * st["jitter"] + bob
        xs = cx + radius * np.cos(st["angles"])
        ys = cy + radius * np.sin(st["angles"]) * 0.72
        sizes = (3.5 + v * 14.0) * self.k
        for i in range(len(xs)):
            al = 128 if bg else self.cloud_alpha[i]
            pygame.draw.circle(surf, lerp(quiet, loud, v[i]) + (al,), (float(xs[i]), float(ys[i])), float(sizes[i]))

    def _cloud(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        if info.chips <= 1:
            self._cloud_system(surf, self.cloud[0], a.smoothed, W / 2, H / 2, min(W, H), (180, 220, 255),
                               (255, 45, 210), bg, now)
            return
        hw = W / 2
        side = min(hw, H)
        self._cloud_system(surf, self.cloud[0], a.smoothed_l, hw / 2, H / 2, side, (180, 220, 255), (255, 45, 210), bg, now)
        self._cloud_system(surf, self.cloud[1], a.smoothed_r, hw * 1.5, H / 2, side, (255, 224, 180), (255, 100, 20), bg, now)
        f = font(round(15 * self.k), bold=True)
        self._text(surf, tr("Links"), (6, 4), f, LABEL)
        self._text(surf, tr("Rechts"), (hw + 6, 4), f, LABEL)

    def _osc_line(self, surf, samples, cy, half, color):
        n = min(300, len(samples))
        if n < 2:
            return
        idx = np.linspace(0, len(samples) - 1, n).astype(int)
        norm = np.clip(samples[idx] / 20000.0, -1.0, 1.0)
        xs = np.linspace(0, self.W, n)
        ys = cy - norm * half
        pygame.draw.lines(surf, color, False, list(zip(xs.tolist(), ys.tolist())), max(1, round(2 * self.k)))

    def _oscilloscope(self, surf, a, info, bg, now):
        H = self.H
        if info.chips <= 1:
            self._osc_line(surf, a.samples, H / 2, H / 2 * 0.9, rgb("#39ff6a"))
            return
        rh = H / 2
        self._osc_line(surf, a.stereo[:, 0], rh / 2, rh / 2 * 0.85, rgb("#39ff6a"))
        self._osc_line(surf, a.stereo[:, 1], rh * 1.5, rh / 2 * 0.85, rgb("#ff9a3c"))
        f = font(round(15 * self.k), bold=True)
        self._text(surf, tr("Links"), (6, 4), f, LABEL)
        self._text(surf, tr("Rechts"), (6, rh + 4), f, LABEL)

    def _radial(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        cx, cy = W / 2, H / 2
        side = min(W, H)
        base, extra, margin = side * 0.14, side * 0.68, 4
        ang = np.linspace(0, 2 * np.pi, BANDS, endpoint=False)
        ca, sa = np.cos(ang), np.sin(ang)
        with np.errstate(divide="ignore"):
            lx = np.where(np.abs(ca) > 1e-6, (W / 2 - margin) / np.abs(ca), np.inf)
            ly = np.where(np.abs(sa) > 1e-6, (H / 2 - margin) / np.abs(sa), np.inf)
        mx = np.minimum(lx, ly)
        outer = np.minimum(base + a.smoothed * extra, mx)
        inner = np.minimum(base, mx)
        w = max(1, round(7 * self.k))
        for i in range(BANDS):
            lvl = int(np.clip(a.smoothed[i] * (SEGMENTS - 1), 0, SEGMENTS - 1))
            p0 = (cx + inner[i] * ca[i], cy + inner[i] * sa[i])
            p1 = (cx + outer[i] * ca[i], cy + outer[i] * sa[i])
            pygame.draw.line(surf, SEG_LIT[lvl], p0, p1, w)
            for p in (p0, p1):                                   # round caps
                pygame.draw.circle(surf, SEG_LIT[lvl], p, w / 2)

    def _glyph(self, ch, t):
        key = (ch, t)
        if key not in self._glyphs:
            self._glyphs[key] = font(round(16 * self.k), bold=True, mono=True).render(ch, True, RAIN_TRAIL[t])
        return self._glyphs[key]

    def _rain(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        cw = W / BANDS
        self.rain_y += (0.012 + a.smoothed * 0.055)[:, None]
        self.rain_y = np.where(self.rain_y > 1.05, -0.05, self.rain_y)
        g0 = self._glyph("0", 0)
        gw, gh = g0.get_width() / 2, g0.get_height() / 2
        glyphs = [[self._glyph(c, t) for t in range(self.RAIN_LEN)] for c in "01"]
        flips = self.rs.random_sample((BANDS, self.RAIN_DROPS, self.RAIN_LEN)) < 0.06
        todo = []                                            # one blits() call: the Pi 3B spends its time in Python
        for i in range(BANDS):
            for d in range(self.RAIN_DROPS):
                x = round(i * cw + cw * (0.3 + 0.4 * d) - gw)
                head = self.rain_y[i, d] * H - gh
                chars = self.rain_ch[i][d]
                for t in range(self.RAIN_LEN):
                    if flips[i, d, t]:
                        chars[t] = self.rnd.choice("01")
                    y = head - t * 0.035 * H
                    if -40 < y < H + 20:
                        todo.append((glyphs[chars[t] == "1"][t], (x, round(y))))
        surf.blits(todo, doreturn=False)

    def _c64(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        surf.fill(C64_BG + (255,))
        bw = max(1, round(6 * self.k))
        pygame.draw.rect(surf, C64_BORDER, R(3 - bw / 2, 3 - bw / 2, W - 3 + bw / 2, H - 3 + bw / 2), bw)
        segs = len(C64_SEG)
        bwid, sh = W / BANDS, H / segs
        gap = sh * 0.15
        w = round(bwid - 4)
        ys = [(round(H - s * sh - sh + gap), round(H - s * sh)) for s in range(segs)]
        todo = []
        for i in range(BANDS):
            lit = int(round(float(a.smoothed[i]) * segs))
            x0 = round(i * bwid + 2)
            for s, (y0, y1) in enumerate(ys):
                todo.append((self._tile(w, y1 - y0, (C64_SEG[s] if s < lit else C64_DIM) + (255,), C64_BG), (x0, y0)))
        surf.blits(todo, doreturn=False)

    def _kaleidoscope(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        cx, cy = W / 2, H / 2
        side = min(W, H)
        span = 2 * np.pi / 8
        wedge = np.linspace(0, span, BANDS)
        radii = side * 0.05 + a.smoothed * side * 0.45
        for k in range(8):
            ang = (wedge if k % 2 == 0 else span - wedge) + k * span
            pts = [(cx, cy)] + list(zip((cx + radii * np.cos(ang)).tolist(), (cy + radii * np.sin(ang)).tolist())) + [(cx, cy)]
            pygame.draw.polygon(surf, KALEIDO[k % len(KALEIDO)] + (191,), pts)

    def _vu(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        for i in range(2):
            t, cur = a.lr_levels[i], self.vu[i]
            self.vu[i] = cur + (t - cur) * (0.55 if t > cur else 0.10)
        dw = W / 2
        radius = min(dw, H) * 0.62
        f = font(round(15 * self.k), bold=True)
        for i in range(2):
            cx, cy = dw * i + dw / 2, H * 0.82
            pygame.draw.arc(surf, rgb("#4a4a58"), R(cx - radius, cy - radius, cx + radius, cy + radius), 0, math.pi,
                            max(1, round(3 * self.k)))
            level = float(self.vu[i])
            r = math.radians(165 - level * 150)
            nl = radius * 0.92
            col = rgb("#ff3b30") if level > 0.85 else rgb("#39c0ff")
            pygame.draw.line(surf, col, (cx, cy), (cx + nl * math.cos(r), cy - nl * math.sin(r)), max(1, round(3 * self.k)))
            self._text(surf, "L" if i == 0 else "R", (cx, cy - radius - 14 * self.k), f, rgb("#888888"), anchor="c")

    def _wave_row(self, surf, hist, cy, maxh, dark, bright):
        n = self.WAVE_LEN
        step = self.W / n
        w = max(1, round(2 * self.k))
        for i, v in enumerate(hist):
            x = i * step + step / 2
            h = v * maxh
            pygame.draw.line(surf, lerp(dark, bright, i / max(1, n - 1)), (x, cy - h), (x, cy + h), w)

    def _waveform_history(self, surf, a, info, bg, now):
        H = self.H
        if info.chips <= 1:
            chunk = a.samples[-512:]
            self.wave[0].append(min(1.0, float(np.max(np.abs(chunk))) / 20000.0) if len(chunk) else 0.0)
            self._wave_row(surf, self.wave[0], H / 2, H * 0.45, (20, 60, 90), (57, 192, 255))
            return
        chunk = a.stereo[-512:]
        self.wave[0].append(min(1.0, float(np.max(np.abs(chunk[:, 0]))) / 20000.0))
        self.wave[1].append(min(1.0, float(np.max(np.abs(chunk[:, 1]))) / 20000.0))
        rh = H / 2
        self._wave_row(surf, self.wave[0], rh / 2, rh * 0.40, (20, 60, 90), (57, 192, 255))
        self._wave_row(surf, self.wave[1], rh * 1.5, rh * 0.40, (90, 45, 15), (255, 154, 60))
        f = font(round(15 * self.k), bold=True)
        self._text(surf, tr("Links"), (6, 4), f, LABEL)
        self._text(surf, tr("Rechts"), (6, rh + 4), f, LABEL)

    @staticmethod
    def _fit(text, f, width):
        if not text or f.size(text)[0] <= width:
            return text or ""
        while text and f.size(text + "...")[0] > width:
            text = text[:-1]
        return (text + "...") if text else "..."

    def _vinyl_label(self, d, title, author):
        img = pygame.Surface((d, d), pygame.SRCALPHA)
        ft, fa = font(max(7, d // 9), bold=True), font(max(6, d // 12))
        mw = d * 0.72
        img.blit(ft.render(self._fit(title, ft, mw), True, (244, 228, 193)), (d * 0.14, d * 0.30))
        img.blit(fa.render(self._fit(author, fa, mw), True, (232, 201, 201)), (d * 0.14, d * 0.56))
        return img

    def _vinyl(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        cx, cy = W / 2, H / 2
        r = min(W, H) * 0.42
        vol = boost(band_energy(a.smoothed))
        self.vinyl_angle += 0.02 + vol * 0.22
        c = (cx, cy)
        pygame.draw.circle(surf, rgb("#111114"), c, r)
        pygame.draw.circle(surf, rgb("#2a2a30"), c, r, max(1, round(2 * self.k)))
        for i in range(6):
            pygame.draw.circle(surf, rgb("#232328"), c, r * (0.35 + 0.1 * i), 1)
        lr = r * (0.30 + vol * 0.24)
        pygame.draw.circle(surf, rgb("#b83c3c"), c, lr)
        pygame.draw.circle(surf, rgb("#7a2424"), c, lr, 1)
        ang = self.vinyl_angle
        pygame.draw.line(surf, rgb("#5a5a62"), (cx + r * 0.32 * math.cos(ang), cy + r * 0.32 * math.sin(ang)),
                         (cx + r * 0.97 * math.cos(ang), cy + r * 0.97 * math.sin(ang)), max(1, round(2 * self.k)))
        d = round(max(24, int(lr * 2)) / 4) * 4
        key = (info.title, info.author, d)
        if key != self._vinyl_key:
            self._vinyl_key, self._vinyl_img = key, self._vinyl_label(d, info.title, info.author)
        rot = pygame.transform.rotozoom(self._vinyl_img, -math.degrees(ang), 1.0)
        surf.blit(rot, rot.get_rect(center=(round(cx), round(cy))))
        pygame.draw.circle(surf, (0, 0, 0), c, r * 0.045)

    def _sid3voice(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        rows = info.chips
        groups = 3 * rows
        step = BANDS / groups
        vals = []
        for g in range(groups):
            lo = int(g * step)
            hi = max(lo + 1, int((g + 1) * step))
            vals.append(boost(band_energy(a.smoothed[lo:hi])))
        margin, gap = W * 0.08, W * 0.05
        bw = (W - 2 * margin - 2 * gap) / 3
        rh = H / rows
        sh = rh * 0.62 / 16
        sg = sh * 0.18
        for slot in range(groups):
            row, col = divmod(slot, 3)
            lit = int(round(vals[slot] * 16))
            base = row * rh + rh * 0.94
            x0 = margin + col * (bw + gap)
            for s in range(16):
                y1 = base - s * sh
                c = SEG_LIT[int(s / 15 * (len(SEG_LIT) - 1))] if s < lit else rgb("#222222")
                surf.fill(c + (255,), R(x0, y1 - sh + sg, x0 + bw, y1))
        f = font(round(16 * self.k), bold=True)
        for r in range(rows):
            addr = info.addresses[r] if r < len(info.addresses) else "?"
            self._text(surf, "SID%d (%s)" % (r + 1, addr) if rows > 1 else "SID (%s)" % addr,
                       (W / 2, r * rh + rh * 0.10), f, LABEL, anchor="c")

    VOICE_COLORS = (rgb("#ff7070"), rgb("#7ce67c"), rgb("#70a0ff"))
    ROLL_LO, ROLL_HI = 12, 108                                   # C0 .. C8 at most

    def _roll_range(self, frames, base):
        """the octaves the visible notes need (at least two), so a tune in a narrow range is not squeezed flat"""
        ns = [v[0] for _, ch in frames if base in ch for v in ch[base][3] if v[0] is not None and v[1] > 0.03]
        if not ns:
            return 36, 72
        lo = max(self.ROLL_LO, int(min(ns) - 1) // 12 * 12)
        hi = min(self.ROLL_HI, (int(max(ns) + 1) // 12 + 1) * 12)
        if hi - lo < 24:                                         # one octave: one more below (or above)
            lo = max(self.ROLL_LO, lo - 12)
            hi = lo + 24
        return lo, hi

    def _sidvoices(self, surf, a, info, bg, now):
        """the real voices from the Ultimate's debug stream: per SID a piano roll of the last 5 s (pitch up, time to
        the right, brightness = envelope) and on the right note, waveform and level of each voice"""
        W, H, k = self.W, self.H, self.k
        frames = info.sid[-250:]
        bases = sorted({b for _, chips in frames[-50:] for b in chips})[:3]
        if not bases:
            f = font(round(22 * k), bold=True)
            self._text(surf, tr("SID-Stimmen"), (W / 2, H * 0.42), f, LABEL, anchor="c")
            self._text(surf, info.sid_note or tr("Warte auf die Daten des Ultimate …"), (W / 2, H * 0.52),
                       font(round(16 * k)), rgb("#9a9a9a"), anchor="c")
            return
        rows = len(bases)
        y_top, y_bot = H * 0.15, H * 0.92                        # room for the title (top right) and the time
        rh = (y_bot - y_top) / rows
        x0, x1 = W * 0.06, W * 0.74
        n = 250
        dx = (x1 - x0) / n
        first = len(frames) - n                                  # index of the leftmost column (may be < 0)
        fh = font(round(15 * k), bold=True)
        fv = font(round(17 * k), bold=True)
        fs = font(round(13 * k))
        for r, base in enumerate(bases):
            r0 = y_top + r * rh
            top, bot = r0 + rh * 0.14, r0 + rh * 0.97
            lo, hi = self._roll_range(frames, base)
            span = hi - lo
            if not bg:
                surf.fill((14, 12, 40, 200), R(x0, top, x1, bot))
            for c in range(lo, hi + 1, 12):                       # a faint line at every C
                y = bot - (c - lo) / span * (bot - top)
                surf.fill((70, 64, 140, 255), R(x0, y, x1, y + 1))
                self._text(surf, "C%d" % (c // 12 - 1), (x0 - 5 * k, y), fs, (110, 105, 196), anchor="e")
            nh = max(3, min(round((bot - top) / span * 0.8), round(10 * k)))
            for v in range(3):
                col = self.VOICE_COLORS[v]
                run = None                                       # (start column, note, level step)
                for i in range(max(0, first), len(frames) + 1):
                    cur = None
                    if i < len(frames):
                        ch = frames[i][1].get(base)
                        if ch:
                            midi, lvl = ch[3][v][0], ch[3][v][1] * ch[0] / 15
                            if midi is not None and lvl > 0.03:
                                cur = (int(round(min(max(midi, lo), hi))), min(6, int(lvl * 7)))
                    if run and (cur is None or cur != run[1:]):
                        y = bot - (run[1] - lo) / span * (bot - top)
                        c = lerp((0, 0, 0), col, 0.25 + 0.75 * run[2] / 6)
                        surf.fill(c + (255,), R(x0 + (run[0] - first) * dx, y - nh / 2,
                                                 x0 + (i - first) * dx, y + nh / 2))
                        run = None
                    if cur and not run:
                        run = (i, cur[0], cur[1])
            last = frames[-1][1].get(base)
            self._text(surf, "SID%d %s" % (r + 1, "$%04X" % base) if rows > 1 else "SID $%04X" % base,
                       (x0, r0), fh, LABEL)
            if last:
                vol, cut, filt, vs = last
                self._text(surf, tr("Lautstärke %d") % vol + ("  Filter %d %%" % round(cut * 100) if filt & 7 else ""),
                           (x1, r0), fs, rgb("#9a9a9a"), anchor="ne")
                lh = (bot - top) / 3
                for v, (midi, lvl, ctrl, pw) in enumerate(vs):
                    y = top + v * lh
                    col = self.VOICE_COLORS[v]
                    on = lvl * vol / 15
                    px = W * 0.77
                    surf.fill(col + (255,), R(px, y + lh * 0.12, px + 6 * k, y + lh * 0.82))
                    self._text(surf, note_name(midi) if midi is not None and on > 0.03 else "---",
                               (px + 14 * k, y + lh * 0.08), fv, col if on > 0.03 else rgb("#666666"))
                    w = wave_name(ctrl) + (" %d%%" % round(pw * 100) if ctrl & 0x40 else "") + (" F" if filt >> v & 1 else "")
                    self._text(surf, w, (px + 70 * k, y + lh * 0.14), fs, LABEL)
                    bw = W * 0.18
                    surf.fill((40, 40, 60, 255), R(px + 14 * k, y + lh * 0.66, px + 14 * k + bw, y + lh * 0.78))
                    if on > 0.01:
                        surf.fill(col + (255,), R(px + 14 * k, y + lh * 0.66, px + 14 * k + bw * on, y + lh * 0.78))

    def _neon_grid(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        hy, cx = H * 0.56, W / 2
        dt = 0.0 if self.neon_last is None else max(0.0, min(0.2, now - self.neon_last))
        self.neon_last = now
        self.neon_phase = (self.neon_phase + dt * 0.45) % 1.0
        sm = a.smoothed
        bass = float(np.mean(sm[:max(1, BANDS // 6)]))
        overall = float(np.mean(sm))
        hz = lerp((255, 46, 108), (255, 180, 220), bass)
        pygame.draw.line(surf, hz, (0, hy), (W, hy), max(1, round((2 + bass * 2) * self.k)))
        grid = lerp((30, 120, 180), (120, 220, 255), bass)
        depth = H * 0.10 * bass
        for k in range(8):
            frac = min(((k + self.neon_phase) / 8) ** 2.2, 1.0)
            y = hy + frac * (H - hy)
            pts = []
            for p in range(25):
                xf = p / 24
                pts.append((xf * W, y + (1.0 - (2 * xf - 1) ** 2) * depth * frac))
            pygame.draw.lines(surf, grid, False, pts, 1)
        for i in range(14):
            t = i / 13
            pygame.draw.line(surf, grid, (-W * 0.5 + t * W * 2.0, H), (cx, hy), 1)
        nb = 56
        vals = np.interp(np.linspace(0, 1, nb), np.linspace(0, 1, BANDS), sm)
        bw, mh = W / nb, hy * 0.92
        for i in range(nb):
            lv = float(vals[i])
            surf.fill(lerp((57, 192, 255), (255, 46, 200), lv) + (255,),
                      R(i * bw + bw * 0.18, hy - lv * mh, (i + 1) * bw - bw * 0.18, hy))
        sr = min(W, H) * (0.15 + 0.02 * overall)
        scy = hy - sr * 0.5
        sc = lerp((255, 60, 110), (255, 210, 90), overall)
        n = 7
        for i in range(n):
            y0 = scy - sr + (i / n) ** 1.15 * 2 * sr
            y1 = min(scy - sr + ((i + 0.62) / n) ** 1.15 * 2 * sr, scy + sr)
            dy = (y0 + y1) / 2 - scy
            if y0 >= y1 or abs(dy) >= sr:
                continue
            hw = (sr ** 2 - dy ** 2) ** 0.5
            surf.fill(sc + (255,), R(cx - hw, y0, cx + hw, y1))

    def _flicker(self, slots, now, make, surf, f, color):
        for slot in slots:
            if now >= slot[0]:
                slot[0], slot[1], slot[2] = make()
            if slot[1]:
                self._text(surf, slot[1], slot[2], f, color)

    def _glitch(self, st, overall, now):
        delta = overall - st["prev"]
        st["prev"] = overall
        if delta > 0.18 or (overall > 0.75 and self.rnd.random() < 0.04):
            st["glitch_until"] = now + self.rnd.uniform(0.06, 0.16)
        return now < st["glitch_until"]

    def _cyberpunk(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        overall = float(np.mean(a.smoothed))
        glitching = self._glitch(self.cyber, overall, now)
        bw, mh = W / BANDS, H * 0.85
        dx = bw * 0.35
        ghosts = []
        for i in range(BANDS):
            lv = float(a.smoothed[i])
            x0, x1, y0 = i * bw + bw * 0.1, (i + 1) * bw - bw * 0.1, H - lv * mh
            col = lerp((252, 238, 10), (255, 0, 90), lv) + (255,)
            if glitching and self.rnd.random() < 0.6:
                j = self.rnd.uniform(-bw * 0.4, bw * 0.4)
                surf.fill(col, R(x0 + j, y0, x1 + j, H))
                ghosts.append((x0 + j, x1 + j, y0))
            else:
                surf.fill(col, R(x0, y0, x1, H))
        for x0, x1, y0 in ghosts:
            surf.fill(rgb("#ff003c") + (255,), R(x0 - dx, y0, x1 - dx, H))
        for x0, x1, y0 in ghosts:
            surf.fill(rgb("#00f0ff") + (255,), R(x0 + dx, y0, x1 + dx, H))
        for i in range(40):
            y = (i + 0.5) * H / 40
            pygame.draw.line(surf, rgb("#332400"), (0, y), (W, y), 1)
        bl, m = min(W, H) * 0.06, 10 * self.k
        hw = max(1, round(2 * self.k))
        for x, y, sx, sy in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
            pygame.draw.line(surf, rgb("#fcee0a"), (x, y), (x + sx * bl, y), hw)
            pygame.draw.line(surf, rgb("#fcee0a"), (x, y), (x, y + sy * bl), hw)

        def make():
            nxt = now + self.rnd.uniform(0.15, 0.7)
            if self.rnd.random() < 0.55:
                return nxt, "0x" + "".join(self.rnd.choice("0123456789ABCDEF") for _ in range(4)), \
                    (self.rnd.uniform(W * 0.05, W * 0.85), self.rnd.uniform(H * 0.05, H * 0.30))
            return nxt, None, (0, 0)
        self._flicker(self.cyber["hex"], now, make, surf, font(round(13 * self.k), bold=True, mono=True), rgb("#00f0ff"))

    def _shadowrun(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        overall = float(np.mean(a.smoothed))
        gc = lerp((10, 40, 32), (20, 90, 70), overall)
        for i in range(9):
            y = (i + 1) * H / 10
            pygame.draw.line(surf, gc, (0, y), (W, y), 1)
        for i in range(13):
            x = (i + 1) * W / 14
            pygame.draw.line(surf, gc, (x, 0), (x, H), 1)
        glitching = self._glitch(self.sr, overall, now)
        bw, mh = W / BANDS, H * 0.85
        gx, gy, gdy = bw * 0.25, H * 0.02, H * 0.025
        cores = []
        for i in range(BANDS):
            lv = float(a.smoothed[i])
            x0, x1, y0 = i * bw + bw * 0.18, (i + 1) * bw - bw * 0.18, H - lv * mh
            surf.fill(lerp((6, 40, 32), (0, 130, 105), lv) + (255,), R(x0 - gx, y0 - gy, x1 + gx, H))
            cores.append((x0, x1, y0, lerp((0, 140, 100), (170, 255, 235), lv), glitching and self.rnd.random() < 0.6))
        for x0, x1, y0, c, _g in cores:
            surf.fill(c + (255,), R(x0, y0, x1, H))
        for x0, x1, y0, c, g in cores:
            if g:
                surf.fill(rgb("#ff2a4d") + (255,), R(x0, y0 - gdy, x1, H - gdy))
        for x0, x1, y0, c, g in cores:
            if g:
                surf.fill(rgb("#00d9ff") + (255,), R(x0, y0 + gdy, x1, H + gdy))
        rr = min(W, H) * 0.035
        rot = (now * 20) % 360
        for idx, (cx, cy) in enumerate(((W * 0.12, H * 0.18), (W * 0.88, H * 0.80))):
            pygame.draw.circle(surf, rgb("#00ff9c"), (cx, cy), rr, 1)
            ang = math.radians(rot if idx == 0 else -rot)
            for an in (ang, ang + math.pi / 2):
                dx, dy = math.cos(an) * rr * 1.6, math.sin(an) * rr * 1.6
                pygame.draw.line(surf, rgb("#00ff9c"), (cx - dx, cy - dy), (cx + dx, cy + dy), 1)
        for i in range(36):
            y = (i + 0.5) * H / 36
            pygame.draw.line(surf, rgb("#062018"), (0, y), (W, y), 1)
        fixed = ["SYSTEM: ACTIVE", "DECK_TEMP: %dC" % (42 + int(overall * 8)), "SIGNAL: %d%%" % int(overall * 100)]
        pos = [(W * 0.03, H * 0.03), (W * 0.03, H * 0.085), (W * 0.03, H * 0.14),
               (W * 0.74, H * 0.03), (W * 0.74, H * 0.085), (W * 0.74, H * 0.14)]
        f = font(round(13 * self.k), bold=True, mono=True)
        for idx, slot in enumerate(self.sr["read"]):
            if now >= slot[0]:
                slot[0] = now + self.rnd.uniform(0.4, 1.4)
                if idx < len(fixed):
                    slot[1] = fixed[idx]
                else:
                    slot[1] = ("0x" + "".join(self.rnd.choice("0123456789ABCDEF") for _ in range(4))
                               if self.rnd.random() < 0.7 else None)
                slot[2] = pos[idx]
            if slot[1]:
                self._text(surf, slot[1], slot[2], f, rgb("#00ff9c"))

    def _milkdrop(self, surf, a, info, bg, now):
        W, H = self.W, self.H
        cx, cy = W / 2, H / 2
        base, extra = min(W, H) * 0.15, min(W, H) * 0.17
        sm = a.smoothed
        pulse = 1.0 + float(np.mean(sm[:max(1, BANDS // 6)])) * 0.12
        self.milk_hue = (self.milk_hue + 0.0035) % 1.0
        n = self.MILK_POINTS
        vals = sm[np.linspace(0, BANDS - 1, n).astype(int)]
        lv = np.array([boost(float(v), power=0.7, gain=1.15) for v in vals])
        ang0 = np.arange(n) / n * 2 * math.pi
        for scale, ph, hue, bright, al in ((1.18, 0.6, 0.5, 0.35, 128), (1.06, -0.4, 0.25, 0.55, 128),
                                           (0.92, 0.0, 0.0, 0.9, 191)):
            ang = ang0 + ph
            r = (base + lv * extra) * scale * pulse + np.sin(ang * 3 + now * 1.4 + ph) * (base * 0.06)
            pts = list(zip((cx + r * np.cos(ang)).tolist(), (cy + r * np.sin(ang)).tolist()))
            pygame.draw.polygon(surf, hsv(self.milk_hue + hue, 0.75, bright) + (al,), pts)
