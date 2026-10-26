"""SID addresses on the Ultimate, like "Auto-adjust SID addresses" of the PC jukebox: only the clear case, only
sockets (never an UltiSID), restored after the tune, on stop and after a restart."""
import asyncio
import json
import os

from c64jukebox.core import Jukebox
from c64jukebox.sidaddr import norm, plan
from fakes import FakeUltimate, make_sid

S1, S2, U1, U2 = "SID Socket 1 Address", "SID Socket 2 Address", "UltiSID 1 Address", "UltiSID 2 Address"


def test_plan_only_the_clear_case():
    base = {S1: "$D400", S2: "$D500", U1: "Unmapped", U2: "Unmapped"}
    assert plan(base, ["D400"]) == (None, "")                                    # nothing missing
    assert plan(base, ["D400", "D500"]) == (None, "")
    assert plan(base, ["D400", "D420"]) == ((2, "$D420"), "")                    # one missing, socket 2 is spare
    assert plan(dict(base, **{U1: "$D420"}), ["D400", "D420"]) == (None, "")     # an UltiSID gives it already
    sw, why = plan(base, ["D400", "D420", "D440"])                              # two missing
    assert sw is None and "nicht eindeutig" in why
    sw, why = plan({S1: "$D500", S2: "$D600"}, ["D400", "D420"])                # two missing again
    assert sw is None
    sw, why = plan({S1: "$D400", S2: "$D500", "SID Socket 3 Address": "$D600"}, ["D400", "D420"])   # two spare
    assert sw is None and "nicht eindeutig" in why
    assert plan({S1: "$D400", S2: "Unmapped", U1: "$D500"}, ["D400", "D420"])[0] is None   # never an UltiSID
    assert norm("d420") == "$D420" and norm("Unmapped") is None


A = make_sid("Mono", "Ann")
B = make_sid("Stereo", "Bob", version=3, second=0x42)          # needs $D420
C = make_sid("Stereo2", "Cid", version=3, second=0x42)


def test_switch_play_restore(tmp_path):
    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        for n, data in (("a.sid", A), ("b.sid", B), ("c.sid", C)):
            (d / n).write_bytes(data)
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "Elite", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        jb.config.save()                                          # the next start knows the Ultimate
        await jb.start()
        p = jb.player
        try:
            def items(*names):
                return [{"src": "pi", "path": "/" + n, "name": n} for n in names]
            await p.set_items(items("b.sid", "c.sid", "a.sid"), 0, play=True, source="t")
            assert u64.sid_cfg[S2] == "$D420"                                            # switched for the tune
            order = [c[1] for c in u64.calls]                                            # (files from the Pi: POST)
            assert order.index("/v1/configs/SID Addressing/" + S2) < order.index("/v1/runners:sidplay")   # before playing
            saved = json.load(open(tmp_path / "data" / "sid-socket.json"))
            assert saved == [{"addr": u64.addr, "pw": "", "sock": 2, "orig": "$D500", "new": "$D420"}]
            assert "Sockel 2" in jb.state()["sidaddr"]
            n_put = len(u64.find("PUT", "/v1/configs/SID Addressing/" + S2))
            await p.next()                                                               # c.sid needs $D420 too
            assert u64.sid_cfg[S2] == "$D420" and len(u64.find("PUT", "/v1/configs/SID Addressing/" + S2)) == n_put
            await p.next()                                                               # a.sid: one SID
            assert u64.sid_cfg[S2] == "$D500" and not os.path.exists(tmp_path / "data" / "sid-socket.json")
            await p.play_pos(0)
            assert u64.sid_cfg[S2] == "$D420"
            await p.stop()                                                               # stop: back
            assert u64.sid_cfg[S2] == "$D500" and "zurück" in jb.sidaddr.msg
            # switched off: nothing is changed
            jb.config.data["player"]["sidauto"] = False
            await p.play_pos(0)
            assert u64.sid_cfg[S2] == "$D500"
            jb.config.data["player"]["sidauto"] = True
            await p.play_pos(0)
            assert u64.sid_cfg[S2] == "$D420"
        finally:
            await jb.close()
        # the power goes off in the middle of the tune: the next start restores the socket
        jb2 = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        await jb2.start()
        try:
            assert u64.sid_cfg[S2] == "$D500" and jb2.sidaddr.pending == {}
        finally:
            await jb2.close()
            await u64.stop()
    asyncio.run(t())


def test_fit_marks_like_the_pc_jukebox():
    from c64jukebox.sidaddr import SidAddressing
    s = SidAddressing("/nonexistent/x.json")
    assert s.fit(["D400"]) is None                                                # configuration not read yet
    base = {S1: "$D400", S2: "$D500", U1: "Unmapped", U2: "Unmapped"}
    assert s.fit(["D400"], base) == "ok" and s.fit(["D400", "D500"], base) == "ok"
    assert s.fit(["D400", "D420"], base) == "fix"
    assert s.fit(["D400", "D420", "D440"], base) == "no"
    assert s.fit(["D400", "D420"], dict(base, **{U1: "$D420"})) == "ok"          # an UltiSID has it
    # while a socket is switched, the list still marks against the normal configuration
    s.known, s.known_addr = dict(base, **{S2: "$D420"}), "1.2.3.4"
    s.pending = {"1.2.3.4": {"addr": "1.2.3.4", "sock": 2, "orig": "$D500", "new": "$D420"}}
    assert s.fit(["D400", "D420"]) == "fix" and s.fit(["D400", "D500"]) == "ok"


def test_rows_carry_the_marking(tmp_path):
    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        for n, data in (("a.sid", A), ("b.sid", B)):
            (d / n).write_bytes(data)
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "Elite", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        await jb.start()
        try:
            await jb.player.set_items([{"src": "pi", "path": "/" + n, "name": n} for n in ("a.sid", "b.sid")], 0,
                                      play=False, source="t")
            lver = jb.player.lver
            await jb.sid_refresh()
            assert jb.player.lver > lver                                           # the page reloads its rows
            await jb.player.play_pos(1)                                            # reads b.sid's header
            await jb.player.stop()
            await jb.player.play_pos(0)
            by = {r["name"]: r["sfit"] for r in jb.list_rows(0, 10)["rows"]}
            assert by == {"a.sid": "ok", "b.sid": "fix"}
            u64.sid_cfg[S2] = "Unmapped"                                           # socket 2 off: no clear fix
            await jb.sid_refresh()
            by = {r["name"]: r["sfit"] for r in jb.list_rows(0, 10)["rows"]}
            assert by == {"a.sid": "ok", "b.sid": "no"}
        finally:
            await jb.close()
            await u64.stop()
    asyncio.run(t())


def test_restore_never_lost(tmp_path):
    """found in the review: an unreachable Ultimate's record must not block another one, a lost answer must not drop
    the record, failed playing restores, and an Ultimate switched off between two tunes gets the address again"""
    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        for n, data in (("a.sid", A), ("b.sid", B), ("c.sid", C)):
            (d / n).write_bytes(data)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        gone = "127.0.0.1:1"                                     # nobody listens there
        (data_dir / "sid-socket.json").write_text(json.dumps({"addr": gone, "sock": 2, "orig": "$D500", "new": "$D420"}))
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(data_dir), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "B", "addr": u64.addr, "pw": ""}, {"label": "A", "addr": gone, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        await jb.start()
        p = jb.player
        try:
            assert gone in jb.sidaddr.pending                    # the first format is read; A cannot be reached
            items = [{"src": "pi", "path": "/" + n, "name": n} for n in ("b.sid", "c.sid", "a.sid")]
            await p.set_items(items, 0, play=True, source="t")
            assert u64.sid_cfg[S2] == "$D420"                    # B switched although A's record is open
            assert set(jb.sidaddr.pending) == {gone, u64.addr}
            # the Ultimate was switched off and on between two tunes: its RAM setting is back to $D500
            u64.sid_cfg[S2] = "$D500"
            await p.next()                                       # c.sid needs $D420 too
            assert u64.sid_cfg[S2] == "$D420"
            await p.stop()
            assert u64.sid_cfg[S2] == "$D500" and u64.addr not in jb.sidaddr.pending
            assert gone in jb.sidaddr.pending                    # A is still entered: kept for later
            new = jb.config.data["ultimates"][:1]
            await jb.sid_config_change(new)                      # A removed on the page: tried once more, forgotten
            jb.config.data["ultimates"] = new
            assert jb.sidaddr.pending == {}
            # the answer to the switch gets lost, but the Ultimate did it: the record stays and restores
            u64.lose_sid_put = 1
            await p.play_pos(0)
            assert u64.sid_cfg[S2] == "$D420" and u64.addr in jb.sidaddr.pending
            await p.stop()
            assert u64.sid_cfg[S2] == "$D500"
            # the tune cannot be played: playing stops and the socket goes back
            u64.fail_play = 10
            await p.set_items(items[:1], 0, play=True, source="t")
            assert p.state == "stop" and u64.sid_cfg[S2] == "$D500" and jb.sidaddr.pending == {}
        finally:
            await jb.close()
            await u64.stop()
    asyncio.run(t())


def test_edited_entry_and_stale_refresh(tmp_path):
    """second review: an entry edited on the page (new address, password) keeps the way back; a stop of the player
    does not wait for another Ultimate that is off; a refresh that ran while a socket was restored is dropped"""
    async def t():
        d = tmp_path / "sids"
        d.mkdir()
        (d / "b.sid").write_bytes(B)
        u64 = await FakeUltimate(pw="geheim").start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": "127.0.0.1:1", "pw": "geheim"}]     # wrong address first
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)}]
        await jb.start()
        p = jb.player
        try:
            jb.config.data["ultimates"] = [{"label": "E", "addr": u64.addr, "pw": "geheim"}]
            await p.set_items([{"src": "pi", "path": "/b.sid", "name": "b.sid"}], 0, play=True, source="t")
            assert u64.sid_cfg[S2] == "$D420"
            # the user writes the address differently (same device): the record moves along
            alias = "localhost:%d" % int(u64.addr.rsplit(":", 1)[1])
            new = [{"label": "E", "addr": alias, "pw": "geheim"}]
            await jb.sid_config_change(new)
            jb.config.data["ultimates"] = new
            assert list(jb.sidaddr.pending) == [alias] and jb.sidaddr.pending[alias]["pw"] == "geheim"
            await p.stop()
            assert u64.sid_cfg[S2] == "$D500" and jb.sidaddr.pending == {}
            # another Ultimate that is off: a stop does not wait for it
            jb.sidaddr.pending = {"192.0.2.9": {"addr": "192.0.2.9", "pw": "", "sock": 2, "orig": "$D500", "new": "$D420"}}
            import time as _t
            t0 = _t.monotonic()
            await p.play_pos(0)
            await p.stop()
            assert _t.monotonic() - t0 < 2
            # a refresh that was running while the socket went back must not bring the old reading back
            jb.config.data["ultimates"] = [{"label": "E", "addr": alias, "pw": "geheim"}]
            gen = jb.sidaddr.gen
            jb.sidaddr.gen += 1                                   # as if a restore happened during the GET
            real = jb.sidaddr.read

            async def slow(u, keep=True):
                cfg = await real(u, keep)
                jb.sidaddr.gen = gen + 5
                return dict(cfg, **{S2: "$D420"})
            jb.sidaddr.read = slow
            known = dict(jb.sidaddr.known)
            await jb.sid_refresh()
            assert jb.sidaddr.known == known
        finally:
            for t in jb.side.values():
                t.cancel()
            await jb.close()
            await u64.stop()
    asyncio.run(t())
