"""The player against a fake Ultimate, with a clock the test moves forward."""
import asyncio
import os

from c64jukebox import sidfile
from c64jukebox.core import Jukebox
from fakes import FakeFTP, FakeUltimate, make_sid

A = make_sid("Alpha", "Ann", "1986 X")
B = make_sid("Beta", "Bob", "1987 Y", songs=2, start=1, version=3, second=0x42)
C = make_sid("Gamma", "Cid", "1988 Z")


class Env:
    def __init__(self, tmp):
        self.tmp = tmp
        self.now = [1000.0]

    async def __aenter__(self):
        d = self.tmp / "sids"
        (d / "sub").mkdir(parents=True)
        (d / "a.sid").write_bytes(A)
        (d / "b.sid").write_bytes(B)
        (d / "sub" / "c.sid").write_bytes(C)
        (d / "readme.txt").write_text("x")
        self.u64 = await FakeUltimate(pw="np").start()
        self.ftp = FakeFTP({"USB0": {"a.sid": A}})
        self.jb = Jukebox(str(self.tmp / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", clock=lambda: self.now[0])
        c = self.jb.config.data
        c["ultimates"] = [{"label": "Elite", "addr": self.u64.addr, "pw": "np"}]
        c["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)},
                        {"id": "u64", "kind": "u64", "label": "Ultimate", "path": "/", "port": self.ftp.port}]
        c["player"]["silence"] = False
        await self.jb.start()
        return self

    async def __aexit__(self, *a):
        await self.jb.close()
        await self.u64.stop()
        self.ftp.stop()

    def items(self, *names):
        return [{"src": "pi", "path": "/" + n, "name": n.split("/")[-1]} for n in names]

    def plays(self):
        return [c for c in self.u64.calls if c[1] == "/v1/runners:sidplay"]

    async def step(self, secs):
        self.now[0] += secs
        await asyncio.sleep(0.35)          # the background clock ticks every 0.25 s
        p = self.jb.player
        if p.task:
            await p.task


def run(tmp, fn):
    async def t():
        async with Env(tmp) as e:
            await fn(e)
    asyncio.run(t())


def test_upload_and_song_length(tmp_path):
    async def t(e):
        p = e.jb.player
        await e.jb.set_songlengths("hvsc", ("%s=0:10\n" % sidfile.md5(A)).encode(), "test")
        await p.set_items(e.items("a.sid", "b.sid", "sub/c.sid"))
        assert p.state == "play" and p.cur["secs"] == 10
        up = e.plays()[0]
        assert up[0] == "POST" and up[3]["data"] == A and up[2] == {"songnr": "1"}
        st = e.jb.state()["player"]
        assert st["now"]["title"] == "Alpha" and st["now"]["chips"] == 1
        await e.step(9)
        assert len(e.plays()) == 1
        await e.step(2.5)                   # end of the tune (+1 s)
        assert len(e.plays()) == 2 and p.cur["info"]["title"] == "Beta" and p.cur["info"]["sids"] == ["D400", "D420"]
    run(tmp_path, t)


def test_limit_subsongs_and_end_of_list(tmp_path):
    async def t(e):
        p, o = e.jb.player, e.jb.config["player"]
        o["limit_min"], o["subsongs"], o["repeat"] = 0.5, "all", False
        await e.jb.set_songlengths("hvsc", ("%s=0:05 0:07\n" % sidfile.md5(B)).encode(), "test")
        await p.set_items(e.items("b.sid", "a.sid"))
        await e.step(6.5)
        assert p.cur["song"] == 2 and e.plays()[-1][2] == {"songnr": "2"} and p.cur["secs"] == 7
        await e.step(8.5)
        assert p.cur["info"]["title"] == "Alpha" and p.cur["secs"] is None
        await e.step(29)
        assert p.state == "play"
        await e.step(2)                     # 30 s limit, last entry, no repeat: stop and reset
        assert p.state == "stop" and e.u64.calls[-1][1] == "/v1/machine:reset"
    run(tmp_path, t)


def test_silence(tmp_path):
    async def t(e):
        from test_net import audio
        p, hub = e.jb.player, e.jb.hub
        e.jb.config["player"]["silence"] = True
        await p.set_items(e.items("a.sid", "b.sid"))
        hub.my_ips = set()                                       # the fake Ultimate sends from 127.0.0.1
        for i in range(3):
            await e.step(1)
            hub.datagram_received(audio(i, 4000), ("127.0.0.1", 5555))
        for i in range(5):
            await e.step(0.95)                                   # a stream without gaps (> 1 s would be a new start)
            hub.datagram_received(audio(i, 3), ("127.0.0.1", 5555))
        assert p.cur["info"]["title"] == "Alpha"
        await e.step(0.5)
        hub.datagram_received(audio(9, 3), ("127.0.0.1", 5555))
        await e.step(0.1)
        assert p.cur["info"]["title"] == "Beta"
        # a hanging Ultimate: a second of quiet packets now and then (no stream in between) - not silence of the tune
        for i in range(4):
            await e.step(9)
            for k in range(5):
                hub.datagram_received(audio(k, 3), ("127.0.0.1", 5555))
                await e.step(0.2)
        assert p.cur["info"]["title"] == "Beta"
    run(tmp_path, t)


def test_direct_play_pause_and_controls(tmp_path):
    async def t(e):
        p = e.jb.player
        await p.set_items([{"src": "u64", "path": "/USB0/a.sid", "name": "a.sid"}] + e.items("b.sid", "sub/c.sid"))
        m, path, q, _ = e.plays()[0]
        assert (m, q) == ("PUT", {"file": "/USB0/a.sid", "songnr": "1"})     # on the Ultimate itself: by path
        await e.step(3)
        await p.pause()
        assert e.u64.calls[-1][1] == "/v1/machine:pause" and p.state == "pause"
        await e.step(100)
        assert abs(p.elapsed() - 3) < 0.01
        await p.resume()
        await e.step(2)
        assert abs(p.elapsed() - 2.35 - 3) < 0.4 and e.u64.find("PUT", "/v1/machine:resume")
        await p.next()
        assert p.cur["info"]["title"] == "Beta"
        await p.set_song(2)
        assert e.plays()[-1][2] == {"songnr": "2"}
        await e.step(6)
        await p.prev()                      # more than 5 s in: the same tune again
        assert p.cur["info"]["title"] == "Beta"
        await p.prev()
        assert p.cur["info"]["title"] == "Alpha"
        await p.play_index(2)
        assert p.cur["info"]["title"] == "Gamma"
        await p.remove(0)
        assert [i["name"] for i in p.items] == ["b.sid", "c.sid"] and p.current_index() == 1
        await p.move(1, 0)
        assert [i["name"] for i in p.items] == ["c.sid", "b.sid"] and p.current_index() == 0
        n = await p.add_items(e.items("a.sid"), play_next=True)
        assert n == 1 and p.order[p.pos + 1] == 2
        await p.stop()
        assert p.state == "stop" and e.u64.calls[-1][1] == "/v1/machine:reset"
        await p.clear()
        assert p.items == [] and p.pos == -1
    run(tmp_path, t)


def test_errors_skip_and_give_up(tmp_path):
    async def t(e):
        p = e.jb.player
        e.u64.fail_play = 1
        await p.set_items(e.items("a.sid", "readme.txt", "b.sid"))
        assert p.state == "load" and "Fehler 500" in p.msg
        await e.step(2.1)
        assert "Keine SID-Datei" in p.msg   # readme.txt
        await e.step(2.1)
        assert p.state == "play" and p.cur["info"]["title"] == "Beta"
        e.u64.fail_play = 99
        await p.set_items(e.items("a.sid"))
        assert p.state == "stop" and "angehalten" in p.msg
    run(tmp_path, t)


def test_shuffle_keeps_every_tune(tmp_path):
    async def t(e):
        p = e.jb.player
        await p.set_shuffle(True)
        await p.set_items(e.items("a.sid", "b.sid", "sub/c.sid"), start=1)
        assert p.cur["info"]["title"] == "Beta" and sorted(p.order) == [0, 1, 2]
        seen = {p.current_index()}
        for _ in range(2):
            await p.next()
            seen.add(p.current_index())
        assert seen == {0, 1, 2}
    run(tmp_path, t)


def test_list_kept_over_restart(tmp_path):
    async def t(e):
        await e.jb.player.set_items(e.items("a.sid", "b.sid"), start=1, play=False)
        e.jb.player.save_to(e.jb._current_path())
        j2 = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1")
        await j2.start()
        assert [i["name"] for i in j2.player.items] == ["a.sid", "b.sid"] and j2.player.current_index() == 1
        await j2.close()
    run(tmp_path, t)


def test_folder_collect_and_search(tmp_path):
    async def t(e):
        class J:
            dirs = 0
            progress = ""
        items = await e.jb.collect(J(), "pi", "/", True)
        assert [i["path"] for i in items] == ["/a.sid", "/b.sid", "/sub/c.sid"]
        assert [i["path"] for i in await e.jb.collect(J(), "pi", "/", False)] == ["/a.sid", "/b.sid"]
        await e.jb.info("pi", "/sub/c.sid")                 # header known -> found by composer too
        hits = await e.jb.search(J(), "pi", "/", "cid")
        assert [h["p"] for h in hits] == ["/sub/c.sid"] and hits[0]["i"]["t"] == "Gamma"
        assert [h["p"] for h in await e.jb.search(J(), "pi", "/", "sub c")] == ["/sub/c.sid"]
        assert await e.jb.search(J(), "pi", "/", "zzz") == []
    run(tmp_path, t)


def test_stream_request_and_switch(tmp_path):
    async def t(e):
        await e.jb.set_stream(True)
        st = e.u64.find("PUT", "/v1/streams/audio:start")
        assert st and st[0][2]["ip"].endswith(":%d" % e.jb.hub.port)
        await e.step(5)
        await asyncio.sleep(1.1)            # the stream is looked after once a second
        assert len(e.u64.find("PUT", "/v1/streams/audio:start")) == 1    # again only after 10 s without packets
        await e.step(6)
        await asyncio.sleep(1.1)
        assert len(e.u64.find("PUT", "/v1/streams/audio:start")) == 2
        await e.jb.set_stream(False)
        assert e.u64.find("PUT", "/v1/streams/audio:stop")
    run(tmp_path, t)


def test_remember_end_and_length_for_the_playing_tune(tmp_path):
    async def t(e):
        import pytest
        jb, p = e.jb, e.jb.player
        jb.config["player"]["limit_min"] = 3
        with pytest.raises(ValueError):
            await jb.remember_end()                         # nothing plays
        await p.set_items(e.items("a.sid", "b.sid"))
        assert p.cur["secs"] is None and p.state_json()["now"]["end"] == 180     # the TV fades out at the time limit
        await e.step(3)
        with pytest.raises(ValueError):
            await jb.remember_end()                         # too short to be a whole tune
        await e.step(80)
        secs = await jb.remember_end()                      # the tune is over here: remember 83 s, go on
        assert secs == 83 and p.cur["info"]["title"] == "Beta"
        assert jb.songlengths.lookup(sidfile.md5(A), 1) == 83
        # a length typed in counts at once for the tune that plays now
        jb.set_user_length(p.cur["item"], 20)
        assert p.cur["secs"] == 20
        await e.step(21.5)
        assert p.cur["info"]["title"] == "Alpha" and p.cur["secs"] == 83
        jb.set_user_length(p.cur["item"], None)             # removed: unknown again, the time limit counts
        assert p.cur["secs"] is None
    run(tmp_path, t)


def test_the_tv_sound_gets_the_stream(tmp_path):
    """HDMI on with sound: the stream also goes to the TV sound's own process (hdmi/soundproc.py)"""
    async def t(e):
        jb = e.jb
        jb.config.data["hdmi"].update(on=True, sound=True)
        jb.apply_targets()
        assert ("127.0.0.1", jb.hdmi_sound_port) in jb.hub.local and ("127.0.0.1", jb.hdmi_audio_port) in jb.hub.local
        jb.config.data["hdmi"]["sound"] = False
        jb.apply_targets()
        assert ("127.0.0.1", jb.hdmi_sound_port) not in jb.hub.local
    run(tmp_path, t)


def test_blocked_tunes_are_skipped(tmp_path):
    async def t(e):
        p, jb = e.jb.player, e.jb
        await p.set_items(e.items("a.sid", "b.sid", "sub/c.sid"))
        assert p.cur["info"]["title"] == "Alpha"
        await p.next()                                   # Beta known by MD5 now
        await jb.block()                                 # the playing tune: blocked, the next one starts
        assert p.cur["info"]["title"] == "Gamma" and jb.stats.is_blocked(p.items[1])
        assert jb.row(1, p.items[1], -1)["blk"] and not jb.row(0, p.items[0], -1)["blk"]
        await p.next()                                   # Alpha, Beta skipped on the next round
        await p.next()
        assert p.cur["info"]["title"] == "Gamma"
        await p.play_index(1)                            # chosen by hand: it plays
        assert p.cur["info"]["title"] == "Beta"
        # blocked before the MD5 was known in this list: found when read, skipped
        await p.set_items(e.items("b.sid", "a.sid"), start=1)
        await p.next()
        assert p.cur["info"]["title"] == "Alpha"
        # a star takes it off the list again; the list survives a restart
        key = jb.stats.blocked_list()[0]["key"]
        assert key.startswith("md5:") and jb.stats.blocked_md5s() == {key[4:]}
        jb.stats.save(force=True)
        from c64jukebox.stats import Stats
        assert Stats(jb.stats.path).block.keys() == {key}
        jb.stats.toggle_fav(p.items[0])
        assert not jb.stats.block
        # all blocked: the player stops instead of going round
        jb.stats.block_item(p.items[0])
        jb.stats.block_item(p.items[1])
        await p.next()
        assert p.state == "stop" and "gesperrt" in p.msg
    run(tmp_path, t)


def test_blocked_out_of_discover(tmp_path):
    async def t(e):
        p, jb = e.jb.player, e.jb
        await p.set_items(e.items("a.sid", "b.sid"), play=False)
        await p.play_index(0)
        jb.stats.block_item(p.items[0])
        for _ in range(5):
            await p.discover()
            assert p.cur["info"]["title"] == "Beta"
    run(tmp_path, t)
