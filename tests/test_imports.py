"""Play lists of the PC program: matching rules, formats, statistics files."""
import asyncio
import json

from c64jukebox import imports, sidfile
from c64jukebox.core import Jukebox
from c64jukebox.stats import Stats
from fakes import FakeUltimate, make_sid


def idx_of(paths, md5s=None):
    ix = imports.FolderIndex()
    for p in paths:
        ix.add(p)
    for p, m in (md5s or {}).items():
        ix.add_md5(p, m)
    return ix


def test_match_shared_rules():
    ix = idx_of(["/A/Commando.sid", "/B/commando.SID", "/C/other.sid"],
                {"/A/Commando.sid": "aa" * 16, "/C/other.sid": "bb" * 16, "/B/commando.SID": "bb" * 16})
    songs = [{"md5": "bb" * 16, "filename": "Commando.sid"},           # md5 first: other.sid (first hit of that md5)
             {"md5": "BB" * 16, "filename": "COMMANDO.sid"},           # upper-case md5 does not count (as in the PC program)
             {"md5": "cc" * 16, "filename": "x.sid", "title": "T", "author": "A"},
             {"md5": "", "filename": "", "title": ""},
             {"md5": "aa" * 16, "filename": "y.sid"}, {"md5": "aa" * 16, "filename": "y.sid"}]   # duplicates stay
    found, missing = imports.match_shared(songs, ix)
    assert found == ["/C/other.sid", "/A/Commando.sid", "/A/Commando.sid", "/A/Commando.sid"]
    assert missing == ["T - A", "(unnamed)"]


def test_parse_shared_and_export():
    try:
        imports.parse_shared({"format": "x"})
        raise AssertionError
    except ValueError:
        pass
    data, skipped = imports.export_shared("Party", [{"md5": "AB" * 16, "name": "a.sid", "title": "T", "author": "A"},
                                                    {"name": "b.sid"}])
    assert skipped == 1 and data["format"] == imports.SHARED_FORMAT and data["version"] == 1
    assert data["songs"] == [{"md5": "ab" * 16, "filename": "a.sid", "title": "T", "author": "A"}]
    assert imports.parse_shared(data) == ("Party", data["songs"])


def test_u64pl():
    text = "# Ultimate64 SID Player Playlist\n\n/Volumes/Musik/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid\r\n" \
           "C:\\SIDs\\X24\\A_Boot.sid\n# comment\nu64://192.168.1.168/USB2/a b.sid\n /x/leading_space.sid\n"
    e = imports.parse_u64pl(text)
    assert e == ["/Volumes/Musik/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid", "C:\\SIDs\\X24\\A_Boot.sid",
                 "u64://192.168.1.168/USB2/a b.sid", " /x/leading_space.sid"]
    assert imports.parse_device_path(e[2]) == ("192.168.1.168", "/USB2/a b.sid")
    ix = idx_of(["/HVSC/C64Music/MUSICIANS/G/Galway/Commando.sid", "/HVSC/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid",
                 "/stick/x24/a_boot.sid"])
    assert imports.match_u64pl_path(e[0], ix) == "/HVSC/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid"   # longest end
    assert imports.match_u64pl_path(e[1], ix) == "/stick/x24/a_boot.sid"
    assert imports.match_u64pl_path("/nowhere/none.sid", ix) is None


def test_hvsc_paths():
    text = "[Database]\n; /MUSICIANS/H/Hubbard_Rob/Commando.sid\n%s=3:56 1:01\n; /GAMES/S-Z/Turrican.sid\n%s\n=2:00\n" % (
        "Ab" * 16, "cd" * 16)
    m = imports.hvsc_paths(text)
    assert m == {"/musicians/h/hubbard_rob/commando.sid": "ab" * 16, "/games/s-z/turrican.sid": "cd" * 16}
    assert imports.hvsc_rel("/SID Tunes/HVSC 85/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid") == "/musicians/h/hubbard_rob/commando.sid"


def test_stats_pc_files(tmp_path):
    st = Stats(str(tmp_path / "stats.json"))
    it = {"md5": "AB" * 16, "src": "s", "path": "/a.sid"}
    st.played(it)
    n_p, n_f = st.merge_pc(plays={"md5:" + "ab" * 16: 4, "/x/y.sid": 2},
                           favorites={"md5:" + "ab" * 16: {"path": "/Users/x/a.sid", "title": "T", "author": "A"}})
    assert (n_p, n_f) == (1, 1) and st.count(it) == 5 and st.is_fav(it)
    st.save(force=True)
    assert Stats(str(tmp_path / "stats.json")).count(it) == 5
    assert st.merge_pc(favorites=["md5:" + "cd" * 16]) == (0, 1)


def test_import_shared_with_hvsc_map(tmp_path):
    """a HVSC folder: the MD5s come from Songlengths.md5 - no file is read for the index"""
    async def t():
        d = tmp_path / "C64Music" / "MUSICIANS" / "H" / "Hubbard_Rob"
        d.mkdir(parents=True)
        a, b = make_sid("Commando"), make_sid("Delta")
        (d / "Commando.sid").write_bytes(a)
        (d / "Delta.sid").write_bytes(b)
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1")
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(tmp_path)}]
        u = await FakeUltimate().start()
        jb.config.data["ultimates"] = [{"label": "E", "addr": u.addr, "pw": ""}]
        await jb.start()
        await jb.set_songlengths("hvsc", ("; /MUSICIANS/H/Hubbard_Rob/Commando.sid\n%s=3:56\n; /MUSICIANS/H/Hubbard_Rob/Delta.sid\n%s=11:22\n"
                                          % (sidfile.md5(a), "ee" * 16)).encode(), "t")
        reads = []
        src = jb.sources.get("pi")
        orig = src.read

        async def counting(p, limit=1 << 20):
            reads.append(p)
            return await orig(p, limit)
        src.read = counting

        class J:
            dirs, progress, pct = 0, "", None
        data = {"format": imports.SHARED_FORMAT, "version": 1, "name": "Hub",
                "songs": [{"md5": sidfile.md5(a), "filename": "zzz.sid"}, {"md5": sidfile.md5(b), "filename": "Delta.sid"}]}
        r = await jb.import_shared(J(), data, "pi", "/", save=True)
        assert r["found"] == 2 and r["saved"] == "Hub" and r["missing"] == []
        # the HVSC file is trusted (Delta's entry "ee.." does not fit the file): nothing was read, Delta came by name
        assert reads == []
        assert [i["name"] for i in jb.player.items] == ["Commando.sid", "Delta.sid"]
        await jb.close()
        await u.stop()
    asyncio.run(t())
