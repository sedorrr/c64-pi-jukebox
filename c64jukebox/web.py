"""Web server: the page (c64jukebox/web), the JSON API under /api and the manual under /hilfe.

Login with the web password gives a signed cookie (30 days, survives restarts; changing the password logs out
every browser). Every POST to /api needs the header "X-C64: 1" - a form on another web site cannot send it.
With trust_local, requests from the Pi itself (127.0.0.1) need no login: administration over SSH, e.g.
    curl -s -H 'X-C64: 1' -d '{"c":"next"}' http://127.0.0.1/api/ctl"""
import asyncio
import hashlib
import hmac
import json
import os
import time

from aiohttp import web

from . import VERSION, bt, events, plug, wol
from .config import MASK, unmask_list
from .hdmi.modes import MODES as HDMI_MODES
from . import i18n
from .i18n import tr
from .markdown import to_html
from .sources import SourceError, norm
from .ultimate import UltimateError

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
MANUAL = os.path.join(os.path.dirname(HERE), "docs", "HANDBUCH.md")
MANUAL_EN = os.path.join(os.path.dirname(HERE), "docs", "MANUAL.md")        # the same section ids (markdown.py)
COOKIE = "c64pi"
COOKIE_DAYS = 30
OPEN = {"/api/login", "/api/logout", "/api/hello"}
# the page's files (no login: the login form needs them; the icons + manifest for "Zum Home-Bildschirm")
STATIC = ("app.js", "style.css", "icon.svg", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "manifest.json",
          "lang-en.json")


def _sign(secret, exp):
    return hmac.new(secret.encode(), str(exp).encode(), hashlib.sha256).hexdigest()


def make_cookie(secret, now=None):
    exp = int((now or time.time()) + COOKIE_DAYS * 86400)
    return "%d.%s" % (exp, _sign(secret, exp))


def cookie_ok(secret, value):
    try:
        exp, sig = value.split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(sig, _sign(secret, int(exp)))
    except (ValueError, AttributeError):
        return False


def ok(**kw):
    return web.json_response(dict({"ok": True}, **kw))


def fail(msg, status=400, **extra):
    return web.json_response(dict(extra, ok=False, msg=msg), status=status)


async def body(req):
    try:
        d = await req.json()
        return d if isinstance(d, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


LOCAL = ("127.0.0.1", "::1")


def make_app(jb, trust_local=False):
    @web.middleware
    async def guard(req, handler):
        p = req.path
        if p.startswith("/api/"):
            jb.web_used()
            local = trust_local and req.remote in LOCAL and "X-Forwarded-For" not in req.headers
            if p not in OPEN and not local and not cookie_ok(jb.config["web"]["secret"], req.cookies.get(COOKIE, "")):
                return fail(tr("Bitte anmelden"), 401)
            if req.method == "POST" and req.headers.get("X-C64") != "1":
                return fail(tr("Anfrage abgelehnt"), 403)
        try:
            return await handler(req)
        except (SourceError, UltimateError, ValueError) as e:
            return fail(str(e))

    app = web.Application(middlewares=[guard], client_max_size=40 * 1024 * 1024)
    r = app.router
    j = jb

    # ---------------------------------------------------------------- page, manual, login
    async def page(req):
        return web.FileResponse(os.path.join(WEB_DIR, "index.html"), headers={"Cache-Control": "no-cache"})

    async def static(req):
        name = req.match_info["name"]
        if name not in STATIC:
            raise web.HTTPNotFound()
        return web.FileResponse(os.path.join(WEB_DIR, name), headers={"Cache-Control": "no-cache"})

    manual_cache = {}

    async def manual(req):
        path = MANUAL_EN if i18n.lang() == "en" and os.path.exists(MANUAL_EN) else MANUAL
        try:
            mt = os.path.getmtime(path)
            if manual_cache.get("key") != (path, mt):
                with open(path, encoding="utf-8") as f:
                    manual_cache["html"], _ = to_html(f.read(), contents=tr("Inhalt"))
                manual_cache["key"] = (path, mt)
            return web.Response(text=manual_cache["html"], content_type="text/html")
        except (OSError, ValueError):
            return web.Response(text="<p>%s</p>" % tr("Handbuch nicht gefunden."), content_type="text/html")

    async def hello(req):
        return ok(login=cookie_ok(j.config["web"]["secret"], req.cookies.get(COOKIE, "")), name=j.config["name"],
                  lang=j.config.data.get("lang", ""))

    async def login(req):
        d = await body(req)
        if not j.config.password_ok(str(d.get("pw", ""))):
            await asyncio.sleep(1.0)
            return fail(tr("Passwort falsch"), 401)
        resp = ok(pwdefault=j.config.password_default())
        resp.set_cookie(COOKIE, make_cookie(j.config["web"]["secret"]), max_age=COOKIE_DAYS * 86400,
                        httponly=True, samesite="Strict")
        return resp

    async def logout(req):
        resp = ok()
        resp.del_cookie(COOKIE)
        return resp

    async def password(req):
        d = await body(req)
        if not j.config.password_ok(str(d.get("old", ""))):
            return fail(tr("Bisheriges Passwort falsch"), 401)
        new = str(d.get("new", ""))
        if len(new) < 4:
            return fail(tr("Das neue Passwort braucht mindestens 4 Zeichen"))
        j.config.set_password(new)
        resp = ok()
        resp.set_cookie(COOKIE, make_cookie(j.config["web"]["secret"]), max_age=COOKIE_DAYS * 86400,
                        httponly=True, samesite="Strict")
        return resp

    # ---------------------------------------------------------------- player
    async def state(req):
        return web.json_response(j.state())

    async def events_get(req):
        return web.json_response({"events": events.recent()})

    async def listing(req):
        return web.json_response(j.player.listing(int(req.query.get("start", 0)), min(int(req.query.get("n", 200)), 1000)))

    async def rows(req):
        q = req.query
        return web.json_response(j.list_rows(int(q.get("start", 0)), min(int(q.get("n", 100)), 500), q.get("q", ""),
                                             q.get("fav") == "1", q.get("ids") == "1"))

    async def list_check(req):
        return ok(job=j.start_job("check", j.check_list).id)

    async def import_shared(req):
        q = req.query
        try:
            data = json.loads(await req.text())
        except ValueError:
            return fail(tr("Die Datei ist kein JSON"))
        src, path = q.get("src", ""), norm(q.get("path", "/"))
        if not j.config.source(src):
            return fail(tr("Bitte einen Suchordner wählen"))
        return ok(job=j.start_job("import", lambda job: j.import_shared(job, data, src, path, q.get("save") != "0")).id)

    async def import_u64pl(req):
        q = req.query
        text = (await req.read()).decode("utf-8", "replace")
        name = (q.get("name") or tr("Importierte Playlist")).rsplit(".", 1)[0][:60]
        src, path = q.get("src", ""), norm(q.get("path", "/"))
        if src and not j.config.source(src):
            return fail(tr("Suchordner unbekannt"))
        return ok(job=j.start_job("import", lambda job: j.import_u64pl(job, text, name, src, path, q.get("save") != "0")).id)

    async def export_shared(req):
        d = await body(req)
        return ok(job=j.start_job("export", lambda job: j.export_shared(job, str(d.get("name", "")))).id)

    async def import_pcstats(req):
        try:
            data = json.loads(await req.text())
        except ValueError:
            return fail(tr("Die Datei ist kein JSON"))
        kind = req.query.get("kind")
        if not isinstance(data, (dict, list)):
            return fail(tr("Unbekanntes Format"))
        if kind == "plays":
            n, _ = j.stats.merge_pc(plays=data)
            msg = tr("%d Zähler übernommen") % n
        else:
            _, n = j.stats.merge_pc(favorites=data)
            msg = tr("%d Favoriten übernommen") % n
        j.stats.save(force=True)
        j.player.lver += 1
        return ok(msg=msg)

    async def sl_export(req):
        from .imports import user_lengths_text
        return web.Response(text=user_lengths_text(j.songlengths.custom), content_type="text/plain", headers={
            "Content-Disposition": 'attachment; filename="user_songlengths.txt"'})

    async def history(req):
        return web.json_response({"ok": True, "now": round(time.time()), "items": j.history.items[::-1]})

    async def history_clear(req):
        await body(req)
        j.history.clear()
        j.history.save()
        return ok()

    async def statistics(req):
        return web.json_response(dict(j.statistics(), ok=True))

    async def hvsc_titles_get(req):
        await j.hvsc_hay()
        run = next((x.id for x in j.jobs.values() if x.kind == "hvsctitles" and not x.done), None)
        return web.json_response(dict(j.hvsc_titles_state(), ok=True, job=run))

    async def hvsc_titles_post(req):
        if not j.hvsc_root():
            return fail(tr("Dafür zuerst die Songlängen der HVSC aus einer Quelle laden (Tab „Dateien“)"))
        return ok(job=j.start_job("hvsctitles", j.hvsc_titles).id)

    async def update_post(req):
        u = await j.update_check()
        if not u:
            return fail(tr("GitHub nicht erreichbar"))
        return ok(ver=u["ver"], newer=u["newer"], installed=VERSION)

    async def update_install_post(req):
        try:
            return ok(**await j.update_install())
        except ValueError as e:
            return fail(str(e))

    async def power_get(req):
        return ok(**await j.power_state())

    async def power_off_post(req):
        d = await body(req)
        try:
            return ok(**await j.power_off(force=bool(d.get("force"))))
        except ValueError as e:                  # plug=True: the plug did not answer (the page offers "anyway")
            return fail(str(e), plug=isinstance(e, plug.PlugError) or isinstance(e.__context__, plug.PlugError))

    async def plug_check_post(req):
        if not plug.configured(j.config["plug"]):
            return fail(tr("Geräte-ID und Schlüssel der Steckdose fehlen"))
        return ok(job=j.start_job("plug", j.plug_check).id)

    async def bt_get(req):
        out = dict(j.bt_status(), ok=True)
        if req.query.get("devices") == "1":
            out["devices"] = await j.bt_devices()
        return web.json_response(out)

    async def bt_post(req):
        d = await body(req)
        act, mac = str(d.get("act", "")), str(d.get("mac", "")).upper()
        if act not in ("scan", "on") and not bt.MAC_RE.match(mac):
            return fail(tr("Gerät fehlt"))
        if not j.bt.present:
            return fail(tr("Bluetooth fehlt auf dem Pi (Pakete bluez und bluez-alsa-utils)"))
        try:
            if act == "scan":
                return ok(job=j.start_job("btscan", j.bt_scan).id)
            if act == "pair":
                return ok(job=j.start_job("btpair", lambda job: j.bt_pair(job, mac)).id)
            if act == "connect":
                await j.bt_connect(mac)
            elif act == "disconnect":
                await j.bt_disconnect(mac)
            elif act == "forget":
                await j.bt_forget(mac)
            elif act == "on":
                j.bt_set(bool(d.get("on")))
            else:
                return fail(tr("unbekannte Aktion"))
        except ValueError as e:
            return fail(str(e))
        return ok(**j.bt_status())

    async def blocked(req):
        return web.json_response({"ok": True, "items": j.stats.blocked_list()})

    async def wlan_get(req):
        return web.json_response(dict(j.net_state(), ok=True))

    async def wlan_post(req):
        d = await body(req)
        act = d.get("action")
        if act not in ("scan", "connect", "forget"):
            return fail(tr("unbekannte Aktion"))
        if act != "scan" and not str(d.get("ssid", "")).strip():
            return fail(tr("WLAN-Name fehlt"))
        if act == "connect" and d.get("pw") and len(str(d["pw"])) < 8:
            return fail(tr("WLAN-Passwörter haben mindestens 8 Zeichen"))
        rid = j.net_request(act, str(d.get("ssid", "")), str(d.get("pw", "")))
        for _ in range(240):                     # the watcher looks every 5 s; connecting takes up to a minute
            await asyncio.sleep(0.5)
            st = j.net_state()
            if (st.get("last") or {}).get("id") == rid:
                return web.json_response(dict(st, ok=st["last"]["ok"], msg=st["last"]["msg"]))
        return fail(tr("Keine Antwort vom Netzwerk-Dienst"))

    async def ctl(req):
        d = await body(req)
        c, p = d.get("c"), j.player
        # commands naming entries by index: refuse when the page's numbering is out of date
        if c in ("remove", "nextup", "fav", "block", "unblock", "setlen", "setsong", "move", "goto") and d.get("over") is not None \
                and int(d["over"]) != p.over:
            return fail(tr("Die Liste hat sich inzwischen geändert – bitte noch einmal"), 409)
        if c == "play":
            await p.play()
        elif c == "pause":
            await (p.resume() if p.state == "pause" else p.pause())
        elif c == "stop":
            await p.stop()
        elif c == "next":
            await p.next()
        elif c == "prev":
            await p.prev()
        elif c == "goto":
            await p.play_index(int(d.get("i", -1)))
        elif c == "song":
            await p.set_song(int(d.get("n", 1)))
        elif c == "remove":
            await p.remove_many([int(x) for x in d.get("is", [d.get("i", -1)])])
        elif c == "nextup":
            n = await p.queue_next([int(x) for x in d.get("is", [])])
            return ok(n=n, player=p.state_json())
        elif c == "sort":
            await j.sort_list(str(d.get("col", "")))
        elif c == "fav":
            i = int(d.get("i", -1))
            if not 0 <= i < len(p.items):
                return fail(tr("Eintrag fehlt"))
            on = j.stats.toggle_fav(await j.with_md5(p.items[i]))
            p.lver += 1
            return ok(fav=on, player=p.state_json())
        elif c == "block":
            try:
                it = await j.block(int(d["i"]) if d.get("i") is not None else None)
            except ValueError as e:
                return fail(str(e))
            return ok(title=it.get("title") or it.get("name", ""), player=p.state_json())
        elif c == "unblock":
            key = str(d.get("key", ""))
            if d.get("i") is not None:                 # a list entry instead of a key of the blocked list
                i = int(d["i"])
                if not 0 <= i < len(p.items):
                    return fail(tr("Eintrag fehlt"))
                key = next((k for k in j.stats.keys_of(p.items[i]) if k in j.stats.block), "")
            if not j.unblock(key):
                return fail(tr("Nicht (mehr) gesperrt"))
        elif c == "setlen":
            i = int(d.get("i", -1))
            if not 0 <= i < len(p.items):
                return fail(tr("Eintrag fehlt"))
            j.set_user_length(p.items[i], d.get("secs"))
        elif c == "endhere":
            await j.remember_end()
        elif c == "looptake":
            j.loop_take()
        elif c == "loopno":
            j.loop_reject()
        elif c == "takenames":
            return ok(n=j.take_list_hits())
        elif c == "nametake":
            j.name_take()
        elif c == "nameno":
            j.name_reject()
        elif c == "setsong":
            i, n = int(d.get("i", -1)), int(d.get("n", 1))
            if i == p.current_index() and p.cur:
                p.set_item_song(i, n)
                await p.set_song(n)
            else:
                p.set_item_song(i, n)
        elif c == "dedupe":
            n = await j.dedupe()
            return ok(n=n, player=p.state_json())
        elif c == "discover":
            if await p.discover(bool(d.get("author"))) is None:
                return fail(tr("Die Liste ist leer"))
        elif c == "stopafter":
            if d.get("songs"):
                p.stop_after = {"songs": max(1, min(int(d["songs"]), 999))}
            elif d.get("minutes"):
                p.stop_after = {"until": p.clock() + max(1, min(float(d["minutes"]), 1440)) * 60}
            else:
                p.stop_after = None
        elif c == "move":
            await p.move(int(d.get("i", -1)), int(d.get("j", -1)))
        elif c == "clear":
            await p.clear()
        elif c == "shuffle":
            await p.set_shuffle(bool(d.get("on")))
        else:
            return fail(tr("unbekannter Befehl"))
        return ok(player=p.state_json())

    async def queue(req):
        d = await body(req)
        items = [i for i in d.get("items", []) if isinstance(i, dict) and i.get("src") and i.get("path")]
        mode = d.get("mode", "replace")
        if mode == "replace":
            await j.player.set_items(items, int(d.get("start", 0)), play=d.get("play", True), source=d.get("source"))
        else:
            n = await j.player.add_items(items, play_next=mode == "next")
            if d.get("play") and j.player.state == "stop":
                await j.player.play_index(len(j.player.items) - n)
        return ok(total=len(j.player.items))

    async def folder(req):
        d = await body(req)
        src, path = str(d.get("src", "")), norm(d.get("path", "/"))
        rec, mode = bool(d.get("recursive")), d.get("mode", "replace")
        shuffle = d.get("shuffle")

        return ok(job=j.start_job("folder", lambda job: j.play_folder(job, src, path, rec, mode, shuffle)).id)

    # ---------------------------------------------------------------- files
    async def sources_get(req):
        return web.json_response({"sources": j.config.public()["sources"]})

    async def sources_set(req):
        d = await body(req)
        new = d.get("sources")
        if not isinstance(new, list):
            return fail(tr("sources fehlt"))
        seen = set()
        for s in new:
            if not isinstance(s, dict) or s.get("kind") not in ("smb", "ftp", "u64", "local"):
                return fail(tr("Ungültige Quelle"))
            if not s.get("id"):
                s["id"] = "s" + os.urandom(3).hex()
            if s["id"] in seen:
                return fail(tr("Doppelte Quelle"))
            seen.add(s["id"])
            s["label"] = str(s.get("label") or s["id"])[:40]
        old_ids = {s["id"] for s in j.config["sources"]}
        unmask_list(new, j.config["sources"], match=("id",))
        j.config.data["sources"] = new
        j.config.save()
        for gone in old_ids - seen:
            j.catalog.forget(gone)
        return ok(sources=j.config.public()["sources"])

    async def source_test(req):
        d = await body(req)
        s = d.get("source") or {}
        if s.get("pw") == MASK and s.get("id"):
            s["pw"] = (j.config.source(s["id"]) or {}).get("pw", "")
        src = j.sources.build_temp(s)
        try:
            entries = await src.list("/")
        finally:
            src.close()
        sids = sum(1 for e in entries if not e["d"] and e["n"].lower().endswith(".sid"))
        dirs = sum(1 for e in entries if e["d"])
        return ok(msg=tr("Verbindung klappt: %d Ordner, %d SIDs im Hauptordner") % (dirs, sids))

    async def ls(req):
        src, path = req.query.get("src", ""), norm(req.query.get("path", "/"))
        entries = await j.ls(src, path)
        return web.json_response({"ok": True, "path": path, "items": j.annotate(src, path, entries)})

    async def info(req):
        d = await body(req)
        src = str(d.get("src", ""))
        out = {}
        for p in (d.get("paths") or [])[:60]:
            try:
                out[p] = await j.info(src, norm(p))
            except SourceError as e:
                out[p] = {"err": str(e)}
        return web.json_response({"ok": True, "info": out})

    async def search(req):
        d = await body(req)
        q = str(d.get("q", "")).strip()
        if len(q) < 2:
            return fail(tr("Mindestens 2 Zeichen suchen"))
        src, path = str(d.get("src", "")), norm(d.get("path", "/"))
        return ok(job=j.start_job("search", lambda job: j.search(job, src, path, q)).id)

    async def job_get(req):
        job = j.jobs.get(req.query.get("id", ""))
        if not job:
            return fail(tr("Auftrag unbekannt"), 404)
        return web.json_response(job.json())

    async def job_cancel(req):
        d = await body(req)
        job = j.jobs.get(str(d.get("id", "")))
        if job and job.task and not job.done:
            job.task.cancel()
        return ok()

    async def netscan(req):
        return ok(job=j.start_job("scan", j.net_scan).id)

    async def shares(req):
        d = await body(req)
        pw = str(d.get("pw", ""))
        if pw == MASK and d.get("id"):
            pw = (j.config.source(d["id"]) or {}).get("pw", "")
        return ok(shares=await j.shares(str(d.get("host", "")).strip(), str(d.get("user", "")), pw))

    async def u64_find(req):
        """Ultimates only (tab "Geräte")"""
        return ok(job=j.start_job("scan", j.find_ultimates).id)

    # ---------------------------------------------------------------- song lengths
    async def sl_load(req):
        d = await body(req)
        src, path, kind = str(d.get("src", "")), norm(d.get("path", "/")), d.get("kind", "hvsc")

        async def run(job):
            job.progress = tr("lese Datei …")
            data = await j.sources.get(src).read(path, 64 << 20)
            job.progress = tr("werte aus …")
            label = "%s: %s" % ((j.config.source(src) or {}).get("label", src), path)
            n = await j.set_songlengths(kind, data, {"src": src, "path": path, "label": label})
            return {"n": n}
        return ok(job=j.start_job("songlengths", run).id)

    async def sl_upload(req):
        kind = req.query.get("kind", "hvsc")
        data = await req.read()
        if kind == "custom" and req.query.get("merge") == "1":
            r = j.merge_custom_lengths(data.decode("latin-1"), req.query.get("overwrite") == "1")
            return ok(n=r["added"] + r["changed"], **r)
        label = tr("hochgeladen: %s") % req.query.get("name", tr("Datei"))[:80]
        n = await j.set_songlengths(kind, data, {"label": label})
        return ok(n=n)

    async def stil_load(req):
        d = await body(req)
        src, path = str(d.get("src", "")), norm(d.get("path", "/"))

        async def run(job):
            job.progress = tr("lese Datei …")
            data = await j.sources.get(src).read(path, 32 << 20)
            job.progress = tr("werte aus …")
            label = "%s: %s" % ((j.config.source(src) or {}).get("label", src), path)
            return {"n": await j.set_stil(data, {"src": src, "path": path, "label": label})}
        return ok(job=j.start_job("stil", run).id)

    async def stil_clear(req):
        j.clear_stil()
        return ok()

    async def sl_clear(req):
        d = await body(req)
        j.clear_songlengths(d.get("kind", "hvsc"))
        return ok()

    # ---------------------------------------------------------------- play lists
    async def pl_list(req):
        return web.json_response({"ok": True, "lists": j.playlists()})

    async def pl_get(req):
        return web.json_response(dict(j.playlist_read(req.query.get("name", "")), ok=True))

    async def pl_save(req):
        d = await body(req)
        name = str(d.get("name", "")).strip()
        items = d.get("items") if isinstance(d.get("items"), list) else j.player.items
        if not items:
            return fail(tr("Die Liste ist leer"))
        j.playlist_write(name, items)
        return ok(lists=j.playlists())

    async def pl_load(req):
        d = await body(req)
        name = str(d.get("name", ""))
        items = j.playlist_read(name).get("items", [])
        if d.get("mode", "replace") == "replace":
            start = None if items and j.config["player"].get("shuffle") else 0
            await j.player.set_items(items, start, play=d.get("play", True), source=tr("Liste „%s“") % name)
            j.auto_check()
        else:
            await j.player.add_items(items)
        return ok(n=len(items))

    async def pl_rename(req):
        d = await body(req)
        new = j.playlist_rename(str(d.get("name", "")), str(d.get("new", "")))
        return ok(name=new, lists=j.playlists())

    async def u64_power(req):
        d = await body(req)
        msg = await j.u64_power(int(d.get("i", j.config["u64_sel"])), bool(d.get("on")))
        return ok(msg=msg)

    async def pl_delete(req):
        d = await body(req)
        j.playlist_delete(str(d.get("name", "")))
        return ok(lists=j.playlists())

    # ---------------------------------------------------------------- settings, devices, backup
    async def config_get(req):
        return web.json_response(j.config.public())

    async def config_set(req):
        d = await body(req)
        c = j.config.data
        if "ultimates" in d:
            u = [x for x in d["ultimates"] if isinstance(x, dict)][:8]
            for x in u:
                x["label"] = str(x.get("label", ""))[:30]
                x["addr"] = str(x.get("addr", "")).strip()[:80]
                if "wmac" in x:                          # the WLAN MAC for waking it (wol.py): "" = unknown
                    raw = str(x.get("wmac") or "").strip()
                    x["wmac"] = wol.normalize_mac(raw) or ""
                    if raw and not x["wmac"]:
                        return fail(tr("Keine gültige WLAN-MAC: %s (12 Hex-Ziffern, z. B. 12:34:56:78:9A:BC)") % raw)
                else:                                    # not sent: keep the one learnt for this address
                    old = next((o for o in c["ultimates"] if o.get("addr") == x["addr"]), {})
                    if old.get("wmac"):
                        x["wmac"] = old["wmac"]
            if not u:
                u = [{"label": "Ultimate", "addr": "", "pw": ""}]
            u = unmask_list(u, c["ultimates"])
            await j.sid_config_change(u)                 # a switched SID socket keeps its way back
            c["ultimates"] = u
            c["u64_sel"] = min(c["u64_sel"], len(u) - 1)
        if "picos" in d:
            p = [x for x in d["picos"] if isinstance(x, dict) and str(x.get("addr", "")).strip()][:16]
            for x in p:
                x["addr"] = str(x["addr"]).strip()[:80]
                x["np"] = x.get("np") if x.get("np") in ("udp", "http", "off") else "udp"
                x["stream"] = bool(x.get("stream", True))
            c["picos"] = unmask_list(p, c["picos"])
            j.apply_targets()
            await j.hub.resolve_all()
        if "pico_news" in d:
            c["pico_news"] = bool(d["pico_news"])
        if "updates" in d:
            c["updates"] = bool(d["updates"])
        if d.get("lang") in i18n.LANGS:
            c["lang"] = d["lang"]
            i18n.set_lang(c["lang"])
        if "plug" in d and isinstance(d["plug"], dict):
            pg, n = c["plug"], d["plug"]
            for k, size in (("ip", 64), ("id", 40)):
                if k in n:
                    pg[k] = str(n[k]).strip()[:size]
            if n.get("key") not in (None, MASK):
                pg["key"] = str(n["key"]).strip()[:64]
            if str(n.get("ver")) in plug.VERSIONS:
                pg["ver"] = str(n["ver"])
            if "off_s" in n:
                pg["off_s"] = max(20, min(int(n["off_s"] or 30), 600))
        if "player" in d and isinstance(d["player"], dict):
            pl = c["player"]
            for k, typ in (("limit_min", float), ("silence", bool), ("silence_s", float), ("repeat", bool),
                           ("sidauto", bool)):
                if k in d["player"]:
                    pl[k] = typ(d["player"][k])
            if d["player"].get("subsongs") in ("start", "all"):
                pl["subsongs"] = d["player"]["subsongs"]
            for k in ("loopfind", "hvsc_name"):
                if d["player"].get(k) in ("off", "suggest", "auto"):
                    pl[k] = d["player"][k]
        if "wlan" in d and isinstance(d["wlan"], dict):
            w = c["wlan"]
            if "ap" in d["wlan"]:
                w["ap"] = bool(d["wlan"]["ap"])
            if "ap_ssid" in d["wlan"]:
                w["ap_ssid"] = str(d["wlan"]["ap_ssid"]).strip()[:32]
            pw = d["wlan"].get("ap_pw")
            if pw is not None and pw != MASK:
                if pw and len(pw) < 8:
                    return fail(tr("Das Passwort des Zugangspunkts braucht mindestens 8 Zeichen"))
                w["ap_pw"] = str(pw)[:63]
        if "display" in d and isinstance(d["display"], dict):
            dd = c["display"]
            if d["display"].get("type") in ("auto", "ssd1306", "sh1106", "tft", "off"):
                dd["type"] = d["display"]["type"]
            if "off_min" in d["display"]:
                dd["off_min"] = max(0, min(int(d["display"]["off_min"]), 1440))
            if "flip" in d["display"]:
                dd["flip"] = bool(d["display"]["flip"])
            if d["display"].get("touch") in ("own", "shared"):
                dd["touch"] = d["display"]["touch"]
            if d["display"].get("dc") in (24, 23, 6):
                dd["dc"] = d["display"]["dc"]
            j.display_reconfigure()
        if "name" in d:
            name = "".join(ch for ch in str(d["name"]).lower() if ch.isalnum() or ch == "-")[:16]
            c["name"] = name or "c64pi"
        j.config.save()
        if "stream" in d and isinstance(d["stream"], dict):
            await j.set_stream(d["stream"].get("on"))
        if "u64_sel" in d:
            await j.select_ultimate(int(d["u64_sel"]))
        return ok(config=j.config.public())

    async def devices(req):
        return web.json_response(j.devices.listing())

    # ---- HDMI output
    async def hdmi_get(req):
        sj = j.hdmi_sync_job
        cache = len([n for n in os.listdir(j.hdmi_cache_dir()) if n.endswith(".jpg")]) \
            if os.path.isdir(j.hdmi_cache_dir()) else 0
        return web.json_response({"cfg": j.config["hdmi"], "modes": {k: tr(v) for k, v in HDMI_MODES.items()},
                                  "status": j.hdmi_status(),
                                  "images": j.hdmi_images(), "src_images": cache,
                                  "sync": sj.json() if sj else None, "news": j.news_state(),
                                  "cec": dict(j.config["cec"], status=j.cec_status())})

    async def party_get(req):
        return web.json_response(dict(j.party_state(), ok=True))

    async def party_post(req):
        return ok(**j.party_set(await body(req)))

    async def smart_get(req):
        return web.json_response(dict(await j.smart_info(), ok=True))

    async def smart_post(req):
        d = await body(req)
        n = await j.smart(d.get("filter") or {}, d.get("mode", "play"), str(d.get("name", ""))[:60])
        return ok(n=n)

    async def schedule_get(req):
        return web.json_response(dict(j.schedule_state(), ok=True))

    async def schedule_post(req):
        d = await body(req)
        return ok(**j.schedule_set(d.get("entries") or []))

    async def cec_post(req):
        d = await body(req)
        if d.get("tv") in ("on", "standby"):
            j.cec_tv(d["tv"])
        else:
            j.cec_set(d)
        return ok(cec=dict(j.config["cec"], status=j.cec_status()))

    async def news_refresh(req):
        t = j.news_refresh()
        await asyncio.wait({t}, timeout=25)
        return ok(news=j.news_state())

    async def hdmi_thumb(req):
        jpg = await j.hdmi_thumb(req.query.get("src", ""), req.query.get("path", ""))
        return web.Response(body=jpg, content_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    async def hdmi_sync(req):
        if not j.config["hdmi"].get("img_src"):
            return fail(tr("Erst eine Quelle für die Bilder wählen"))
        return ok(job=j.hdmi_sync().id)

    async def hdmi_post(req):
        d = await body(req)
        before = j.hdmi_sync_job
        cfg = j.hdmi_set(d)
        sj = j.hdmi_sync_job
        return ok(cfg=cfg, job=sj.id if sj is not before and sj else None)

    async def hdmi_upload(req):
        data = await req.read()
        if not data:
            return fail(tr("Leere Datei"))
        name = await asyncio.get_running_loop().run_in_executor(None, j.hdmi_add_image,
                                                                req.query.get("name", "bild.jpg")[:120], data)
        return ok(name=name, images=j.hdmi_images())

    async def hdmi_delete(req):
        d = await body(req)
        for n in d.get("names") or [d.get("name")]:
            j.hdmi_del_image(str(n or ""))
        return ok(images=j.hdmi_images())

    async def hdmi_image(req):
        return web.FileResponse(j.hdmi_image_path(req.query.get("name", "")),
                                headers={"Cache-Control": "max-age=86400"})

    async def sid_config(req):
        """the SID addresses of the selected Ultimate (like "Check SID Addresses..." of the PC jukebox)"""
        u = j.ultimate()
        cfg = await j.sidaddr.read(u)
        p = j.sidaddr.pending.get(u.addr)
        return web.json_response({"cfg": cfg, "pending": p, "msg": j.sidaddr.msg})

    async def display_calibrate(req):
        if not j.display.calibrate():
            return fail(tr("Kein Touch-Display in Betrieb (Art „2,8″ mit Touch“ wählen und speichern)"))
        return ok()

    async def devices_query(req):
        j.devices.query()
        return ok()

    async def backup(req):
        return web.json_response(j.backup(), headers={
            "Content-Disposition": 'attachment; filename="c64pi-sicherung-%s.json"' % time.strftime("%Y-%m-%d")})

    async def restore(req):
        try:
            d = json.loads(await req.text())
        except ValueError:
            return fail(tr("Die Datei ist keine Sicherung (kein JSON)"))
        n = await j.restore(d)
        return ok(msg=tr("Sicherung eingespielt (%d Wiedergabelisten)") % n)

    r.add_get("/", page)
    r.add_get("/hilfe", manual)
    r.add_get("/{name:[a-z0-9-]+\\.(?:js|css|svg|png|json)}", static)
    r.add_get("/api/hello", hello)
    r.add_post("/api/login", login)
    r.add_post("/api/logout", logout)
    r.add_post("/api/password", password)
    r.add_get("/api/state", state)
    r.add_get("/api/events", events_get)
    r.add_get("/api/list", listing)
    r.add_get("/api/rows", rows)
    r.add_get("/api/wlan", wlan_get)
    r.add_get("/api/statistics", statistics)
    r.add_get("/api/history", history)
    r.add_get("/api/blocked", blocked)
    r.add_get("/api/bt", bt_get)
    r.add_post("/api/bt", bt_post)
    r.add_post("/api/update/check", update_post)
    r.add_post("/api/update/install", update_install_post)
    r.add_get("/api/hvsc/titles", hvsc_titles_get)
    r.add_post("/api/hvsc/titles", hvsc_titles_post)
    r.add_post("/api/cec", cec_post)
    r.add_get("/api/power", power_get)
    r.add_post("/api/power/off", power_off_post)
    r.add_post("/api/plug/check", plug_check_post)
    r.add_get("/api/schedule", schedule_get)
    r.add_get("/api/smart", smart_get)
    r.add_get("/api/party", party_get)
    r.add_post("/api/party", party_post)
    r.add_post("/api/smart", smart_post)
    r.add_post("/api/schedule", schedule_post)
    r.add_post("/api/history/clear", history_clear)
    r.add_post("/api/wlan", wlan_post)
    r.add_post("/api/list/check", list_check)
    r.add_post("/api/import/shared", import_shared)
    r.add_post("/api/import/u64pl", import_u64pl)
    r.add_post("/api/export/shared", export_shared)
    r.add_post("/api/import/pcstats", import_pcstats)
    r.add_get("/api/songlengths/export", sl_export)
    r.add_post("/api/ctl", ctl)
    r.add_post("/api/queue", queue)
    r.add_post("/api/folder", folder)
    r.add_get("/api/sources", sources_get)
    r.add_post("/api/sources", sources_set)
    r.add_post("/api/sources/test", source_test)
    r.add_get("/api/ls", ls)
    r.add_post("/api/info", info)
    r.add_post("/api/search", search)
    r.add_get("/api/job", job_get)
    r.add_post("/api/job/cancel", job_cancel)
    r.add_post("/api/scan", netscan)
    r.add_post("/api/scan/u64", u64_find)
    r.add_post("/api/shares", shares)
    r.add_post("/api/songlengths/load", sl_load)
    r.add_post("/api/songlengths/upload", sl_upload)
    r.add_post("/api/songlengths/clear", sl_clear)
    r.add_post("/api/stil/load", stil_load)
    r.add_post("/api/stil/clear", stil_clear)
    r.add_get("/api/playlists", pl_list)
    r.add_get("/api/playlist", pl_get)
    r.add_post("/api/playlist/save", pl_save)
    r.add_post("/api/playlist/load", pl_load)
    r.add_post("/api/playlist/delete", pl_delete)
    r.add_post("/api/playlist/rename", pl_rename)
    r.add_post("/api/u64/power", u64_power)
    r.add_get("/api/config", config_get)
    r.add_post("/api/config", config_set)
    r.add_get("/api/devices", devices)
    r.add_post("/api/devices/query", devices_query)
    r.add_post("/api/display/calibrate", display_calibrate)
    r.add_get("/api/sidcfg", sid_config)
    r.add_get("/api/hdmi", hdmi_get)
    r.add_post("/api/hdmi", hdmi_post)
    r.add_post("/api/hdmi/upload", hdmi_upload)
    r.add_post("/api/hdmi/delete", hdmi_delete)
    r.add_post("/api/hdmi/sync", hdmi_sync)
    r.add_get("/api/hdmi/thumb", hdmi_thumb)
    r.add_post("/api/hdmi/news", news_refresh)
    r.add_get("/api/hdmi/image", hdmi_image)
    r.add_get("/api/backup", backup)
    r.add_post("/api/restore", restore)
    return app
