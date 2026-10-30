"""Lists put together from what the jukebox knows ("Listen zusammenstellen"): the whole HVSC from the comment lines of
the loaded Songlengths.md5 (path, MD5, length of every sub-tune - no file needs to be read), the play counts and the
favorites. The HVSC folder is where the Songlengths.md5 was loaded from (<root>/DOCUMENTS/Songlengths.md5)."""
import random
import re

AREAS = ("MUSICIANS", "GAMES", "DEMOS")
PRESETS = {
    "fav": "★ Favoriten",
    "top": "Meistgespielt",
    "never": "Nie gespielt",
    "random": "Zufällige aus der HVSC",
    "short": "Kurze Stücke (unter 2 Minuten)",
    "multi": "Stücke für 2 oder 3 SIDs",
}


def parse_hvsc(text):
    """Songlengths.md5 -> [(path as written, md5, [seconds per sub-tune])], the path with its own capitals (servers
    that care about them)"""
    out, path = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(";"):
            p = s[1:].strip()
            path = p if p.startswith("/") else None
        elif path and len(s) > 33 and s[32] == "=" and re.match(r"^[0-9A-Fa-f]{32}$", s[:32]):
            secs = []
            for t in s[33:].split():
                m = re.match(r"^(\d+):(\d+)", t)
                if m:
                    secs.append(int(m.group(1)) * 60 + int(m.group(2)))
            out.append((path, s[:32].lower(), secs))
            path = None
    return out


def hvsc_root(origin):
    """where Songlengths.md5 came from -> (source id, HVSC folder) or None (uploaded from a PC: no folder known)"""
    if not isinstance(origin, dict) or not origin.get("src") or not origin.get("path"):
        return None
    m = re.match(r"^(.*)/DOCUMENTS/Songlengths\.(md5|txt)$", origin["path"], re.I)
    return (origin["src"], m.group(1)) if m else None


def item(src, root, path):
    return {"src": src, "path": root.rstrip("/") + path, "name": path.rsplit("/", 1)[-1]}


def pick(hvsc, root, f, plays, favs, stil=None, blocked=None, rnd=random):
    """hvsc: parse_hvsc(); root: (src, folder); f: filters; plays: {md5: count}; favs: set of md5; blocked: set of
    md5 never picked -> items.
    Filters: area (one of AREAS or ""), text (in the path), min_s / max_s (length of the first sub-tune),
    sids ("" | "multi"), stil (bool: only with STIL background), never (bool), sort ("random" | "top" | "path"), n."""
    area = str(f.get("area") or "").upper()
    text = str(f.get("text") or "").strip().lower().replace(" ", "_")
    lo, hi = float(f.get("min_s") or 0), float(f.get("max_s") or 0)
    out = []
    for path, md5, secs in hvsc:
        if blocked and md5 in blocked:
            continue
        up = path.upper()
        if area and not up.startswith("/" + area + "/"):
            continue
        if text and text not in path.lower():
            continue
        s = secs[0] if secs else 0
        if lo and s < lo or hi and (not s or s > hi):
            continue
        if f.get("sids") == "multi" and not re.search(r"_[23]SID\.SID$", up):
            continue
        if f.get("stil") and stil is not None and not stil.lookup(path, 1):
            continue
        if f.get("never") and plays.get(md5):
            continue
        if f.get("fav") and md5 not in favs:
            continue
        out.append((path, md5))
    sort = f.get("sort") or "random"
    if sort == "top":
        out = [x for x in out if plays.get(x[1])]
        out.sort(key=lambda x: -plays[x[1]])
    elif sort == "random":
        rnd.shuffle(out)
    else:
        out.sort(key=lambda x: x[0].lower())
    n = max(1, min(1000, int(f.get("n") or 50)))
    return [dict(item(root[0], root[1], p), md5=m) for p, m in out[:n]]


def preset(name):
    """the filters behind a preset button"""
    return {"fav": {"fav": True, "sort": "path", "n": 1000}, "top": {"sort": "top", "n": 50},
            "never": {"never": True, "sort": "random", "n": 50}, "random": {"sort": "random", "n": 50},
            "short": {"max_s": 120, "sort": "random", "n": 50},
            "multi": {"sids": "multi", "sort": "random", "n": 100}}.get(name, {})
