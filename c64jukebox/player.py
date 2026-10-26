"""The play list and the player: one tune at a time on the selected Ultimate, the next one at the end of the tune
(song length database), after the time limit or after N seconds of silence in the stream.

Items: {"src": source id, "path": path in the source, "name": file name, "song": 0 = the tune's start song,
"title"/"author" when known}. A file on the USB stick of the very Ultimate that plays is started by its path,
every other file is uploaded."""
import asyncio
import json
import os
import random
import time

from . import events, sidfile
from .sources import SourceError, join
from .ultimate import UltimateError

LIST_MAX = 50000
RETRY_S = 2.0


class Player:
    def __init__(self, core, clock=time.monotonic):
        self.core = core
        self.clock = clock
        self.items = []
        self.order = []
        self.pos = -1
        self.state = "stop"            # stop, load, play, pause
        self.cur = None
        self.msg = ""
        self.version = 0
        self.fails = 0
        self.lock = asyncio.Lock()
        self.task = None
        self.retry_at = None
        self.saved_at = 0.0
        self.dirty = False
        self.lver = 0                  # changes of the list or its rows' data (the page reloads its rows)
        self.over = 0                  # changes of which entry has which index (selections on the page go stale)
        self.source = ""               # what the list came from, for the page ("Ordner …", "Liste „…“", …)
        self.stop_after = None         # {"songs": n} or {"until": clock} - stop at the next tune boundary

    # ------------------------------------------------------------ the list
    @property
    def opts(self):
        return self.core.config["player"]

    def _changed(self):
        self.version += 1
        self.lver += 1
        self.over += 1
        self.dirty = True

    def _make_order(self, first=None):
        idx = list(range(len(self.items)))
        if self.opts.get("shuffle"):
            # weighted like the PC program (Efraimidis-Spirakis): weight 1/(1+plays), less played tunes come earlier
            stats = getattr(self.core, "stats", None)
            keys = {}
            for i in idx:
                w = 1.0 / (1 + (stats.count(self.items[i]) if stats else 0))
                keys[i] = random.random() ** (1.0 / w)
            idx.sort(key=lambda i: keys[i], reverse=True)
            if first is not None and first in idx:
                idx.remove(first)
                idx.insert(0, first)
        self.order = idx

    def current_index(self):
        if 0 <= self.pos < len(self.order):
            return self.order[self.pos]
        return -1

    async def set_items(self, items, start=0, play=True, source=None):
        items = [self._clean(i) for i in items][:LIST_MAX]
        async with self.lock:
            self.items = items
            if source is not None:
                self.source = source
            if start is None:                  # shuffled: the weighted order decides where to begin
                self._make_order()
                self.pos = 0 if items else -1
            else:
                start = start if 0 <= start < len(items) else 0
                self._make_order(first=start if items else None)
                self.pos = self.order.index(start) if items else -1
            self.fails = 0
            self._changed()
        if play and items:
            await self.play_pos(self.pos)

    async def add_items(self, items, play_next=False):
        items = [self._clean(i) for i in items][:max(0, LIST_MAX - len(self.items))]
        async with self.lock:
            base = len(self.items)
            self.items.extend(items)
            new = list(range(base, base + len(items)))
            if self.opts.get("shuffle") and not play_next:
                for n in new:
                    self.order.insert(random.randint(max(self.pos + 1, 0), len(self.order)), n)
            elif play_next:
                at = self.pos + 1
                self.order[at:at] = new
            else:
                self.order.extend(new)
            if self.pos < 0 and self.items:
                self.pos = 0 if not play_next else self.order.index(base)
            self._changed()
        return len(items)

    @staticmethod
    def _clean(i):
        out = {"src": str(i.get("src", "")), "path": str(i.get("path", "")),
               "name": str(i.get("name") or i.get("path", "").rsplit("/", 1)[-1])}
        for k in ("title", "author", "year"):
            if i.get(k):
                out[k] = str(i[k])[:64]
        for k in ("song", "songs", "start", "chips"):
            if i.get(k):
                out[k] = int(i[k])
        if i.get("md5"):
            out["md5"] = str(i["md5"]).lower()[:32]
        if isinstance(i.get("sids"), list):
            out["sids"] = [str(a)[:4] for a in i["sids"][:3]]
        return out

    async def remove(self, index):
        await self.remove_many([index])

    async def remove_many(self, indices):
        await self.remove_where(lambda items: indices)

    async def remove_where(self, pick):
        """pick(items) -> indices to remove, called under the lock (so the indices cannot go stale)"""
        async with self.lock:
            rm = {i for i in pick(self.items) if 0 <= i < len(self.items)}
            if not rm:
                return 0
            cur = self.current_index()
            playing = cur in rm
            keep = [i for i in range(len(self.items)) if i not in rm]
            new_of_old = {old: new for new, old in enumerate(keep)}
            newpos = sum(1 for o in self.order[:max(self.pos, 0)] if o not in rm)
            self.items = [self.items[i] for i in keep]
            self.order = [new_of_old[o] for o in self.order if o not in rm]
            if not self.order:
                self.pos = -1
            elif self.pos >= 0:
                self.pos = min(newpos, len(self.order) - 1)
            self._changed()
        if playing and self.state in ("play", "pause", "load"):
            if self.items:
                await self.play_pos(max(self.pos, 0))
            else:
                await self.stop()
        return len(rm)

    async def queue_next(self, indices):
        """"Als Nächstes": these entries come right after the running one (in the given order)"""
        async with self.lock:
            cur = self.current_index()
            want = []
            for i in indices:
                if 0 <= i < len(self.items) and i != cur and i not in want:
                    want.append(i)
            for i in want:
                p = self.order.index(i)
                del self.order[p]
                if p < self.pos:
                    self.pos -= 1
            at = self.pos + 1 if self.pos >= 0 else 0
            self.order[at:at] = want
            self._changed()
            return len(want)

    async def sort(self, key_fn, reverse=False):
        """sort the list itself (like a click on a column header); the running tune stays where it is in the play"""
        async with self.lock:
            cur = self.current_index()
            cur_item = self.items[cur] if cur >= 0 else None
            self.items.sort(key=key_fn, reverse=reverse)
            if self.opts.get("shuffle"):
                ci = next((k for k, it in enumerate(self.items) if it is cur_item), None)
                self._make_order(first=ci)
                self.pos = 0 if ci is not None else -1
            else:
                self.order = list(range(len(self.items)))
                self.pos = next((k for k, it in enumerate(self.items) if it is cur_item), self.pos if self.items else -1)
                if self.pos >= len(self.items):
                    self.pos = len(self.items) - 1
            self._changed()

    def set_item_song(self, index, song):
        if 0 <= index < len(self.items):
            it = self.items[index]
            n = max(1, int(song))
            if it.get("songs"):
                n = min(n, it["songs"])
            it["song"] = n
            self._changed()

    async def move(self, i, j):
        async with self.lock:
            n = len(self.items)
            if not (0 <= i < n and 0 <= j < n) or i == j:
                return
            cur = self.current_index()
            item = self.items.pop(i)
            self.items.insert(j, item)
            remap = list(range(n))
            remap.pop(i)
            remap.insert(j, i)
            new_of_old = {old: new for new, old in enumerate(remap)}
            self.order = [new_of_old[o] for o in self.order]
            if not self.opts.get("shuffle"):
                self.order = list(range(n))
                if cur >= 0:
                    self.pos = new_of_old[cur]
            self._changed()

    async def clear(self):
        await self.stop()
        async with self.lock:
            self.items, self.order, self.pos = [], [], -1
            self._changed()

    async def set_shuffle(self, on):
        async with self.lock:
            self.opts["shuffle"] = bool(on)
            cur = self.current_index()
            self._make_order(first=cur if cur >= 0 else None)
            if cur >= 0:
                self.pos = self.order.index(cur)
            self._changed()
        self.core.config.save()

    def listing(self, start=0, n=200):
        start = max(0, start)
        return {"total": len(self.items), "start": start, "cur": self.current_index(), "version": self.version,
                "items": self.items[start:start + n]}

    # ------------------------------------------------------------ playing
    def elapsed(self):
        c = self.cur
        if not c:
            return 0.0
        end = c["paused_at"] if c["paused_at"] is not None else self.clock()
        return max(0.0, end - c["t0"] - c["paused"])

    async def play_index(self, index, song=None):
        if 0 <= index < len(self.items):
            await self.play_pos(self.order.index(index), song)

    async def play_pos(self, pos, song=None):
        async with self.lock:
            if not 0 <= pos < len(self.order):
                return
            self.pos = pos
            self.retry_at = None
            await self._start(song)

    async def _start(self, song=None):
        """lock held"""
        item = self.items[self.order[self.pos]]
        self.state, self.msg = "load", ""
        self.version += 1
        core = self.core
        try:
            u = core.ultimate()
            src = core.sources.get(item["src"])
            direct = core.sources.on_ultimate(item["src"], core.config["u64_sel"])
            data = await src.read(item["path"])
            head = sidfile.parse_header(data)
            if head is None:
                raise SourceError("Keine SID-Datei: " + item["name"])
            md5 = sidfile.md5(data)
            core.remember_info(item["src"], item["path"], len(data), md5, head)
            if song is None:
                song = item.get("song") or head["start"]
            song = min(max(1, int(song)), head["songs"])
            await core.sid_prepare(u, head["sids"])            # a SID socket to the address the tune needs?
            if direct:
                await u.play_path(join(src.root, item["path"]), song)
            else:
                await u.play_data(item["name"], data, song)
        except (SourceError, UltimateError) as e:
            self.fails += 1
            self.msg = str(e)
            self.cur = None
            if self.fails >= min(5, max(1, len(self.items))):
                self.state = "stop"
                self.msg += " – Wiedergabe angehalten"
                await core.sid_release()                   # a socket switched for the failed tune goes back
                core.notifier.stopped()
            else:
                self.retry_at = self.clock() + RETRY_S
            return
        self.fails = 0
        secs = core.songlengths.lookup(md5, song)
        info = dict(head, name=item["name"], path=item["path"], src=item["src"], md5=md5, song=song)
        item.setdefault("title", head["title"])
        item.setdefault("author", head["author"])
        old_key = None if item.get("md5") else "path:%s:%s" % (item["src"], item["path"])
        item.update(md5=md5, songs=head["songs"], start=head["start"], chips=head["chips"], sids=head["sids"],
                    year=head.get("year", ""))
        stats = getattr(core, "stats", None)
        if stats:
            if old_key:
                stats.migrate(old_key, item)
            stats.played(item)
        hist = getattr(core, "history", None)
        if hist:
            hist.add(item, song, secs)
        self.lver += 1
        self.cur = {"item": item, "info": info, "song": song, "secs": secs, "t0": self.clock(), "paused": 0.0,
                    "paused_at": None}
        self.state = "play"
        events.log("Titel: %s (Lied %d, %s)" % (item["name"], song, "%d s" % secs if secs else "Länge unbekannt"))
        core.hub.mark_loud()
        core.notifier.playing(info, secs, self.elapsed)

    async def discover(self, by_author=False):
        """like the PC program: a never played tune (else one of the least played); or a tune of an author
        nobody has listened to yet"""
        stats = getattr(self.core, "stats", None)
        async with self.lock:
            if not self.items or not stats:
                return None
            pick = self._discover_pick(stats, by_author)
            self.pos = self.order.index(pick)
            self.retry_at = None
            await self._start()
            return pick

    def _discover_pick(self, stats, by_author):
        counts = [stats.count(it) for it in self.items]
        cand = list(range(len(self.items)))
        if by_author:
            per = {}
            for i, it in enumerate(self.items):
                a = (it.get("author") or "").strip()
                if a.lower() in ("", "<?>", "unknown", "n/a"):
                    continue
                per.setdefault(a, []).append(i)
            if per:
                least = min(sum(counts[i] for i in v) for v in per.values())
                authors = [a for a, v in per.items() if sum(counts[i] for i in v) == least]
                cand = per[random.choice(authors)]
        low = min(counts[i] for i in cand)
        return random.choice([i for i in cand if counts[i] == low])

    async def next(self):
        async with self.lock:
            await self._advance(manual=True)

    async def prev(self):
        async with self.lock:
            if not self.order:
                return
            if self.cur and self.elapsed() > 5:
                await self._start(self.cur["song"])           # like a CD player: back to the start first
                return
            self.pos = (self.pos - 1) % len(self.order)
            await self._start()

    async def _advance(self, manual=False):
        """lock held"""
        if not self.order:
            return
        c = self.cur
        if not manual and self.stop_after:
            sa = self.stop_after
            if "songs" in sa:
                sa["songs"] -= 1
                if sa["songs"] <= 0:
                    self.stop_after = None
                    await self._stop("Gestoppt (Stopp nach Titeln)")
                    return
            elif self.clock() >= sa.get("until", 0):
                self.stop_after = None
                await self._stop("Gestoppt (Stopp nach Zeit)")
                return
        if not manual and c and self.opts.get("subsongs") == "all" and c["song"] < c["info"]["songs"]:
            await self._start(c["song"] + 1)
            return
        if self.pos + 1 >= len(self.order):
            if not self.opts.get("repeat", True) and not manual:
                await self._stop("Ende der Liste")
                return
            if self.opts.get("shuffle"):
                self._make_order()
            self.pos = 0
        else:
            self.pos += 1
        await self._start()

    async def set_song(self, song):
        async with self.lock:
            if self.cur:
                await self._start(song)

    async def pause(self):
        async with self.lock:
            if self.state != "play":
                return
            try:
                await self.core.ultimate().machine("pause")
            except UltimateError as e:
                self.msg = str(e)
                return
            self.cur["paused_at"] = self.clock()
            self.state = "pause"
            self.version += 1

    async def resume(self):
        async with self.lock:
            if self.state != "pause":
                return
            try:
                await self.core.ultimate().machine("resume")
            except UltimateError as e:
                self.msg = str(e)
                return
            c = self.cur
            c["paused"] += self.clock() - c["paused_at"]
            c["paused_at"] = None
            self.state = "play"
            self.core.hub.mark_loud()
            self.version += 1

    async def play(self):
        """the play button: resume, or start the current entry"""
        if self.state == "pause":
            await self.resume()
        elif self.state == "stop" and self.items:
            await self.play_pos(max(self.pos, 0))

    async def stop(self):
        async with self.lock:
            await self._stop("")

    async def _stop(self, why):
        was = self.state != "stop"
        self.state, self.cur, self.retry_at = "stop", None, None
        self.msg = why
        self.version += 1
        if was:
            try:
                await self.core.ultimate().machine("reset")
            except UltimateError as e:
                self.msg = str(e)
        await self.core.sid_release()                          # a switched SID socket back to its address
        self.core.notifier.stopped()

    # ------------------------------------------------------------ the clock (called a few times a second)
    def due(self):
        """what tick would do: None or a reason"""
        now = self.clock()
        if self.state == "load" and self.retry_at is not None and now >= self.retry_at:
            return "retry"
        if self.state != "play" or not self.cur:
            return None
        el = self.elapsed()
        secs = self.cur["secs"]
        o = self.opts
        if secs:
            if el >= secs + 1:
                return "end"
        else:
            limit = float(o.get("limit_min") or 0) * 60
            if limit and el >= limit:
                return "limit"
        if o.get("silence") and el > 3:
            s = self.core.hub.silent_for()
            if s is not None and s >= float(o.get("silence_s") or 5):
                return "silence"
        return None

    def tick(self):
        if self.task and not self.task.done():
            return
        why = self.due()
        if why:
            self.task = asyncio.get_running_loop().create_task(self._on_due(why))

    async def _on_due(self, why):
        async with self.lock:
            if self.due() != why:
                return
            events.log("weiter: %s nach %.0f s" % ({"end": "Titelende", "limit": "Zeitgrenze", "silence": "Stille",
                                                      "retry": "neuer Versuch"}.get(why, why), self.elapsed()))
            if why == "retry":
                self.retry_at = None
                await self._advance(manual=True)
            else:
                await self._advance()

    # ------------------------------------------------------------ state for the page, kept over a restart
    def state_json(self):
        c = self.cur
        d = {"state": self.state, "msg": self.msg, "version": self.version, "lver": self.lver, "total": len(self.items),
             "index": self.current_index(), "pos": self.pos, "source": self.source}
        sa = self.stop_after
        if sa:
            d["stop_after"] = {"songs": sa["songs"]} if "songs" in sa else {"min": max(0, int((sa["until"] - self.clock()) / 60 + 0.99))}
        if c:
            i = c["info"]
            d["now"] = {k: i.get(k) for k in ("title", "author", "released", "year", "songs", "start", "chips", "sids",
                                              "models", "name", "path", "src", "md5", "type")}
            d["now"]["song"] = c["song"]
            d["now"]["secs"] = c["secs"]
            # where it really ends: its length, or else the time limit (the "default" length) - the TV fades out there
            d["now"]["end"] = c["secs"] or (float(self.opts.get("limit_min") or 0) * 60 or None)
            h = getattr(self.core, "loop_hint", None)              # a repeat found (loopwatch.py), not taken yet
            if h and h["cur"] is c:
                d["now"]["loop"] = h["len"]
            h = getattr(self.core, "name_hint", None)              # the same tune by name in the HVSC
            if h and h["cur"] is c:
                d["now"]["hvsc"] = {"len": h["len"], "path": h["path"]}
            d["el"] = round(self.elapsed(), 1)
        d["over"] = self.over
        return d

    def save_to(self, path):
        data = {"items": self.items, "index": self.current_index(), "source": self.source}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        self.dirty = False

    def load_from(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        self.items = [self._clean(i) for i in d.get("items", [])][:LIST_MAX]
        self.source = d.get("source", "")
        idx = d.get("index", 0)
        self._make_order(first=idx if 0 <= idx < len(self.items) else None)
        self.pos = self.order.index(idx) if 0 <= idx < len(self.items) else (0 if self.items else -1)
        self.version += 1
