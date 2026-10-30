"""The menu on the TV, worked with the TV's remote (HDMI-CEC): OK or a menu key opens it, up/down choose, OK or right
does it, back or left goes back. Choose the music: a source and its folders (play a folder, with sub-folders, add it,
play from a file on), the presets of "Listen zusammenstellen", the saved lists (which can also be renamed, with a
keyboard on the screen, and deleted); shuffle, repeat, the effect and its automatic change, sound over HDMI and its
volume, the title card; which Ultimate plays (a network search adds more) and that one on (over its WLAN) and off.
Closed after 30 s without a key (60 s at the keyboard). Only the logic - the HDMI service draws what view() returns
(hdmi-in.json "menu")."""
from . import plug, sidfile, smartlist
from .hdmi.modes import MODES
from .sources import SourceError

TIMEOUT_S = 30
KBD_TIMEOUT_S = 60
WINDOW = 9                                       # lines shown at once
VOLUMES = (100, 90, 80, 70, 60, 50, 40, 30, 20, 10)
KBD_ROWS = ["ABCDEFGHIJKLM", "NOPQRSTUVWXYZ", "abcdefghijklm", "nopqrstuvwxyz", "0123456789-_.",
            ["Leer", "←", "Fertig", "Abbrechen"]]
NAME_MAX = 40
TV_HITS = 200                                    # search hits on the TV (the page shows up to 500)
DONE_S = 2.0                                     # a length taken: the note this long, then the menu closes by itself


def c_bt_on(core):
    return bool(core.config["bt"].get("on"))


def onoff(v):
    return "an" if v else "aus"


class TvMenu:
    TITLES = {"main": "C64-Jukebox", "lists": "Musik wählen", "effects": "Effekt am Fernseher",
              "ultimates": "Welches Ultimate spielt"}

    def __init__(self, core, clock):
        self.core, self.clock = core, clock
        self.level = None                        # None = closed, "main", "lists", "effects", "list", "confirm", "kbd"
        self.sel = {"main": 0, "lists": 0, "effects": 0, "list": 0, "confirm": 0, "dir": 0, "ultimates": 0}
        self.at = 0.0
        self.note = ""                           # one line under the items (what just happened, or why not)
        self.version = 0
        self.cur_list = ""                       # the saved list of the "list" level
        self.confirm = None                      # (question, yes label, action, level "Nein" goes back to)
        self.kbd = None                          # {"text", "r", "c", "title", "list"}
        self.close_at = None                     # closes by itself then (after a length was taken)
        self.job = None                          # "Längen prüfen" started here
        self.dir = None                          # the "dir" level: {"src", "label", "path", "items"}
        self.play_job = None                     # a folder being collected for playing
        self.scan_job = None                     # the network search for Ultimates
        self.found = []                          # Ultimates it found that are not in the list yet

    # ---- state
    def is_open(self):
        limit = KBD_TIMEOUT_S if self.level == "kbd" else TIMEOUT_S
        if self.level and (self.clock() - self.at > limit or (self.close_at and self.clock() >= self.close_at)):
            self.close()
        return self.level is not None

    def open(self):
        self.level, self.note, self.at, self.close_at = "main", "", self.clock(), None
        acts = [e[2][0] for e in self.entries()]
        for take in ("nametake", "looptake"):                # a length found: OK, OK takes it (the TV shows the hint)
            if take in acts:
                self.sel["main"] = acts.index(take)
                break
        self.version += 1

    def close(self):
        self.level, self.note, self.confirm, self.kbd, self.close_at = None, "", None, None, None
        self.version += 1

    def _u64_name(self, u=None):
        u = u if u is not None else self.core.config.ultimate()
        return u.get("label") or u.get("addr") or "Ultimate"

    def _busy(self, job):
        return job is not None and not job.done

    def entries_of(self, level):
        old, self.level = self.level, level
        try:
            return self.entries()
        finally:
            self.level = old

    def entries(self):
        """[(label, value, action)] of the current level"""
        c = self.core.config
        h, pl = c["hdmi"], c["player"]
        if self.level == "lists":
            out = [("In der HVSC suchen", "›", ("search",))] if self.core.hvsc_root() else []
            out += [("Ordner: " + (s.get("label") or s["id"]), "›", ("browse", s["id"], "/")) for s in c["sources"]]
            out += [(label, "", ("preset", key)) for key, label in smartlist.PRESETS.items()]
            out += [(p["name"], "%d Titel ›" % p["n"], ("listmenu", p["name"])) for p in self.core.playlists()]
            return out
        if self.level == "list":
            return [("Abspielen", "", ("list", self.cur_list)),
                    ("Hinten anhängen", "", ("listadd", self.cur_list)),
                    ("Umbenennen", "›", ("rename", self.cur_list)),
                    ("Löschen", "›", ("ask", "Liste „%s“ löschen?" % self.cur_list, "Ja, löschen",
                                           ("delete", self.cur_list), "list"))]
        if self.level == "confirm":
            q, yes, act, _ = self.confirm
            return [("Nein", "", ("unconfirm",)), (yes, "", act)]
        if self.level == "effects":
            return [(name, "●" if key == h.get("mode") else "", ("mode", key)) for key, name in MODES.items()]
        if self.level == "dir" and self.dir.get("q") is not None:      # search hits
            d = self.dir
            if not d["items"]:
                return [("Nichts gefunden – andere Wörter", "›", ("search",))]
            return [("Alle %d abspielen" % len(d["items"]), "", ("playhit", 0))] + \
                [((e.get("i") or {}).get("t") or e["n"], (e.get("i") or {}).get("a", ""), ("playhit", k))
                 for k, e in enumerate(d["items"])]
        if self.level == "dir":
            d = self.dir
            out = [("Diesen Ordner abspielen", "", ("playdir", False, "replace")),
                   ("… mit allen Unterordnern", "", ("playdir", True, "replace")),
                   ("Ordner hinten anhängen", "", ("playdir", False, "add"))]
            out += [(e["n"] + "/", "›", ("cd", e["n"])) for e in d["items"] if e["d"]]
            out += [((e.get("i") or {}).get("t") or e["n"], "", ("playfile", e["n"])) for e in d["items"] if not e["d"]]
            return out
        if self.level == "ultimates":
            sel = c["u64_sel"]
            out = [(self._u64_name(u), "●" if i == sel else u.get("addr", ""), ("u64sel", i))
                   for i, u in enumerate(c["ultimates"]) if u.get("addr")]
            out.append(("Im Netzwerk suchen", "%d %%" % (self.scan_job.pct or 0) if self._busy(self.scan_job) else "›",
                        ("u64scan",)))
            out += [("+ " + f["name"], f["ip"], ("u64add", k)) for k, f in enumerate(self.found)]
            return out
        name = self._u64_name()
        p = self.core.player
        lh = getattr(self.core, "loop_hint", None)
        p_loop = lh["len"] if lh and lh["cur"] is p.cur else 0
        nh = getattr(self.core, "name_hint", None)
        p_name = nh["len"] if nh and nh["cur"] is p.cur else 0
        return [
            ("Musik wählen", "›", ("go", "lists")),
            *([("HVSC-Länge übernehmen", "%d:%02d" % divmod(p_name, 60), ("nametake",))] if p_name else []),
            *([("Erkannte Länge übernehmen", "%d:%02d" % divmod(p_loop, 60), ("looptake",))] if p_loop else []),
            *([("Ende hier merken", "Länge unbekannt", ("endhere",))]
              if p.state == "play" and p.cur and not p.cur.get("secs") and not p_loop and not p_name else []),
            *([("Titel nicht mehr spielen", "›", ("ask", "„%s“ überspringen und nicht mehr von selbst spielen?"
                                                  % (p.cur["item"].get("title") or p.cur["item"].get("name", "")),
                                                  "Ja, nicht mehr spielen", ("block",), "main"))] if p.cur else []),
            ("Zufall", onoff(pl.get("shuffle")), ("shuffle",)),
            ("Wiederholen", onoff(pl.get("repeat")), ("repeat",)),
            ("Effekt", MODES.get(h.get("mode"), "?") + " ›", ("go", "effects")),
            ("Effekte automatisch wechseln", onoff(h.get("auto")), ("auto",)),
            ("Ton am Fernseher", onoff(h.get("sound")), ("sound",)),
            *([("Ton über Kopfhörer", onoff(c["bt"].get("on")) + ("" if self.core.bt_conn else " (nicht verbunden)"),
                ("btout",))] if c["bt"].get("mac") else []),
            ("Lautstärke am Fernseher", "%d %%" % int(h.get("volume", 100)), ("volume",)),
            ("Titel einblenden", onoff(h.get("osd", True)), ("osd",)),
            ("Längen prüfen", self._check_value(), ("checklens",)),
            *([("%d HVSC-Längen übernehmen" % len(self.core.list_hits), "", ("listnames",))]
              if getattr(self.core, "list_hits", None) else []),
            ("Ultimate", name + " ›", ("go", "ultimates")),
            ("Ultimate einschalten", name, ("power", True)),
            ("Ultimate ausschalten", name + " ›", ("ask", "„%s“ ausschalten?" % name, "Ja, ausschalten",
                                                      ("power", False), "main")),
            ("Pi ausschalten", "›", ("ask", "Jukebox-Pi ausschalten?" + (" Die Steckdose schaltet danach ab."
                                                                          if plug.configured(c["plug"]) else ""),
                                     "Ja, ausschalten", ("pioff",), "main")),
            ("Schließen", "", ("close",)),
        ]

    def _check_value(self):
        j = self.job
        if j and not j.done:
            return "%d %%" % (j.pct or 0)
        return "›"

    def _jobs_note(self):
        """the jobs started here: their progress in the note line, then their result"""
        self._check_note()
        j = self.play_job
        if j:
            if not j.done:
                self.note = "Ordner wird gelesen: " + (j.progress or "…")
            else:
                self.play_job = None
                if j.error:
                    self.note = j.error
                else:
                    r = j.result or {}
                    self.note = "%d Titel %s" % (r.get("n", 0), "angehängt" if self.level == "dir" and
                                                 getattr(j, "mode", "") == "add" else "– spielt")
                    self.close_at = self.clock() + DONE_S
                self.version += 1
        j = self.scan_job
        if j:
            if not j.done:
                self.note = "Suche im Netzwerk: " + (j.progress or "…")
            else:
                self.scan_job = None
                known = {u.get("addr") for u in self.core.config["ultimates"]}
                self.found = [{"ip": e["ip"], "name": (e.get("u64") or {}).get("product") or e.get("name") or e["ip"]}
                              for e in (j.result or []) if e["ip"] not in known and e.get("alt") not in known]
                n = len(self.found)
                self.note = j.error or ("%s gefunden – mit OK übernehmen" % ("1 neues Ultimate" if n == 1 else
                                                                         "%d neue Ultimates" % n)
                                        if n else "Kein neues Ultimate gefunden")
                self.version += 1

    def _check_note(self):
        """the running check in the note line, its result once it is done"""
        j = self.job
        if not j:
            return
        if not j.done:
            self.note = "Längen prüfen: " + (j.progress or "…")
            return
        self.job = None
        r = j.result or {}
        if j.error:
            self.note = "Längen prüfen: " + j.error
        elif r.get("taken"):
            self.note = "%d Längen aus der HVSC übernommen" % r["taken"]
        elif r.get("found"):
            self.note = "%d von %d Titeln ohne Länge in der HVSC gefunden" % (r["found"], r["nolen"])
        else:
            self.note = "%d Titel ohne Länge, nichts in der HVSC gefunden" % r.get("nolen", 0) if r.get("nolen") \
                else "Alle Titel haben eine Länge"
        self.version += 1

    def view(self):
        """what the HDMI service draws, or None (closed)"""
        if not self.is_open():
            return None
        self._jobs_note()
        if self.level == "kbd":
            k = self.kbd
            return {"kind": "kbd", "title": k["title"], "text": k["text"], "rows": [list(r) for r in KBD_ROWS],
                    "cur": [k["r"], k["c"]], "note": self.note, "v": self.version,
                    "hint": "Pfeile wählen · OK tippt · Zurück löscht"}
        e = self.entries()
        sel = min(self.sel[self.level], max(0, len(e) - 1))
        top = max(0, min(sel - WINDOW // 2, len(e) - WINDOW))
        if self.level == "confirm":
            title = self.confirm[0]
        elif self.level == "list":
            title = "Liste „%s“" % self.cur_list
        elif self.level == "dir" and self.dir.get("q") is not None:
            title = "Suche „%s“" % self.dir["q"]
        elif self.level == "dir":
            title = self.dir["label"] + " " + self.dir["path"]
            if len(title) > 50:
                title = "…" + title[-49:]
        else:
            title = self.TITLES[self.level]
        return {"title": title, "sel": sel - top, "more_up": top > 0,
                "more_down": top + WINDOW < len(e), "note": self.note, "v": self.version,
                "items": [{"l": l, "v": v} for l, v, _ in e[top:top + WINDOW]],
                "hint": "↑↓ wählen · OK · ← zurück"}

    # ---- keys
    async def key(self, cmd):
        """a remote key -> True when the menu took it (closed: only "menu"/"select" open it)"""
        if not self.is_open():
            if cmd in ("menu", "select"):
                self.open()
                return True
            return False
        self.at = self.clock()
        if self.level == "kbd":
            return await self._kbd_key(cmd)
        n = len(self.entries())
        if cmd == "up":
            self.sel[self.level] = (self.sel[self.level] - 1) % max(1, n)
        elif cmd == "down":
            self.sel[self.level] = (self.sel[self.level] + 1) % max(1, n)
        elif cmd in ("select", "right"):
            if n:
                await self._do(self.entries()[min(self.sel[self.level], n - 1)][2])
        elif cmd in ("back", "left"):
            await self._back()
        elif cmd == "menu":
            self.close()
        else:
            return False                         # play, stop, next ... work as without the menu
        self.version += 1
        return True

    async def _back(self):
        self.note = ""
        if self.level == "main":
            self.close()
        elif self.level == "list":
            self.level = "lists"
        elif self.level == "dir" and self.dir.get("q") is not None:     # back to the words, to change them
            self._search_kbd(self.dir["q"])
        elif self.level == "dir":
            path = self.dir["path"].rstrip("/")
            if path:                                     # one folder up
                await self._open_dir(self.dir["src"], path.rsplit("/", 1)[0] or "/", select=path.rsplit("/", 1)[1])
            else:
                self.level, self.dir = "lists", None
        elif self.level == "confirm":
            self.level, self.confirm = self.confirm[3], None
        else:
            self.level = "main"

    def _select_list(self, name):
        names = [p["name"] for p in self.core.playlists()]
        self.sel["lists"] = (1 if self.core.hvsc_root() else 0) + len(self.core.config["sources"]) + \
            len(smartlist.PRESETS) + (names.index(name) if name in names else 0)

    def _search_kbd(self, text=""):
        self.kbd = {"text": text, "r": 0, "c": 0, "title": "In der HVSC suchen (Titel, Komponist, Datei)",
                    "search": True, "back": "lists"}
        self.level = "kbd"

    async def _search_done(self):
        q = self.kbd["text"].strip()
        if len(q) < 2:
            self.note = "Mindestens 2 Zeichen"
            return
        try:
            hits = await self.core.hvsc_find(q, TV_HITS)
        except ValueError as e:
            self.note = str(e)
            return
        root = self.core.hvsc_root()
        self.dir = {"src": root[0], "label": "HVSC", "path": root[1], "q": q, "items": hits}
        self.level, self.kbd, self.sel["dir"] = "dir", None, 0
        self.note = "%d Treffer%s" % (len(hits), " (gekürzt)" if len(hits) >= TV_HITS else "")

    async def _open_dir(self, src, path, select=None):
        """a folder of a source as the "dir" level: sub-folders and SID files (titles of files read before)"""
        try:
            entries = await self.core.ls(src, path)
        except (SourceError, OSError) as e:
            self.note = str(e) or "Ordner nicht lesbar"
            return
        items = [e for e in self.core.annotate(src, path, entries) if e["d"] or sidfile.is_sid_name(e["n"])]
        label = (self.core.config.source(src) or {}).get("label") or src
        self.dir, self.level, self.sel["dir"] = {"src": src, "label": label, "path": path, "items": items}, "dir", 0
        if select:                                       # coming up from a sub-folder: stand on it
            names = [e[2][1] if e[2][0] == "cd" else None for e in self.entries()]
            if select in names:
                self.sel["dir"] = names.index(select)
        if not items:
            self.note = "Keine Ordner oder SID-Dateien hier"

    async def _do(self, a):
        core, kind = self.core, a[0]
        self.note = ""
        h, pl = core.config["hdmi"], core.config["player"]
        if kind == "go":
            self.level = a[1]
            if a[1] == "effects":
                self.sel["effects"] = list(MODES).index(h["mode"]) if h.get("mode") in MODES else 0
        elif kind == "close":
            self.close()
        elif kind == "shuffle":
            await core.player.set_shuffle(not pl.get("shuffle"))
            core.config.save()
        elif kind == "repeat":
            pl["repeat"] = not pl.get("repeat")
            core.config.save()
        elif kind in ("auto", "sound", "osd"):
            core.hdmi_set({kind: not h.get(kind, kind == "osd")})
        elif kind == "btout":
            core.bt_set(not c_bt_on(core))
            name = core.config["bt"].get("name") or "Kopfhörer"
            self.note = ("Ton über „%s“" % name if core.bt_active() else "Ton über „%s“, sobald verbunden" % name) \
                if core.config["bt"].get("on") else "Ton über den Fernseher"
        elif kind == "volume":
            v = int(h.get("volume", 100))
            nxt = [x for x in VOLUMES if x < v]
            core.hdmi_set({"volume": nxt[0] if nxt else VOLUMES[0]})
        elif kind == "mode":
            was_auto = h.get("auto")
            core.hdmi_set({"mode": a[1], "auto": False})
            self.note = "Automatischer Wechsel ist jetzt aus" if was_auto else ""
            self.level = "main"
        elif kind == "preset":
            try:
                n = await core.smart({"preset": a[1]})
                self.note = "%d Titel – %s" % (n, smartlist.PRESETS.get(a[1], ""))
                self.close()
            except ValueError as e:
                self.note = str(e)
        elif kind == "listmenu":
            self.cur_list, self.level, self.sel["list"] = a[1], "list", 0
        elif kind in ("list", "listadd"):
            try:
                items = core.playlist_read(a[1]).get("items", [])
            except ValueError as e:
                self.note = str(e)
                return
            if not items:
                self.note = "Die Liste ist leer"
                return
            if kind == "listadd":
                await core.player.add_items(items)
                core.auto_check()
                self.note = "%d Titel angehängt" % len(items)
                return
            await core.player.set_items(items, None if pl.get("shuffle") else 0, play=True,
                                        source="Liste „%s“" % a[1])
            core.auto_check()
            self.close()
        elif kind == "ask":
            self.confirm = (a[1], a[2], a[3], a[4])
            self.level, self.sel["confirm"] = "confirm", 0          # "Nein" first: OK twice must not delete
        elif kind == "unconfirm":
            await self._back()
        elif kind == "delete":
            try:
                core.playlist_delete(a[1])
                self.note = "Liste „%s“ gelöscht" % a[1]
            except ValueError as e:
                self.note = str(e)
            self.level, self.confirm = "lists", None
            self.sel["lists"] = min(self.sel["lists"], max(0, len(self.entries()) - 1))
        elif kind == "search":
            self._search_kbd(self.dir["q"] if self.level == "dir" and self.dir and self.dir.get("q") else "")
        elif kind == "playhit":
            d = self.dir
            items = [{"src": d["src"], "path": e["p"], "name": e["n"]} for e in d["items"]]
            await core.player.set_items(items, a[1], play=True, source="Suche „%s“" % d["q"])
            core.auto_check()
            self.close()
        elif kind == "rename":
            self.kbd = {"text": a[1][:NAME_MAX], "r": 0, "c": 0, "title": "Neuer Name für „%s“" % a[1], "list": a[1]}
            self.level = "kbd"
        elif kind == "browse":
            await self._open_dir(a[1], a[2])
        elif kind == "cd":
            d = self.dir
            await self._open_dir(d["src"], d["path"].rstrip("/") + "/" + a[1])
        elif kind == "playdir":
            if self._busy(self.play_job):
                self.note = "Der Ordner wird noch gelesen …"
                return
            d = self.dir
            self.play_job = core.start_job("folder", lambda job: core.play_folder(job, d["src"], d["path"], a[1], a[2]))
            self.play_job.mode = a[2]
            self.note = "Ordner wird gelesen …"
        elif kind == "playfile":
            d = self.dir
            files = [e for e in d["items"] if not e["d"]]
            items = [{"src": d["src"], "path": d["path"].rstrip("/") + "/" + e["n"], "name": e["n"]} for e in files]
            start = [e["n"] for e in files].index(a[1])
            await core.player.set_items(items, start, play=True, source="%s %s" % (d["label"], d["path"]))
            core.auto_check()
            self.close()
        elif kind == "u64sel":
            if a[1] == core.config["u64_sel"]:
                self.note = "„%s“ spielt schon" % self._u64_name()
            elif core.player.state in ("play", "pause", "load"):
                name = self._u64_name(core.config["ultimates"][a[1]])
                await self._do(("ask", "Musik stoppen und zu „%s“ wechseln?" % name, "Ja, wechseln",
                                ("u64set", a[1]), "ultimates"))
            else:
                await self._do(("u64set", a[1]))
        elif kind == "u64set":
            await core.select_ultimate(a[1])
            self.level, self.confirm = "ultimates", None
            self.note = "Es spielt jetzt „%s“" % self._u64_name()
        elif kind == "u64scan":
            if not self._busy(self.scan_job):
                self.found = []
                self.scan_job = core.start_job("scan", core.find_ultimates)
            self.note = "Suche im Netzwerk …"
        elif kind == "u64add":
            f = self.found.pop(a[1])
            i = core.add_ultimate(f["ip"], f["name"])
            self.note = "„%s“ übernommen" % f["name"]
            await self._do(("u64sel", i))
        elif kind == "checklens":
            if not (self.job and not self.job.done):
                self.job = core.start_job("check", core.check_list)
            self.note = "Längen prüfen …"
        elif kind == "listnames":
            n = core.take_list_hits()
            self.note = "%d Längen übernommen" % n
            self.close_at = self.clock() + DONE_S
        elif kind == "nametake":
            try:
                secs = core.name_take()
                self.note = "Länge %d:%02d aus der HVSC übernommen" % (secs // 60, secs % 60)
                self.close_at = self.clock() + DONE_S
            except ValueError as e:
                self.note = str(e)
        elif kind == "looptake":
            try:
                secs = core.loop_take()
                self.note = "Länge %d:%02d übernommen – nächstes Stück" % (secs // 60, secs % 60)
                self.close_at = self.clock() + DONE_S
            except ValueError as e:
                self.note = str(e)
        elif kind == "endhere":
            try:
                secs = await core.remember_end()
                self.note = "Länge %d:%02d gemerkt – nächstes Stück" % (secs // 60, secs % 60)
                self.close_at = self.clock() + DONE_S
            except ValueError as e:
                self.note = str(e)
        elif kind == "block":
            try:
                it = await core.block()
                self.note = "„%s“ gesperrt – nächstes Stück" % (it.get("title") or it.get("name", ""))
                self.close_at = self.clock() + DONE_S
            except ValueError as e:
                self.note = str(e)
            self.level, self.confirm = "main", None
        elif kind == "pioff":
            try:
                r = await core.power_off()
                self.note = "Pi wird ausgeschaltet" + (" – Strom aus in %d s" % r["secs"] if r["timer"] else "")
            except ValueError as e:
                self.note = str(e)
            self.level, self.confirm = "main", None
        elif kind == "power":
            try:
                self.note = await core.u64_power(core.config["u64_sel"], a[1])
            except ValueError as e:
                self.note = str(e)
            self.level, self.confirm = "main", None

    async def _kbd_key(self, cmd):
        k = self.kbd
        rows = KBD_ROWS
        if cmd in ("up", "down"):
            k["r"] = (k["r"] + (1 if cmd == "down" else -1)) % len(rows)
            k["c"] = min(k["c"], len(rows[k["r"]]) - 1)
        elif cmd in ("left", "right"):
            k["c"] = (k["c"] + (1 if cmd == "right" else -1)) % len(rows[k["r"]])
        elif cmd == "back":
            if k["text"]:
                k["text"] = k["text"][:-1]
            else:
                self.level, self.kbd = k.get("back", "list"), None
        elif cmd == "select":
            key = rows[k["r"]][k["c"]]
            if key == "Leer":
                k["text"] = (k["text"] + " ")[:NAME_MAX]
            elif key == "←":
                k["text"] = k["text"][:-1]
            elif key == "Abbrechen":
                self.level, self.kbd = k.get("back", "list"), None
            elif key == "Fertig":
                await (self._search_done() if k.get("search") else self._rename_done())
            else:
                k["text"] = (k["text"] + key)[:NAME_MAX]
        elif cmd == "menu":
            self.close()
        else:
            return False
        self.version += 1
        return True

    async def _rename_done(self):
        k = self.kbd
        new = k["text"].strip()
        if new == k["list"]:
            self.level, self.kbd = "list", None
            return
        try:
            new = self.core.playlist_rename(k["list"], new)
        except ValueError as e:
            self.note = str(e)                   # stays at the keyboard: name taken or empty
            return
        self.note = "Umbenannt in „%s“" % new
        self.cur_list, self.level, self.kbd = new, "list", None
        self._select_list(new)
