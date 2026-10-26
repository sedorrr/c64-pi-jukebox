"""The timer: entries are checked, run once in their minute on their weekdays, the next run is found, and the
jukebox plays a saved list / stops at that time."""
import asyncio
import time

import pytest

from c64jukebox import schedule
from c64jukebox.core import Jukebox
from fakes import FakeUltimate, make_sid


def lt(y, mo, d, h, mi):
    return time.localtime(time.mktime((y, mo, d, h, mi, 0, 0, 0, -1)))


def test_clean_due_next():
    e = schedule.clean([{"id": "a", "days": [0, 1, 2, 3, 4], "time": "8:05", "do": "play", "list": "Abend"},
                        {"id": "b", "days": [6], "time": "23:00", "do": "stop", "list": "x", "tv": True}], {"Abend"})
    assert e[0]["time"] == "08:05" and e[0]["on"] and e[1]["list"] == ""               # stop needs no list
    with pytest.raises(ValueError):
        schedule.clean([{"days": [1], "time": "25:00"}])
    with pytest.raises(ValueError):
        schedule.clean([{"days": [], "time": "10:00"}])
    with pytest.raises(ValueError):
        schedule.clean([{"days": [1], "time": "10:00", "list": "fehlt"}], {"Abend"})
    mon = lt(2026, 10, 19, 8, 5)                                  # a Monday
    assert mon.tm_wday == 0
    fired = set()
    assert [x["id"] for x in schedule.due(e, mon, fired)] == ["a"]
    assert schedule.due(e, mon, fired) == []                       # once per minute
    assert schedule.due(e, lt(2026, 10, 19, 8, 6), fired) == [] and not fired
    assert schedule.due(e, lt(2026, 10, 25, 8, 5), fired) == []    # Sunday: not a day of "a"
    nxt = schedule.next_run(e, lt(2026, 10, 24, 12, 0))            # Saturday noon -> Sunday 23:00
    assert nxt[0]["id"] == "b" and nxt[1].tm_wday == 6 and nxt[1].tm_hour == 23
    assert schedule.describe(*nxt) == "So 23:00 · Stoppen (Fernseher aus)"
    e[1]["on"] = False
    assert schedule.next_run(e, lt(2026, 10, 24, 12, 0))[1].tm_wday == 0      # then Monday 08:05


def test_jukebox_runs_the_timer(tmp_path):
    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        (d / "a.sid").write_bytes(make_sid("Alpha", "Ann"))
        (d / "b.sid").write_bytes(make_sid("Beta", "Bob"))
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        await jb.start()
        try:
            jb.playlist_write("Feierabend", [{"src": "pi", "path": "/b.sid", "name": "b.sid"}])
            now = [time.mktime((2026, 10, 19, 17, 59, 30, 0, 0, -1))]               # Monday 17:59:30
            jb.wall = lambda: now[0]
            st = jb.schedule_set([{"id": "on", "days": [0], "time": "18:00", "do": "play", "list": "Feierabend"},
                                  {"id": "off", "days": [0], "time": "18:01", "do": "stop"}])
            assert st["next"] == "Mo 18:00 · Abspielen „Feierabend“" and "Feierabend" in st["lists"]
            with pytest.raises(ValueError):
                jb.schedule_set([{"days": [0], "time": "18:00", "list": "Gibt es nicht"}])
            now[0] += 35                                                            # 18:00:05
            for _ in range(60):
                await asyncio.sleep(0.05)
                if jb.player.state == "play":
                    break
            assert jb.player.state == "play" and jb.player.cur["item"]["name"] == "b.sid"
            assert "Feierabend" in jb.schedule_state()["last"]
            now[0] += 60                                                            # 18:01:05
            for _ in range(100):                     # the timer's entry, not just "stop" (a short list may end first)
                await asyncio.sleep(0.05)
                if jb.player.state == "stop" and jb.schedule_state()["last"].endswith("Stoppen"):
                    break
            assert jb.player.state == "stop" and jb.schedule_state()["last"].endswith("Stoppen"), \
                (jb.player.msg, jb.schedule_state())
        finally:
            await jb.close()
            await u64.stop()
    asyncio.run(t())
