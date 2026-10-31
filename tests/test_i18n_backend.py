"""English texts of the backend (i18n.py): messages of the web API, of the sources, the timer, the STIL lines and the
smart plug flag that the page tests instead of the German word. Every test goes back to German (the others need it)."""
import time

import pytest

from c64jukebox import i18n, schedule, smartlist, stil
from c64jukebox.cec import KEY_NAMES
from test_plug import ID, setup
from test_web import get, login, post, run


@pytest.fixture
def en():
    i18n.set_lang("en")
    try:
        yield
    finally:
        i18n.set_lang("de")


def test_api_errors_in_english(tmp_path):
    async def t(c, jb, u64):
        i18n.set_lang("en")                                     # the Jukebox set the language of its config
        s, r = await login(c, "wrong")
        assert s == 401 and r["msg"] == "Wrong password"
        await login(c)
        s, r = await post(c, "/api/search", {"q": "a"})
        assert r["msg"] == "Search for at least 2 characters"
        s, r = await get(c, "/api/ls?src=nix&path=/")
        assert r["msg"] == "Source not found"
        fake, mark = setup(jb, tmp_path)                        # a smart plug with a wrong key: it does not answer
        jb.config["plug"].update(ip=fake.ip, id=ID, key="wrong")
        s, r = await post(c, "/api/power/off", {})
        assert not r["ok"] and r["plug"] is True and "check device ID, key and version" in r["msg"]
        assert not jb.powering_off
        s, r = await get(c, "/api/hdmi")
        assert r["modes"]["bars"] != "Balken"                 # the effect names in English (hdmi/modes.py)
    try:
        run(tmp_path, t)
    finally:
        i18n.set_lang("de")


def test_timer_presets_stil_and_remote_keys(en):
    e = {"on": True, "days": [6], "time": "23:00", "do": "stop", "list": "", "tv": True}
    assert schedule.describe(e, time.strptime("2026-11-01 12:00", "%Y-%m-%d %H:%M")) == "Sun 23:00 · Stop (TV off)"
    assert schedule.describe(dict(e, do="play", list="Abend", tv=False)) == "23:00 · Play “Abend”"
    with pytest.raises(ValueError, match="No weekday chosen"):
        schedule.clean([{"time": "8:00", "days": []}])
    assert i18n.tr(smartlist.PRESETS["fav"]) == "★ Favourites"
    st = stil.Stil()
    st.load("/MUSICIANS/X/x.sid\n  TITLE: Commando\n ARTIST: Rob Hubbard\n")
    assert st.lookup("/musicians/x/x.sid", 1) == ["Title: Commando", "Original by: Rob Hubbard"]
    assert i18n.tr(KEY_NAMES[0x01]) == "up" and i18n.tr(KEY_NAMES[0x44]) == "Play"


def test_german_stays_as_it_was():
    assert i18n.lang() == "de"
    e = {"on": True, "days": [0], "time": "18:00", "do": "play", "list": "Feierabend", "tv": True}
    assert schedule.describe(e, time.strptime("2026-11-02 12:00", "%Y-%m-%d %H:%M")) == \
        "Mo 18:00 · Abspielen „Feierabend“ (Fernseher an)"
    assert schedule.describe(dict(e, list="")) == "18:00 · Abspielen (aktuelle Liste) (Fernseher an)"
    st = stil.Stil()
    st.load("/MUSICIANS/X/x.sid\n  TITLE: Commando\n")
    assert st.lookup("/musicians/x/x.sid", 1) == ["Titel: Commando"]
