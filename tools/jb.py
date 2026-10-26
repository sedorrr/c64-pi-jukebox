"""Tiny client for the jukebox API on the Pi itself (127.0.0.1, no login).
    jb.py get /api/state            jb.py post /api/ctl '{"c":"next"}'          jb.py job /api/folder '{...}'
    jb.py now                       (short line: state, title, song, elapsed/length, stream, np status)"""
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1"


def call(method, path, data=None):
    path = urllib.parse.quote(path, safe="/?=&:,")
    req = urllib.request.Request(BASE + path, method=method, data=None if data is None else data.encode(),
                                 headers={"X-C64": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") | {"http": e.code}


def now():
    s = call("GET", "/api/state")
    p, st = s["player"], s["stream"]
    n = p.get("now") or {}
    print("%s | %s | %s | Lied %s/%s | %s / %s s | Stream %s/s von %s | Pico-Titel %s | %s" % (
        time.strftime("%H:%M:%S"), p["state"], (n.get("title") or "-") + " – " + (n.get("author") or ""),
        n.get("song"), n.get("songs"), p.get("el"), n.get("secs"), st["pps"], st["from"] or "-",
        s.get("np") or {}, p.get("msg") or ""))


cmd = sys.argv[1]
if cmd == "now":
    for i in range(int(sys.argv[2]) if len(sys.argv) > 2 else 1):
        if i:
            time.sleep(float(sys.argv[3]) if len(sys.argv) > 3 else 2)
        now()
elif cmd == "get":
    print(json.dumps(call("GET", sys.argv[2]), ensure_ascii=False)[:4000])
elif cmd == "post":
    print(json.dumps(call("POST", sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "{}"), ensure_ascii=False)[:4000])
elif cmd == "job":
    r = call("POST", sys.argv[2], sys.argv[3])
    if not r.get("job"):
        print(r)
        sys.exit(1)
    while True:
        time.sleep(0.5)
        j = call("GET", "/api/job?id=" + r["job"])
        if j["done"]:
            res = j["result"]
            print("Fehler:" if j["error"] else "fertig:", j["error"] or json.dumps(res, ensure_ascii=False)[:1500], "|", j["progress"])
            break
