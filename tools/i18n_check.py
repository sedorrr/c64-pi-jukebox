#!/usr/bin/env python3
"""Translations of the jukebox (i18n.py): which texts have no English yet, which entries are no longer used, and which
German-looking texts are not marked for translation at all.

  python3 tools/i18n_check.py            summary + missing entries
  python3 tools/i18n_check.py --todo     also the German-looking texts outside tr()/T() (file:line)
  python3 tools/i18n_check.py --stub     add the missing entries with an empty English text (to fill in)

Python: tr("...") with a literal; the table c64jukebox/lang/en.json. The page: T('...') in web/app.js, the texts and
the title/placeholder/aria-label attributes of web/index.html (white space folded; an element with translate="no" and
its children are left out); the table c64jukebox/web/lang-en.json. The manual: docs/MANUAL.md must have the same
section ids as docs/HANDBUCH.md."""
import ast
import glob
import html.parser
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "c64jukebox")
PY_TABLE = os.path.join(PKG, "lang", "en.json")
WEB_TABLE = os.path.join(PKG, "web", "lang-en.json")
GERMAN = re.compile(r"[äöüÄÖÜß„“–]|\b(der|die|das|den|dem|nicht|und|ist|kein|keine|nur|noch|wird|bitte|Titel|Liste|"
                    r"Fehler|gefunden|läuft|Stück|Ordner|Quelle|Gerät|Einstellungen|Passwort|Fernseher|schalten)\b")
ATTRS = ("title", "placeholder", "aria-label")
PLACEHOLDER = re.compile(r"%[sd]")


def fold(t):
    return re.sub(r"\s+", " ", t).strip()


def wanted(t):
    """a text worth translating: has letters, is not only a symbol, a number or a brand/technical name"""
    return bool(re.search(r"[A-Za-zÄÖÜäöüß]{2,}", t))


# ---- Python
def _docstring_ids(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and \
                isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            out.add(id(n.body[0].value))
    return out


def python_texts():
    """-> ({text: [file:line]} inside tr(), [(file:line, text)] German-looking outside)"""
    keys, todo = {}, []
    for f in sorted(glob.glob(os.path.join(PKG, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(f, ROOT)
        if rel.endswith("i18n.py"):
            continue
        tree = ast.parse(open(f, encoding="utf-8").read())
        docs, inside = _docstring_ids(tree), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.setdefault(a.value, []).append("%s:%d" % (rel, a.lineno))
                    inside.add(id(a))
                elif isinstance(a, ast.JoinedStr):
                    todo.append(("%s:%d" % (rel, a.lineno), "tr(f-string) – mit %s/%d schreiben"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and \
                    id(n) not in inside and GERMAN.search(n.value) and " " in n.value.strip():
                todo.append(("%s:%d" % (rel, n.lineno), n.value))
    return keys, todo


# ---- the page
class _Html(html.parser.HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.texts = [], {}

    def _skip(self):
        return any(no or tag in ("script", "style") for tag, no in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        no = a.get("translate") == "no"
        if not (self._skip() or no):
            for k in ATTRS:
                if a.get(k) and wanted(a[k]):
                    self.texts.setdefault(fold(a[k]), []).append("index.html:%d" % self.getpos()[0])
        if tag not in self.VOID:
            self.stack.append((tag, no))

    def handle_endtag(self, tag):
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        t = fold(data)
        if t and wanted(t) and not self._skip():
            self.texts.setdefault(t, []).append("index.html:%d" % self.getpos()[0])


JS_T = re.compile(r"""\bT\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")
JS_STR = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`""")


def _js_unescape(s):
    return json.loads('"' + s.replace('"', '\\"').replace("\\'", "'") + '"')


def web_texts():
    p = _Html()
    p.feed(open(os.path.join(PKG, "web", "index.html"), encoding="utf-8").read())
    keys = dict(p.texts)
    todo = []
    js = open(os.path.join(PKG, "web", "app.js"), encoding="utf-8").read()
    marked = set()
    for m in JS_T.finditer(js):
        s = _js_unescape(m.group(1) if m.group(1) is not None else m.group(2))
        keys.setdefault(s, []).append("app.js:%d" % (js.count("\n", 0, m.start()) + 1))
        marked.add(m.start(1) if m.group(1) is not None else m.start(2))
    for m in JS_STR.finditer(js):
        start = next(m.start(k) for k in (1, 2, 3) if m.group(k) is not None)
        s = next(m.group(k) for k in (1, 2, 3) if m.group(k) is not None)
        if start not in marked and GERMAN.search(s) and not s.startswith(("/", "#", "c64")):
            todo.append(("app.js:%d" % (js.count("\n", 0, m.start()) + 1), s))
    return keys, todo


# ---- the manual
def manual_ids():
    sys.path.insert(0, ROOT)
    from c64jukebox.markdown import to_html
    out = {}
    for name in ("HANDBUCH.md", "MANUAL.md"):
        p = os.path.join(ROOT, "docs", name)
        if os.path.exists(p):
            out[name] = to_html(open(p, encoding="utf-8").read())[1]
    return out


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def check():
    """-> dict of problems (the tests use it)"""
    res = {}
    for name, (keys, todo), path in (("python", python_texts(), PY_TABLE), ("web", web_texts(), WEB_TABLE)):
        table = load(path)
        res[name] = {
            "keys": keys, "todo": todo, "table": table, "path": path,
            "missing": sorted(k for k in keys if not table.get(k)),
            "unused": sorted(k for k in table if k not in keys),
            "placeholders": sorted(k for k, v in table.items()
                                   if v and sorted(PLACEHOLDER.findall(k)) != sorted(PLACEHOLDER.findall(v))),
        }
    ids = manual_ids()
    res["manual"] = {"missing_ids": sorted(ids["HANDBUCH.md"] - ids["MANUAL.md"]) if "MANUAL.md" in ids else None,
                     "extra_ids": sorted(ids["MANUAL.md"] - ids["HANDBUCH.md"]) if "MANUAL.md" in ids else None}
    return res


def main():
    res = check()
    for name in ("python", "web"):
        r = res[name]
        print("%s: %d Texte, %d ohne Englisch, %d unbenutzte Einträge, %d mit falschen Platzhaltern, %d unmarkiert"
              % (name, len(r["keys"]), len(r["missing"]), len(r["unused"]), len(r["placeholders"]), len(r["todo"])))
        for k in r["missing"][:400]:
            print("  fehlt: %r  (%s)" % (k, r["keys"][k][0]))
        for k in r["placeholders"]:
            print("  Platzhalter: %r" % k)
        for k in r["unused"]:
            print("  unbenutzt: %r" % k)
        if "--todo" in sys.argv:
            for where, s in r["todo"]:
                print("  unmarkiert %s: %r" % (where, s[:100]))
        if "--stub" in sys.argv and r["missing"]:
            table = dict(r["table"])
            for k in r["missing"]:
                table.setdefault(k, "")
            with open(r["path"], "w", encoding="utf-8") as f:
                json.dump(dict(sorted(table.items())), f, ensure_ascii=False, indent=1)
                f.write("\n")
    m = res["manual"]
    if m["missing_ids"] is None:
        print("manual: docs/MANUAL.md fehlt")
    else:
        print("manual: %d Abschnitte fehlen, %d zu viel" % (len(m["missing_ids"]), len(m["extra_ids"])))
        for h in m["missing_ids"] + m["extra_ids"]:
            print("  " + h)


if __name__ == "__main__":
    main()
