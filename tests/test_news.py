"""Retro news: RSS 2.0 / Atom, the fetch (fake web server with feeds and a picture), and how the TV shows them."""
import asyncio
import io
import json
import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import aiohttp                                                  # noqa: E402
import pygame                                                   # noqa: E402
from aiohttp import web                                         # noqa: E402
from aiohttp.test_utils import TestClient, TestServer           # noqa: E402
from PIL import Image                                           # noqa: E402

from c64jukebox.core import Jukebox                             # noqa: E402
from c64jukebox.hdmi.app import HdmiApp                         # noqa: E402
from c64jukebox.hdmi.screen import SoftScreen                   # noqa: E402
from c64jukebox.news import News, bigger_blogger, interleave, parse, text_of  # noqa: E402
from c64jukebox.web import make_app                             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
H = {"X-C64": "1"}

RSS = """<?xml version="1.0" encoding="ISO-8859-15"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>amiga-news.de</title>
<item><title>Die Hauptseite</title><link>https://x/</link></item>
<item><title>Spiel: Gr&#252;ne Wiese 2</title><link>https://x/2</link><pubDate>Tue, 20 Oct 2026 18:23:30 +0200</pubDate>
 <description>&lt;p&gt;Ein &lt;b&gt;neues&lt;/b&gt; Spiel&lt;/p&gt;&lt;img src="https://x/bild.png"&gt;</description></item>
<item><title>Älter</title><pubDate>Mon, 19 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>""".encode("iso-8859-15")
ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/"><title>Indie Retro News</title>
<entry><title>Steel Ranger 2 for your C64</title><published>2026-10-20T12:09:53.000+01:00</published>
 <link rel="replies" href="https://x/c"/><link rel="alternate" href="https://x/sr2"/>
 <summary type="text">Well, here's a reason to fire up your C64.</summary>
 <media:thumbnail url="https://blogger.googleusercontent.com/img/b/AB/s72-w640-h422-c/steel.jpg"/></entry>
</feed>"""


def test_sources_in_turn():
    a = [{"src": "A", "t": t} for t in (100, 99, 98, 97)]                  # four the same day
    b = [{"src": "B", "t": t} for t in (50, 40)]
    c = [{"src": "C", "t": 60}]
    assert [x["src"] for x in interleave([a, b, c])] == ["A", "C", "B", "A", "B", "A", "A"]
    assert interleave([]) == [] and interleave([[], b]) == b


def test_control_characters_are_dropped():
    """a WordPress feed (BrewOtaku) had a \\x02 in its text: not XML - read anyway"""
    bad = RSS.replace(b"Ein &lt;b&gt;neues", b"Ein \x02&lt;b&gt;neues")
    assert parse(bad, "x")[0]["summary"] == "Ein neues Spiel"


def test_parse_rss_and_atom():
    r = parse(RSS, "amiga-news.de")
    assert [x["title"] for x in r] == ["Spiel: Grüne Wiese 2", "Älter"]             # undated entry left out, newest first
    assert r[0]["summary"] == "Ein neues Spiel" and r[0]["img"] == "https://x/bild.png" and r[0]["src"] == "amiga-news.de"
    a = parse(ATOM, "IRN")[0]
    assert a["link"] == "https://x/sr2" and a["summary"].startswith("Well") and a["t"] > 0
    assert bigger_blogger(a["img"]).endswith("/w640/steel.jpg")
    assert text_of("x " * 300, 50).endswith(" …") and len(text_of("x " * 300, 50)) <= 52


def jpeg(size=(1200, 800)):
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 140, 90)).save(buf, "JPEG")
    return buf.getvalue()


def feed_server(routes):
    """a little web server: path -> (bytes or a function of the base address, content type)"""
    app = web.Application()
    srv = TestServer(app)

    def handler(body, ctype):
        async def h(request):
            data = body("http://127.0.0.1:%d" % srv.port) if callable(body) else body
            return web.Response(body=data, content_type=ctype)
        return h
    for path, (body, ctype) in routes.items():
        app.router.add_get(path, handler(body, ctype))
    return srv


def test_fetch_with_pictures(tmp_path):
    async def t():
        srv = feed_server({"/rss": (lambda base: RSS.replace(b"https://x/bild.png", (base + "/bild.png").encode()),
                                    "application/rss+xml"),
                           "/bild.png": (jpeg(), "image/jpeg"),
                           "/kaputt": (b"<rss><channel><item>", "text/xml")})
        await srv.start_server()
        base = "http://127.0.0.1:%d" % srv.port
        n = News(str(tmp_path / "img"))
        async with aiohttp.ClientSession() as s:
            got = await n.refresh(s, [{"label": "A", "url": base + "/rss"}, {"label": "B", "url": base + "/kaputt"}])
        await srv.close()
        assert got == 2
        assert n.state[base + "/kaputt"]["err"] and n.state[base + "/rss"]["n"] == 2
        scr = n.for_screen()
        assert scr[0]["title"] == "Spiel: Grüne Wiese 2" and scr[0]["date"] == "20.10.2026"
        with Image.open(scr[0]["pic"]) as im:
            assert im.size == (600, 400)                            # made small for the Pi
        assert scr[1]["pic"] == "" and "link" not in scr[0]
    asyncio.run(t())


NEWS = [{"src": "Indie Retro News", "date": "20.10.2026", "title": "Steel Ranger 2 - An epic game for your Commodore 64 by Protovision",
         "summary": "Well, here's a reason to fire up your C64 as Steel Ranger 2 has officially arrived on the Commodore 64. "
                    "Developed as the highly anticipated follow-up to the hit 2018 side-scrolling action-adventure.", "pic": ""},
        {"src": "amiga-news.de", "date": "20.10.2026", "title": "Webkatalog: AmigaSource feiert 25-jähriges Jubiläum mit Relaunch",
         "summary": "", "pic": ""}]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def write_in(run, cfg, player, news):
    with open(os.path.join(run, "hdmi-in.json"), "w") as f:
        json.dump({"t": time.time(), "cfg": cfg, "player": player, "news": news, "name": "c64pi"}, f)


def test_idle_fade_news_card_and_ticker(tmp_path):
    pygame.init()
    pic = tmp_path / "steel.jpg"
    Image.open(io.BytesIO(jpeg((640, 422)))).save(pic)
    news = [dict(NEWS[0], pic=str(pic)), NEWS[1]]
    run = str(tmp_path)
    clock = Clock()
    app = HdmiApp(run, lambda: (SoftScreen(), "Test"), audio_port=0, video_port=0, clock=clock)
    cfg = {"on": True, "mode": "bars", "bg": "none", "idle_hide": True, "idle_s": 20, "news_idle": True,
           "news_ticker": True, "news_s": 15}
    playing = {"state": "play", "el": 12, "now": {"title": "Commando", "author": "Rob Hubbard", "secs": 300, "chips": 1}}
    write_in(run, cfg, playing, news)
    app.tick()
    keys = [i.key for i in app.compose(clock.t)]
    assert "viz" in keys and "ticker_bg" in keys and "news" not in keys                  # music plays (or is starting)
    shot = SoftScreen()
    shot.present(app.compose(clock.t + 3))
    pygame.image.save(shot.snapshot(), os.path.join(HERE, "web", "hdmi_ticker.png"))
    # no sound for 20 s: the effects fade out, the news card comes
    for dt in range(1, 26):
        clock.t += 1
        items = app.compose(clock.t)
    keys = [i.key for i in items]
    assert app.viz_alpha == 0 and "viz" not in keys and "news" in keys and "ticker_bg" not in keys
    card = next(i for i in items if i.key == "news")
    shot = SoftScreen()
    clock.t += 1
    shot.present(app.compose(clock.t))
    pygame.image.save(shot.snapshot(), os.path.join(HERE, "web", "hdmi_news.png"))
    clock.t += 16
    nxt = next(i for i in app.compose(clock.t) if i.key == "news")
    assert nxt.surf is not card.surf                                                        # the next one after 15 s
    # stopped and news off: only the hint; effects come back with the music (fade in)
    write_in(run, dict(cfg, news_idle=False), {"state": "stop"}, news)
    clock.t += 1
    app.read_input(clock.t)
    assert [i.key for i in app.compose(clock.t)] == ["osd_idle"]
    app.last_music = clock.t
    clock.t += 0.5
    app.compose(clock.t)
    assert 0 < app.viz_alpha < 255
    app.stop()


def test_news_settings_and_refresh_route(tmp_path):
    async def t():
        run = tmp_path / "run"
        run.mkdir()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(run))
        fsrv = feed_server({"/rss": (RSS, "application/rss+xml")})
        await fsrv.start_server()
        app = make_app(jb)
        app.on_startup.append(lambda a: jb.start())
        app.on_cleanup.append(lambda a: jb.close())
        c = TestClient(TestServer(app))
        await c.start_server()
        try:
            await c.post("/api/login", json={"pw": "commodore64"}, headers=H)
            d = await (await c.get("/api/hdmi")).json()
            assert d["cfg"]["idle_hide"] is True and d["news"]["default"] and len(d["news"]["feeds"]) == 7
            assert [f["on"] for f in d["news"]["feeds"]].count(True) == 5
            r = await c.post("/api/hdmi", json={"news_feeds": [{"label": "X", "url": "ftp://nein"}]}, headers=H)
            assert r.status == 400
            url = "http://127.0.0.1:%d/rss" % fsrv.port
            r = await (await c.post("/api/hdmi", json={"on": True, "news_idle": True, "idle_s": 2,
                                                         "news_feeds": [{"label": "Amiga", "url": url},
                                                                        {"label": "Aus", "url": url + "?aus", "on": False}]},
                                    headers=H)).json()
            assert r["cfg"]["idle_s"] == 5 and r["cfg"]["news_feeds"][0] == {"label": "Amiga", "url": url, "on": True}
            d = await (await c.post("/api/hdmi/news", json={}, headers=H)).json()
            assert d["news"]["n"] == 2 and d["news"]["feeds"][0]["n"] == 2 and not d["news"]["default"]
            assert "n" not in d["news"]["feeds"][1] and (url + "?aus") not in jb.news.state          # switched off: not fetched
            jb._hdmi_write()
            hin = json.load(open(run / "hdmi-in.json"))
            assert [n["title"] for n in hin["news"]] == ["Spiel: Grüne Wiese 2", "Älter"]
            await c.post("/api/hdmi", json={"news_idle": False}, headers=H)
            assert json.load(open(run / "hdmi-in.json"))["news"] == []
        finally:
            await c.close()
            await fsrv.close()
    asyncio.run(t())
