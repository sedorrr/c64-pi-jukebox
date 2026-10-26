"""Timer ("Zeitplan"): on chosen weekdays at a time of day, start playing (the current list or a saved one) or stop,
and if wanted switch the TV on / to standby with it (HDMI-CEC). Entries:
    {"id", "on": bool, "days": [0..6] (Monday = 0), "time": "HH:MM", "do": "play" | "stop", "list": "" | name, "tv": bool}
A time that passed while the Pi was off is not made up for."""
import re
import time

DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MAX = 20


def clean(entries, lists=()):
    """entries from the page -> checked entries (ValueError with a message for the page)"""
    out = []
    for k, e in enumerate(entries[:MAX]):
        if not isinstance(e, dict):
            continue
        t = str(e.get("time", "")).strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", t)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError("Keine gültige Uhrzeit: %s" % (t or "(leer)"))
        days = sorted({int(d) for d in e.get("days", []) if str(d).isdigit() and 0 <= int(d) <= 6})
        if not days:
            raise ValueError("Kein Wochentag gewählt (%s)" % t)
        do = "stop" if e.get("do") == "stop" else "play"
        name = str(e.get("list") or "").strip()[:60] if do == "play" else ""
        if name and lists and name not in lists:
            raise ValueError("Liste nicht gefunden: %s" % name)
        out.append({"id": str(e.get("id") or "e%d" % k)[:20], "on": bool(e.get("on", True)), "days": days,
                    "time": "%02d:%02d" % (int(m.group(1)), int(m.group(2))), "do": do, "list": name,
                    "tv": bool(e.get("tv"))})
    return out


def due(entries, now, fired):
    """the entries to run at local time `now` (time.struct_time); `fired` (set) remembers what ran this minute"""
    key = time.strftime("%Y-%m-%d %H:%M", now)
    hm = "%02d:%02d" % (now.tm_hour, now.tm_min)
    out = []
    for e in entries:
        if e.get("on") and now.tm_wday in e.get("days", []) and e.get("time") == hm and (e["id"], key) not in fired:
            fired.add((e["id"], key))
            out.append(e)
    for f in [f for f in fired if f[1] != key]:          # only this minute matters
        fired.discard(f)
    return out


def next_run(entries, now):
    """-> (entry, struct_time) of the next run within a week, or None"""
    best = None
    t0 = time.mktime(now) - now.tm_sec
    for e in entries:
        if not e.get("on"):
            continue
        h, m = (int(x) for x in e["time"].split(":"))
        for d in range(8):
            day = time.localtime(t0 + d * 86400)
            ts = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, h, m, 0, 0, 0, -1))
            if ts <= t0 or time.localtime(ts).tm_wday not in e["days"]:
                continue
            if best is None or ts < best[1]:
                best = (e, ts)
            break
    return (best[0], time.localtime(best[1])) if best else None


def describe(e, when=None):
    """short text for the page: "Mo 18:00 · Abspielen „Feierabend“ (Fernseher an)" """
    what = ("Abspielen " + ("„%s“" % e["list"] if e.get("list") else "(aktuelle Liste)")) if e["do"] == "play" else "Stoppen"
    if e.get("tv"):
        what += " (Fernseher an)" if e["do"] == "play" else " (Fernseher aus)"
    day = DAYS[when.tm_wday] + " " if when else ""
    return "%s%s · %s" % (day, e["time"], what)
