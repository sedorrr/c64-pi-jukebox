#!/usr/bin/env python3
"""
The illustrated operating guide of the jukebox (web page, TV, touch display): docs/bedienung/bedienung.html ->
docs/Bedienung_Pi-Jukebox.pdf (German, pictures in docs/bedienung/bilder/) and docs/bedienung/operation_en.html ->
docs/Operation_Pi-Jukebox.pdf (English, pictures in docs/bedienung/bilder_en/), Chromium via Playwright.

    .venv/bin/python tools/make_bedienung.py            only the PDFs from the HTML and the pictures
    .venv/bin/python tools/make_bedienung.py --shots    take the pictures first, each in German and in English
    DEJAVU_DIR=<folder with DejaVuSans*.ttf>             (optional) draw the TV pictures in the Pi's font

The pictures come from the real code with made-up data, no Pi needed: the web page from the demo server
(tests/web/demo_server.py, one per language, config "lang" set), the TV pictures from the HDMI service drawing into
memory with the menu of the real tvmenu.py and - for the effects, title card, news, QR code - the drawing steps of
tests/test_hdmi.py and tests/test_news.py (their output folder pointed elsewhere, the language put into the service's
cfg), the touch display from tft.py. Addresses are neutral examples (192.168.1.x). The language is German again
at the end.
"""
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "bedienung")
IMGS = {"de": os.path.join(DOC, "bilder"), "en": os.path.join(DOC, "bilder_en")}
PDFS = (("bedienung.html", "Bedienung_Pi-Jukebox.pdf", "C64-Jukebox – Bedienung · Seite", "von"),
        ("operation_en.html", "Operation_Pi-Jukebox.pdf", "C64 jukebox – operation · page", "of"))
PHONE = {"width": 420, "height": 900}
DESK = {"width": 1280, "height": 860}
ULT, PI_IP = "192.168.1.168", "192.168.1.78"
PLAYER = {"state": "play", "el": 83, "now": {"title": "Commando", "author": "Rob Hubbard", "year": "1985 Elite",
                                             "models": ["MOS6581"], "sids": ["D400"], "chips": 1,
                                             "secs": 246, "song": 1, "songs": 3}}
# made-up data that is shown, per language
DATA = {"de": {"list": "Feierabend", "u64src": "USB-Stick am Ultimate", "pisrc": "Ordner am Pi", "phones": "Kopfhörer",
               "locale": "de-DE"},
        "en": {"list": "Evening", "u64src": "Ultimate USB stick", "pisrc": "Folder on the Pi", "phones": "Headphones",
               "locale": "en-GB"}}
NEWS_EN = {"src": "Commodore News", "date": "20.10.2026", "title": "New cartridge game for the C64 announced",
           "summary": "", "pic": ""}               # instead of the German headline of tests/test_news.py


def clip(pg, out, name, top=None, bottom=None, pad=10):
    """screenshot from the top edge of one element to an edge of another: (selector, "top"|"bottom")"""
    pg.evaluate("window.scrollTo(0, 0)")

    def edge(spec):
        sel, side = spec
        bb = pg.locator(sel).first.bounding_box()
        return bb["y"] + (bb["height"] if side == "bottom" else 0)
    y0 = max(0, edge(top) - pad) if top else 0
    y1 = edge(bottom) + pad if bottom else pg.evaluate("document.documentElement.scrollHeight")
    pg.screenshot(path=os.path.join(out, name + ".png"), full_page=True,
                  clip={"x": 0, "y": y0, "width": pg.viewport_size["width"], "height": y1 - y0})


def setup(here):
    sys.path.insert(0, os.path.join(here, "tests", "web"))
    sys.path.insert(0, os.path.join(here, "tests"))
    sys.path.insert(0, here)
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import c64jukebox.core
    c64jukebox.core.local_ip = lambda towards="": PI_IP                   # the page shows the Pi's own address
    c64jukebox.core.UPDATE_URL = ""                                       # no look at GitHub; the hint is made up


def set_lang(lang, demo=None):
    from c64jukebox import i18n
    i18n.set_lang(lang)
    if demo:
        demo.jb.config.data["lang"] = lang                                 # what /api/hello tells the page


def page_tr(lang):
    """German text of the page -> the text the page shows (web/lang-en.json, like T() in app.js)"""
    if lang == "de":
        return lambda s: s
    with open(os.path.join(ROOT, "c64jukebox", "web", "lang-en.json"), encoding="utf-8") as f:
        table = json.load(f)
    return lambda s: table.get(s) or s


def prepare(demo, lang):
    """the demo's data in the language of the pictures; the HVSC song lengths loaded from the folder on the Pi"""
    set_lang(lang, demo)
    c = demo.jb.config.data
    for s in c["sources"]:
        s["label"] = {"u64": DATA[lang]["u64src"], "pi": DATA[lang]["pisrc"]}.get(s["id"], s["label"])
    src = demo.jb.config.source("pi")
    with open(os.path.join(src["path"], "DOCUMENTS", "Songlengths.md5"), "rb") as f:
        path = "/DOCUMENTS/Songlengths.md5"
        meta = {"src": "pi", "path": path, "label": "%s: %s" % (src["label"], path)}
        demo.call(demo.jb.set_songlengths("hvsc", f.read(), meta))


# ---------------------------------------------------------------- the web page
def web_shots(demo, lang, out):
    from playwright.sync_api import sync_playwright
    fake = re.compile(r"127\.0\.0\.1:\d+")
    T = page_tr(lang)
    d = DATA[lang]

    def handler(route):
        res = route.fetch()
        body = res.text()
        url, method = route.request.url, route.request.method
        if "/api/state" in url:
            s = json.loads(body)
            s["pwdefault"] = False
            body = json.dumps(s)
        elif "/api/hdmi" in url and method == "GET":                   # as with the TV service running
            s = json.loads(body)
            s["status"] = dict(s.get("status") or {}, age=0.4, fps=30, screen="1920 × 1080", audio_age=0.1, sound=True,
                               mode=s["cfg"].get("mode"))
            body = json.dumps(s)
        elif "/api/bt" in url and method == "GET":                     # paired headphones, connected
            mac = "12:34:56:78:9A:BC"
            body = json.dumps({"ok": True, "present": True, "on": True, "mac": mac, "name": d["phones"],
                               "connected": True, "active": True,
                               "devices": [{"mac": mac, "name": d["phones"], "paired": True, "connected": True}]})
        body = fake.sub(ULT, body)
        for t in {demo.tmp, os.path.realpath(demo.tmp)}:
            body = body.replace(t, "/media/usb")
        route.fulfill(status=res.status, headers=dict(res.headers, **{"content-length": str(len(body.encode()))}),
                      body=body)

    def page(b, size):
        ctx = b.new_context(viewport=size, device_scale_factor=2, locale=d["locale"])
        ctx.route(re.compile(r".*/api/.*"), handler)
        pg = ctx.new_page()
        pg.goto(demo.url)
        pg.fill("#lpw", "commodore64")
        pg.press("#lpw", "Enter")
        pg.wait_for_selector("html[lang=%s] #app:not([hidden])" % lang)
        pg.add_style_tag(content="#toast{display:none!important}")
        return pg

    def tab(pg, t, wait=900):
        pg.click("#tabs button[data-t=%s]" % t)
        pg.wait_for_timeout(wait)

    def h3(text):
        return "h3:text-is('%s')" % T(text).replace("'", "\\'")

    def h2(text):
        return "h2.group:text-is('%s')" % T(text).replace("'", "\\'")

    def into(pg, *names):
        reading = T("Lese Ordner …").split()[0]
        for n in names:
            pg.click("#flist li.dir:has-text('%s')" % n)
            pg.wait_for_function("document.getElementById('fstatus').textContent.indexOf('%s') < 0" % reading)

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = page(b, PHONE)
        tab(pg, "files")
        pg.wait_for_selector(".src.on")
        into(pg, "USB2", "SID-Tunes", "MUSICIANS", "H", "Hubbard_Rob")
        pg.wait_for_selector("#flist li.sid:has-text('Rob Hubbard')")
        clip(pg, out, "web_dateien", None, ("#flist", "bottom"), pad=24)
        pg.click("#flist li.sid:has-text('Commando')")
        tab(pg, "play", 1500)
        pg.wait_for_selector("#nt:has-text('Commando')")
        clip(pg, out, "web_wiedergabe", None, ("#lrows .lrow[data-i='1']", "bottom"), pad=24)
        pg.click("#lsave")                                               # a saved list for "Listen"
        pg.fill("#askin", d["list"])
        pg.click("#askok")
        pg.wait_for_timeout(600)
        tab(pg, "lists", 1200)
        clip(pg, out, "web_listen", None, (h3("Statistik"), "top"), pad=-4)
        tab(pg, "dev", 1200)
        clip(pg, out, "web_ultimates", ("h3:text-is('Ultimates')", "top"), (h3("Picos und Stream-Verteiler"), "top"), pad=24)
        c = demo.jb.config.data                                         # the cards as with a TV connected
        c["hdmi"].update(on=True, sound=True, fade=True)
        c["cec"].update(on=True, tv_on_boot=True, pi_off=True)
        tab(pg, "show", 1200)
        clip(pg, out, "web_fernseher", (h3("Fernseher (HDMI)"), "top"), (h3("Hintergrund am Fernseher"), "top"), pad=24)
        clip(pg, out, "web_hintergrund", (h3("Hintergrund am Fernseher"), "top"), (h3("Retro-News am Fernseher"), "top"), pad=24)
        clip(pg, out, "web_tvton", (h3("Ton am Fernseher"), "top"), (h3("Bluetooth-Kopfhörer"), "top"), pad=24)
        clip(pg, out, "web_bluetooth", (h3("Bluetooth-Kopfhörer"), "top"), (h2("Bedienung"), "top"), pad=24)
        clip(pg, out, "web_cec", (h3("TV-Fernbedienung (HDMI-CEC)"), "top"), (h3("Display am Pi"), "top"), pad=24)
        tab(pg, "set", 1200)
        clip(pg, out, "web_einstellungen", None, (h3("Songlängen"), "top"), pad=24)
        clip(pg, out, "web_sprache", (h2("System"), "top"), (h3("Web-Passwort"), "top"), pad=24)
        clip(pg, out, "web_steckdose", (h3("Ausschalten und Steckdose"), "top"), (h3("Sicherung"), "top"), pad=24)
        tab(pg, "play", 600)
        pg.click("#topoff")                                             # the ⏻ menu at the top of every page
        pg.wait_for_selector("#menudlg[open]")
        pg.wait_for_timeout(400)
        clip(pg, out, "web_power", None, ("#menudlg", "bottom"), pad=24)
        pg.click("#menudlg button:has-text('%s')" % T("Schließen"))
        demo.jb.update = {"ver": "1.3", "newer": True, "at": 0}         # a newer version on GitHub (made up)
        pg.wait_for_selector("#updbar:not([hidden])", timeout=15000)
        pg.wait_for_timeout(400)
        clip(pg, out, "web_update", None, ("#tabs", "bottom"), pad=12)
        demo.jb.update = None
        pg.context.close()
        pg = page(b, DESK)                                              # the playlist window on the PC
        tab(pg, "files")
        pg.wait_for_selector(".src.on")
        into(pg, "USB2", "SID-Tunes")
        pg.click("#fplay")
        pg.wait_for_timeout(2500)
        tab(pg, "play", 2500)
        pg.screenshot(path=os.path.join(out, "web_pc.png"))
        b.close()


# ---------------------------------------------------------------- the TV menu
def tv_views(demo, lang):
    """the menu as tvmenu.py builds it, at a few places (in the language set with set_lang)"""
    from c64jukebox.i18n import tr
    jb = demo.jb
    jb.config.data["hdmi"]["on"] = True
    cmd = lambda c: demo.call(jb._cec_cmd(c))                          # noqa: E731
    views = {}

    def at(label):
        for _ in range(40):
            v = jb.menu.view()
            if v and any(i["l"].startswith(label) for i in v.get("items", [])):
                return v
            time.sleep(0.1)
        raise RuntimeError("menu: %s not found" % label)

    def go(label):                                                      # all entries (the view shows a window)
        labels = [e[0] for e in jb.menu.entries()]
        exact = [k for k, s in enumerate(labels) if s == label]
        target = exact[0] if exact else next(k for k, s in enumerate(labels) if s.startswith(label))
        sel = jb.menu.sel[jb.menu.level]
        for _ in range(abs(target - sel)):
            cmd("down" if target > sel else "up")
        cmd("select")

    def home():
        for _ in range(8):
            v = jb.menu.view()
            if v and v.get("title") == "C64-Jukebox":
                return
            cmd("back")
        raise RuntimeError("menu: main level not reached")

    cmd("select")
    views["tv_menu"] = at(tr("Musik wählen"))
    go(tr("Musik wählen"))
    views["tv_musik"] = at(tr("★ Favoriten"))
    go(tr("In der HVSC suchen"))                                        # the keyboard, a few letters typed
    jb.menu._search_kbd("hubbard")
    jb.menu.kbd.update(r=2, c=3)
    views["tv_suche"] = jb.menu.view()
    from c64jukebox import tvmenu
    jb.menu.kbd.update(r=len(tvmenu.KBD_ROWS) - 1, c=3)                 # "Abbrechen": back to "Musik wählen"
    cmd("select")
    at(tr("★ Favoriten"))
    go(tr("Ordner: %s") % DATA[lang]["u64src"])
    at(tr("Diesen Ordner abspielen"))
    for n in ("USB2/", "SID-Tunes/", "MUSICIANS/"):
        go(n)
        at(tr("Diesen Ordner abspielen"))
        time.sleep(0.3)
    views["tv_ordner"] = jb.menu.view()
    home()
    go(tr("Effekt"))
    views["tv_effekt"] = at(tr("Balken"))
    home()
    go(tr("Ausschalten"))
    views["tv_ausschalten"] = at(tr("Fernseher ausschalten"))
    home()
    cmd("back")                                                          # closed
    return views


def dejavu():
    from c64jukebox.hdmi import styles
    if os.environ.get("DEJAVU_DIR"):                                # the Pi's font (has the ★); not on a Mac
        d = os.environ["DEJAVU_DIR"].rstrip("/") + "/"
        if d not in styles.FONT_DIRS:
            styles.FONT_DIRS = (d,) + tuple(styles.FONT_DIRS)


def tv_menu_shots(views, lang, out):
    import pygame
    dejavu()
    from c64jukebox.hdmi.app import HdmiApp
    from c64jukebox.hdmi.screen import SoftScreen
    pygame.init()
    run = tempfile.mkdtemp(prefix="c64pi-tv-")

    class Clock:
        t = 1000.0

        def __call__(self):
            return self.t
    clock = Clock()
    app = HdmiApp(run, lambda: (SoftScreen(), "Bedienung"), audio_port=0, video_port=0, clock=clock, seed=5)
    try:
        for name, menu in views.items():
            p = os.path.join(run, "hdmi-in.json")
            with open(p + ".tmp", "w") as f:
                json.dump({"t": time.time(), "cfg": {"on": True, "mode": "bars", "bg": "none", "osd_big": False,
                                                     "lang": lang},
                           "player": PLAYER, "img_dir": "", "name": "c64pi", "menu": menu}, f)
            os.replace(p + ".tmp", p)
            clock.t += 1
            app.tick()
            clock.t += 0.5
            app.read_input(clock.t)
            scr = SoftScreen()
            scr.present(app.compose(clock.t))
            pygame.image.save(scr.snapshot(), os.path.join(out, name + ".png"))
    finally:
        app.stop()
        set_lang("de")


# ---------------------------------------------------------------- the TV: effects, title card, news, QR code
def tv_screen_shots(lang, out):
    """the pictures the tests of the TV part draw - drawn here again in the given language, into a folder of our own"""
    import test_hdmi
    import test_news
    dejavu()
    tmp = tempfile.mkdtemp(prefix="c64pi-tvshots-")
    os.makedirs(os.path.join(tmp, "web"))
    mods = (test_hdmi, test_news)
    saved = {m: (m.HERE, m.write_in) for m in mods}
    news = test_news.NEWS
    for m in mods:
        m.HERE = tmp
        m.write_in = (lambda orig: lambda run, cfg, *a, **k: orig(run, dict(cfg, lang=lang), *stil(a), **k))(m.write_in)
    if lang != "de":
        test_news.NEWS = [news[0], NEWS_EN]

    def stil(args):                                                     # the STIL lines as the jukebox makes them
        player = args[0] if args else None
        if lang == "de" or not (player and (player.get("now") or {}).get("stil")):
            return args
        from c64jukebox.i18n import tr
        now = dict(player["now"], stil=[tr("Original von: %s") % "Tamayo Kawamoto", tr("Titel: %s") % "BGM1"])
        return (dict(player, now=now),) + tuple(args[1:])
    set_lang(lang)
    try:
        new = lambda: pathlib.Path(tempfile.mkdtemp(prefix="c64pi-t-"))          # noqa: E731
        test_hdmi.test_service_loop_in_memory(new())
        test_hdmi.test_title_card(new())
        test_hdmi.test_qr_code(new())
        test_hdmi.test_sid_voices_style_and_service(new())
        test_news.test_idle_fade_news_card_and_ticker(new())
    finally:
        for m in mods:
            m.HERE, m.write_in = saved[m]
        test_news.NEWS = news
        set_lang("de")
    for n in ("titlecard", "bars", "sidvoices", "c64", "idle_qr", "news", "ticker", "vinyl", "neon_pictures",
              "milkdrop", "cloud"):
        shutil.copy(os.path.join(tmp, "web", "hdmi_%s.png" % n), os.path.join(out, "tv_%s.png" % n))
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the 2.8" touch display
def tft_shots(lang, out):
    from test_display import PLAY
    from c64jukebox.tft import TftScreen
    set_lang(lang)
    try:
        scr = TftScreen()
        level = dict(PLAY, level={"now": [0.55, 0.83], "peak": [0.7, 0.95],
                                  "hist": [abs(((i * 7) % 23) - 11) / 11 for i in range(60)]})
        for name, page, st in (("tft_play", "play", PLAY),
                               ("tft_power", "power", dict(PLAY, tvctl={"ready": True, "tv": "on"})),
                               ("tft_level", "level", level), ("tft_net", "net", PLAY)):
            scr.render(st, page).resize((640, 480), 0).save(os.path.join(out, name + ".png"))
    finally:
        set_lang("de")


def shots():
    setup(ROOT)
    from demo_server import Demo
    try:
        for lang, out in IMGS.items():
            os.makedirs(out, exist_ok=True)
            demo = Demo().start()
            try:
                prepare(demo, lang)
                web_shots(demo, lang, out)
                views = tv_views(demo, lang)
            finally:
                demo.stop()
            tv_menu_shots(views, lang, out)
            tv_screen_shots(lang, out)
            tft_shots(lang, out)
            print("pictures (%s) in" % lang, out)
    finally:
        set_lang("de")


def make_pdf():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        for html, pdf, page, of in PDFS:
            pdf = os.path.join(ROOT, "docs", pdf)
            pg.goto("file://" + os.path.join(DOC, html))
            pg.wait_for_timeout(500)
            missing = pg.evaluate("[...document.images].filter(i => !i.naturalWidth).map(i => i.getAttribute('src'))")
            if missing:
                raise SystemExit("%s: pictures missing: %s" % (html, ", ".join(missing)))
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
