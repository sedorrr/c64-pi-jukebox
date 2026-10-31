"""The language of the jukebox (setting "lang": "de" or "en"; empty = not chosen yet, German until the page sets the
browser's language). German is the source text in the code: tr("Musik wählen") returns it as it is, or the English
text from lang/en.json (German text -> English text; "%s"/"%d" placeholders stay, formatted after the lookup:
tr("%d Titel") % n). The page has its own table (web/lang-en.json, T() in app.js). tools/i18n_check.py lists texts
without a translation. Also imported by the HDMI service (hdmi/app.py, the language comes in its cfg)."""
import json
import os

LANGS = ("de", "en")
HERE = os.path.dirname(os.path.abspath(__file__))
_state = {"lang": "de"}
_tables = {}


def table(lang):
    """German -> lang for one language (read once)"""
    if lang not in _tables:
        try:
            with open(os.path.join(HERE, "lang", lang + ".json"), encoding="utf-8") as f:
                _tables[lang] = json.load(f)
        except (OSError, ValueError):
            _tables[lang] = {}
    return _tables[lang]


def set_lang(lang):
    _state["lang"] = lang if lang in LANGS else "de"


def lang():
    return _state["lang"]


def tr(text):
    """text (German) in the chosen language; a text without a translation stays German"""
    if _state["lang"] == "de" or not text:
        return text
    return table(_state["lang"]).get(text) or text      # an empty entry (still to be filled in) stays German
