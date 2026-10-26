"""Long jobs must not stop the jukebox's loop - it also passes the stream on to the TV and the Picos (2026-10-23: a
playlist import over the HVSC stopped it for up to 31 s, the TV's sound broke off)."""
import asyncio
import time

from c64jukebox import imports
from c64jukebox.core import Jukebox


class Job:
    dirs = 0
    progress = ""
    pct = 0


def test_index_folder_keeps_the_loop_running(tmp_path, monkeypatch):
    async def t():
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        await jb.start()
        try:
            async def walk(src, path, recursive=True, max_age=None, job=None):     # 400 folders from the cache
                for k in range(400):
                    if k % 10 == 0:
                        await asyncio.sleep(0)
                    yield "/D%d" % k, [{"n": "t%d.sid" % i, "d": False} for i in range(10)]
            monkeypatch.setattr(jb, "walk", walk)

            def slow_info(src, p, size=None):                # a sqlite lookup on the Pi: ~1 ms
                time.sleep(0.001)
                return {"md5": "%032x" % hash(p)}
            monkeypatch.setattr(jb.catalog, "get_info", slow_info)
            lag = []

            async def ticker():
                while True:
                    t0 = time.perf_counter()
                    await asyncio.sleep(0.01)
                    lag.append(time.perf_counter() - t0 - 0.01)
            tk = asyncio.create_task(ticker())
            idx = await jb.index_folder(Job(), "pi", "/")
            tk.cancel()
            assert len(idx.paths) == 4000
            assert max(lag) < 0.1, max(lag)                  # a turn at least every 20 ms (one slow lookup on top)
        finally:
            await jb.close()
    asyncio.run(t())


def test_a_standstill_is_logged(tmp_path):
    async def t():
        from c64jukebox import events
        events.clear()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        await jb.start()
        try:
            await asyncio.sleep(0.3)
            time.sleep(0.6)                                  # something holds the loop
            await asyncio.sleep(0.4)
            assert any(e["text"].startswith("Jukebox stand 0.") for e in events.recent())
        finally:
            await jb.close()
    asyncio.run(t())


def test_catalog_commits_do_not_wait_for_the_card(tmp_path):
    from c64jukebox.catalog import Catalog
    c = Catalog(str(tmp_path / "c.db"))
    assert c.db.execute("PRAGMA synchronous").fetchone()[0] == 1 and c.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    c.close()
