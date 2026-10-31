"""Manual, install scripts, dependencies."""
import ast
import os
import re
import shutil
import subprocess
import sys

import pytest

from c64jukebox.markdown import to_html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_manual_renders_and_links_resolve():
    html, ids = to_html(open(os.path.join(ROOT, "docs", "HANDBUCH.md"), encoding="utf-8").read())
    assert {"dateien-auswaehlen", "songlaengen", "stream-verteiler", "sicherung", "wiedergabelisten"} <= ids
    assert "<table>" in html and "<pre>" in html
    text = open(os.path.join(ROOT, "docs", "HANDBUCH.md"), encoding="utf-8").read()
    assert set(re.findall(r"\]\(#([^)]+)\)", text)) <= ids                  # every link inside the manual has a target
    # every table row has as many cells as its header (a "|" inside `code` would break the table)
    for table in re.findall(r"<table>(.*?)</table>", html):
        n = table.split("</thead>")[0].count("<th>")
        assert all(r.count("<td>") == n for r in re.findall(r"<tr>(.*?)</tr>", table.split("</thead>")[1])), table[:80]


def test_scripts_parse():
    for f in ("install.sh", "deploy.sh"):
        subprocess.run(["bash", "-n", os.path.join(ROOT, "install", f)], check=True)
    net = open(os.path.join(ROOT, "install", "c64pi-net.service")).read()
    assert "-m c64jukebox.netwatch" in net and "RuntimeDirectory=c64pi" in net and "Group=c64jukebox" in net
    unit = open(os.path.join(ROOT, "install", "c64jukebox.service")).read()
    assert "-/run/c64pi" in unit and "SupplementaryGroups=i2c" in unit
    assert "ExecStart=/opt/c64jukebox/venv/bin/python -m c64jukebox --data /var/lib/c64jukebox --port 80" in unit


def _imports(path):
    """-> (third-party top-level modules, relative/own modules) imported by a file"""
    third, own = set(), set()
    tree = ast.parse(open(path, encoding="utf-8").read())
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            third.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            if n.level == 0:
                third.add(n.module.split(".")[0])
            else:
                own.add("." * n.level + (n.module or ""))
    return third - set(sys.stdlib_module_names) - {"c64jukebox"}, own


def test_requirements_cover_imports():
    """the jukebox (venv, requirements.txt) - the HDMI part runs with the system's Python and takes only
    python3-pygame + python3-numpy from apt; the jukebox may use its pygame-free hdmi/modes.py only"""
    req = open(os.path.join(ROOT, "requirements.txt")).read()
    third = set()
    for dirpath, _, files in os.walk(os.path.join(ROOT, "c64jukebox")):
        for f in files:
            if not f.endswith(".py"):
                continue
            t, own = _imports(os.path.join(dirpath, f))
            if os.path.basename(dirpath) == "hdmi":
                assert t <= {"pygame", "numpy"}, (f, t)
                # (..i18n: the language, standard library only)
                assert all(o.startswith(".") and (not o.startswith("..") or o == "..i18n") for o in own), (f, own)
                if f == "modes.py":
                    assert not t, "modes.py is read by the jukebox: no pygame/numpy"
                continue
            if f in ("loopfind.py", "loopwatch.py"):      # the repeat search: its own process, system Python too
                assert t <= {"numpy"}, (f, t)
                if f == "loopwatch.py":                    # the jukebox imports it: numpy only inside main()
                    import ast
                    top = ast.parse(open(os.path.join(dirpath, f)).read()).body
                    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and "numpy" in ast.dump(n) for n in top)
                continue
            third |= t
            assert ".loopfind" not in own, (f, "loopfind needs numpy: only through loopwatch's process")
            assert not any(o.startswith(".hdmi") and o != ".hdmi.modes" for o in own), (f, own)
    names = {"aiohttp": "aiohttp", "yarl": "aiohttp", "smb": "pysmb", "nmb": "pysmb", "smbprotocol": "smbprotocol", "PIL": "Pillow",
             "tinytuya": "tinytuya"}
    assert third <= set(names), third
    for mod in third:
        assert names[mod] in req


@pytest.mark.skipif(not shutil.which("python3.10") and not os.path.exists("/opt/homebrew/bin/python3.10"),
                    reason="no older Python to check the syntax with")
def test_syntax_for_older_python():
    """the Pi has Python 3.11: nothing newer than that may be used (checked with 3.10)"""
    py = shutil.which("python3.10") or "/opt/homebrew/bin/python3.10"
    files = [os.path.join(d, f) for d, _, fs in os.walk(os.path.join(ROOT, "c64jukebox")) for f in fs if f.endswith(".py")]
    subprocess.run([py, "-c", "import ast,sys\nfor f in sys.argv[1:]: ast.parse(open(f,encoding='utf-8').read(), f)"] + files,
                   check=True)
