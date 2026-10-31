"""The update on request: from the TV menu and the page (the jukebox starts the root unit, fake commands here), its end
reported once from update.json; update.sh itself against a local "GitHub" archive - installed, and put back when
install.sh fails."""
import json
import os
import subprocess
import sys
import tarfile
import time

from c64jukebox import VERSION
from test_player import run
from test_web import get, login, post, run as run_web

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE_SH = os.path.join(os.path.dirname(HERE), "install", "update.sh")


def fake_unit(jb, tmp_path, loaded=True, starts=True):
    mark = tmp_path / "started"
    jb.update_can_cmd = [sys.executable, "-c", "print(%r)" % ("loaded" if loaded else "not-found")]
    jb.update_cmd = [sys.executable, "-c", "open(%r, 'w').write('x'); raise SystemExit(%d)" % (str(mark), 0 if starts else 1)]
    return mark


def write_state(jb, **kw):
    with open(os.path.join(jb.data_dir, "update.json"), "w") as f:
        json.dump(dict({"at": int(time.time())}, **kw), f)


def test_update_from_the_tv(tmp_path):
    async def t(e):
        jb = e.jb
        mark = fake_unit(jb, tmp_path)
        jb.config.data["hdmi"]["on"] = True
        await jb._cec_cmd("select")
        names = [x[0] for x in jb.menu.entries()]
        assert "Nach Update sehen" in names                     # nothing known: look on GitHub from here

        async def check():
            jb.update = {"ver": "99.1", "newer": True, "at": 0}
            return jb.update
        jb.update_check = check
        jb.menu.sel["main"] = names.index("Nach Update sehen")
        await jb._cec_cmd("select")
        assert "99.1 ist erschienen" in jb.menu.view()["note"]
        v = jb.menu.view()
        assert v["items"][v["sel"]]["l"] == "Update auf 99.1 installieren"   # the same line, now to install
        await jb._cec_cmd("select")                              # asks first, "Nein" stands first
        assert "99.1 installieren?" in jb.menu.view()["title"]
        await jb._cec_cmd("down")
        await jb._cec_cmd("select")
        assert "läuft" in jb.menu.view()["note"] and mark.exists() and jb.update_running()
        assert dict((x[0], x[1]) for x in jb.menu.entries())["Update"] == "läuft …"
        try:
            await jb.update_install()
            raise AssertionError("twice")
        except ValueError as err:
            assert "schon" in str(err)
        # update.sh at work, the service restarted by install.sh, then the end: reported once, on the TV too
        jb.menu.close()
        write_state(jb, state="run", ver="99.1", **{"from": VERSION})
        jb._update_watch()
        assert jb.menu.view() is None and jb.update_running()
        write_state(jb, state="ok", ver="99.1", msg="Version 99.1 installiert", **{"from": VERSION})
        os.utime(os.path.join(jb.data_dir, "update.json"), (time.time() + 5, time.time() + 5))
        jb._update_watch()
        assert jb.menu.view()["note"] == "Update auf 99.1 installiert" and not jb.update_running()
        assert jb.update_file()["seen"] is True
        jb.menu.close()
        jb._update_mtime = None
        jb._update_watch()                                       # seen: not again (also not after a restart)
        assert jb.menu.view() is None
    run(tmp_path, t)


def test_update_not_set_up(tmp_path):
    async def t(e):
        jb = e.jb
        try:
            await jb.update_install()
            raise AssertionError("nothing known")
        except ValueError as err:
            assert "Keine neuere Version" in str(err)
        jb.update = {"ver": "99.1", "newer": True, "at": 0}
        mark = fake_unit(jb, tmp_path, loaded=False)
        try:
            await jb.update_install()
            raise AssertionError("no unit")
        except ValueError as err:
            assert "nicht eingerichtet" in str(err) and not mark.exists() and not jb.updating
        mark = fake_unit(jb, tmp_path, starts=False)
        try:
            await jb.update_install()
            raise AssertionError("not started")
        except ValueError as err:
            assert "nicht starten" in str(err) and not jb.updating
        # a failed update: the reason on the TV
        write_state(jb, state="fail", ver="99.1", msg="GitHub nicht erreichbar")
        jb._update_watch()
        assert jb.menu.view()["note"] == "Update fehlgeschlagen: GitHub nicht erreichbar"
    run(tmp_path, t)


def test_update_from_the_page(tmp_path):
    async def t(c, jb, u64):
        mark = fake_unit(jb, tmp_path)
        await login(c)
        s, r = await post(c, "/api/update/install")
        assert not r["ok"] and "Keine neuere" in r["msg"]
        assert (await get(c, "/api/state"))[1]["upd"] == {"running": False, "last": None}
        jb.update = {"ver": "99.1", "newer": True, "at": 0}
        s, r = await post(c, "/api/update/install")
        assert r == {"ok": True, "ver": "99.1"} and mark.exists()
        assert (await get(c, "/api/state"))[1]["upd"]["running"] is True
        write_state(jb, state="ok", ver=VERSION, msg="x", **{"from": "1.0"})
        jb.updating = False
        last = (await get(c, "/api/state"))[1]["upd"]["last"]
        assert last["state"] == "ok" and last["ver"] == VERSION and last["from"] == "1.0"
    run_web(tmp_path, t)


# ---- update.sh
def _archive(tmp_path, ver, install_ok=True):
    """github.com/.../archive/refs/heads/main.tar.gz: one top folder; its install.sh copies like the real one"""
    top = tmp_path / "gh" / "c64-pi-jukebox-main"
    (top / "c64jukebox").mkdir(parents=True)
    (top / "install").mkdir()
    (top / "docs").mkdir()
    (top / "c64jukebox" / "__init__.py").write_text('"""x"""\n\nVERSION = "%s"\n' % ver)
    (top / "c64jukebox" / "__main__.py").write_text("")
    (top / "requirements.txt").write_text("")
    (top / "install" / "install.sh").write_text(
        '#!/bin/bash\nset -e\nSRC=$(cd "$(dirname "$0")/.." && pwd)\necho "install.sh $*" > "$C64JB_DATA/args"\n'
        'rm -rf "$C64JB_APP/c64jukebox" "$C64JB_APP/docs"\ncp -r "$SRC/c64jukebox" "$SRC/docs" "$C64JB_APP/"\n'
        + ("" if install_ok else 'echo "pip kaputt"; exit 1\n'))
    path = tmp_path / "main.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        tf.add(top, arcname="c64-pi-jukebox-main")
    return path


def _app(tmp_path, ver="1.0"):
    app, data = tmp_path / "opt", tmp_path / "data"
    (app / "c64jukebox").mkdir(parents=True)
    (app / "docs").mkdir()
    (app / "c64jukebox" / "__init__.py").write_text('VERSION = "%s"\n' % ver)
    (app / "requirements.txt").write_text("")
    data.mkdir()
    return app, data


def _run(tmp_path, url, app, data):
    env = dict(os.environ, C64JB_UPDATE_URL=url, C64JB_APP=str(app), C64JB_DATA=str(data), PATH="/usr/bin:/bin")
    return subprocess.run(["bash", UPDATE_SH], env=env, capture_output=True, text=True, timeout=60)


def test_update_sh_installs(tmp_path):
    app, data = _app(tmp_path)
    r = _run(tmp_path, _archive(tmp_path, "1.2").as_uri(), app, data)
    st = json.loads((data / "update.json").read_text())
    assert r.returncode == 0, (data / "update.log").read_text()
    assert st["state"] == "ok" and st["ver"] == "1.2" and st["from"] == "1.0"
    assert 'VERSION = "1.2"' in (app / "c64jukebox" / "__init__.py").read_text()
    assert (data / "args").read_text().strip() == "install.sh --keep-hostname"      # the Pi keeps its name
    assert "Neue Version: 1.2" in (data / "update.log").read_text()


def test_update_sh_puts_the_old_program_back(tmp_path):
    app, data = _app(tmp_path)
    r = _run(tmp_path, _archive(tmp_path, "1.2", install_ok=False).as_uri(), app, data)
    st = json.loads((data / "update.json").read_text())
    assert r.returncode == 1 and st["state"] == "fail" and "1.0 läuft weiter" in st["msg"]
    assert 'VERSION = "1.0"' in (app / "c64jukebox" / "__init__.py").read_text()
    assert "pip kaputt" in (data / "update.log").read_text()


def test_update_sh_without_github(tmp_path):
    app, data = _app(tmp_path)
    r = _run(tmp_path, (tmp_path / "nichts.tar.gz").as_uri(), app, data)
    st = json.loads((data / "update.json").read_text())
    assert r.returncode == 1 and st["state"] == "fail" and st["msg"] == "GitHub nicht erreichbar"
    assert 'VERSION = "1.0"' in (app / "c64jukebox" / "__init__.py").read_text()
