"""The JSON API through aiohttp's test client, against a fake Ultimate, FTP server and SMB server."""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from c64jukebox import sidfile
from c64jukebox.config import MASK
from c64jukebox.core import Jukebox
from c64jukebox.web import make_app
from fakes import FakeFTP, FakeSMBServer, FakeUltimate, free_port, install_fake_smb, make_sid

A = make_sid("Alpha", "Ann", "1986 X", songs=3)
B = make_sid("Beta", "Bob", "1987 Y")
H = {"X-C64": "1"}


def setup_files(tmp):
    d = tmp / "sids"
    (d / "Hubbard").mkdir(parents=True)
    (d / "Hubbard" / "Commando.sid").write_bytes(A)
    (d / "b.sid").write_bytes(B)
    (d / "Songlengths.md5").write_text("[Database]\n%s=1:00 0:30 0:20\n" % sidfile.md5(A))
    return d


def run(tmp, fn, monkeypatch=None, trust_local=False, **kw):
    async def t():
        d = setup_files(tmp)
        u64 = await FakeUltimate().start()
        ftp = FakeFTP({"USB2": {"x.sid": B}})
        jb = Jukebox(str(tmp / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", scan_hosts=["127.0.0.1"],
                     scan_ports={"smb": free_port(1), "ftp": ftp.port, "http": u64.port})
        c = jb.config.data
        c["ultimates"] = [{"label": "Elite II", "addr": u64.addr, "pw": "netz"}]
        c["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(d)},
                        {"id": "u64", "kind": "u64", "label": "Ultimate", "path": "/", "port": ftp.port}]
        u64.pw = "netz"
        app = make_app(jb, trust_local=trust_local)
        app.on_startup.append(lambda a: jb.start())
        app.on_cleanup.append(lambda a: jb.close())
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            await fn(client, jb, u64)
        finally:
            await client.close()
            await u64.stop()
            ftp.stop()
    asyncio.run(t())


async def login(c, pw="commodore64"):
    r = await c.post("/api/login", json={"pw": pw}, headers=H)
    return r.status, await r.json()


async def post(c, path, data=None):
    r = await c.post(path, json=data or {}, headers=H)
    return r.status, await r.json()


async def get(c, path):
    r = await c.get(path)
    return r.status, await r.json()


async def job(c, jid):
    for _ in range(100):
        s, j = await get(c, "/api/job?id=" + jid)
        if j["done"]:
            return j
        await asyncio.sleep(0.05)
    raise AssertionError("job never finished")


def test_login_and_guard(tmp_path):
    async def t(c, jb, u64):
        assert (await c.get("/")).status == 200 and (await c.get("/app.js")).status == 200
        assert (await c.get("/../config.py")).status == 404
        s, j = await get(c, "/api/state")
        assert s == 401
        s, j = await get(c, "/api/hello")
        assert s == 200 and j["login"] is False
        r = await c.post("/api/login", json={"pw": "commodore64"})        # without X-C64: refused
        assert r.status == 403
        s, j = await login(c, "falsch")
        assert s == 401
        s, j = await login(c)
        assert s == 200 and j["pwdefault"] is True
        s, j = await get(c, "/api/state")
        assert s == 200 and j["pwdefault"] and j["ultimates"][0]["label"] == "Elite II"
        r = await c.post("/api/ctl", json={"c": "stop"})                  # a cross-site form cannot set the header
        assert r.status == 403
        s, j = await post(c, "/api/password", {"old": "commodore64", "new": "neu1234"})
        assert s == 200
        s, j = await get(c, "/api/state")
        assert s == 200 and not j["pwdefault"]                             # this browser got a new cookie
        c.session.cookie_jar.clear()
        assert (await login(c, "commodore64"))[0] == 401
        assert (await login(c, "neu1234"))[0] == 200
        html = await (await c.get("/hilfe")).text()
        assert "<h2" in html and "Inhalt" in html
    run(tmp_path, t)


def test_config_masks_passwords(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        s, cfg = await get(c, "/api/config")
        assert cfg["ultimates"][0]["pw"] == MASK and "web" not in cfg
        s, j = await post(c, "/api/config", {"ultimates": [{"label": "Neu", "addr": u64.addr, "pw": MASK},
                                                             {"label": "Zwei", "addr": "10.0.0.2", "pw": "x"}],
                                              "picos": [{"addr": "c64viz.local", "np": "http", "pw": "p"},
                                                        {"addr": " ", "np": "udp"}],
                                              "player": {"limit_min": "2.5", "subsongs": "all", "bogus": 1},
                                              "name": "Wohn Zimmer!"})
        assert s == 200
        d = jb.config.data
        assert d["ultimates"][0]["pw"] == "netz" and d["ultimates"][1]["pw"] == "x"     # MASK kept the old one
        assert d["picos"] == [{"addr": "c64viz.local", "np": "http", "pw": "p", "stream": True}]
        assert d["player"]["limit_min"] == 2.5 and d["player"]["subsongs"] == "all" and "bogus" not in d["player"]
        assert d["name"] == "wohnzimmer"
        assert [t.addr for t in jb.hub.targets] == ["c64viz.local"]
        s, j = await post(c, "/api/config", {"u64_sel": 1})
        assert jb.config["u64_sel"] == 1
        raw = json.load(open(jb.config.path))
        assert raw["ultimates"][0]["pw"] == "netz"
    run(tmp_path, t)


def test_browse_info_play(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        s, j = await get(c, "/api/ls?src=pi&path=/")
        assert [e["n"] for e in j["items"]] == ["Hubbard", "b.sid", "Songlengths.md5"]
        s, j = await post(c, "/api/info", {"src": "pi", "paths": ["/Hubbard/Commando.sid", "/Songlengths.md5", "/x.sid"]})
        i = j["info"]
        assert i["/Hubbard/Commando.sid"]["t"] == "Alpha" and i["/Hubbard/Commando.sid"]["n"] == 3
        assert "err" in i["/Songlengths.md5"] and "err" in i["/x.sid"]
        s, j = await get(c, "/api/ls?src=pi&path=/Hubbard")
        assert j["items"][0]["i"]["a"] == "Ann"                            # from the cache now
        s, j = await get(c, "/api/ls?src=pi&path=/nope")
        assert s == 400 and "nicht gefunden" in j["msg"]
        # song lengths from the browsed folder
        s, j = await post(c, "/api/songlengths/load", {"src": "pi", "path": "/Songlengths.md5", "kind": "hvsc"})
        assert (await job(c, j["job"]))["result"] == {"n": 1}
        s, j = await post(c, "/api/info", {"src": "pi", "paths": ["/Hubbard/Commando.sid"]})
        assert j["info"]["/Hubbard/Commando.sid"]["lens"] == [60, 30, 20]
        # play a tune
        s, j = await post(c, "/api/queue", {"mode": "replace", "items": [{"src": "pi", "path": "/b.sid", "name": "b.sid"},
                                                                        {"src": "pi", "path": "/Hubbard/Commando.sid"}], "start": 1})
        assert s == 200 and j["total"] == 2
        up = [x for x in u64.calls if x[1] == "/v1/runners:sidplay"][-1]
        assert up[3]["data"] == A
        s, st = await get(c, "/api/state")
        assert st["player"]["now"]["title"] == "Alpha" and st["player"]["now"]["secs"] == 60
        s, j = await post(c, "/api/ctl", {"c": "song", "n": 2})
        assert j["player"]["now"]["song"] == 2 and j["player"]["now"]["secs"] == 30
        s, j = await post(c, "/api/ctl", {"c": "pause"})
        assert j["player"]["state"] == "pause"
        s, j = await post(c, "/api/ctl", {"c": "pause"})                  # the same button resumes
        assert j["player"]["state"] == "play"
        s, j = await post(c, "/api/ctl", {"c": "nonsense"})
        assert s == 400
        s, j = await get(c, "/api/list?start=0&n=10")
        assert j["total"] == 2 and j["cur"] == 1 and j["items"][1]["title"] == "Alpha"
        # a file on the Ultimate's own stick is started by its path
        s, j = await post(c, "/api/queue", {"mode": "replace", "items": [{"src": "u64", "path": "/USB2/x.sid"}]})
        assert u64.calls[-1][:3] == ("PUT", "/v1/runners:sidplay", {"file": "/USB2/x.sid", "songnr": "1"})
    run(tmp_path, t)


def test_folder_search_playlists(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        s, j = await post(c, "/api/folder", {"src": "pi", "path": "/", "recursive": True, "mode": "replace"})
        r = await job(c, j["job"])
        assert r["result"]["n"] == 2 and jb.player.state == "play"
        assert [i["path"] for i in jb.player.items] == ["/b.sid", "/Hubbard/Commando.sid"]
        s, j = await post(c, "/api/folder", {"src": "pi", "path": "/Hubbard", "recursive": False, "mode": "add"})
        await job(c, j["job"])
        assert len(jb.player.items) == 3
        s, j = await post(c, "/api/search", {"src": "pi", "path": "/", "q": "hubbard"})
        r = await job(c, j["job"])
        assert [h["p"] for h in r["result"]] == ["/Hubbard/Commando.sid"]
        s, j = await post(c, "/api/search", {"src": "pi", "path": "/", "q": "x"})
        assert s == 400
        s, j = await post(c, "/api/playlist/save", {"name": "Party 64 / Teil 1"})
        assert s == 200 and j["lists"][0] == {"name": "Party 64 / Teil 1", "n": 3, "saved": j["lists"][0]["saved"]}
        s, j = await post(c, "/api/ctl", {"c": "clear"})
        assert jb.player.items == [] and jb.player.state == "stop"
        s, j = await post(c, "/api/playlist/load", {"name": "Party 64 / Teil 1"})
        assert j["n"] == 3 and len(jb.player.items) == 3 and jb.player.state == "play"
        s, j = await get(c, "/api/playlist?name=" + "Party 64 / Teil 1")
        assert len(j["items"]) == 3
        s, j = await post(c, "/api/playlist/delete", {"name": "Party 64 / Teil 1"})
        assert j["lists"] == []
        s, j = await post(c, "/api/playlist/load", {"name": "gibtsnicht"})
        assert s == 400
    run(tmp_path, t)


def test_sources_shares_scan(tmp_path, monkeypatch):
    servers = install_fake_smb(monkeypatch)
    servers["nas.local"] = FakeSMBServer({"Musik": {"C64": {"a.sid": A}}, "Video": {}}, user="nutzer", pw="geheim")

    async def t(c, jb, u64):
        await login(c)
        s, j = await post(c, "/api/shares", {"host": "nas.local", "user": "nutzer", "pw": "geheim"})
        assert [x["name"] for x in j["shares"]] == ["Musik", "Video"]
        smb = {"kind": "smb", "label": "NAS", "host": "nas.local", "share": "Musik", "path": "/C64", "user": "nutzer", "pw": "geheim"}
        s, j = await post(c, "/api/sources/test", {"source": smb})
        assert s == 200 and "1 SIDs" in j["msg"]
        s, cur = await get(c, "/api/sources")
        s, j = await post(c, "/api/sources", {"sources": cur["sources"] + [smb]})
        new = j["sources"][-1]
        assert new["id"] and new["pw"] == MASK
        # saved again from the page with the mask: the password stays
        s, j = await post(c, "/api/sources", {"sources": j["sources"]})
        assert jb.config.source(new["id"])["pw"] == "geheim"
        s, j = await post(c, "/api/shares", {"host": "nas.local", "user": "nutzer", "pw": MASK, "id": new["id"]})
        assert s == 200
        s, j = await get(c, "/api/ls?src=%s&path=/" % new["id"])
        assert j["items"][0]["n"] == "a.sid"
        s, j = await post(c, "/api/sources", {"sources": [{"kind": "zip"}]})
        assert s == 400
        # network search: the fake Ultimate answers /v1/info, the fake FTP server is found too
        s, j = await post(c, "/api/scan", {})
        r = await job(c, j["job"])
        h = r["result"][0]
        assert h["ip"] == "127.0.0.1" and h["ftp"] and not h["smb"] and h["u64"]["product"] == "Ultimate 64 Elite II"
    run(tmp_path, t, monkeypatch)


def test_backup_restore_upload(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        r = await c.post("/api/songlengths/upload?kind=custom&name=mine.txt", data=("%s=99\n" % sidfile.md5(B)).encode(), headers=H)
        assert (await r.json())["n"] == 1
        r = await c.post("/api/songlengths/upload?kind=hvsc", data=b"nothing here", headers=H)
        assert r.status == 400
        await post(c, "/api/queue", {"mode": "replace", "items": [{"src": "pi", "path": "/b.sid"}], "play": False})
        await post(c, "/api/playlist/save", {"name": "Liste"})
        r = await c.get("/api/backup")
        assert "attachment" in r.headers["Content-Disposition"]
        bk = await r.json()
        assert bk["fmt"] == "c64pi-backup" and bk["config"]["ultimates"][0]["pw"] == "netz"
        assert "secret" not in bk["config"]["web"] and bk["playlists"]["Liste"][0]["path"] == "/b.sid"
        # change things, then restore
        await post(c, "/api/config", {"ultimates": [{"label": "X", "addr": "1.2.3.4", "pw": ""}]})
        await post(c, "/api/playlist/delete", {"name": "Liste"})
        await post(c, "/api/songlengths/clear", {"kind": "custom"})
        assert jb.songlengths.counts()["custom"] == 0
        r = await c.post("/api/restore", data=json.dumps(bk), headers=H)
        assert r.status == 200
        assert jb.config["ultimates"][0]["addr"] == u64.addr and jb.songlengths.counts()["custom"] == 1
        assert [p["name"] for p in jb.playlists()] == ["Liste"]
        s, st = await get(c, "/api/state")
        assert s == 200                                                     # still logged in (secret kept)
        r = await c.post("/api/restore", data=b"{\"fmt\": \"anders\"}", headers=H)
        assert r.status == 400
    run(tmp_path, t)


def test_local_admin_without_login(tmp_path):
    """on the Pi itself (over SSH) no login is needed - the header against foreign forms still is"""
    async def t(c, jb, u64):
        s, j = await get(c, "/api/state")
        assert s == 200 and j["ultimates"][0]["label"] == "Elite II"
        r = await c.post("/api/config", json={"stream": {"on": False}})
        assert r.status == 403
        s, j = await post(c, "/api/config", {"name": "pi-test"})
        assert s == 200 and jb.config["name"] == "pi-test"
        r = await c.get("/api/state", headers={"X-Forwarded-For": "1.2.3.4"})      # through a proxy: not local
        assert r.status == 401
    run(tmp_path, t, trust_local=True)


def test_table_api_dedupe_statistics(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        items = [{"src": "pi", "path": "/b.sid"}, {"src": "pi", "path": "/Hubbard/Commando.sid"}, {"src": "pi", "path": "/b.sid"}]
        await post(c, "/api/queue", {"mode": "replace", "items": items, "start": 0})
        s, j = await post(c, "/api/list/check", {})
        await job(c, j["job"])
        s, r = await get(c, "/api/rows?start=0&n=10")
        assert r["count"] == 3 and r["rows"][0]["title"] == "Beta" and r["rows"][1]["songs"] == 3 and r["cur"] == 0
        assert r["rows"][0]["plays"] == 1 and r["rows"][0]["lk"] == "default"
        s, r = await get(c, "/api/rows?q=alpha")
        assert [x["i"] for x in r["rows"]] == [1]
        s, j = await post(c, "/api/ctl", {"c": "fav", "i": 1})
        assert j["fav"] is True
        s, r = await get(c, "/api/rows?fav=1")
        assert [x["i"] for x in r["rows"]] == [1]
        s, j = await post(c, "/api/ctl", {"c": "setlen", "i": 1, "secs": 185})
        s, r = await get(c, "/api/rows")
        assert r["rows"][1]["len"] == 185 and r["rows"][1]["lk"] == "user"
        s, j = await post(c, "/api/ctl", {"c": "sort", "col": "title"})
        s, r = await get(c, "/api/rows")
        assert [x["title"] for x in r["rows"]] == ["Alpha", "Beta", "Beta"] and r["sort"] == {"col": "title", "rev": False}
        s, j = await post(c, "/api/ctl", {"c": "dedupe"})
        assert j["n"] == 1 and len(jb.player.items) == 2
        s, st = await get(c, "/api/statistics")
        assert st["plays"] == 1 and st["favs"] == 1 and st["top"] == [["Bob", 1]] and st["chips"]["1"] == 2
        r = await c.get("/api/songlengths/export")
        assert (await r.text()).count("=185") == 1
        s, j = await post(c, "/api/ctl", {"c": "stopafter", "songs": 2})
        s, st = await get(c, "/api/state")
        assert st["player"]["stop_after"] == {"songs": 2}
    run(tmp_path, t)


def test_stale_numbering_and_early_star(tmp_path):
    async def t(c, jb, u64):
        await login(c)
        items = [{"src": "pi", "path": "/b.sid"}, {"src": "pi", "path": "/Hubbard/Commando.sid"}]
        await post(c, "/api/queue", {"mode": "replace", "items": items, "start": 0, "play": False})
        s, r = await get(c, "/api/rows")
        over = r["over"]
        # a star before the header (MD5) is known: the file is read first, so the star keeps
        assert "md5" not in jb.player.items[1]
        s, j = await post(c, "/api/ctl", {"c": "fav", "i": 1, "over": over})
        assert j["fav"] and jb.player.items[1]["md5"]
        assert all(k.startswith("md5:") for k in jb.stats.fav)
        await post(c, "/api/ctl", {"c": "sort", "col": "name"})
        s, j = await post(c, "/api/ctl", {"c": "remove", "is": [0], "over": over})       # numbering of before the sort
        assert s == 409 and len(jb.player.items) == 2
        s, r = await get(c, "/api/rows?ids=1")
        assert r["ids"] == [0, 1] and r["over"] != over
        s, j = await post(c, "/api/ctl", {"c": "remove", "is": [0], "over": r["over"]})
        assert s == 200 and len(jb.player.items) == 1
        # counted before the MD5 was known -> moves to the MD5 key on the first start
        jb.stats.plays["path:pi:/b.sid"] = 3
        await post(c, "/api/queue", {"mode": "replace", "items": [{"src": "pi", "path": "/b.sid"}], "start": 0})
        assert "path:pi:/b.sid" not in jb.stats.plays and max(jb.stats.plays.values()) == 4
    run(tmp_path, t)


def test_update_hint(tmp_path, monkeypatch):
    """the published VERSION once a day: newer -> a hint in the state; switched off -> none"""
    from aiohttp import web as aweb
    from c64jukebox import VERSION, core
    published = {"v": "99.1"}

    async def init_py(req):
        return aweb.Response(text='"""doc"""\n\nVERSION = "%s"\n' % published["v"])

    async def t(c, jb, u64):
        gh = aweb.Application()
        gh.router.add_get("/c64jukebox/__init__.py", init_py)
        srv = TestServer(gh)
        await srv.start_server()
        monkeypatch.setattr(core, "UPDATE_URL", str(srv.make_url("/c64jukebox/__init__.py")))
        try:
            await login(c)
            s, st = await get(c, "/api/state")
            assert st["update"] is None
            s, r = await post(c, "/api/update/check")
            assert r == {"ok": True, "ver": "99.1", "newer": True, "installed": VERSION}
            assert (await get(c, "/api/state"))[1]["update"] == "99.1"
            await post(c, "/api/config", {"updates": False})                 # switched off: no hint
            assert (await get(c, "/api/state"))[1]["update"] is None and (await get(c, "/api/config"))[1]["updates"] is False
            await post(c, "/api/config", {"updates": True})
            published["v"] = VERSION                                        # the same as ours: no hint
            await post(c, "/api/update/check")
            assert (await get(c, "/api/state"))[1]["update"] is None
            jb._update_at -= core.UPDATE_EVERY_S                             # the daily look from the clock
            published["v"] = "99.2"
            for _ in range(40):
                await asyncio.sleep(0.1)
                if jb.update["ver"] == "99.2":
                    break
            assert jb.update["newer"] and jb.update["ver"] == "99.2"
            monkeypatch.setattr(core, "UPDATE_URL", "http://127.0.0.1:%d/x" % free_port(1))  # GitHub away
            s, r = await post(c, "/api/update/check")
            assert not r["ok"] and "nicht erreichbar" in r["msg"]
        finally:
            await srv.close()
    run(tmp_path, t)
    k = core.version_key                     # decimal: a small step gets another digit (1.1, 1.11, 1.12, then 1.2)
    assert k("1.2") > k("1.12") > k("1.11") > k("1.1") > k("1.0") and k("2.0") > k("1.99") and k("1.10") == k("1.1")


def test_home_screen_icons(tmp_path):
    """iPhone/Android "Zum Home-Bildschirm": icon + manifest without a login (the page's head points to them)"""
    async def t(c, jb, u64):
        page = await (await c.get("/")).text()
        for name in ("apple-touch-icon.png", "manifest.json"):
            assert 'href="%s"' % name in page
        for name in ("apple-touch-icon.png", "icon-192.png", "icon-512.png"):
            r = await c.get("/" + name)
            assert r.status == 200 and (await r.read())[:8] == b"\x89PNG\r\n\x1a\n"
        m = await (await c.get("/manifest.json")).json(content_type=None)
        assert m["display"] == "standalone" and [i["src"] for i in m["icons"]] == ["icon-192.png", "icon-512.png"]
        assert (await c.get("/nope.png")).status == 404
    run(tmp_path, t)


def test_messages_in_english(tmp_path):
    """language "en": errors raised in core reach the page in English, the event log too, and a list renamed
    while it plays keeps its "List “…”" source (set in English)"""
    from c64jukebox import events, i18n

    async def t(c, jb, u64):
        i18n.set_lang("en")                                  # after Jukebox() took the (empty) setting
        await login(c)
        s, j = await post(c, "/api/playlist/load", {"name": "gibtsnicht"})
        assert s == 400 and j["msg"] == "List not found"
        jb.player.items = [{"src": "pi", "path": "/b.sid", "name": "b.sid"}]
        jb.playlist_write("Abend", jb.player.items)
        s, j = await post(c, "/api/playlist/load", {"name": "Abend", "play": False})
        assert jb.player.source == "List “Abend”"
        jb.playlist_rename("Abend", "Nacht")
        assert jb.player.source == "List “Nacht”"
        try:
            jb.playlist_rename("Nacht", "")
        except ValueError as e:
            assert str(e) == "Please enter a new name"
        jb.add_ultimate("192.168.1.99", "Elite")
        assert (await get(c, "/api/events"))[1]["events"][-1]["text"] == "Ultimate added: Elite (192.168.1.99)"
    i18n._tables.clear()
    try:
        run(tmp_path, t)
    finally:
        i18n.set_lang("de")
        i18n._tables.clear()
        events.clear()
