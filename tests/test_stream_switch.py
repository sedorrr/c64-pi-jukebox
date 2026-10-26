"""The sound must come from the chosen Ultimate: one that still streams to the Pi (asked before a restart, which
forgets whom it asked, or before a switch) is told to stop, and the chosen one is asked."""
import asyncio

from c64jukebox.core import Jukebox
from fakes import FakeUltimate


def test_foreign_stream_is_stopped(tmp_path):
    async def t():
        a, b = await FakeUltimate().start(), await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "Elite II", "addr": a.addr, "pw": ""},
                                       {"label": "Elite", "addr": b.addr, "pw": ""}]
        jb.config.data["stream"]["on"] = True
        await jb.start()
        try:
            ips = {"127.0.0.1": "10.0.0.1"}

            async def resolve(host):                      # both fakes live on 127.0.0.1: give each its own address
                return "10.0.0.2" if host == "localhost" else ips.get(host, host)
            jb.resolve = resolve
            jb.config.data["ultimates"][1]["addr"] = "localhost:%s" % b.addr.rsplit(":", 1)[1]
            # Elite (b) still streams to the Pi although the Elite II (a) is chosen
            jb.hub.lock_ip, jb.hub.rx, jb.hub.last_rx = "10.0.0.2", 100, jb.clock()
            await jb._stream_keep()
            assert jb.hub.allow == {"10.0.0.1", "10.0.0.2"}                     # stream data only from these
            assert b.find("PUT", "/v1/streams/audio:stop")                     # the wrong one stops
            assert a.find("PUT", "/v1/streams/audio:start")                    # the chosen one is asked
            assert "Elite" in jb.stream_msg or jb._stream_asked == a.addr
            # the chosen one streams: nothing more happens
            n = len(a.calls) + len(b.calls)
            jb.hub.lock_ip, jb._stream_req_at = "10.0.0.1", -1e9
            await jb._stream_keep()
            assert len(a.calls) + len(b.calls) == n
            # a sender that is none of the entered Ultimates is left alone
            jb.hub.lock_ip = "10.9.9.9"
            await jb._stream_keep()
            assert len(a.calls) + len(b.calls) == n
        finally:
            await jb.close()
            await a.stop()
            await b.stop()
    asyncio.run(t())


def test_levels_for_the_level_page(tmp_path):
    async def t():
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        await jb.start()
        try:
            assert "level" not in jb.display_state() and not jb.hub.want_levels
            jb.display.page = "level"
            jb.hub.rx, jb.hub.last_rx, jb.hub.lvl = 10, jb.clock(), [0.5, 0.25]
            jb._levels_tick()
            assert jb.hub.want_levels and jb.hub.lvl == [0.0, 0.0]
            lv = jb.display_state()["level"]
            assert lv["now"] == [0.5, 0.25] and lv["peak"] == [0.5, 0.25] and lv["hist"] == [0.5]
            jb._levels_tick()                                     # quiet now: the peaks fall slowly
            lv = jb.display_state()["level"]
            assert lv["now"] == [0.0, 0.0] and abs(lv["peak"][0] - 0.46) < 1e-9 and len(lv["hist"]) == 2
            jb.display.page = "play"
            assert "level" not in jb.display_state() and not jb.hub.want_levels   # not measured any more
        finally:
            await jb.close()
    asyncio.run(t())
