"""The menu on the TV: opened with OK / a menu key, worked with the arrows, loads lists, switches shuffle / repeat /
effect / sound; closed it leaves the arrows to tunes and effects; without the HDMI picture OK plays/stops as before.
Preview of the drawn menu: tests/web/hdmi_menu.png."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame                                                           # noqa: E402

from c64jukebox import tvmenu                                           # noqa: E402
from c64jukebox.hdmi.app import MenuView                                # noqa: E402
from c64jukebox.hdmi.screen import SoftScreen                           # noqa: E402
from test_player import run                                             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def test_menu(tmp_path):
    async def t(e):
        jb, p = e.jb, e.jb.player
        jb.config.data["hdmi"].update(on=True, mode="bars", auto=True, sound=False, volume=100)
        jb.playlist_write("Feierabend", e.items("b.sid", "a.sid"))
        # closed: the arrows as before (up = next effect), OK opens the menu
        await jb._cec_cmd("up")
        assert jb.config["hdmi"]["mode"] != "bars" and jb.menu.view() is None
        jb.config.data["hdmi"]["mode"] = "bars"
        await jb._cec_cmd("select")
        v = jb.menu.view()
        assert v["title"] == "C64-Jukebox" and v["sel"] == 0 and v["items"][0]["l"] == "Musik wählen"
        assert {"l": "Zufall", "v": "aus"} in v["items"]
        # shuffle on, repeat on
        await jb._cec_cmd("down")
        await jb._cec_cmd("select")
        assert jb.config["player"]["shuffle"] is True and jb.menu.view()["items"][1]["v"] == "an"
        rep = bool(jb.config["player"].get("repeat"))
        await jb._cec_cmd("down")
        await jb._cec_cmd("right")
        assert jb.config["player"]["repeat"] is (not rep)
        # volume steps down, sound on
        for _ in range(4):
            await jb._cec_cmd("down")                       # Effekt, automatisch, Ton, Lautstärke
        await jb._cec_cmd("select")
        assert jb.config["hdmi"]["volume"] == 90
        await jb._cec_cmd("up")
        await jb._cec_cmd("select")
        assert jb.config["hdmi"]["sound"] is True
        # effect: the effects level starts at the current one; choosing switches the automatic change off
        await jb._cec_cmd("up")
        await jb._cec_cmd("up")
        await jb._cec_cmd("select")
        v = jb.menu.view()
        assert v["title"] == "Effekt am Fernseher" and v["items"][v["sel"]]["v"] == "●"
        await jb._cec_cmd("down")
        await jb._cec_cmd("select")
        assert jb.config["hdmi"]["mode"] == "net" and jb.config["hdmi"]["auto"] is False
        v = jb.menu.view()
        assert v["title"] == "C64-Jukebox" and "Wechsel" in v["note"]
        # play, stop ... still work with the menu open
        await jb._cec_cmd("stop")
        assert jb.menu.view() is not None
        # load a saved list: plays, menu closes
        for _ in range(3):
            await jb._cec_cmd("up")
        await jb._cec_cmd("select")
        v = jb.menu.view()
        assert v["title"] == "Musik wählen" and v["items"][0]["l"] == "Ordner: Pi"
        assert v["items"][2]["l"] == "★ Favoriten"                       # the sources first, then the presets
        names = [x["l"] for x in v["items"]]
        assert "Feierabend" in names or v["more_down"]
        for _ in range(2 + len(tvmenu.smartlist.PRESETS)):
            await jb._cec_cmd("down")
        assert jb.menu.view()["items"][jb.menu.view()["sel"]]["l"] == "Feierabend"
        await jb._cec_cmd("select")                         # a saved list: its own little menu
        v = jb.menu.view()
        assert v["title"] == "Liste \u201eFeierabend\u201c" and [x["l"] for x in v["items"]] == \
            ["Abspielen", "Hinten anhängen", "Umbenennen", "Löschen"]
        await jb._cec_cmd("select")                         # Abspielen
        await e.step(1)
        assert jb.menu.view() is None and p.source == "Liste „Feierabend“" and len(p.items) == 2
        assert p.state in ("play", "load")
        # back closes; 30 s without a key closes too
        await jb._cec_cmd("menu")
        await jb._cec_cmd("back")
        assert jb.menu.view() is None
        await jb._cec_cmd("select")
        e.now[0] += 31
        assert jb.menu.view() is None
        # no picture on the TV: OK plays / stops as before
        jb.config.data["hdmi"]["on"] = False
        await jb._cec_cmd("select")
        assert jb.menu.view() is None and p.state == "stop"
    run(tmp_path, t)


def test_menu_drawing():
    pygame.init()
    m = {"title": "C64-Jukebox", "sel": 1, "more_up": False, "more_down": True, "note": "Automatischer Wechsel ist jetzt aus",
         "items": [{"l": "Liste laden", "v": "›"}, {"l": "Zufall", "v": "an"}, {"l": "Wiederholen", "v": "aus"},
                   {"l": "Effekt", "v": "Milkdrop ›"}, {"l": "Ton am Fernseher", "v": "an"}],
         "hint": "↑↓ wählen · OK · ← zurück"}
    mv = MenuView()
    it = mv.items(m)
    assert len(it) == 1 and it[0].key == "menu" and mv.items(m)[0].version == it[0].version   # drawn once
    assert mv.items(dict(m, sel=2))[0].version == it[0].version + 1 and mv.items(None) == []
    scr = SoftScreen()
    scr.present(mv.items(m))
    pygame.image.save(scr.snapshot(), os.path.join(HERE, "web", "hdmi_menu.png"))


def test_long_question_wraps():
    """the block question names the tune: it wraps inside the box instead of running over its edge"""
    pygame.init()
    q = "„Rave-N - Jussi Hannula (Juzdie) - Extended Remix“ überspringen und nicht mehr von selbst spielen?"
    m = {"title": q, "sel": 0, "more_up": False, "more_down": False, "note": "", "hint": "↑↓ wählen · OK · ← zurück",
         "items": [{"l": "Nein", "v": ""}, {"l": "Ja, nicht mehr spielen", "v": ""}]}
    mv = MenuView()
    short = mv.items(dict(m, title="Kurz?"))[0].surf.get_height()
    s = mv.items(m)[0].surf
    assert s.get_width() == MenuView.W and s.get_height() >= short + MenuView.TITLE_LINE      # two or three lines
    from c64jukebox.hdmi.app import wrap
    assert all(mv.f_title.size(x)[0] <= MenuView.W - 100 for x in wrap(q, mv.f_title, MenuView.W - 100, 3))
    scr = SoftScreen()
    scr.present(mv.items(m))
    pygame.image.save(scr.snapshot(), os.path.join(HERE, "web", "hdmi_menu_ask.png"))


def test_sub_tune_keys_only_with_sub_tunes(tmp_path):
    async def t(e):
        jb, p = e.jb, e.jb.player
        await p.set_items(e.items("a.sid", "b.sid"), 0, play=True)
        await e.step(1)
        n = len(e.plays())
        await jb._cec_cmd("song_next")                      # Alpha has one sub-tune: not started again
        assert len(e.plays()) == n and p.cur["song"] == 1
        await p.next()
        await e.step(1)
        assert p.cur["info"]["songs"] == 2
        song = p.cur["song"]
        await jb._cec_cmd("song_next")
        await e.step(1)
        assert p.cur["song"] == song % 2 + 1
    run(tmp_path, t)


def test_rename_and_delete_on_the_tv(tmp_path):
    async def t(e):
        jb = e.jb
        jb.config.data["hdmi"]["on"] = True
        jb.playlist_write("Abend", e.items("a.sid"))
        jb.playlist_write("Party", e.items("b.sid"))
        jb.config.data["schedule"] = [{"id": "e1", "on": True, "days": [0], "time": "18:00", "do": "play", "list": "Abend", "tv": False}]

        async def keys(*ks):
            for k in ks:
                await jb._cec_cmd(k)
        await keys("select", "select")                      # menu, "Musik wählen"
        n = 2 + len(tvmenu.smartlist.PRESETS)               # the two sources, the presets
        await keys(*["down"] * n, "select")                 # "Abend" (sorted first)
        assert jb.menu.view()["title"] == "Liste \u201eAbend\u201c"
        await keys("down", "down", "select")                # Umbenennen: the keyboard, the old name in it
        v = jb.menu.view()
        assert v["kind"] == "kbd" and v["text"] == "Abend" and v["cur"] == [0, 0]
        await keys("back", "back", "back", "back", "back")  # Zurück deletes ...
        assert jb.menu.view()["text"] == ""
        await keys("select", "right", "right", "right", "select")   # "A", "D"
        await keys("down", "down", "left", "left", "select")   # small letters, column 4 ("d") -> two left: "b"
        assert jb.menu.view()["text"] == "ADb"
        await keys("down", "down", "down", "right", "select")  # bottom row, column 2 ("\u2190") -> right: Fertig
        v = jb.menu.view()
        assert v["title"] == "Liste \u201eADb\u201c" and "Umbenannt" in v["note"]
        assert [p["name"] for p in jb.playlists()] == ["ADb", "Party"]
        assert jb.config["schedule"][0]["list"] == "ADb"     # the timer follows the new name
        # a name that exists already: refused, stays at the keyboard ("Umbenennen" is still chosen)
        await keys("select")
        await keys(*["back"] * 3)
        for ch in "Party":
            r = next(i for i, row in enumerate(tvmenu.KBD_ROWS) if ch in row)
            jb.menu.kbd.update(r=r, c=tvmenu.KBD_ROWS[r].index(ch))
            await keys("select")
        jb.menu.kbd.update(r=5, c=2)
        await keys("select")
        v = jb.menu.view()
        assert v["kind"] == "kbd" and "schon" in v["note"]
        await keys(*["back"] * 6)                           # empty: back leaves the keyboard
        assert jb.menu.view()["title"] == "Liste \u201eADb\u201c"
        # delete: asks first, "Nein" is chosen at first
        await keys("down", "select")
        v = jb.menu.view()
        assert v["title"] == "Liste \u201eADb\u201c löschen?" and v["items"][v["sel"]]["l"] == "Nein"
        await keys("select")                                # Nein
        assert jb.menu.view()["title"] == "Liste \u201eADb\u201c" and len(jb.playlists()) == 2
        await keys("select", "down", "select")              # Löschen, Ja
        v = jb.menu.view()
        assert v["title"] == "Musik wählen" and "gelöscht" in v["note"] and [p["name"] for p in jb.playlists()] == ["Party"]
        assert jb.config["schedule"][0]["on"] is False       # its timer entry is off now (it would play something else)
    run(tmp_path, t)


def test_ultimate_on_and_off_from_the_tv(tmp_path, monkeypatch):
    async def t(e):
        from c64jukebox import wol
        jb = e.jb
        jb.config.data["hdmi"]["on"] = True
        sent = []
        monkeypatch.setattr(wol, "send", lambda mac, towards="", opener=None: sent.append(mac) or ["x:9"])
        await jb._cec_cmd("select")
        names = [e[0] for e in jb.menu.entries()]          # (the window shows 9 of them)
        i_on = names.index("Ultimate einschalten")
        jb.menu.sel["main"] = i_on
        await jb._cec_cmd("select")                         # no WLAN MAC known yet
        assert "WLAN-MAC" in jb.menu.view()["note"] and not sent
        jb.menu.sel["main"] = i_on + 1
        await jb._cec_cmd("select")                         # Ausschalten: asks first
        v = jb.menu.view()
        assert v["title"] == "\u201eElite\u201c ausschalten?"
        await jb._cec_cmd("down")
        await jb._cec_cmd("select")
        assert e.u64.find("PUT", "/v1/machine:poweroff") and "ausgeschaltet" in jb.menu.view()["note"]
        jb.config.data["ultimates"][0]["wmac"] = "12:34:56:78:9A:BC"
        jb.menu.sel["main"] = i_on
        await jb._cec_cmd("select")
        assert sent == ["12:34:56:78:9A:BC"] and "Weckruf" in jb.menu.view()["note"]
        for _ in range(20):                                 # the fake answers at once: awake
            await asyncio.sleep(0.1)
            e.now[0] += 2
            if "wach" in jb.power_msg:
                break
        assert "ist wach" in jb.power_msg
    import asyncio
    run(tmp_path, t)


def test_keyboard_drawing():
    pygame.init()
    m = {"kind": "kbd", "title": "Neuer Name für \u201eAbend\u201c", "text": "Feier", "rows": [list(r) for r in tvmenu.KBD_ROWS],
         "cur": [2, 4], "note": "", "hint": "Pfeile wählen \u00b7 OK tippt \u00b7 Zurück löscht"}
    scr = SoftScreen()
    scr.present(MenuView().items(m))
    pygame.image.save(scr.snapshot(), os.path.join(HERE, "web", "hdmi_keyboard.png"))


def test_remember_end_from_the_tv(tmp_path):
    async def t(e):
        jb, p = e.jb, e.jb.player
        jb.config.data["hdmi"]["on"] = True
        await p.set_items(e.items("b.sid", "a.sid"))
        await e.step(40)
        await jb._cec_cmd("select")
        assert "Ende hier merken" in [x["l"] for x in jb.menu.view()["items"]]        # no length known
        jb.menu.sel["main"] = [x["l"] for x in jb.menu.view()["items"]].index("Ende hier merken")
        await jb._cec_cmd("select")
        assert "0:40 gemerkt" in jb.menu.view()["note"] and p.cur["info"]["title"] == "Alpha"
        jb.set_user_length(p.cur["item"], 90)               # known now: the entry goes
        assert "Ende hier merken" not in [x["l"] for x in jb.menu.view()["items"]]
    run(tmp_path, t)


def test_folders_on_the_tv(tmp_path):
    """Musik wählen -> a source: its folders and SID files; a folder plays (with or without its sub-folders) or is
    added, a file plays the folder from there on; back goes one folder up"""
    async def t(e):
        jb, p = e.jb, e.jb.player
        jb.config.data["hdmi"]["on"] = True

        async def keys(*ks):
            for k in ks:
                await jb._cec_cmd(k)
        await keys("select", "select", "select")             # menu, "Musik wählen", "Ordner: Pi"
        v = jb.menu.view()
        names = [x["l"] for x in v["items"]]
        assert v["title"] == "Pi /" and names[:4] == ["Diesen Ordner abspielen", "… mit allen Unterordnern",
                                                       "Ordner hinten anhängen", "sub/"]
        assert len(names) == 6 and "readme.txt" not in names    # a.sid, b.sid - no other files
        await keys("down", "down", "down", "select")          # into "sub/"
        assert jb.menu.view()["title"] == "Pi /sub"
        await keys("back")                                    # up again, standing on "sub/"
        v = jb.menu.view()
        assert v["title"] == "Pi /" and v["items"][v["sel"]]["l"] == "sub/"
        await keys("up", "up", "select")                      # "… mit allen Unterordnern"
        await jb.menu.play_job.task
        assert "3 Titel" in jb.menu.view()["note"] and len(p.items) == 3 and p.state in ("play", "load")
        e.now[0] += 2.5
        assert jb.menu.view() is None
        # a file: the folder from there on
        jb.menu.sel["main"] = 0
        await keys("select", "select", "select")             # menu, "Musik wählen", "Ordner: Pi"
        last = len(jb.menu.entries()) - 1
        jb.menu.sel["dir"] = last                             # the last file: b.sid
        await keys("select")
        assert jb.menu.view() is None and p.cur["item"]["name"] == "b.sid" and len(p.items) == 2
        assert p.source == "Pi /"
    run(tmp_path, t)


def test_choose_the_ultimate_on_the_tv(tmp_path, monkeypatch):
    """which Ultimate plays: the known ones (the active one marked), switching asks while music plays, a network
    search offers the new ones; on/off follow the choice"""
    async def t(e):
        jb, p = e.jb, e.jb.player
        jb.config.data["hdmi"]["on"] = True
        jb.config.data["ultimates"].append({"label": "Zweiter", "addr": "127.0.0.2", "pw": ""})
        m = jb.menu
        await jb._cec_cmd("select")
        names = [x[0] for x in m.entries()]
        assert ("Ultimate", "Elite ›") == m.entries()[names.index("Ultimate")][:2]
        m.sel["main"] = names.index("Ultimate")
        await jb._cec_cmd("select")
        v = m.view()
        assert v["title"] == "Welches Ultimate spielt" and [(x["l"], x["v"]) for x in v["items"]] == \
            [("Elite", "●"), ("Zweiter", "127.0.0.2"), ("Im Netzwerk suchen", "›")]
        await jb._cec_cmd("down")
        await jb._cec_cmd("select")                          # nothing plays: switched at once
        assert jb.config["u64_sel"] == 1 and "Zweiter" in m.view()["note"]
        assert ("Ultimate einschalten", "Zweiter") == [x for x in m.entries_of("main") if x[0] == "Ultimate einschalten"][0][:2]
        # music plays: asks first
        jb.config.data["u64_sel"] = 0
        await p.set_items(e.items("a.sid"))
        m.sel["ultimates"] = 1
        await jb._cec_cmd("select")
        v = m.view()
        assert v["title"] == "Musik stoppen und zu „Zweiter“ wechseln?" and v["items"][v["sel"]]["l"] == "Nein"
        await jb._cec_cmd("select")                          # Nein
        assert jb.config["u64_sel"] == 0 and m.view()["title"] == "Welches Ultimate spielt"
        # the network search: new ones offered, taken with OK
        await p.stop()

        async def fake_find(job):
            job.progress = "192.168.1.0/24"
            return [{"ip": "127.0.0.3", "name": "u64", "u64": {"product": "C64 Ultimate"}, "alt": ""},
                    {"ip": "127.0.0.2", "name": "zwei", "u64": {"product": "Ultimate 64"}, "alt": ""}]
        monkeypatch.setattr(jb, "find_ultimates", fake_find)
        m.sel["ultimates"] = 2
        await jb._cec_cmd("select")
        await m.scan_job.task
        v = m.view()
        assert "1 neues Ultimate" in v["note"] and v["items"][-1]["l"] == "+ C64 Ultimate"
        m.sel["ultimates"] = len(m.entries()) - 1
        await jb._cec_cmd("select")
        assert jb.config["ultimates"][-1]["addr"] == "127.0.0.3" and jb.config["u64_sel"] == len(jb.config["ultimates"]) - 1
        assert m.found == []
    run(tmp_path, t)


def test_block_from_the_tv(tmp_path):
    async def t(e):
        jb, p = e.jb, e.jb.player
        jb.config.data["hdmi"]["on"] = True
        await p.set_items(e.items("b.sid", "a.sid"))
        await jb._cec_cmd("select")
        names = [x[0] for x in jb.menu.entries()]
        jb.menu.sel["main"] = names.index("Titel nicht mehr spielen")
        await jb._cec_cmd("select")                         # asks first
        assert "nicht mehr von selbst spielen" in jb.menu.view()["title"]
        await jb._cec_cmd("down")
        await jb._cec_cmd("select")
        assert "gesperrt" in jb.menu.view()["note"] and p.cur["info"]["title"] == "Alpha"
        assert jb.stats.is_blocked(p.items[0])
    run(tmp_path, t)
