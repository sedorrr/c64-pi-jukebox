"""Two languages (i18n.py): German in the code, English from the tables; the setting on the page; the English manual
with the German section ids; every marked text has its English (tools/i18n_check.py)."""
import importlib.util
import os

from c64jukebox import i18n
from c64jukebox.markdown import to_html
from test_web import get, login, post, run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _check():
    spec = importlib.util.spec_from_file_location("i18n_check", os.path.join(ROOT, "tools", "i18n_check.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.check()


def test_tr():
    try:
        i18n._tables["en"] = {"%d Titel": "%d tunes"}
        assert i18n.tr("%d Titel") % 3 == "3 Titel"            # German: as it is
        i18n.set_lang("en")
        assert i18n.tr("%d Titel") % 3 == "3 tunes" and i18n.tr("Unbekannt") == "Unbekannt"
        i18n.set_lang("xx")
        assert i18n.lang() == "de"
    finally:
        i18n.set_lang("de")
        i18n._tables.clear()


def test_heading_ids_of_the_english_manual():
    html, ids = to_html("# Manual\n\n## Updating {#aktualisieren}\n\nSee [above](#aktualisieren).\n", contents="Contents")
    assert ids == {"aktualisieren"} and '<h2 id="h-aktualisieren">Updating</h2>' in html and "<b>Contents</b>" in html


def test_language_setting(tmp_path):
    async def t(c, jb, u64):
        s, h = await get(c, "/api/hello")
        assert h["lang"] == ""                                  # not chosen yet: the page sends its browser's
        await login(c)
        s, r = await post(c, "/api/config", {"lang": "en"})
        assert jb.config["lang"] == "en" and i18n.lang() == "en"
        assert (await get(c, "/api/hello"))[1]["lang"] == "en"
        r = await c.get("/hilfe")
        text = await r.text()
        assert ("Contents" in text) == os.path.exists(os.path.join(ROOT, "docs", "MANUAL.md"))
        jb._hdmi_was_on = True
        jb.run_dir = str(tmp_path)
        jb._hdmi_write()
        import json
        assert json.load(open(os.path.join(jb.run_dir, "hdmi-in.json")))["cfg"]["lang"] == "en"
        await post(c, "/api/config", {"lang": "xx"})            # unknown: stays
        assert jb.config["lang"] == "en"
        await post(c, "/api/config", {"lang": "de"})
        assert i18n.lang() == "de"
    try:
        run(tmp_path, t)
    finally:
        i18n.set_lang("de")


def test_every_text_has_its_english():
    res = _check()
    for name in ("python", "web"):
        r = res[name]
        assert not r["missing"], "%s: %d texts without English, e.g. %r" % (name, len(r["missing"]), r["missing"][:5])
        assert not r["placeholders"], "%s: placeholders differ: %r" % (name, r["placeholders"][:5])
        assert not r["unused"], "%s: unused entries: %r" % (name, r["unused"][:5])
    m = res["manual"]
    assert m["missing_ids"] == [] and m["extra_ids"] == [], m
