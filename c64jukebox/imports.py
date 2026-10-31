"""Play lists of the PC program "Ultimate64 SID Player / Ultimate64-JukeBox" (v1.82):

- Shared playlist (.json, "Export Playlist for Sharing"): {"format": "ultimate64_sid_player_shared_playlist",
  "version": 1, "name", "songs": [{"md5", "filename", "title", "author"}]}. Import exactly like the PC program:
  index the chosen folder with all sub-folders first (MD5 of every .sid, first hit wins; file name in lower case,
  first hit wins), then per song: by_md5[md5] or by_filename[filename.lower()]. Duplicates stay, title and author are
  not used for matching, missing songs are listed as "Titel - Autor" (or the title, the file name, "(unnamed)").
- .u64pl: "# Ultimate64 SID Player Playlist", then one absolute PC path or "u64://<ip>/<path>" per line; empty lines
  and "#" lines are skipped. The PC program only keeps paths that exist on that PC - here the paths of the Mac/PC
  never exist, so they are looked for in a chosen folder: the longest matching end of the path ("H/Hubbard_Rob/
  Commando.sid" before "Commando.sid"), then the file name alone. u64:// entries go to the Ultimate with that address.

The MD5 of a file comes from the cache, from the HVSC song length file (its comment lines name the HVSC path of every
MD5 - a whole HVSC needs no file read) or, for the rest, from reading the file."""
import os
import re

from .i18n import tr

SHARED_FORMAT = "ultimate64_sid_player_shared_playlist"
U64PL_HEADER = "# Ultimate64 SID Player Playlist"
HVSC_TOPS = ("/MUSICIANS/", "/GAMES/", "/DEMOS/")
SUFFIX_MAX = 5


def hvsc_paths(text):
    """{"/musicians/h/hubbard_rob/commando.sid": md5} from the comment lines of Songlengths.md5"""
    out, path = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(";"):
            p = s[1:].strip()
            path = p.lower() if p.startswith("/") else None
        elif path and len(s) > 33 and s[32] == "=" and re.match(r"^[0-9A-Fa-f]{32}$", s[:32]):
            out[path] = s[:32].lower()
            path = None
        elif re.match(r"^[0-9A-Fa-f]{32}$", s) and path:          # old format: md5 alone on its line
            out[path] = s.lower()
            path = None
    return out


def hvsc_rel(path):
    """the HVSC part of a path: ".../C64Music/MUSICIANS/H/x.sid" -> "/musicians/h/x.sid" (or None)"""
    for top in HVSC_TOPS:
        k = path.upper().find(top)
        if k >= 0:
            return path[k:].lower()
    return None


class FolderIndex:
    """all .sid files below one folder of one source, in walk order (folders in name order, depth first)"""

    def __init__(self):
        self.paths = []
        self.by_md5 = {}
        self.by_filename = {}
        self.by_suffix = {}            # "h/hubbard_rob/commando.sid" (2..SUFFIX_MAX parts) -> first path

    def add(self, path):
        self.paths.append(path)
        name = path.rsplit("/", 1)[-1].lower()
        self.by_filename.setdefault(name, path)
        parts = path.lower().strip("/").split("/")
        for k in range(2, min(SUFFIX_MAX, len(parts)) + 1):
            self.by_suffix.setdefault("/".join(parts[-k:]), path)

    def add_md5(self, path, md5):
        if md5:
            self.by_md5.setdefault(md5.lower(), path)


def parse_shared(data):
    """-> (name, songs) or ValueError with a message for the page"""
    if not isinstance(data, dict) or data.get("format") != SHARED_FORMAT:
        raise ValueError(tr("Das ist keine geteilte Playlist des Ultimate64 SID Player"))
    songs = [s for s in (data.get("songs") or []) if isinstance(s, dict)]
    if not songs:
        raise ValueError(tr("Die Playlist enthält keine Titel"))
    return str(data.get("name") or tr("Importierte Playlist"))[:60], songs


def missing_label(entry):
    t, a = (entry.get("title") or "").strip(), (entry.get("author") or "").strip()
    if t and a:
        return "%s - %s" % (t, a)
    return t or entry.get("filename") or "(unnamed)"


def match_shared(songs, index):
    """PC rules: md5 first (exact string), then the file name in lower case. -> (paths in order, missing labels)"""
    found, missing = [], []
    for e in songs:
        p = index.by_md5.get(e.get("md5", "")) or index.by_filename.get((e.get("filename") or "").lower())
        if p:
            found.append(p)
        else:
            missing.append(missing_label(e))
    return found, missing


def parse_u64pl(text):
    """the entries of a .u64pl (PC rules: empty lines and lines with "#" at the start are skipped)"""
    out = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line and not line.startswith("#"):
            out.append(line)
    return out


def match_u64pl_path(pc_path, index):
    """a path of the PC (Windows or Unix) -> path in the folder: the longest matching end, then the file name"""
    parts = [p for p in pc_path.replace("\\", "/").split("/") if p]
    if not parts:
        return None
    for k in range(min(SUFFIX_MAX, len(parts)), 1, -1):
        p = index.by_suffix.get("/".join(parts[-k:]).lower())
        if p:
            return p
    return index.by_filename.get(parts[-1].lower())


def parse_device_path(entry):
    """"u64://192.168.1.168/USB2/x.sid" -> ("192.168.1.168", "/USB2/x.sid") or None"""
    if not entry.lower().startswith("u64://"):
        return None
    rest = entry[6:]
    k = rest.find("/")
    if k <= 0:
        return None
    return rest[:k], rest[k:]


def export_shared(name, items):
    """items with md5 -> the PC program's shared playlist; those without MD5 are left out (and counted)"""
    songs, skipped = [], 0
    for it in items:
        if not it.get("md5"):
            skipped += 1
            continue
        songs.append({"md5": it["md5"].lower(), "filename": it.get("name") or os.path.basename(it.get("path", "")),
                      "title": it.get("title", ""), "author": it.get("author", "")})
    return {"format": SHARED_FORMAT, "version": 1, "name": name or "playlist", "songs": songs}, skipped


def user_lengths_text(db):
    """the PC program's user_songlengths.txt from {md5 bytes: (secs, ...)}"""
    lines = ["# Ultimate64 SID Player - user-defined song lengths", "# Format: <md5>=<seconds> (one entry per line)"]
    for k in sorted(db, key=lambda b: b.hex()):
        t = db[k]
        if len(t) == 1:
            lines.append("%s=%d" % (k.hex(), t[0]))
        else:
            lines.append("%s=%s" % (k.hex(), " ".join("%d:%02d" % (s // 60, s % 60) for s in t)))
    return "\n".join(lines) + "\n"
