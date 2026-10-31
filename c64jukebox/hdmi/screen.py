"""Putting the picture together: background (slide show or C64 picture), the effects layer, the text. GpuScreen lets the
graphics chip scale and blend (SDL2 renderer on KMS/DRM, no desktop needed): the CPU only draws the 960 x 540 effects
layer. SoftScreen does the same with pygame surfaces - for the tests and as a fallback without a usable renderer.

A frame is a list of Item: what to draw (a surface, identified by key + version so a texture is only uploaded when
it changed), where, how opaque (alpha) and how bright (light 0..255, darkens towards black)."""
import os

import pygame

from ..i18n import tr

SIZE = (1920, 1080)


class Item:
    __slots__ = ("key", "surf", "version", "rect", "alpha", "light", "smooth")

    def __init__(self, key, surf, version, rect, alpha=255, light=255, smooth=True):
        self.key, self.surf, self.version, self.rect = key, surf, version, pygame.Rect(rect)
        self.alpha, self.light, self.smooth = int(alpha), int(light), smooth


class SoftScreen:
    gpu = False

    def __init__(self, size=SIZE, display=False):
        self.size = size
        if display:
            self.out = pygame.display.set_mode(size, pygame.FULLSCREEN)
            pygame.mouse.set_visible(False)
        else:
            self.out = pygame.Surface(size)
        self.display = display
        self._cache = {}

    def _scaled(self, it):
        key = (it.key, it.version, it.rect.size)
        c = self._cache.get(it.key)
        if c and c[0] == key:
            return c[1]
        s = it.surf
        if s.get_size() != it.rect.size:
            if s.get_bitsize() not in (24, 32):                  # smoothscale takes 24/32 bit only
                rgb = pygame.Surface(s.get_size(), 0, 24)
                rgb.blit(s, (0, 0))
                s = rgb
            s = (pygame.transform.smoothscale if it.smooth else pygame.transform.scale)(s, it.rect.size)
        self._cache[it.key] = (key, s)
        return s

    def present(self, items):
        self.out.fill((0, 0, 0))
        for it in items:
            s = self._scaled(it)
            if it.light < 255:
                s = s.copy()
                s.fill((it.light, it.light, it.light, 255), special_flags=pygame.BLEND_RGBA_MULT)
            if it.alpha < 255:
                s = s.copy() if it.light >= 255 else s
                s.set_alpha(it.alpha)
            self.out.blit(s, it.rect)
        if self.display:
            pygame.display.flip()

    def snapshot(self):
        return self.out.copy()

    def forget(self, key):
        self._cache.pop(key, None)

    def close(self):
        if self.display:
            pygame.display.quit()


RENDER_DRIVERS = ("opengles2",)     # Pi 3B (VC4): "opengl" comes first in SDL's list but shows textures black


def preferred_driver():
    """-> (index for Renderer, name): OpenGL ES 2 if there, else SDL's choice"""
    from pygame._sdl2.video import get_drivers
    names = [d.name for d in get_drivers()]
    for want in RENDER_DRIVERS:
        if want in names:
            return names.index(want), want
    return -1, "Standard"


class GpuScreen:
    gpu = True

    def __init__(self, size=SIZE, windowed=False):
        from pygame._sdl2.video import Renderer, Window
        self.size = size
        if not pygame.display.get_init():
            pygame.display.init()
        if windowed:
            self.win = Window("C64 Jukebox", size=(size[0] // 2, size[1] // 2))
        else:
            self.win = Window("C64 Jukebox", size=size, fullscreen=True)
        pygame.mouse.set_visible(False)
        self.driver = preferred_driver()
        try:
            self.ren = Renderer(self.win, index=self.driver[0], accelerated=1, vsync=True)
        except Exception:                                # e.g. no GLES library on a PC
            self.driver = (-1, "Standard")
            self.ren = Renderer(self.win, accelerated=1, vsync=True)
        self.ren.logical_size = size
        self.tex = {}                  # key -> (texture, version, size)

    def _texture(self, it):
        from pygame._sdl2.video import Texture
        t = self.tex.get(it.key)
        size = it.surf.get_size()
        if t and t[2] == size and t[1] == it.version:
            return t[0]
        if t and t[2] == size:
            t[0].update(it.surf)
            tex = t[0]
        else:
            tex = Texture.from_surface(self.ren, it.surf)
            tex.blend_mode = 1                       # SDL_BLENDMODE_BLEND
        self.tex[it.key] = (tex, it.version, size)
        return tex

    def present(self, items):
        self.ren.draw_color = (0, 0, 0, 255)
        self.ren.clear()
        for it in items:
            tex = self._texture(it)
            tex.alpha = it.alpha
            tex.color = (it.light, it.light, it.light, 255)
            tex.draw(dstrect=it.rect)
        self.ren.present()

    def snapshot(self):
        return self.ren.to_surface()

    def forget(self, key):
        self.tex.pop(key, None)

    def close(self):
        self.tex.clear()
        self.ren = None
        self.win.destroy()
        pygame.display.quit()


def open_screen(prefer_gpu=True, windowed=False, size=SIZE):
    """GPU if possible, else plain surfaces on the display; -> (screen, note for the status)"""
    if not windowed:
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
    os.environ.setdefault("SDL_HINT_RENDER_SCALE_QUALITY", "1")          # linear when scaling up
    pygame.display.init()
    if prefer_gpu:
        try:
            scr = GpuScreen(size, windowed)
            return scr, tr("Grafikchip (%s, %s)") % (pygame.display.get_driver(),
                                                     tr("Standard") if scr.driver[0] < 0 else scr.driver[1])
        except Exception as e:                       # pygame._sdl2 raises its own error class (e.g. "EGL not initialized")
            note = tr("ohne Grafikchip: %s") % e
    else:
        note = tr("ohne Grafikchip")
    return SoftScreen(size, display=True), note
