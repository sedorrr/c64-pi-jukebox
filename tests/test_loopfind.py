"""The repeat of a tune without a length: synthetic SID-like tunes (square-wave notes, a noise drum that never sounds
the same twice) through LoopFinder, through the process (loopwatch.py, UDP like the stream) and the jukebox's side:
a suggestion on the page / the TV, taken or not, or taken at once ("auto").
Measured on 40 HVSC tunes rendered with VICE (2026-10-24, tools/loopfind_eval.py): see docs/HANDBUCH.md."""
import asyncio
import json
import socket
import sys

import numpy as np

from c64jukebox import loopfind, loopwatch
from test_player import run

R = loopfind.RATE


def tune(seed, secs):
    """a melody of random notes (8 a second) with a bass line, as int16 mono at 48 kHz"""
    rng = np.random.default_rng(seed)
    n = int(secs * 8)
    notes = rng.integers(48, 84, n)
    bass = np.repeat(rng.integers(36, 48, n // 8 + 1), 8)[:n]
    t = np.arange(R // 8) / R
    out = []
    for a, b in zip(notes, bass):
        fa, fb = 440 * 2 ** ((a - 69) / 12), 440 * 2 ** ((b - 69) / 12)
        env = np.exp(-t * 6)
        out.append(0.5 * np.sign(np.sin(2 * np.pi * fa * t)) * env + 0.4 * np.sign(np.sin(2 * np.pi * fb * t)))
    return np.concatenate(out)


def with_drums(x, seed):
    rng = np.random.default_rng(seed)
    hit = np.zeros(len(x))
    for i in range(0, len(x) - R // 20, R // 2):
        hit[i:i + R // 20] = rng.normal(0, 0.4, R // 20) * np.exp(-np.arange(R // 20) / (R / 200))
    return np.clip((x + hit) * 9000, -32767, 32767).astype(np.int16)


def find(x):
    lf = loopfind.LoopFinder()
    for i in range(0, len(x), 192 * 25):
        if lf.feed(x[i:i + 192 * 25]):
            break
    return lf.result()


def test_loop_back_to_the_start():
    loop = tune(1, 37.5)
    r = find(with_drums(np.concatenate([loop, loop, loop[:R * 30]]), 7))
    assert r and abs(r["len"] - 37.5) <= 1.0 and abs(r["from"]) <= 1.0 and r["at"] < 37.5 + 30


def test_a_pattern_played_over_and_over_is_no_loop():
    bar = tune(2, 5)                                       # one bar of 5 s, 20 times: matches at 20, 25, 30 s ...
    assert find(with_drums(np.tile(bar, 20), 3)) is None


def test_an_intro_then_the_loop_is_left_alone():
    intro, loop = tune(3, 12), tune(4, 30)                 # back into the middle: as often a part played twice
    assert find(with_drums(np.concatenate([intro, loop, loop, loop]), 5)) is None


def test_no_repeat_no_result():
    assert find(with_drums(tune(5, 120), 9)) is None


def test_the_process(tmp_path):
    """loopwatch as its own process: packets as from the Ultimate (2 bytes + 192 stereo frames), the answer on stdout"""
    loop = with_drums(np.concatenate([np.concatenate([tune(6, 30)] * 2), tune(6, 30)[:R * 20]]), 11)
    found = []

    async def t():
        lw = loopwatch.LoopWatch(found.append, python=sys.executable)
        assert await lw.ensure() and lw.port
        lw.begin("7")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        st = np.repeat(loop, 2).reshape(-1, 2)
        for k, i in enumerate(range(0, len(st) - 192, 192)):
            if k % 500 == 250:
                continue                                   # a packet lost now and then: filled with silence
            s.sendto((k & 0xFFFF).to_bytes(2, "little") + st[i:i + 192].tobytes(), ("127.0.0.1", lw.port))
            if k % 100 == 99:
                await asyncio.sleep(0.02)                  # not faster than the process takes them
            if found:
                break
        for _ in range(100):
            if found:
                break
            await asyncio.sleep(0.05)
        await lw.close()
    asyncio.run(t())
    assert found and found[0]["id"] == "7" and abs(found[0]["len"] - 30) <= 1.0


def test_no_numpy_python(tmp_path):
    msgs = []

    async def t():
        lw = loopwatch.LoopWatch(lambda d: None, python=str(tmp_path / "nopython"), log=msgs.append)
        assert not await lw.ensure() and not lw.available()
    asyncio.run(t())
    assert msgs and "nicht verfügbar" in msgs[0]


class FakeLoops:
    port = 49999

    def __init__(self):
        self.cmds = []

    def available(self):
        return True

    async def ensure(self):
        return True

    def begin(self, tid):
        self.cmds.append("start " + tid)

    def end(self):
        self.cmds.append("stop")

    async def close(self):
        pass


def test_suggest_take_reject_and_auto(tmp_path):
    async def t(e):
        jb, p = e.jb, e.jb.player
        jb.loops = fl = FakeLoops()
        jb.config["player"]["limit_min"] = 5
        await p.set_items(e.items("a.sid", "b.sid"))                    # no length known
        await jb._loop_keep()
        assert fl.cmds == ["start 1"] and ("127.0.0.1", 49999) in jb.hub.local
        jb._loop_found({"id": "0", "len": 30, "lag": 30, "from": 0, "at": 45})       # an old answer: ignored
        assert jb.loop_hint is None
        jb._loop_found({"id": "1", "len": 41.6, "lag": 41.6, "from": 0, "at": 57})
        assert jb.loop_hint["len"] == 42 and p.state_json()["now"]["loop"] == 42
        assert ("127.0.0.1", 49999) not in jb.hub.local                # found: no more packets to it
        # TV: the entry instead of "Ende hier merken"
        jb.config.data["hdmi"]["on"] = True
        await jb._cec_cmd("select")
        names = [x["l"] for x in jb.menu.view()["items"]]
        assert "Erkannte Länge übernehmen" in names and "Ende hier merken" not in names
        jb.menu.close()
        # "Nein": gone, the tune plays on (and is not looked at again)
        jb.loop_reject()
        assert jb.loop_hint is None and "loop" not in p.state_json()["now"]
        await jb._loop_keep()
        assert fl.cmds == ["start 1"]
        # next tune: looked at; taken -> its own length, on to the next at once
        await p.next()
        await jb._loop_keep()
        assert fl.cmds == ["start 1", "start 2"]
        await e.step(60)
        jb._loop_found({"id": "2", "len": 50, "lag": 50, "from": 0, "at": 60})
        name = p.cur["item"]["name"]
        assert jb.loop_take() == 50 and jb.songlengths.lookup(p.cur["item"]["md5"], 1) == 50
        await e.step(1)
        assert p.cur["item"]["name"] != name
        # auto: taken without asking
        jb.config["player"]["loopfind"] = "auto"
        await jb._loop_keep()
        await e.step(70)
        cur = p.cur
        jb._loop_found({"id": str(jb._loop_id), "len": 66, "lag": 66, "from": 0, "at": 70})
        assert jb.loop_hint is None and cur["secs"] == 66
        # a tune with a length is not looked at; "off" looks at nothing
        n = len(fl.cmds)
        jb.config["player"]["loopfind"] = "off"
        await e.step(2)
        await jb._loop_keep()
        assert fl.cmds[n:] in ([], ["stop"])
    run(tmp_path, t)


def test_the_process_runs_below_the_tv_sound(tmp_path):
    """the jukebox runs at nice -5, the HDMI service at 5: the repeat search must not take the TV sound's time"""
    import os

    async def t():
        lw = loopwatch.LoopWatch(lambda d: None, python=sys.executable)
        assert await lw.ensure()
        nice = os.getpriority(os.PRIO_PROCESS, lw.proc.pid)
        await lw.close()
        return nice
    assert asyncio.run(t()) >= loopwatch.NICE
