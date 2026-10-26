"""What happened when - for finding sporadic faults afterwards (2026-10-23: the TV lost its sound now and then, while a
Pico was switched off or the SID voices started). Every entry goes to the journal (journalctl -u c64jukebox) and into
the last 300 entries for GET /api/events."""
import time
from collections import deque

_log = deque(maxlen=300)


def log(text, wall=time.time):
    t = wall()
    stamp = time.strftime("%H:%M:%S", time.localtime(t)) + ".%d" % int(t * 10 % 10)
    _log.append((round(t, 1), text))
    print("EVENT %s %s" % (stamp, text), flush=True)


def recent(n=300):
    return [{"t": t, "time": time.strftime("%d.%m. %H:%M:%S", time.localtime(t)), "text": x} for t, x in list(_log)[-n:]]


def clear():
    _log.clear()
