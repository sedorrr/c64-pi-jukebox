"""Play counts, favorites and blocked tunes, keyed like the PC program Ultimate64 SID Player: "md5:<lowercase md5>" for a file
whose MD5 is known, otherwise "path:<source>:<path>". The PC program's play_counts.json ({key: n}) and
favorites.json ({key: {path, title, author}}) can be merged in. A blocked tune ("nicht mehr spielen") is skipped when
the list moves on by itself, in shuffle, discover and the lists put together from the HVSC; chosen by hand it plays."""
import json
import os
import time


def item_key(item):
    m = item.get("md5")
    return "md5:" + m.lower() if m else "path:%s:%s" % (item.get("src", ""), item.get("path", ""))


class Stats:
    def __init__(self, path):
        self.path = path
        self.plays = {}
        self.fav = {}
        self.block = {}
        self._dirty = False
        self._saved = 0.0
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            self.plays = {k: int(v) for k, v in (d.get("plays") or {}).items()}
            self.fav = dict(d.get("fav") or {})
            self.block = dict(d.get("block") or {})
        except (OSError, ValueError):
            pass

    def save(self, force=False):
        if not self._dirty or (not force and time.monotonic() - self._saved < 5):
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"plays": self.plays, "fav": self.fav, "block": self.block}, f, ensure_ascii=False)
        os.replace(tmp, self.path)
        self._dirty = False
        self._saved = time.monotonic()

    def count(self, item):
        return self.plays.get(item_key(item), 0)

    def played(self, item):
        k = item_key(item)
        self.plays[k] = self.plays.get(k, 0) + 1
        self._dirty = True

    def is_fav(self, item):
        return item_key(item) in self.fav

    @staticmethod
    def _entry(item):
        return {"src": item.get("src", ""), "path": item.get("path", ""), "title": item.get("title", ""),
                "author": item.get("author", ""), "name": item.get("name", "")}

    def toggle_fav(self, item):
        k = item_key(item)
        if k in self.fav:
            del self.fav[k]
        else:
            self.fav[k] = self._entry(item)
            self._unblock_item(item)                  # a star takes the tune off the blocked list
        self._dirty = True
        return k in self.fav

    def keys_of(self, item):
        ks = [item_key(item)]
        if item.get("md5") and item.get("path"):      # blocked before its MD5 was known
            ks.append("path:%s:%s" % (item.get("src", ""), item.get("path", "")))
        return ks

    def is_blocked(self, item):
        return bool(self.block) and any(k in self.block for k in self.keys_of(item))

    def block_item(self, item):
        """never again on its own; a favourite loses its star"""
        k = item_key(item)
        self.block[k] = dict(self._entry(item), at=int(time.time()))
        self.fav.pop(k, None)
        self._dirty = True
        return k

    def _unblock_item(self, item):
        for k in self.keys_of(item):
            if self.block.pop(k, None) is not None:
                self._dirty = True

    def unblock(self, key):
        if self.block.pop(key, None) is None:
            return False
        self._dirty = True
        return True

    def blocked_md5s(self):
        return {k[4:] for k in self.block if k.startswith("md5:")}

    def blocked_list(self):
        """newest first, for the page"""
        return [dict(v, key=k) for k, v in sorted(self.block.items(), key=lambda x: -int(x[1].get("at") or 0))]

    def merge_pc(self, plays=None, favorites=None):
        """the PC program's files: counts are added up, favorites joined (their PC paths only for the titles)"""
        n_p = n_f = 0
        for k, v in (plays or {}).items():
            if isinstance(k, str) and k.startswith("md5:"):
                try:
                    self.plays[k.lower()] = self.plays.get(k.lower(), 0) + int(v)
                    n_p += 1
                except (TypeError, ValueError):
                    pass
        if isinstance(favorites, list):                          # old PC format: a list of keys
            favorites = {k: {} for k in favorites if isinstance(k, str)}
        for k, v in (favorites or {}).items():
            if isinstance(k, str) and k.startswith("md5:") and k.lower() not in self.fav:
                v = v if isinstance(v, dict) else {}
                self.fav[k.lower()] = {"src": "", "path": "", "pc_path": v.get("path", ""), "title": v.get("title", ""),
                                       "author": v.get("author", ""), "name": os.path.basename(v.get("path", "") or "")}
                n_f += 1
        self._dirty = True
        return n_p, n_f

    def migrate(self, old_key, item):
        """an entry counted or starred before its MD5 was known moves to the MD5 key"""
        new = item_key(item)
        if old_key == new:
            return
        if old_key in self.plays:
            self.plays[new] = self.plays.get(new, 0) + self.plays.pop(old_key)
            self._dirty = True
        if old_key in self.fav:
            self.fav.setdefault(new, self.fav.pop(old_key))
            self._dirty = True
        if old_key in self.block:
            self.block.setdefault(new, self.block.pop(old_key))
            self._dirty = True

    def backup(self):
        return {"plays": self.plays, "fav": self.fav, "block": self.block}

    def restore(self, d):
        if isinstance(d, dict):
            self.plays = {k: int(v) for k, v in (d.get("plays") or {}).items()}
            self.fav = dict(d.get("fav") or {})
            self.block = dict(d.get("block") or {})
            self._dirty = True
            self.save(force=True)


class History:
    """the last tunes played, newest last (tab "Listen": "Zuletzt gespielt") - also what played while nobody looked"""
    MAX = 100

    def __init__(self, path):
        self.path = path
        self.items = []
        self._dirty = False
        try:
            with open(path, encoding="utf-8") as f:
                self.items = [x for x in json.load(f) if isinstance(x, dict)][-self.MAX:]
        except (OSError, ValueError, TypeError):
            pass

    def add(self, item, song, secs=None, now=None):
        now = time.time() if now is None else now
        e = {"t": round(now), "src": item.get("src", ""), "path": item.get("path", ""), "name": item.get("name", ""),
             "title": item.get("title", ""), "author": item.get("author", ""), "song": song, "songs": item.get("songs", 0)}
        if item.get("md5"):
            e["md5"] = item["md5"]
        if secs:
            e["secs"] = secs
        last = self.items[-1] if self.items else None
        if last and (last["src"], last["path"], last["song"]) == (e["src"], e["path"], song) and now - last["t"] < 10:
            self.items[-1] = e                     # the same tune again at once (a retry, "back"): one line
        else:
            self.items.append(e)
        del self.items[:-self.MAX]
        self._dirty = True

    def clear(self):
        self.items = []
        self._dirty = True

    def save(self):
        if not self._dirty:
            return
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False)
        os.replace(self.path + ".tmp", self.path)
        self._dirty = False
