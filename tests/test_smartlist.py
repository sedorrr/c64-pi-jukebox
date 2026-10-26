"""Lists put together: the HVSC from Songlengths.md5 (paths with their capitals), filters, presets with the play
counts and favourites, and playing / saving through the page."""
import asyncio
import random

from aiohttp.test_utils import TestClient, TestServer

from c64jukebox import smartlist
from c64jukebox.core import Jukebox
from c64jukebox.web import make_app
from fakes import FakeUltimate, make_sid

H = {"X-C64": "1"}
M = ["%032x" % k for k in range(1, 7)]
SL = """[Database]
; /MUSICIANS/H/Hubbard_Rob/Commando.sid
%s=4:36 0:40 0:20
; /MUSICIANS/H/Hubbard_Rob/Delta.sid
%s=1:30
; /GAMES/S-Z/Turrican.sid
%s=3:00
; /DEMOS/A-F/Dual_Core_2SID.sid
%s=2:10
; /MUSICIANS/G/Galway_Martin/Wizball.sid
%s=0:50.123
; /MUSICIANS/G/Galway_Martin/Comic_Bakery.sid
%s=5:00
""" % tuple(M)


def test_parse_and_pick():
    hv = smartlist.parse_hvsc(SL)
    assert len(hv) == 6 and hv[0] == ("/MUSICIANS/H/Hubbard_Rob/Commando.sid", M[0], [276, 40, 20])
    assert smartlist.hvsc_root({"src": "nas", "path": "/SID/HVSC 85/C64Music/DOCUMENTS/Songlengths.md5"}) == \
        ("nas", "/SID/HVSC 85/C64Music")
    assert smartlist.hvsc_root("hochgeladen") is None
    root = ("nas", "/HVSC/C64Music")
    names = lambda f, **kw: [i["name"] for i in smartlist.pick(hv, root, dict(f, sort="path"), {}, set(), **kw)]   # noqa: E731
    assert names({"area": "MUSICIANS", "text": "hubbard"}) == ["Commando.sid", "Delta.sid"]
    assert names({"max_s": 120}) == ["Wizball.sid", "Delta.sid"]                 # by path: G before H
    assert names({"min_s": 180}) == ["Turrican.sid", "Comic_Bakery.sid", "Commando.sid"]   # /GAMES before /MUSICIANS
    assert names({"sids": "multi"}) == ["Dual_Core_2SID.sid"]
    assert names({"text": "martin galway"}) == []                  # spaces become "_": "martin_galway" is not in it
    assert names({"text": "galway_martin"}) == ["Comic_Bakery.sid", "Wizball.sid"]
    it = smartlist.pick(hv, root, {"text": "turrican"}, {}, set())[0]
    assert it["src"] == "nas" and it["path"] == "/HVSC/C64Music/GAMES/S-Z/Turrican.sid"      # capitals kept
    plays = {M[2]: 5, M[0]: 9}
    assert [i["name"] for i in smartlist.pick(hv, root, {"sort": "top"}, plays, set())] == ["Commando.sid", "Turrican.sid"]
    assert len(smartlist.pick(hv, root, {"never": True}, plays, set())) == 4
    assert [i["name"] for i in smartlist.pick(hv, root, {"fav": True}, {}, {M[4]})] == ["Wizball.sid"]
    r = smartlist.pick(hv, root, {"n": 3}, {}, set(), rnd=random.Random(1))
    assert len(r) == 3


def test_page_plays_and_saves(tmp_path):
    async def t():
        root = tmp_path / "hvsc" / "C64Music"
        (root / "DOCUMENTS").mkdir(parents=True)
        (root / "DOCUMENTS" / "Songlengths.md5").write_text(SL, encoding="latin-1")
        for p in ("MUSICIANS/H/Hubbard_Rob/Commando.sid", "MUSICIANS/H/Hubbard_Rob/Delta.sid"):
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_bytes(make_sid(p.rsplit("/", 1)[1][:-4], "Rob Hubbard"))
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(tmp_path / "hvsc")}]
        app = make_app(jb)
        app.on_startup.append(lambda a: jb.start())
        app.on_cleanup.append(lambda a: jb.close())
        c = TestClient(TestServer(app))
        await c.start_server()
        try:
            await c.post("/api/login", json={"pw": "commodore64"}, headers=H)
            r = await (await c.post("/api/smart", json={"filter": {"preset": "random"}}, headers=H)).json()
            assert not r["ok"] and "Songlängen" in r["msg"]                     # nothing loaded yet
            await (await c.post("/api/songlengths/load", json={"src": "pi", "kind": "hvsc",
                                                               "path": "/C64Music/DOCUMENTS/Songlengths.md5"}, headers=H)).json()
            for _ in range(100):
                if jb.songlengths.hvsc:
                    break
                await asyncio.sleep(0.05)
            info = await (await c.get("/api/smart")).json()
            assert info["hvsc"] == 6 and info["root"] == "Pi: /C64Music"
            r = await (await c.post("/api/smart", json={"filter": {"text": "hubbard", "sort": "path"}}, headers=H)).json()
            assert r["ok"] and r["n"] == 2
            assert [i["name"] for i in jb.player.items] == ["Commando.sid", "Delta.sid"] and jb.player.state == "play"
            r = await (await c.post("/api/smart", json={"filter": {"text": "galway", "sort": "path"}, "mode": "save",
                                                        "name": "Galway"}, headers=H)).json()
            assert r["n"] == 2 and [i["name"] for i in jb.playlist_read("Galway")["items"]] == ["Comic_Bakery.sid", "Wizball.sid"]
            r = await (await c.post("/api/smart", json={"filter": {"text": "nichtda"}}, headers=H)).json()
            assert not r["ok"] and "Keine Stücke" in r["msg"]
            # favourites (also outside the HVSC) and the most played
            jb.stats.toggle_fav({"src": "pi", "path": "/eigene/x.sid", "name": "x.sid", "md5": "ab" * 16})
            jb.stats.plays["md5:" + M[1]] = 7
            jb.stats.plays["path:pi:/eigene/y.sid"] = 3
            fav = await jb.smart_items({"preset": "fav"})
            assert [i["path"] for i in fav] == ["/eigene/x.sid"]
            top = await jb.smart_items({"preset": "top"})
            assert [i["name"] for i in top][:2] == ["Delta.sid", "y.sid"]
        finally:
            await c.close()
            await u64.stop()
    asyncio.run(t())
