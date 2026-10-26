#!/usr/bin/env python3
"""
The illustrated operating guide of the jukebox (web page and TV): docs/bedienung/bedienung.html ->
docs/Bedienung_Pi-Jukebox.pdf (German) and docs/bedienung/operation_en.html -> docs/Operation_Pi-Jukebox.pdf (English),
both with the same pictures (Chromium via Playwright).

    .venv/bin/python tools/make_bedienung.py            only the PDFs from the HTML and the pictures in docs/bedienung/bilder/
    .venv/bin/python tools/make_bedienung.py --shots    take the pictures first
    DEJAVU_DIR=<folder with DejaVuSans*.ttf>             (optional) draw the TV pictures in the Pi's font

The pictures come from the real code with made-up data, no Pi needed: the web page from the demo server
(tests/web/demo_server.py), the TV pictures from the HDMI service drawing into memory (like tests/test_hdmi.py) with
the menu of the real tvmenu.py. Addresses are neutral examples (192.168.1.x).
"""
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "bedienung")
IMG = os.path.join(DOC, "bilder")
PDFS = (("bedienung.html", "Bedienung_Pi-Jukebox.pdf", "C64-Jukebox – Bedienung · Seite", "von"),
        ("operation_en.html", "Operation_Pi-Jukebox.pdf", "C64 jukebox – operation · page", "of"))
PHONE = {"width": 420, "height": 900}
DESK = {"width": 1280, "height": 860}
ULT, PI_IP = "192.168.1.168", "192.168.1.78"
PLAYER = {"state": "play", "el": 83, "now": {"title": "Commando", "author": "Rob Hubbard", "year": "1985 Elite",
                                             "models": ["MOS6581"], "sids": ["D400"], "chips": 1,
                                             "secs": 246, "song": 1, "songs": 3}}


def clip(pg, name, top=None, bottom=None, pad=10):
    """screenshot from the top edge of one element to an edge of another: (selector, "top"|"bottom")"""
    pg.evaluate("window.scrollTo(0, 0)")

    def edge(spec):
        sel, side = spec
        bb = pg.locator(sel).first.bounding_box()
        return bb["y"] + (bb["height"] if side == "bottom" else 0)
    y0 = max(0, edge(top) - pad) if top else 0
    y1 = edge(bottom) + pad if bottom else pg.evaluate("document.documentElement.scrollHeight")
    pg.screenshot(path=os.path.join(IMG, name + ".png"), full_page=True,
                  clip={"x": 0, "y": y0, "width": pg.viewport_size["width"], "height": y1 - y0})


def setup(here):
    sys.path.insert(0, os.path.join(here, "tests", "web"))
    sys.path.insert(0, os.path.join(here, "tests"))
    sys.path.insert(0, here)
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import c64jukebox.core
    c64jukebox.core.local_ip = lambda towards="": PI_IP                   # the page shows the Pi's own address


# ---------------------------------------------------------------- the web page
def web_shots(demo):
    from playwright.sync_api import sync_playwright
    fake = re.compile(r"127\.0\.0\.1:\d+")

    def handler(route):
        res = route.fetch()
        body = res.text()
        if "/api/state" in route.request.url:
            s = json.loads(body)
            s["pwdefault"] = False
            body = json.dumps(s)
        elif "/api/hdmi" in route.request.url and route.request.method == "GET":   # as with the TV service running
            s = json.loads(body)
            s["status"] = dict(s.get("status") or {}, age=0.4, fps=30, screen="1920 × 1080", audio_age=0.1, sound=True,
                               mode=s["cfg"].get("mode"))
            body = json.dumps(s)
        body = fake.sub(ULT, body)
        for t in {demo.tmp, os.path.realpath(demo.tmp)}:
            body = body.replace(t, "/media/usb")
        route.fulfill(status=res.status, headers=dict(res.headers, **{"content-length": str(len(body.encode()))}),
                      body=body)

    def page(b, size):
        ctx = b.new_context(viewport=size, device_scale_factor=2)
        ctx.route(re.compile(r".*/api/.*"), handler)
        pg = ctx.new_page()
        pg.goto(demo.url)
        pg.fill("#lpw", "commodore64")
        pg.press("#lpw", "Enter")
        pg.wait_for_selector("#app:not([hidden])")
        pg.add_style_tag(content="#toast{display:none!important}")
        return pg

    def tab(pg, t, wait=900):
        pg.click("#tabs button[data-t=%s]" % t)
        pg.wait_for_timeout(wait)

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = page(b, PHONE)
        tab(pg, "files")
        pg.wait_for_selector(".src.on")
        for n in ("USB2", "SID-Tunes", "MUSICIANS", "H", "Hubbard_Rob"):
            pg.click("#flist li.dir:has-text('%s')" % n)
            pg.wait_for_function("document.getElementById('fstatus').textContent.indexOf('Lese') < 0")
        pg.wait_for_selector("#flist li.sid:has-text('Rob Hubbard')")
        clip(pg, "web_dateien", None, ("#flist", "bottom"), pad=24)
        pg.click("#flist li.sid:has-text('Commando')")
        tab(pg, "play", 1500)
        pg.wait_for_selector("#nt:has-text('Commando')")
        clip(pg, "web_wiedergabe", None, ("#lrows .lrow[data-i='1']", "bottom"), pad=24)
        pg.click("#lsave")                                               # a saved list for "Listen"
        pg.fill("#askin", "Feierabend")
        pg.click("#askok")
        pg.wait_for_timeout(600)
        tab(pg, "lists", 1200)
        clip(pg, "web_listen", None, ("h3:has-text('Statistik')", "top"), pad=-4)
        tab(pg, "dev", 1200)
        clip(pg, "web_ultimates", ("h3:has-text('Ultimates')", "top"), ("h3:has-text('Picos und Stream')", "top"), pad=24)
        demo.jb.config.data["hdmi"]["on"] = True                       # the cards as with a TV connected
        tab(pg, "show", 1200)
        clip(pg, "web_fernseher", ("h3:has-text('Fernseher (HDMI)')", "top"), ("h3:has-text('Hintergrund am')", "top"), pad=24)
        clip(pg, "web_hintergrund", ("h3:has-text('Hintergrund am')", "top"), ("h3:has-text('Retro-News am')", "top"), pad=24)
        clip(pg, "web_tvton", ("h3:has-text('Ton am Fernseher')", "top"), ("h3:has-text('TV-Fernbedienung')", "top"), pad=24)
        clip(pg, "web_cec", ("h3:has-text('TV-Fernbedienung')", "top"), ("h3:has-text('Display am Pi')", "top"), pad=24)
        tab(pg, "set", 1200)
        clip(pg, "web_einstellungen", None, ("h3:has-text('Songlängen')", "top"), pad=24)
        pg.context.close()
        pg = page(b, DESK)                                              # the playlist window on the PC
        tab(pg, "files")
        pg.wait_for_selector(".src.on")
        for n in ("USB2", "SID-Tunes"):
            pg.click("#flist li.dir:has-text('%s')" % n)
            pg.wait_for_function("document.getElementById('fstatus').textContent.indexOf('Lese') < 0")
        pg.click("#fplay")
        pg.wait_for_timeout(2500)
        tab(pg, "play", 2500)
        pg.screenshot(path=os.path.join(IMG, "web_pc.png"))
        b.close()


# ---------------------------------------------------------------- the TV
def tv_views(demo):
    """the menu as tvmenu.py builds it, at a few places"""
    jb = demo.jb
    jb.config.data["hdmi"]["on"] = True
    cmd = lambda c: demo.call(jb._cec_cmd(c))                          # noqa: E731
    views = {}

    def at(label):
        for _ in range(40):
            v = jb.menu.view()
            if v and any(i["l"].startswith(label) for i in v["items"]):
                return v
            time.sleep(0.1)
        raise RuntimeError("menu: %s not found" % label)

    def go(label):
        v = jb.menu.view()
        exact = [k for k, i in enumerate(v["items"]) if i["l"] == label]
        target = exact[0] if exact else next(k for k, i in enumerate(v["items"]) if i["l"].startswith(label))
        for _ in range(abs(target - v["sel"])):
            cmd("down" if target > v["sel"] else "up")
        cmd("select")

    cmd("select")
    views["tv_menu"] = at("Musik wählen")
    go("Musik wählen")
    views["tv_musik"] = at("★ Favoriten")
    go("Ordner")
    v = at("Diesen Ordner")
    for n in ("USB2/", "SID-Tunes/", "MUSICIANS/"):
        go(n)
        v = at("Diesen Ordner abspielen")
        time.sleep(0.3)
    views["tv_ordner"] = jb.menu.view()
    for _ in range(6):
        cmd("back")
        if jb.menu.view() and jb.menu.view()["title"] == "C64-Jukebox":
            break
    go("Effekt")
    views["tv_effekt"] = at("Balken")
    cmd("back")
    cmd("back")
    return views


def tv_shots(views):
    import pygame
    from c64jukebox.hdmi import styles
    if os.environ.get("DEJAVU_DIR"):                                # the Pi's font (has the ★); not on a Mac
        styles.FONT_DIRS = (os.environ["DEJAVU_DIR"].rstrip("/") + "/",) + tuple(styles.FONT_DIRS)
    from c64jukebox.hdmi.app import HdmiApp
    from c64jukebox.hdmi.screen import SoftScreen
    import tempfile
    pygame.init()
    run = tempfile.mkdtemp(prefix="c64pi-tv-")

    class Clock:
        t = 1000.0

        def __call__(self):
            return self.t
    clock = Clock()
    app = HdmiApp(run, lambda: (SoftScreen(), "Bedienung"), audio_port=0, video_port=0, clock=clock, seed=5)
    for name, menu in views.items():
        p = os.path.join(run, "hdmi-in.json")
        with open(p + ".tmp", "w") as f:
            json.dump({"t": time.time(), "cfg": {"on": True, "mode": "bars", "bg": "none", "osd_big": False},
                       "player": PLAYER, "img_dir": "", "name": "c64pi", "menu": menu}, f)
        os.replace(p + ".tmp", p)
        clock.t += 1
        app.tick()
        clock.t += 0.5
        app.read_input(clock.t)
        scr = SoftScreen()
        scr.present(app.compose(clock.t))
        pygame.image.save(scr.snapshot(), os.path.join(IMG, name + ".png"))
    app.stop()
    shots = os.path.join(ROOT, "tests", "web")                          # pictures the tests of the TV part draw
    for n in ("hdmi_titlecard", "hdmi_bars", "hdmi_sidvoices", "hdmi_c64", "hdmi_idle_qr", "hdmi_news", "hdmi_ticker",
              "hdmi_keyboard", "hdmi_vinyl", "hdmi_neon_pictures", "hdmi_milkdrop", "hdmi_cloud", "tft_play", "tft_level", "tft_net"):
        src = os.path.join(shots, n + ".png")
        if not os.path.exists(src):
            raise SystemExit("missing %s - run the tests first (.venv/bin/python -m pytest)" % src)
        shutil.copy(src, os.path.join(IMG, n.replace("hdmi_", "tv_") + ".png"))


def shots():
    setup(ROOT)
    from demo_server import Demo
    os.makedirs(IMG, exist_ok=True)
    demo = Demo().start()
    try:
        web_shots(demo)
        views = tv_views(demo)
    finally:
        demo.stop()
    tv_shots(views)
    print("pictures in", IMG)


def make_pdf():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        for html, pdf, page, of in PDFS:
            pdf = os.path.join(ROOT, "docs", pdf)
            pg.goto("file://" + os.path.join(DOC, html))
            pg.wait_for_timeout(500)
            pg.pdf(path=pdf, format="A4", print_background=True, prefer_css_page_size=True,
                   display_header_footer=True, header_template="<span></span>",
                   footer_template='<div style="font:8px Helvetica,Arial,sans-serif;width:100%%;text-align:center;'
                                   'color:#888">%s <span class="pageNumber"></span> %s <span class="totalPages"></span>'
                                   '</div>' % (page, of),
                   margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
            print("PDF:", pdf, "(%d KB)" % (os.path.getsize(pdf) // 1024))
        b.close()


if __name__ == "__main__":
    if "--shots" in sys.argv:
        shots()
    make_pdf()
