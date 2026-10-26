"""A length by name: the same tune in another version of the file (other MD5) found in the HVSC by its file name or
title, the composer folder matching the header's author - a suggestion on the page / the TV, taken with all sub-song
lengths, or at once ("auto"). Measured 2026-10-24 on 600 files of a CSDB collection against HVSC 85: 69 known by MD5,
331 found by name (259 of them with the same music data behind the header), 143 not found."""
from c64jukebox import namematch, sidfile
from test_player import A, B, C, run

HV = {"/musicians/v/vincenzo/verkuerzte_ausfahrt.sid": "a" * 32,
      "/musicians/h/hubbard_rob/commando.sid": "b" * 32,
      "/musicians/x/someone/commando.sid": "c" * 32,
      "/games/a-f/frogger.sid": "d" * 32,
      "/games/s-z/zork.sid": "e" * 32, "/games/a-f/zork.sid": "f" * 32,
      "/musicians/d/dane/intro.sid": "1" * 32}


def test_norm_and_words():
    assert namematch.norm("Verkürzte Ausfahrt") == namematch.norm("verkuerzte_ausfahrt.sid") == "verkuerzteausfahrt"
    assert namematch.norm("László") == "laszlo"
    assert namematch.words("Laszlo Vincze (vincenzo)") == {"laszlo", "vincze", "vincenzo"}
    assert namematch.composer_folder("/musicians/h/hubbard_rob/commando.sid") == {"hubbard", "rob"}
    assert namematch.composer_folder("/games/a-f/frogger.sid") is None


def test_find():
    ix = namematch.NameIndex(HV)
    assert ix.find("verkuerzte_ausfahrt.sid", "Verkuerzte Ausfahrt", "Laszlo Vincze (vincenzo)")[0] == \
        "/musicians/v/vincenzo/verkuerzte_ausfahrt.sid"
    assert ix.find("x.sid", "Verkürzte Ausfahrt", "Vincenzo")                   # by the title alone
    assert ix.find("commando.sid", "Commando", "Rob Hubbard")[1] == "b" * 32     # the composer decides
    assert ix.find("commando.sid", "Commando", "Somebody Else") is None           # a cover by another
    assert ix.find("frogger.sid", "Frogger", "<?>")[1] == "d" * 32               # no composer folder: only one, title
    assert ix.find("zork.sid", "Zork", "<?>") is None                            # two of them: which?
    assert ix.find("frogger2.sid", "Frog", "<?>") is None
    assert ix.find("intro.sid", "Intro", "Dane") is None                         # names too common to mean anything


def test_suggest_and_take(tmp_path):
    async def t(e):
        jb, p = e.jb, e.jb.player
        hv = "".join("; /MUSICIANS/%s\n%s=%s\n" % x for x in [
            ("A/Ann/Alpha.sid", "1" * 32, "1:23"), ("Z/Zed/Alpha.sid", "2" * 32, "2:00"),
            ("B/Bob/Beta.sid", "3" * 32, "0:30 0:45"), ("X/Other/Gamma.sid", "4" * 32, "1:00")])
        hv += "%s=0:10\n" % ("5" * 32)                       # (the file needs a length of a real md5: none of ours)
        await jb.set_songlengths("hvsc", hv.encode(), "test")
        await p.set_items(e.items("a.sid", "b.sid", "sub/c.sid"))
        assert p.cur["secs"] is None
        await jb._name_keep()
        assert jb.name_hint["len"] == 83 and p.state_json()["now"]["hvsc"]["path"] == "/musicians/a/ann/alpha.sid"
        jb.config.data["hdmi"]["on"] = True                  # TV: the entry instead of "Ende hier merken"
        await jb._cec_cmd("select")
        v = jb.menu.view()
        names = [x["l"] for x in v["items"]]
        assert "HVSC-Länge übernehmen" in names and "Ende hier merken" not in names
        assert v["items"][v["sel"]]["l"] == "HVSC-Länge übernehmen"          # OK opened it right there
        jb.menu.close()
        from c64jukebox.hdmi.app import Osd                  # and a small hint on the TV, above the time
        import os
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        pygame.init()
        keys = {i.key for i in Osd().items(p.state_json())}
        assert "osd_hint" in keys
        await jb._cec_cmd("select")                           # OK, OK on the remote: taken
        await jb._cec_cmd("select")
        assert p.cur["secs"] == 83 and jb.name_hint is None and "übernommen" in jb.menu.view()["note"]
        e.now[0] += 2.5                                       # the note for 2 s, then the menu closes by itself
        assert jb.menu.view() is None
        assert jb.songlengths.custom[bytes.fromhex(sidfile.md5(A))] == (83,)
        # Beta: two sub-songs - both lengths taken
        await p.next()
        await jb._name_keep()
        assert jb.name_hint["len"] == 30
        jb.name_take()
        assert jb.songlengths.custom[bytes.fromhex(sidfile.md5(B))] == (30, 45)
        # Gamma by Cid: the HVSC one is by somebody else - nothing
        await p.next()
        await jb._name_keep()
        assert jb.name_hint is None and "hvsc" not in p.state_json()["now"]
        # "auto": taken at once
        jb.songlengths.custom.clear()
        jb.config["player"]["hvsc_name"] = "auto"
        await p.set_items(e.items("a.sid"))
        await jb._name_keep()
        assert jb.name_hint is None and p.cur["secs"] == 83
    run(tmp_path, t)


def test_check_lengths_of_the_list(tmp_path):
    """"Längen prüfen" (page and TV): after reading the headers, every title still without a length is looked up by
    name; the finds are offered, taken in one go (all sub-songs, saved once)"""
    async def t(e):
        jb, p = e.jb, e.jb.player
        hv = "".join("; /MUSICIANS/%s\n%s=%s\n" % x for x in [
            ("A/Ann/Alpha.sid", "1" * 32, "1:23"), ("B/Bob/Beta.sid", "3" * 32, "0:30 0:45")])
        await jb.set_songlengths("hvsc", hv.encode(), "test")
        await p.set_items(e.items("a.sid", "b.sid", "sub/c.sid"), play=False)
        job = jb.start_job("check", jb.check_list)
        await job.task
        assert job.result["nolen"] == 3 and job.result["found"] == 2 and job.result["taken"] == 0
        assert len(jb.list_hits) == 2
        # TV: the entry to take them; OK takes them and the menu closes after the note
        jb.config.data["hdmi"]["on"] = True
        await jb._cec_cmd("select")
        acts = [x[2][0] for x in jb.menu.entries()]
        jb.menu.sel["main"] = acts.index("listnames")
        await jb._cec_cmd("select")
        assert "2 Längen übernommen" in jb.menu.view()["note"] and jb.list_hits == []
        assert jb.songlengths.custom[bytes.fromhex(sidfile.md5(B))] == (30, 45)
        e.now[0] += 2.5
        assert jb.menu.view() is None
        # from the TV menu: started there, its progress and then its result in the note line
        jb.songlengths.custom.clear()
        await jb._cec_cmd("select")
        jb.menu.sel["main"] = [x[2][0] for x in jb.menu.entries()].index("checklens")
        await jb._cec_cmd("select")
        assert jb.menu.view()["note"].startswith("Längen prüfen")
        await jb.menu.job.task
        assert jb.menu.view()["note"] == "2 von 3 Titeln ohne Länge in der HVSC gefunden"
        # "auto": taken at once
        jb.songlengths.custom.clear()
        jb.config["player"]["hvsc_name"] = "auto"
        job = jb.start_job("check", jb.check_list)
        await job.task
        assert job.result["taken"] == 2 and jb.songlengths.lookup(sidfile.md5(A), 1) == 83
    run(tmp_path, t)
