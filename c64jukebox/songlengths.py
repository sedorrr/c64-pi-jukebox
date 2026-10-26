"""Song lengths: HVSC Songlengths.md5 ("<md5>=m:ss[.mmm] m:ss ..." per sub-song, older files put the md5 alone on
a line and the times on the next) and the file of the Ultimate64 SID Player ("<md5>=<seconds>", one per file).
Own entries win over the HVSC. Same rules as the Pico visualizer: fractions of 500 ms and more count as a second."""
import re

_MD5 = re.compile(r"^\s*([0-9A-Fa-f]{32})\s*(=.*)?$")
_TIME = re.compile(r"^(\d+)(?::(\d+)(?:\.(\d+))?)?")


def parse_times(text):
    """'3:57 1:02.600(G) 45' -> [237, 63, 45]"""
    out = []
    for tok in text.split():
        m = _TIME.match(tok)
        if not m:
            continue
        a = int(m.group(1))
        if m.group(2) is None:
            sec = a
        else:
            sec = a * 60 + int(m.group(2))
            if m.group(3):
                ms = int((m.group(3) + "00")[:3])
                if ms >= 500:
                    sec += 1
        out.append(min(sec, 65535))
    return out


def parse(text):
    """{md5_bytes16: (secs, ...)} - accepts both HVSC formats and the plain seconds file"""
    db = {}
    pending = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in ";#[":
            if s.startswith("["):
                pending = None
            continue
        m = _MD5.match(s)
        if m:
            key = bytes.fromhex(m.group(1))
            if m.group(2):
                t = parse_times(m.group(2)[1:])
                if t:
                    db[key] = tuple(t)
                pending = None
            else:
                pending = key
            continue
        if pending is not None and s.startswith("="):
            t = parse_times(s[1:])
            if t:
                db[pending] = tuple(t)
        pending = None
    return db


class SongLengths:
    def __init__(self):
        self.hvsc = {}
        self.custom = {}

    def load(self, kind, text):
        db = parse(text)
        setattr(self, kind, db)
        return len(db)

    def lookup(self, md5_hex, song=1):
        """seconds of the given sub-song (1-based) or None"""
        try:
            key = bytes.fromhex(md5_hex)
        except (ValueError, TypeError):
            return None
        for db in (self.custom, self.hvsc):
            t = db.get(key)
            if t:
                if len(t) == 1 and db is self.custom:
                    return t[0]           # the PC player's file has one length per file
                if 1 <= song <= len(t):
                    return t[song - 1]
                return None
        return None

    def counts(self):
        return {"hvsc": len(self.hvsc), "custom": len(self.custom)}
