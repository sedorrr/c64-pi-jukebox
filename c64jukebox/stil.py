"""STIL.txt of the HVSC (C64Music/DOCUMENTS/STIL.txt): background to a tune - covered from, titles of the sub-tunes,
comments. Like the tooltips of the PC jukebox. Keyed by the HVSC path ("/musicians/h/hubbard_rob/commando.sid");
a file outside an HVSC folder is found through its MD5 and the paths in Songlengths.md5.

Format: an entry starts with a line "/MUSICIANS/.../x.sid", then lines "   FIELD: text" (continued by lines
indented 9 spaces), "(#2)" starts the part for sub-tune 2. Lines starting with "#" are comments."""
import re

from .i18n import tr

# the line of each field (German; tr() here only marks them - German at import - shown as tr(FIELDS[field]) % text)
FIELDS = {"TITLE": tr("Titel: %s"), "ARTIST": tr("Original von: %s"), "NAME": "Name: %s", "AUTHOR": tr("Autor: %s"),
          "COMMENT": "%s"}
FIELD_RE = re.compile(r"^ {0,8}([A-Z]+):\s?(.*)$")         # a field's colon is in column 8; a line with 9 spaces continues the field


def parse(text):
    """-> {hvsc path (lower case): [(sub-tune, field, text), ...]}; sub-tune 0 = the whole file"""
    out, path, tune, cur = {}, None, 0, None
    for line in text.splitlines():
        if not line.strip():
            cur = None
            continue
        if line.startswith("#"):
            continue
        if line.startswith("/"):
            path, tune, cur = line.strip().lower(), 0, None
            out.setdefault(path, [])
            continue
        if path is None:
            continue
        m = re.match(r"^\(#(\d+)\)", line)
        if m:
            tune, cur = int(m.group(1)), None
            continue
        m = FIELD_RE.match(line)
        if m and m.group(1) in FIELDS:
            cur = [tune, m.group(1), m.group(2).strip()]
            out[path].append(cur)
        elif m:
            cur = None                                     # a field we do not show
        elif cur is not None:                              # continuation line
            cur[2] = (cur[2] + " " + line.strip()).strip()
    return {p: [tuple(x) for x in v] for p, v in out.items() if v}


def lines(entries, song):
    """the entries for one sub-tune as short lines for the page and the TV"""
    out = []
    for tune, field, text in entries:
        if tune not in (0, song) or not text:
            continue
        out.append(tr(FIELDS[field]) % text)
    return out[:6]


class Stil:
    def __init__(self):
        self.db = {}

    def load(self, text):
        self.db = parse(text)
        return len(self.db)

    def lookup(self, hvsc_path, song):
        e = self.db.get((hvsc_path or "").lower())
        return lines(e, song) if e else []
