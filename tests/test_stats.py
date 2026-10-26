"""The history of played tunes ("Zuletzt gespielt"): kept over a restart, at most 100, a retry is one line; the page
gets it newest first and can clear it."""
import asyncio

from aiohttp.test_utils import TestClient, TestServer

from c64jukebox.core import Jukebox
from c64jukebox.stats import History
from c64jukebox.web import make_app
from fakes import FakeUltimate, make_sid

H = {"X-C64": "1"}


def test_history_file(tmp_path):
    p = str(tmp_path / "history.json")
    h = History(p)
    a = {"src": "pi", "path": "/a.sid", "name": "a.sid", "title": "A", "author": "Ann", "songs": 3, "md5": "ab"}
    h.add(a, 1, 120, now=1000)
    h.add(a, 1, 120, now=1003)                                  # again at once (retry, "back"): one line
    h.add(a, 2, None, now=1100)
    assert [(e["song"], e["t"]) for e in h.items] == [(1, 1003), (2, 1100)] and "secs" not in h.items[1]
    h.save()
    assert History(p).items == h.items
    for k in range(150):
        h.add(dict(a, path="/x%d.sid" % k), 1, now=2000 + k)
    assert len(h.items) == 100 and h.items[-1]["path"] == "/x149.sid"
    h.clear()
    h.save()
    assert History(p).items == []


def test_history_from_playing(tmp_path):
    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        (d / "a.sid").write_bytes(make_sid("Alpha", "Ann"))
        (d / "b.sid").write_bytes(make_sid("Beta", "Bob"))
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        app = make_app(jb)
        app.on_startup.append(lambda a: jb.start())
        app.on_cleanup.append(lambda a: jb.close())
        c = TestClient(TestServer(app))
        await c.start_server()
        try:
            await c.post("/api/login", json={"pw": "commodore64"}, headers=H)
            await jb.player.set_items([{"src": "pi", "path": "/" + n, "name": n} for n in ("a.sid", "b.sid")], 0,
                                      play=True, source="t")
            await jb.player.next()
            r = await (await c.get("/api/history")).json()
            assert [e["title"] for e in r["items"]] == ["Beta", "Alpha"] and r["now"] >= r["items"][0]["t"]
            assert r["items"][0]["md5"] and r["items"][0]["src"] == "pi"
            await (await c.post("/api/history/clear", json={}, headers=H)).json()
            assert (await (await c.get("/api/history")).json())["items"] == []
        finally:
            await c.close()
            await u64.stop()
    asyncio.run(t())
