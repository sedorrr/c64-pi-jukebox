"""Cache in the data folder (SQLite): SID header data per file (reading a header over SMB costs a round trip, a big
folder has hundreds) and folder listings for the search through sub-folders."""
import json
import sqlite3
import time


class Catalog:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        # a commit waited for the SD card (FULL), up to half a second in the loop that also passes the stream on
        # (2026-10-23, playlist import). NORMAL with WAL: consistent, at worst the last entries of this cache are lost
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS info (k TEXT PRIMARY KEY, size INT, md5 TEXT, data TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS dirs (k TEXT PRIMARY KEY, at REAL, data TEXT)")
        self.db.commit()
        self._dirty = 0

    @staticmethod
    def key(src, path):
        return "%s\x00%s" % (src, path)

    def get_info(self, src, path, size=None):
        r = self.db.execute("SELECT size, md5, data FROM info WHERE k=?", (self.key(src, path),)).fetchone()
        if not r or (size and r[0] and size != r[0]):
            return None
        d = json.loads(r[2])
        d["md5"] = r[1]
        return d

    def put_info(self, src, path, size, md5, header):
        self.db.execute("INSERT OR REPLACE INTO info VALUES (?,?,?,?)",
                        (self.key(src, path), size, md5, json.dumps(header, ensure_ascii=False)))
        self._commit()

    def get_dir(self, src, path, max_age=None):
        r = self.db.execute("SELECT at, data FROM dirs WHERE k=?", (self.key(src, path),)).fetchone()
        if not r or (max_age is not None and time.time() - r[0] > max_age):
            return None
        return json.loads(r[1])

    def put_dir(self, src, path, entries):
        self.db.execute("INSERT OR REPLACE INTO dirs VALUES (?,?,?)",
                        (self.key(src, path), time.time(), json.dumps(entries, ensure_ascii=False)))
        self._commit()

    def under(self, src, folder, batch=2000):
        """(path, header dict) of every file below a folder, a batch (list) at a time - the caller lets the loop run
        between batches (the whole HVSC has ~60 000)"""
        lo = self.key(src, folder.rstrip("/") + "/")
        hi = lo[:-1] + "0"                                       # "/" + 1: the end of the prefix range
        cur = self.db.execute("SELECT k, md5, data FROM info WHERE k >= ? AND k < ?", (lo, hi))
        n = len(src) + 1
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                return
            out = []
            for k, m, d in rows:
                d = json.loads(d)
                d["md5"] = m
                out.append((k[n:], d))
            yield out

    def forget(self, src):
        lo, hi = src + "\x00", src + "\x01"
        self.db.execute("DELETE FROM info WHERE k >= ? AND k < ?", (lo, hi))
        self.db.execute("DELETE FROM dirs WHERE k >= ? AND k < ?", (lo, hi))
        self.db.commit()

    def _commit(self):
        self._dirty += 1
        if self._dirty >= 50:
            self.flush()

    def flush(self):
        if self._dirty:
            self.db.commit()
            self._dirty = 0

    def close(self):
        self.flush()
        self.db.close()
