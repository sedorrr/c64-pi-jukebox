"""The jukebox's clock (4 times a second) must keep running while an Ultimate does not answer: the requests for the
audio/video stream and the SID addresses run beside it."""
import asyncio

from c64jukebox.core import Jukebox


def test_clock_runs_while_the_ultimate_hangs(tmp_path):
    async def t():
        async def never(reader, writer):                   # takes the connection, never answers
            await asyncio.sleep(30)
        srv = await asyncio.start_server(never, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": "127.0.0.1:%d" % port, "pw": ""}]
        jb.config.data["stream"]["on"] = True
        jb.config.data["hdmi"]["on"] = True
        jb.config.data["hdmi"]["bg"] = "video"
        ticks = []
        await jb.start()
        jb._display_tick = lambda: ticks.append(1)
        try:
            await asyncio.sleep(3.2)
            assert len(ticks) >= 3                         # one per second, although both requests hang
            assert not jb.side["stream"].done()            # still waiting for the Ultimate
        finally:
            await jb.close()
            srv.close()
    asyncio.run(t())
