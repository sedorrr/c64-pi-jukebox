"""Play while the Ultimate is off: the jukebox offers to switch it on (Wake-on-WiFi) or to play on another Ultimate
that is on - asked on the page, in the TV menu and on the touch display at once. Switching the jukebox off asks
whether the Ultimate goes off too (when it answers and can switch itself off)."""
import asyncio
import os

from c64jukebox import core as core_mod, wol
from c64jukebox.display import Display
from c64jukebox.tft import TftScreen
from fakes import free_port
from test_plug import setup
from test_web import get, login, post, run

MAC = "12:34:56:78:9A:BC"


def dead():
    """an address where nothing answers (refused at once)"""
    return "127.0.0.1:%d" % free_port(1)


def items():
    return [{"src": "pi", "path": "/b.sid", "name": "b.sid"}, {"src": "pi", "path": "/Hubbard/Commando.sid",
                                                              "name": "Commando.sid"}]


def plays(u64):
    return u64.find("POST", "/v1/runners:sidplay")


async def until(cond, secs=3.0):
    for _ in range(int(secs / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


def test_play_offers_to_wake_or_another_ultimate(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        us = jb.config.data["ultimates"]
        us[:] = [{"label": "Elite II", "addr": dead(), "pw": "", "wmac": MAC},
                 {"label": "C64U", "addr": u64.addr, "pw": "netz"}]
        await jb.player.set_items(items(), 0, play=True)
        p = jb.player
        assert p.state == "stop" and "einschalten?" in p.msg and not plays(u64)
        s, st = await get(c, "/api/state")
        a = st["ask"]
        assert a["kind"] == "wake" and a["q"].startswith("„Elite II“ ist aus")
        assert [(o["k"], o["l"]) for o in a["opts"]] == [
            ("wake:0", "„Elite II“ einschalten und abspielen"), ("use:1", "Stattdessen „C64U“ (ist an)"),
            ("cancel", "Abbrechen")]
        s, r = await post(c, "/api/ask", {"id": "nope", "k": "use:1"})
        assert s == 400 and "nicht mehr offen" in r["msg"]
        s, r = await post(c, "/api/ask", {"id": a["id"], "k": "use:1"})       # the other one is on: plays there
        assert s == 200 and r["msg"] == "Es spielt jetzt „C64U“"
        assert jb.config["u64_sel"] == 1 and p.state == "play" and len(plays(u64)) == 1
        assert p.cur["item"]["name"] == "b.sid" and jb.state()["ask"] is None
        s, r = await post(c, "/api/ask", {"id": a["id"], "k": "cancel"})      # answered once only
        assert s == 400
    run(tmp_path, t)


def test_wake_then_play(tmp_path, monkeypatch):
    async def t(c, jb, u64):
        monkeypatch.setattr(core_mod, "WAKE_POLL_S", 0.05)
        monkeypatch.setattr(core_mod, "WAKE_SETTLE_S", 0)
        us = jb.config.data["ultimates"]
        us[:] = [{"label": "Elite II", "addr": dead(), "pw": "netz", "wmac": MAC}]
        sent = []

        monkeypatch.setattr(wol, "send", lambda mac, towards=None: sent.append(mac) or ["x:9"])
        p = jb.player
        await p.set_items(items(), 1, play=True)
        a = jb.ask_state()
        assert [o["k"] for o in a["opts"]] == ["wake:0", "cancel"]        # no other Ultimate
        jb.menu.ask_show()                            # the same question in the TV menu: the first answer counts
        assert jb.menu.level == "ask" and jb.menu.view()["title"] == a["q"] and jb.menu.view()["sel"] == 0
        await jb.menu.key("select")
        assert sent == [MAC] and "wird eingeschaltet" in p.msg
        # the menu goes at once (no main menu for a moment); while it wakes, a box with a spinner says what happens
        assert jb.menu.level is None and jb.busy["text"] == "„Elite II“ wird eingeschaltet …"
        assert jb.menu.view() is None                 # not in the first 0.4 s (a quick check must not flash)
        jb.busy["since"] -= 1
        v = jb.menu.view()
        assert v == {"kind": "busy", "title": "„Elite II“ wird eingeschaltet …", "spin": True, "hint": "Bitte warten …"}
        assert jb.state()["busy"] == {"text": "„Elite II“ wird eingeschaltet …", "spin": True}
        await p.play()                                # Play again meanwhile: no second question
        assert jb.ask is None and "wird eingeschaltet" in p.msg
        us[0]["addr"] = u64.addr                      # it comes up (at its address)
        assert await until(lambda: p.state == "play")
        assert p.cur["item"]["name"] == "Commando.sid" and len(plays(u64)) == 1     # the entry Play was pressed for
        assert "wach" in jb.power_msg and jb.busy is None and jb.menu.view() is None
    run(tmp_path, t)


def test_no_mac_known_and_cancel(tmp_path):
    async def t(c, jb, u64):
        jb.config.data["ultimates"][:] = [{"label": "Elite II", "addr": dead(), "pw": ""}]
        await jb.player.set_items(items(), 0, play=True)
        a = jb.ask_state()
        assert "WLAN-MAC" in a["q"] and [o["k"] for o in a["opts"]] == ["cancel"]
        assert await jb.ask_answer("cancel") == "" and jb.ask is None and jb.player.state == "stop"
        jb.ask_open("wake", "?", [("cancel", "Abbrechen", False)])
        jb.ask["until"] = jb.clock() - 1               # nobody answered within a minute: gone
        assert jb.ask_state() is None
    run(tmp_path, t)


def test_timer_wakes_without_asking(tmp_path, monkeypatch):
    async def t(c, jb, u64):
        jb.config.data["ultimates"][:] = [{"label": "Elite II", "addr": dead(), "pw": "", "wmac": MAC}]
        sent = []
        monkeypatch.setattr(wol, "send", lambda mac, towards=None: sent.append(mac) or ["x:9"])
        await jb.player.set_items(items(), 0, play=False)
        await jb.schedule_run({"id": "a", "do": "play", "time": "08:00"})
        assert sent == [MAC] and jb.ask is None and "wird eingeschaltet" in jb.player.msg
        assert not jb._auto_wake
    run(tmp_path, t)


def test_switch_off_with_the_ultimate_from_the_page(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        fake, mark = setup(jb, tmp_path)
        s, r = await get(c, "/api/power/u64")
        assert r["name"] == "Elite II"
        u64.product = "Ultimate-II+"                   # a 1541 Ultimate cartridge cannot switch itself off
        assert (await get(c, "/api/power/u64"))[1]["name"] == ""
        u64.product = "C64 Ultimate"
        s, r = await post(c, "/api/power/off", {"u64": True})
        assert s == 200 and u64.find("PUT", "/v1/machine:poweroff") and jb.powering_off
    run(tmp_path, t)


def test_switch_off_only_the_jukebox_and_ultimate_off(tmp_path):
    async def t(c, jb, u64):
        fake, mark = setup(jb, tmp_path)
        await u64.stop()                               # the Ultimate does not answer: no question, as before
        assert await jb.u64_can_off() == "" and await jb.off_ask() is False and jb.ask is None
    run(tmp_path, t)


def test_question_on_the_touch_display():
    scr = TftScreen()
    st = {"ask": {"id": "1", "kind": "off", "q": "Jukebox ausschalten – „Elite II“ auch?",
                  "opts": [{"k": "both", "l": "Jukebox und „Elite II“ ausschalten", "red": True},
                           {"k": "pi", "l": "Nur die Jukebox ausschalten", "red": True},
                           {"k": "cancel", "l": "Abbrechen", "red": False}]}}
    img = scr.render(st, "ask")
    assert img.size == (320, 240)
    img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "tft_ask.png"))
    btns = scr.buttons("ask")
    assert [w for _, w in btns] == ["ask:both", "ask:pi", "ask:cancel"]
    assert all(b[3] - b[1] >= 40 and b[2] - b[0] >= 300 for b, _ in btns)       # big enough for a finger
    assert all(btns[k][0][3] < btns[k + 1][0][1] for k in range(2)) and btns[-1][0][3] <= 240
    got = []
    d = Display(lambda: {}, on_touch=got.append)
    d.tft, d.screen, d.page = True, scr, "ask"
    assert d.page_for(dict(st, player={"state": "play"})) == "ask"            # before every other page
    (x0, y0, x1, y1), _ = btns[1]
    assert d.tap((x0 + x1) // 2, (y0 + y1) // 2) == "ask:pi" and got == ["ask:pi"]
    assert d.tap(5, 40) is None                                               # beside the buttons: nothing


def test_switched_off_then_play_asks(tmp_path):
    """found on the device (2026-11-06): Ultimate switched off in the TV menu, Play right after did not ask - its answer
    to "poweroff" counted as "on" for 20 s"""
    async def t(c, jb, u64):
        jb.config.data["ultimates"][0]["wmac"] = MAC
        await jb.player.set_items(items(), 0, play=True)
        assert jb.player.state == "play"
        await jb.u64_power(0, False)
        assert u64.find("PUT", "/v1/machine:poweroff") and jb.player.state == "stop"
        await u64.stop()                               # it is off now
        await jb.player.play()
        assert jb.player.state == "stop" and jb.ask_state()["kind"] == "wake"
    run(tmp_path, t)


def test_busy_box_on_the_tv_and_the_touch_display():
    """the box on the TV: text, eight dots going round (the lit one moves), "Bitte warten …"; without spin only the
    text. The touch display: the text in the line under the title."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from c64jukebox.hdmi.app import MenuView
    from c64jukebox.hdmi.screen import SoftScreen
    pygame.init()
    mv = MenuView()
    m = {"kind": "busy", "title": "„Elite II“ wird eingeschaltet …", "spin": True, "hint": "Bitte warten …"}
    a = mv.items(m, now=10.0)[0]
    b = mv.items(m, now=10.2)[0]
    assert b.version == a.version + 1                  # the spinner moved: drawn again
    assert mv.items(m, now=10.21)[0].version == b.version   # same eighth of a second: not again
    scr = SoftScreen()
    scr.present(mv.items(m, now=10.4))
    pygame.image.save(scr.snapshot(), os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "hdmi_busy.png"))
    still = mv.items(dict(m, spin=False, hint=""), now=11)[0]
    assert still.rect.h < a.rect.h                    # no dots: a lower box
    img = TftScreen().render({"player": {"state": "stop", "total": 3},
                              "busy": {"text": "„Elite II“ wird eingeschaltet …", "spin": True}}, "play")
    img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "tft_busy.png"))
