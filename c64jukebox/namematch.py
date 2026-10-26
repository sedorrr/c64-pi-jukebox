"""A song length for a file the length databases do not know by its MD5, found by its name: the same tune often lies
in a party or CSDB folder in another version than in the HVSC (the HVSC fixes header texts when it takes a tune in -
"Laszlo Vincze" became "László Vincze", 2026-10-24: Verkuerzte_Ausfahrt.sid). Same name, but a different MD5.

The HVSC paths (comment lines of Songlengths.md5) are looked up by the file name and by the title from the SID header
(spelled the HVSC way: no umlauts, no accents, only letters and digits). A candidate counts when its composer folder
(MUSICIANS/V/Vincenzo) shares a word with the header's author ("Laszlo Vincze (vincenzo)"); outside MUSICIANS (GAMES,
DEMOS: no composer folder) only a single candidate whose name matches the title. Another version may be another
length - so the result is only ever a suggestion."""
import re
import unicodedata

GERMAN = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})
NO_NAME = {"", "unknown", "untitled", "tune", "music", "song", "intro", "title", "sid"}


def norm(text):
    """ "Verkürzte Ausfahrt" / "verkuerzte_ausfahrt.sid" -> "verkuerzteausfahrt" """
    t = re.sub(r"\.sid$", "", str(text or ""), flags=re.I).translate(GERMAN)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", t.lower())


def words(text):
    t = str(text or "").translate(GERMAN)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)).lower()
    return {w for w in re.split(r"[^a-z0-9]+", t) if len(w) >= 3}


def composer_folder(path):
    """ "/musicians/v/vincenzo/verkuerzte_ausfahrt.sid" -> {"vincenzo"}; None outside MUSICIANS"""
    p = path.strip("/").split("/")
    if len(p) >= 4 and p[0] == "musicians":
        return words(p[2].replace("_", " "))
    return None


class NameIndex:
    def __init__(self, hvsc_paths):
        """hvsc_paths: {"/musicians/v/vincenzo/verkuerzte_ausfahrt.sid": md5} (imports.hvsc_paths)"""
        self.by_name = {}
        for path, md5 in hvsc_paths.items():
            self.add(path, md5)

    def add(self, path, md5):
        k = norm(path.rsplit("/", 1)[-1])
        if k not in NO_NAME:
            self.by_name.setdefault(k, []).append((path, md5))

    def find(self, filename, title, author):
        """-> (hvsc path, md5) of the one fitting HVSC file, or None"""
        k_file, k_title = norm(filename.rsplit("/", 1)[-1]), norm(title)
        keys = {k for k in (k_file, k_title) if k not in NO_NAME}
        cands = {c for k in keys for c in self.by_name.get(k, [])}
        if not cands:
            return None
        aw = words(author) - {"unknown"}
        good = []
        for path, md5 in cands:
            folder = composer_folder(path)
            if folder is not None:
                if aw & folder:
                    good.append((path, md5))
            elif len(cands) == 1 and k_title and norm(path.rsplit("/", 1)[-1]) == k_title:
                good.append((path, md5))
        if len({m for _, m in good}) == 1:
            return sorted(good)[0]
        return None
