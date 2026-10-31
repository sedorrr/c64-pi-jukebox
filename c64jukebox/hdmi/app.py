"""The HDMI service's main loop (python3 -m c64jukebox.hdmi): ~30 pictures a second while switched on; off = the
display is released (the text console comes back).

Settings (written by the jukebox into hdmi-in.json, key "cfg"):
  on, mode (style, see styles.MODES), auto + auto_s + auto_modes (change the style every N s while a tune plays,
  like the PC jukebox's "Auto-Switch Style"), bg ("none" | "images" | "video"), img_s (seconds per picture),
  shuffle, opacity (0..100 % brightness of the background), osd (title etc. at the top right, time at the bottom)."""
import json
import os
import queue
import random
import subprocess
import threading
import time
from collections import deque

import numpy as np
import pygame

from ..i18n import set_lang, tr
from .analyzer import Analyzer
from .receivers import AUDIO_PORT, SID_PORT, VIC_PALETTE, VIDEO_PORT, AudioReceiver, SidReceiver, VideoReceiver
from .screen import SIZE, Item
from .modes import DEFAULTS, MODES
from .soundproc import SOUND_PORT, Sound, SoundProc  # noqa: F401  (Sound: the tests)
from .styles import Info, Styles

LAYER = (960, 540)
MARGIN = (60, 48)                              # text this far from the edge: many TVs cut off a little (overscan)
FADE_S = 0.64                                  # cross-fade of the slide show, as in the PC jukebox (10 x 64 ms)
VIDEO_RECT = (240, 0, 1440, 1080)              # the C64 picture in 4:3 with black borders
IMAGE_EXT = (".jpg", ".jpeg", ".png")


def fmt(s):
    s = max(0, int(s or 0))
    return "%d:%02d" % (s // 60, s % 60)


def cover(surf, size=SIZE):
    """scale + crop so the picture fills the screen without distortion (CSS "cover")"""
    w, h = surf.get_size()
    sc = max(size[0] / w, size[1] / h)
    nw, nh = max(size[0], round(w * sc)), max(size[1], round(h * sc))
    if surf.get_bitsize() not in (24, 32):              # e.g. a PNG with a palette: smoothscale wants 24/32 bit
        rgb = pygame.Surface(surf.get_size(), 0, 24)
        rgb.blit(surf, (0, 0))
        surf = rgb
    big = pygame.transform.smoothscale(surf, (nw, nh))
    return big.subsurface(((nw - size[0]) // 2, (nh - size[1]) // 2) + size).copy()


class Slideshow:
    """pictures of a folder, each img_s seconds, cross-faded; loading + scaling run in a thread"""

    def __init__(self, load=pygame.image.load, rnd=None):
        self.load = load
        self.rnd = rnd or random.Random()
        self.folder, self.shuffle = None, False
        self.files, self.idx = [], -1
        self.cur = self.nxt = None                # (surface, version)
        self.fade_t0 = None
        self.switch_at = 0.0
        self.ver = 0
        self.q = queue.Queue()
        self.done = queue.Queue()
        self.loading = False
        self.scanned = 0.0
        self.switches = deque(maxlen=6)          # when a picture was loaded and how long it took (diagnosis)
        threading.Thread(target=self._worker, daemon=True, name="pictures").start()

    def _worker(self):
        while True:
            path = self.q.get()
            t0 = time.monotonic()
            try:
                self.done.put(cover(self.load(path)))
                self.switches.append("%s geladen in %d ms" % (time.strftime("%H:%M:%S"), (time.monotonic() - t0) * 1000))
            except (pygame.error, OSError, ValueError):
                self.done.put(None)

    def scan(self, now):
        try:
            names = sorted(n for n in os.listdir(self.folder) if n.lower().endswith(IMAGE_EXT)) if self.folder else []
        except OSError:
            names = []
        files = [os.path.join(self.folder, n) for n in names]
        if sorted(files) != sorted(self.files):
            if self.shuffle:
                self.rnd.shuffle(files)
            self.files, self.idx = files, -1
        self.scanned = now

    def configure(self, folder, shuffle, now):
        if folder != self.folder or bool(shuffle) != self.shuffle:
            self.folder, self.shuffle = folder, bool(shuffle)
            self.files = []
            self.scan(now)
        elif now - self.scanned > 30:                     # new pictures from the web page
            self.scan(now)

    def _next_path(self):
        if not self.files:
            return None
        self.idx += 1
        if self.idx >= len(self.files):
            last = self.files[-1]
            if self.shuffle and len(self.files) > 1:
                self.rnd.shuffle(self.files)
                if self.files[0] == last:                 # no picture twice in a row
                    j = self.rnd.randrange(1, len(self.files))
                    self.files[0], self.files[j] = self.files[j], self.files[0]
            self.idx = 0
        return self.files[self.idx]

    def items(self, now, interval, light):
        if not self.loading and self.nxt is None:            # always one picture ready ahead
            path = self._next_path()
            if path:
                self.loading = True
                self.q.put(path)
        try:
            surf = self.done.get_nowait()
            self.loading = False
            if surf is not None:
                self.ver += 1
                if self.cur is None:
                    self.cur, self.switch_at = (surf, self.ver), now + interval
                else:
                    self.nxt = (surf, self.ver)
        except queue.Empty:
            pass
        if self.nxt is not None and self.fade_t0 is None and now >= self.switch_at:
            self.fade_t0 = now
        out = []
        if self.cur:
            out.append(Item("bg_a", self.cur[0], self.cur[1], (0, 0) + SIZE, 255, light))
        if self.fade_t0 is not None:
            t = min(1.0, (now - self.fade_t0) / FADE_S)
            out.append(Item("bg_b", self.nxt[0], self.nxt[1], (0, 0) + SIZE, 255 * t, light))
            if t >= 1.0:
                self.cur, self.nxt, self.fade_t0 = self.nxt, None, None
                self.switch_at = now + interval
        return out

    def clear(self):
        self.cur = self.nxt = None
        self.fade_t0 = None


class Osd:
    """title, SID chips and year at the top right, time at the bottom right (like the PC jukebox, for a TV)"""

    def __init__(self):
        from .styles import font
        self.f_title = font(34, italic=True)
        self.f_small = font(26)
        self.cache = {}

    def _block(self, key, lines, anchor):
        sig = tuple(lines)
        c = self.cache.get(key)
        if c and c[0] == sig:
            return c[1], c[2]
        rendered = []
        for i, (txt, f) in enumerate(lines):
            if not txt:
                continue
            rendered.append((f.render(txt, True, (225, 225, 225)), f.render(txt, True, (0, 0, 0))))
        w = max([r[0].get_width() for r in rendered] + [1]) + 4
        h = sum(r[0].get_height() + 2 for r in rendered) + 4
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        y = 0
        for fg, sh in rendered:
            x = w - fg.get_width() - 4 if anchor == "e" else 0
            surf.blit(sh, (x + 2, y + 2))
            surf.blit(fg, (x, y))
            y += fg.get_height() + 2
        ver = (c[2] + 1) if c else 1
        self.cache[key] = (sig, surf, ver)
        return surf, ver

    def qr(self, url):
        """the QR code of the web page's address: dark modules on a white square with a quiet zone"""
        c = self.cache.get("qr")
        if c and c[0] == url:
            return c[1], c[2]
        from .qr import encode
        m = encode(url)
        px, quiet = 7, 3
        side = (len(m) + 2 * quiet) * px
        s = pygame.Surface((side, side))
        s.fill((255, 255, 255))
        for y, row in enumerate(m):
            for x, dark in enumerate(row):
                if dark:
                    s.fill((0, 0, 0), ((x + quiet) * px, (y + quiet) * px, px, px))
        ver = (c[2] + 1) if c else 1
        self.cache["qr"] = (url, s, ver)
        return s, ver

    def items(self, player, note="", name="", lift=0, stil=True, ip=""):
        out = []
        now = (player or {}).get("now") or {}
        state = (player or {}).get("state")
        mx, my = MARGIN
        if not (now and state in ("play", "pause", "load")) and player and name:
            # nothing plays: say so (silence alone would look like a black screen)
            s, v = self._block("idle", [(tr("Es läuft gerade nichts"), self.f_title),
                                        (tr("Bedienen: http://%s.local/") % name, self.f_small)] +
                               ([(tr("oder den QR-Code mit dem Handy scannen"), self.f_small)] if ip else []), "e")
            out.append(Item("osd_idle", s, v, (SIZE[0] - mx - s.get_width(), my) + s.get_size()))
            if ip:                                            # the address as a number: phones often miss ".local"
                q, qv = self.qr("http://%s/" % ip)            # left of the text: the news card (y >= 300) stays clear
                out.append(Item("osd_qr", q, qv, (SIZE[0] - mx - s.get_width() - 24 - q.get_width(), my) + q.get_size(),
                                smooth=False))
        if now and state in ("play", "pause", "load"):
            title = now.get("title") or now.get("name") or ""
            if now.get("author"):
                title = "%s - %s" % (title, now["author"]) if title else now["author"]
            models = now.get("models") or []
            addrs = ["$" + str(a).lstrip("$") for a in now.get("sids") or []]       # the header gives "D400"
            req = ""
            if models and addrs:
                req = ("%s - %s" % (models[0], "/".join(addrs)) if len(set(models)) == 1 else
                       ", ".join("%s - %s" % p for p in zip(models, addrs)))
                req = tr("Benötigt: %s") % req
            lines = [(title, self.f_title), (req, self.f_small), (now.get("year") or "", self.f_small)]
            if (now.get("songs") or 1) > 1:
                lines.append((tr("Lied %d/%d") % (now.get("song") or 1, now["songs"]), self.f_small))
            s, v = self._block("top", lines, "e")
            out.append(Item("osd_top", s, v, (SIZE[0] - mx - s.get_width(), my) + s.get_size()))
            secs, el = now.get("secs") or 0, player.get("el") or 0
            t = fmt(el) + (" / " + fmt(secs) if secs else "") + ("  (%s)" % tr("Pause") if state == "pause" else "")
            s, v = self._block("time", [(t, self.f_title)], "e")
            out.append(Item("osd_time", s, v, (SIZE[0] - mx - s.get_width(), SIZE[1] - my - lift - s.get_height()) + s.get_size()))
            hint = ""                                         # a length found for this tune: small, above the time
            if now.get("hvsc"):
                hint = tr("Länge %s in der HVSC gefunden · OK: übernehmen") % fmt(now["hvsc"]["len"])
            elif now.get("loop"):
                hint = tr("Fängt nach %s von vorn an · OK: als Länge übernehmen") % fmt(now["loop"])
            if hint:
                th = s.get_height()
                s, v = self._block("hint", [(hint, self.f_small)], "e")
                out.append(Item("osd_hint", s, v, (SIZE[0] - mx - s.get_width(),
                                                   SIZE[1] - my - lift - th - s.get_height()) + s.get_size()))
            if stil and now.get("stil"):                      # STIL: background to the tune, bottom left
                text = " · ".join(now["stil"])
                lines = [(x, self.f_small) for x in wrap(text, self.f_small, 1150, 4)]
                s, v = self._block("stil", lines, "w")
                out.append(Item("osd_stil", s, v, (mx, SIZE[1] - my - lift - s.get_height()) + s.get_size()))
        if note:
            s, v = self._block("note", [(note, self.f_title)], "w")
            out.append(Item("osd_note", s, v, ((SIZE[0] - s.get_width()) // 2, (SIZE[1] - s.get_height()) // 2) + s.get_size()))
        return out


class TitleCard:
    """a large card in the middle when a new tune starts (title, composer, SIDs, STIL), fading out after a few
    seconds - the small text at the top right stays"""
    SIZE = (1200, 640)                            # at most; the height follows the text
    IN, OUT = 0.4, 0.8

    def __init__(self):
        from .styles import font
        self.f_head, self.f_title, self.f_author, self.f_info = font(26), font(64, bold=True), font(40), font(30)
        self.key, self.at, self.card, self.ver = None, None, None, 0

    def _render(self, now):
        w, h = self.SIZE
        title = now.get("title") or now.get("name") or ""
        lines = wrap(title, self.f_title, w - 100, 2)
        info = [now.get("year") or ""]
        addrs = now.get("sids") or []
        if addrs:
            info.append("%d SID%s ($%s)" % (len(addrs), "s" if len(addrs) > 1 else "",
                                            "/$".join(str(a).lstrip("$") for a in addrs)))
        if (now.get("songs") or 1) > 1:
            info.append(tr("Lied %d/%d") % (now.get("song") or 1, now["songs"]))
        stil = wrap(" · ".join(now.get("stil") or []), self.f_info, w - 100, 2)
        s = pygame.Surface((w, h), pygame.SRCALPHA)       # the text first, then the card around it

        def put(txt, f, y, color):
            r = f.render(txt, True, color)
            s.blit(r, ((w - r.get_width()) // 2, y))
            return y + r.get_height()
        y = put(tr("Jetzt läuft"), self.f_head, 34, (175, 165, 240)) + 14
        for line in lines:
            y = put(line, self.f_title, y, (255, 255, 255)) + 4
        y = put(now.get("author") or "", self.f_author, y + 6, (159, 226, 255)) + 10
        y = put("  ·  ".join(x for x in info if x), self.f_info, y, (215, 210, 245)) + 16
        for line in stil:
            y = put(line, self.f_info, y, (200, 195, 235)) + 6
        card = pygame.Surface((w, min(h, y + 28)), pygame.SRCALPHA)
        pygame.draw.rect(card, (12, 8, 46, 220), card.get_rect(), border_radius=26)
        pygame.draw.rect(card, (120, 105, 196, 255), card.get_rect(), 3, border_radius=26)
        card.blit(s, (0, 0))
        return card

    def items(self, player, now, secs):
        p = player or {}
        n = p.get("now") or {}
        if not n or p.get("state") not in ("play", "pause", "load"):
            self.key = None
            return []
        key = (n.get("src"), n.get("path"), n.get("song"))
        if key != self.key:
            self.key = key
            # a tune that has long been playing (the service started late, or the TV switched on): no card
            self.at = now if (p.get("el") or 0) < secs else None
            self.card = None
        if self.at is None:
            return []
        t = now - self.at
        if t >= secs:
            self.at = None
            return []
        if self.card is None or (n.get("stil") and self.card[1] != tuple(n.get("stil"))):
            self.ver += 1
            self.card = (self._render(n), tuple(n.get("stil") or ()))
        a = min(1.0, t / self.IN, (secs - t) / self.OUT)
        s = self.card[0]
        return [Item("titlecard", s, self.ver, ((SIZE[0] - s.get_width()) // 2, (SIZE[1] - s.get_height()) // 2)
                     + s.get_size(), 255 * max(0.0, a))]


class MenuView:
    """the TV menu (tvmenu.py) as a box in C64 colours in the middle: the chosen line inverted like the C64's cursor"""
    W, LINE = 1100, 64
    BG, BORDER, TEXT, VALUE, HINT = (53, 40, 121, 240), (108, 94, 181, 255), (255, 255, 255), (159, 226, 255), (175, 165, 240)

    def __init__(self):
        from .styles import font
        self.f_title, self.f_item, self.f_small = font(44, bold=True), font(38), font(28)
        self.key, self.surf, self.ver = None, None, 0

    def _render_kbd(self, m):
        """the keyboard on the screen: the name being typed, the keys in rows, the chosen one inverted"""
        rows, cur = m.get("rows") or [], m.get("cur") or [0, 0]
        key_w, key_h, gap = 66, 62, 8
        h = 150 + 90 + len(rows) * (key_h + gap) + (50 if m.get("note") else 0) + 70
        s = pygame.Surface((self.W, h), pygame.SRCALPHA)
        pygame.draw.rect(s, self.BG, s.get_rect(), border_radius=18)
        pygame.draw.rect(s, self.BORDER, s.get_rect(), 6, border_radius=18)
        t = _fit_surface(self.f_title.render(m.get("title", ""), True, self.TEXT), self.W - 100)
        s.blit(t, ((self.W - t.get_width()) // 2, 34))
        box = pygame.Rect(60, 110, self.W - 120, 70)
        pygame.draw.rect(s, (12, 8, 46, 255), box, border_radius=8)
        txt = self.f_item.render((m.get("text") or "") + "\u2588", True, self.VALUE)       # the C64 cursor block
        s.blit(txt, (box.x + 18, box.y + (box.h - txt.get_height()) // 2))
        y = 210
        for r, row in enumerate(rows):
            widths = [key_w if len(k) == 1 else 200 for k in row]
            x = (self.W - (sum(widths) + gap * (len(row) - 1))) // 2
            for c, k in enumerate(row):
                rect = pygame.Rect(x, y, widths[c], key_h)
                chosen = [r, c] == list(cur)
                pygame.draw.rect(s, self.BORDER if chosen else (40, 30, 100, 255), rect, border_radius=8)
                lab = self.f_item.render(k, True, self.TEXT)
                s.blit(lab, (rect.centerx - lab.get_width() // 2, rect.centery - lab.get_height() // 2))
                x += widths[c] + gap
            y += key_h + gap
        y += 16
        if m.get("note"):
            nt = self.f_small.render(m["note"], True, self.VALUE)
            s.blit(nt, ((self.W - nt.get_width()) // 2, y))
            y += 50
        hint = self.f_small.render(m.get("hint", ""), True, self.HINT)
        s.blit(hint, ((self.W - hint.get_width()) // 2, y))
        return s

    TITLE_LINE, NOTE_LINE = 54, 40

    def _render(self, m):
        """a long title (the questions name the tune) and note wrap onto more lines, the box grows with them"""
        if m.get("kind") == "kbd":
            return self._render_kbd(m)
        n = len(m.get("items") or [])
        width = self.W - 100
        titles = wrap(m.get("title", ""), self.f_title, width, 3) or [""]
        notes = wrap(m.get("note", ""), self.f_small, width, 2)
        extra = (len(titles) - 1) * self.TITLE_LINE
        h = 150 + extra + n * self.LINE + (10 + self.NOTE_LINE * len(notes) if notes else 0) + 70
        s = pygame.Surface((self.W, h), pygame.SRCALPHA)
        pygame.draw.rect(s, self.BG, s.get_rect(), border_radius=18)
        pygame.draw.rect(s, self.BORDER, s.get_rect(), 6, border_radius=18)
        for k, line in enumerate(titles):
            t = _fit_surface(self.f_title.render(line, True, self.TEXT), width)
            s.blit(t, ((self.W - t.get_width()) // 2, 34 + k * self.TITLE_LINE))
        y = 120 + extra
        if m.get("more_up"):
            u = self.f_small.render("▲", True, self.HINT)
            s.blit(u, ((self.W - u.get_width()) // 2, y - 30))
        for i, it in enumerate(m.get("items") or []):
            chosen = i == m.get("sel")
            if chosen:
                pygame.draw.rect(s, self.BORDER, (36, y, self.W - 72, self.LINE - 6), border_radius=8)
            v = self.f_item.render(it["v"], True, self.TEXT if chosen else self.VALUE) if it.get("v") else None
            room = self.W - 120 - (v.get_width() + 30 if v else 0)
            label = self.f_item.render(_shorten(it.get("l", ""), self.f_item, room), True, self.TEXT)
            s.blit(label, (60, y + (self.LINE - 6 - label.get_height()) // 2))
            if v:
                s.blit(v, (self.W - 60 - v.get_width(), y + (self.LINE - 6 - v.get_height()) // 2))
            y += self.LINE
        if m.get("more_down"):
            d = self.f_small.render("▼", True, self.HINT)
            s.blit(d, ((self.W - d.get_width()) // 2, y - 6))
        y += 24
        for line in notes:
            nt = _fit_surface(self.f_small.render(line, True, self.VALUE), width)
            s.blit(nt, ((self.W - nt.get_width()) // 2, y))
            y += self.NOTE_LINE
        if notes:
            y += 10
        hint = self.f_small.render(m.get("hint", ""), True, self.HINT)
        s.blit(hint, ((self.W - hint.get_width()) // 2, y))
        return s

    def items(self, m):
        if not m:
            self.key = None
            return []
        key = json.dumps(m, sort_keys=True)
        if key != self.key:
            self.key, self.surf = key, self._render(m)
            self.ver += 1
        s = self.surf
        return [Item("menu", s, self.ver, ((SIZE[0] - s.get_width()) // 2, (SIZE[1] - s.get_height()) // 2)
                     + s.get_size(), 255)]


def _shorten(text, f, width):
    """one line that fits `width` pixels, shortened with …"""
    if f.size(text)[0] <= width:
        return text
    while text and f.size(text + "…")[0] > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _fit_surface(surf, width):
    """a rendered line wider than `width` (one long word) scaled down to it"""
    if surf.get_width() <= width:
        return surf
    return pygame.transform.smoothscale(surf, (width, max(1, surf.get_height() * width // surf.get_width())))


def wrap(text, f, width, lines):
    """text -> at most `lines` lines that fit `width` pixels (the last one shortened with …)"""
    words, out = (text or "").split(), []
    while words and len(out) < lines:
        line = words.pop(0)
        while words and f.size(line + " " + words[0])[0] <= width:
            line += " " + words.pop(0)
        out.append(line)
    if words and out:
        last = out[-1]
        while last and f.size(last + " …")[0] > width:
            last = last[:-1]
        out[-1] = last.rstrip() + " …"
    return out


class NewsView:
    """retro news: a large card while nothing plays (one after the other), a ticker at the bottom during the music"""
    CARD = (1560, 560)
    TICKER_H = 56
    SPEED = 110                                   # ticker, pixels per second (1080p)

    def __init__(self):
        from .styles import font
        self.f_src, self.f_title, self.f_sum = font(28), font(48, bold=True), font(31)
        self.f_tick = font(30, bold=True)
        self.idx, self.next_at, self.shown_at = 0, 0.0, 0.0
        self.cache = {}                           # key -> (surface, version)
        self.band = None
        self.heads = None

    def _card(self, n):
        key = ("card", n["title"], n.get("pic", ""))
        if key in self.cache:
            return self.cache[key]
        w, h = self.CARD
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(s, (12, 8, 46, 215), s.get_rect(), border_radius=22)
        pygame.draw.rect(s, (120, 105, 196, 255), s.get_rect(), 3, border_radius=22)
        x = 44
        pic = None
        if n.get("pic"):
            try:
                pic = pygame.image.load(n["pic"])
            except (pygame.error, OSError):
                pic = None
        if pic is not None:
            pw, ph = pic.get_size()
            sc = min(560 / pw, (h - 88) / ph)
            if pic.get_bitsize() not in (24, 32):
                rgb = pygame.Surface(pic.get_size(), 0, 24)
                rgb.blit(pic, (0, 0))
                pic = rgb
            pic = pygame.transform.smoothscale(pic, (max(1, int(pw * sc)), max(1, int(ph * sc))))
            s.blit(pic, (x, (h - pic.get_height()) // 2))
            x += pic.get_width() + 40
        tw = w - x - 44
        y = 40
        s.blit(self.f_src.render("%s  ·  %s" % (n.get("src", ""), n.get("date", "")), True, (175, 165, 240)), (x, y))
        y += 52
        for line in wrap(n.get("title", ""), self.f_title, tw, 3):
            s.blit(self.f_title.render(line, True, (255, 255, 255)), (x, y))
            y += 60
        y += 14
        for line in wrap(n.get("summary", ""), self.f_sum, tw, max(0, (h - y - 30) // 40)):
            s.blit(self.f_sum.render(line, True, (215, 210, 245)), (x, y))
            y += 40
        if len(self.cache) > 60:
            self.cache.clear()
        self.cache[key] = (s, len(self.cache) + 1)
        return self.cache[key]

    def panel(self, news, now, every):
        if now >= self.next_at:
            if self.next_at:
                self.idx += 1
            self.next_at, self.shown_at = now + every, now
        n = news[self.idx % len(news)]
        surf, ver = self._card(n)
        w, h = self.CARD
        alpha = min(255, 255 * (now - self.shown_at) / 0.6)            # each card fades in
        return [Item("news", surf, ver, ((SIZE[0] - w) // 2, (SIZE[1] - h) // 2 + 40, w, h), alpha)]   # clear of the text

    def ticker(self, news, now):
        heads = tuple("%s:  %s" % (n.get("src", ""), n.get("title", "")) for n in news)
        if heads != self.heads:
            self.heads = heads
            self.tsurf = []
            for t in heads:
                img = self.f_tick.render(t + "      •      ", True, (255, 240, 160))
                if img.get_width() > 2000:                               # the graphics chip takes at most 2048
                    img = img.subsurface((0, 0, 2000, img.get_height())).copy()
                self.tsurf.append(img)
            self.tver = (self.tver + 1) if hasattr(self, "tver") else 1
        if self.band is None:
            self.band = pygame.Surface((SIZE[0], self.TICKER_H), pygame.SRCALPHA)
            self.band.fill((0, 0, 0, 160))
        y = SIZE[1] - MARGIN[1] - self.TICKER_H
        out = [Item("ticker_bg", self.band, 1, (0, y, SIZE[0], self.TICKER_H))]
        total = sum(s.get_width() for s in self.tsurf) or 1
        x = SIZE[0] - (now * self.SPEED) % (total + SIZE[0])
        for k, s in enumerate(self.tsurf):
            w = s.get_width()
            if x + w > 0 and x < SIZE[0]:
                out.append(Item("tick%d" % k, s, self.tver, (int(x), y + (self.TICKER_H - s.get_height()) // 2) + s.get_size()))
            x += w
        return out


SLOW_S = 0.15                                      # a picture taking this long: logged


class HdmiApp:
    def __init__(self, run_dir, open_screen, fps=30, audio_port=AUDIO_PORT, video_port=VIDEO_PORT, clock=time.monotonic,
                 seed=None, sid_port=SID_PORT):
        self.run_dir = run_dir
        self.open_screen = open_screen
        self.fps = fps
        self.audio_port, self.video_port, self.sid_port = audio_port, video_port, sid_port
        self.clock = clock
        self.cfg = dict(DEFAULTS)
        self.player, self.img_dir, self.name, self.ip = {}, "", "", ""
        self.read_at = -1e9
        self.in_mtime = None
        self.screen = None
        self.screen_note = ""
        self.audio = self.video = self.sid = None
        self.sid_want = False                          # the SID voices are shown: the jukebox asks for the debug stream
        self.sid_msg = ""                              # from the jukebox: why the Ultimate sends none
        self.senders = set()                           # stream data only from these (the Ultimates' Ethernet addresses)
        self.menu = None                               # the TV menu (tvmenu.py view) or None
        self.menuview = None
        self.sound = None
        self.sound_cmd = None                          # tests: something instead of aplay
        self.sound_port = SOUND_PORT                   # the sound process' port (the jukebox sends there; tests: 0)
        self.player_at = 0.0                           # when the player state was read (to count the time on)
        self.fade_song = None                          # the song the fade belongs to
        self.faded_out = False
        self.fade_log = deque(maxlen=8)
        self.slow = deque(maxlen=12)                   # pictures that took long (diagnosis)
        self.in_gap = 0.0
        self.last_music = None                         # idle: effects fade out after idle_s without music
        self.viz_alpha, self.viz_at = 255.0, None
        self.news_list = []
        self.newsview = NewsView()
        self.titlecard = None
        self.analyzer = Analyzer()
        self.styles = Styles(LAYER, seed=seed)
        self.rnd = random.Random(seed)
        self.layer = None
        self.slides = None
        self.osd = None
        self.frame = 0
        self.mode = None
        self.base_mode = None
        self.cycle_at = None
        self.video_surf, self.video_ver = None, 0
        self.stat_at = 0.0
        self.stat = {"frames": 0, "t": clock()}
        self.fps_now = 0.0
        self.msg = ""

    # ---- input from the jukebox
    def read_input(self, now):
        if now - self.read_at < 0.1:                   # only a look at the file's time: the TV menu reacts at once
            return
        self.read_at = now
        path = os.path.join(self.run_dir, "hdmi-in.json")
        try:
            st = os.stat(path)
            if st.st_mtime == self.in_mtime:
                if time.time() - st.st_mtime > 10:
                    self.player = {}                  # the jukebox is not running
                return
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if self.in_mtime:                                 # the longest pause of the jukebox (finding faults)
                self.in_gap = max(self.in_gap, st.st_mtime - self.in_mtime)
            self.in_mtime = st.st_mtime
        except (OSError, ValueError):
            return
        self.cfg = dict(DEFAULTS, **(d.get("cfg") or {}))
        set_lang(self.cfg.get("lang") or "de")
        self.player = d.get("player") or {}
        self.player_at = now
        self.img_dir = d.get("img_dir") or ""
        self.name = d.get("name") or ""
        self.ip = d.get("ip") or ""
        self.news_list = d.get("news") or []
        self.sid_msg = d.get("sid_msg") or ""
        self.senders = set(d.get("senders") or [])
        self.menu = d.get("menu")
        for r in (self.video, self.sid):
            if r:
                r.allow = self.senders

    def write_status(self, now):
        if now - self.stat_at < 1.0:
            return
        dt = now - self.stat["t"]
        self.fps_now = (self.frame - self.stat["frames"]) / dt if dt > 0 else 0.0
        self.stat = {"frames": self.frame, "t": now}
        self.stat_at = now
        a, v, sd = self.audio, self.video, self.sid
        d = {"t": time.time(), "on": bool(self.screen), "fps": round(self.fps_now, 1), "mode": self.mode or "",
             "screen": self.screen_note, "msg": self.msg,
             "audio_age": round(a.age(), 1) if a and a.age() is not None else None,
             "audio_pkts": a.pkts if a else 0,
             "video_age": round(v.age(), 1) if v and v.age() is not None else None,
             "video_frames": v.frames if v else 0,
             "sid_want": self.sid_want, "sid_age": round(sd.age(), 1) if sd and sd.age() is not None else None,
             "sid": sd.stats() if sd else None,
             "pictures": len(self.slides.files) if self.slides else 0,
             "sound": bool(self.sound and self.sound.alive()),
             "sound_dropped": self.sound.dropped if self.sound else 0,
             "sound_filled": self.sound.filled if self.sound else 0,
             "sound_restarts": self.sound.restarts if self.sound else 0,
             "sound_msg": self.sound.msg if self.sound else "", "fades": list(self.fade_log),
             "in_gap": round(self.in_gap, 1),
             "sound_gaps": list(self.sound.gaps) if self.sound else [], "slow": list(self.slow),
             "pic_at": list(self.slides.switches) if self.slides else []}
        tmp = os.path.join(self.run_dir, "hdmi.json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, os.path.join(self.run_dir, "hdmi.json"))
        except OSError:
            pass

    # ---- switching on and off
    def start(self):
        self.screen, self.screen_note = self.open_screen()
        self.msg = ""
        self.layer = pygame.Surface(LAYER, pygame.SRCALPHA)
        self.slides = self.slides or Slideshow(rnd=self.rnd)
        self.osd = self.osd or Osd()
        self.titlecard = self.titlecard or TitleCard()
        self.menuview = self.menuview or MenuView()
        if not self.audio:
            try:
                self.audio = AudioReceiver(self.audio_port)
                self.audio.start()
            except OSError as e:
                self.msg = tr("Ton: %s") % e

    def _sound(self, want):
        """the TV sound: a process of its own (soundproc.py) - the jukebox sends it the stream directly"""
        if self.sound and not want:
            self.sound.close()
            self.sound = None
        elif want and (not self.sound or (self.sound.proc and self.sound.proc.poll() is not None)):
            if self.sound:
                self.sound.close()
            self.sound = SoundProc(self.sound_port, self.sound_cmd, clock=self.clock)

    def stop(self):
        self._sound(False)
        if self.screen:
            self.screen.close()
            self.screen = None
        for r in (self.audio, self.video, self.sid):
            if r:
                r.close()
        self.audio = self.video = self.sid = None
        self.sid_want = False
        if self.slides:
            self.slides.clear()

    def _video(self, want):
        if want and not self.video:
            try:
                self.video = VideoReceiver(self.video_port)
                self.video.allow = self.senders
                self.video.start()
            except OSError as e:
                self.msg = tr("Bild: %s") % e
        elif not want and self.video:
            self.video.close()
            self.video = None
            self.video_surf = None

    def _sidrx(self, want):
        self.sid_want = want
        if want and not self.sid:
            try:
                self.sid = SidReceiver(self.sid_port)
                self.sid.allow = self.senders
                self.sid.start()
            except OSError as e:
                self.msg = tr("SID-Daten: %s") % e
        elif not want and self.sid:
            self.sid.close()
            self.sid = None

    # ---- one picture
    def current_mode(self, now):
        cfg = self.cfg
        if cfg["mode"] != self.base_mode:
            self.base_mode = self.mode = cfg["mode"] if cfg["mode"] in MODES else "bars"
            self.cycle_at = None
        modes = [m for m in cfg.get("auto_modes") or [] if m in MODES]
        playing = (self.player or {}).get("state") in ("play", "load")
        if cfg.get("auto") and len(modes) >= 2 and playing:
            if self.cycle_at is None:
                self.cycle_at = now + max(10, float(cfg.get("auto_s") or 180))
            elif now >= self.cycle_at:
                self.mode = self.rnd.choice([m for m in modes if m != self.mode] or modes)
                self.cycle_at = now + max(10, float(cfg.get("auto_s") or 180))
        else:
            self.cycle_at = None
        return self.mode

    def fade(self, now):
        """out during the last fade_s seconds of a song with a known length (or before the time limit, when the length
        is unknown), in again when the next one starts.
        Only a really different song (source, path, sub-song) fades in - missing data (stopped, the jukebox busy for
        a moment) leaves the volume alone; a song first seen in its middle (service restarted) is not faded in."""
        p = self.player or {}
        cur = p.get("now") or {}
        snd = self.sound
        if not self.cfg.get("fade"):
            if snd.gain < 1.0 or snd.step:
                snd.fade_to(1.0, 0)
            self.fade_song = None
            return
        fs = max(0.2, float(self.cfg.get("fade_s") or 2.0))
        name = cur.get("path") or cur.get("name")
        if not name:
            return
        song = (cur.get("src"), name, cur.get("song"))
        el = float(p.get("el") or 0) + (now - self.player_at if p.get("state") == "play" else 0)
        if song != self.fade_song:
            self.fade_song, self.faded_out = song, False
            if el <= fs + 1.5:                              # it has just begun: fade in
                snd.fade_to(0.0, 0)
                snd.fade_to(1.0, fs)
                self._fade_note("ein", "neuer Titel")
            elif snd.target < 1.0:
                snd.fade_to(1.0, 0)
                self._fade_note("voll", "Titel schon %.0f s alt" % el)
            return
        if p.get("state") != "play":
            return
        secs = cur.get("end") or cur.get("secs") or 0      # its length, or else the time limit
        if self.faded_out:
            if secs and el < secs - fs - 1:                # the same song again from the start (or a jump back)
                self.faded_out = False
                snd.fade_to(1.0, fs)
                self._fade_note("ein", "gleicher Titel neu")
            return
        if snd.target < 1.0 and not snd.step:              # e.g. paused during a fade: back to full volume
            snd.fade_to(1.0, fs)
            self._fade_note("ein", "zurück auf voll")
        if secs and secs - el <= fs:
            self.faded_out = True
            snd.fade_to(0.0, max(0.1, secs - el))
            self._fade_note("aus", "noch %.1f s" % (secs - el))

    def _fade_note(self, what, why):
        self.fade_log.append("%s %s (%s)" % (time.strftime("%H:%M:%S"), what, why))

    def compose(self, now):
        cfg = self.cfg
        light = round(max(0, min(100, int(cfg.get("opacity", 100)))) * 2.55)
        bg = cfg.get("bg", "none")
        items, note = [], ""
        self._video(bg == "video")
        self._sound(bool(cfg.get("sound")))
        if self.sound:
            self.sound.device = cfg.get("sound_dev") or ""          # Bluetooth headphones (bt.py) or the TV
            v = max(0, min(100, int(cfg.get("volume", 100)))) / 100.0
            self.sound.volume = v * v                  # the ear hears it roughly squared: 50 % sounds like half
            self.fade(now)
        if bg == "images":
            self.slides.configure(self.img_dir, cfg.get("shuffle"), now)
            items += self.slides.items(now, max(3, float(cfg.get("img_s") or 20)), light)
            if not self.slides.files:
                note = tr("Keine Bilder – auf der Webseite hochladen")
        elif bg == "video" and self.video:
            pic = self.video.picture()
            if pic is not None:                   # 8 bit with the C64 palette: SDL/the graphics chip turn it into colours
                self.video_surf = pygame.image.frombuffer(pic.tobytes(), (pic.shape[1], pic.shape[0]), "P")
                self.video_surf.set_palette(VIC_PALETTE)
                self.video_ver += 1
            age = self.video.age()
            if self.video_surf is not None and age is not None and age < 2:
                items.append(Item("video", self.video_surf, self.video_ver, VIDEO_RECT, 255, light))
            else:
                note = tr("Warte auf das Bild des C64 …")
        mode = self.current_mode(now)
        a = self.audio
        now_info = (self.player or {}).get("now") or {}
        chips = now_info.get("chips") or 1
        if a and a.age() is not None and a.age() < 1.0:
            self.analyzer.update(a.snapshot(4096), chips)
        else:
            self.analyzer.calm()
        idle = self.idle(now)
        # the SID voices come from the debug stream - which the Ultimate cannot send together with its picture
        self._sidrx(mode == "sidvoices" and bg != "video")
        sid, sid_note = [], ""
        if mode == "sidvoices":
            if bg == "video":
                sid_note = tr("Nicht zusammen mit dem C64-Bild als Hintergrund – beides schafft das Netz des Ultimate nicht")
            elif self.sid and self.sid.age() is not None and self.sid.age() < 2:
                sid = self.sid.frames(now_info.get("sids"))
            else:
                sid_note = self.sid_msg
        if mode != "none" and self.viz_alpha > 0:          # faded out: not drawn at all (saves the Pi's time)
            info = Info(chips, now_info.get("sids"), now_info.get("title") or now_info.get("name"), now_info.get("author"),
                        sid=sid, sid_note=sid_note)
            self.layer.fill((0, 0, 0, 0))
            self.styles.draw(mode, self.layer, self.analyzer, info, bg=bg != "none", now=time.time())
            items.append(Item("viz", self.layer, self.frame, (0, 0) + SIZE, self.viz_alpha))
        news = self.news_list
        ticker = bool(cfg.get("news_ticker") and news and not idle and (self.player or {}).get("state") in ("play", "pause", "load"))
        if idle and cfg.get("news_idle") and news:
            items += self.newsview.panel(news, now, max(5, float(cfg.get("news_s") or 15)))
        if ticker:
            items += self.newsview.ticker(news, now)
        if cfg.get("osd", True) and cfg.get("osd_big", True) and self.titlecard:
            items += self.titlecard.items(self.player, now, max(2.0, float(cfg.get("osd_big_s") or 6)))
        menu_items = self.menuview.items(self.menu) if self.menuview else []
        if cfg.get("osd", True) or note:
            items += self.osd.items(self.player if cfg.get("osd", True) else {}, note, self.name,
                                    ip=self.ip if cfg.get("osd_qr", True) else "",
                                    lift=NewsView.TICKER_H + 8 if ticker else 0, stil=cfg.get("osd_stil", True))
        return items + menu_items                       # the menu on top of everything

    def idle(self, now):
        """nothing to see: no tune plays, or only silence comes - after idle_s seconds the effects fade out (1.5 s)
        and fade in again with the music"""
        playing = (self.player or {}).get("state") in ("play", "load")
        if self.last_music is None or (playing and float(np.max(self.analyzer.smoothed)) > 0.05):
            self.last_music = now
        idle = bool(self.cfg.get("idle_hide", True)) and now - self.last_music > float(self.cfg.get("idle_s") or 20)
        step = 255 * max(0.0, min(0.5, now - (self.viz_at or now))) / 1.5
        self.viz_at = now
        self.viz_alpha = max(0, self.viz_alpha - step) if idle else min(255, self.viz_alpha + step)
        return idle

    def tick(self):
        """-> seconds to wait until the next picture"""
        now = self.clock()
        self.read_input(now)
        if not self.cfg.get("on"):
            if self.screen:
                self.stop()
            self.write_status(now)
            return 0.5
        if not self.screen:
            try:
                self.start()
            except Exception as e:                       # no display, no EGL ...: report, try again in 5 s
                self.msg = tr("Anzeige: %s") % e
                self.screen = None
                if pygame.display.get_init():
                    pygame.display.quit()
                self.write_status(now)
                return 5.0
        if pygame.display.get_init():
            pygame.event.pump()
        self.screen.present(self.compose(now))
        took = self.clock() - now
        if took > SLOW_S:
            self.slow.append("%s %d ms (%s)" % (time.strftime("%H:%M:%S"), took * 1000, self.mode or ""))
        self.frame += 1
        self.write_status(now)
        return max(0.0, 1.0 / self.fps - (self.clock() - now))
