"""Measure the repeat search (c64jukebox/loopfind.py) on real SID tunes: HVSC tunes with a known length are played
with VICE's vsid past their end (in real time, 8 at once - vsid writes no sound faster than that), then the search
runs over the recordings and its length is compared with the HVSC one (within 3 s = right).

    python3 tools/loopfind_eval.py render <HVSC folder> <out folder> [count] [seed]
    python3 tools/loopfind_eval.py eval <out folder>

2026-10-24, 40 tunes (seed 64): 22 right, 5 wrong, 13 none - when it suggests, it is right 4 times in 5. Wrong:
tunes whose first part repeats exactly before the real loop (U2_II: the first half twice), lengths off by 5-10 s."""
import json
import os
import random
import re
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor

VSID = "/Applications/vice-arm64-sdl2-3.9/bin/vsid"
EXTRA_S = 75                               # played past the HVSC length: the search needs the repeat
PAL_HZ = 985248


def hvsc_lengths(hvsc):
    path, out = None, []
    for line in open(os.path.join(hvsc, "DOCUMENTS", "Songlengths.md5"), encoding="latin-1"):
        line = line.strip()
        if line.startswith("; /"):
            path = line[2:]
        elif "=" in line and path and not line.startswith("["):
            m = re.match(r"(\d+):(\d+)", line.split("=", 1)[1].split()[0])
            if m and path.startswith("/MUSICIANS/"):
                s = int(m.group(1)) * 60 + int(m.group(2))
                if 50 <= s <= 230:
                    out.append((path, s))
            path = None
    return out


def render(hvsc, out, count=40, seed=64):
    random.seed(seed)
    pick = random.sample(hvsc_lengths(hvsc), count)
    os.makedirs(out, exist_ok=True)

    def job(i):
        p, s = pick[i]
        f = os.path.join(out, "%02d.wav" % i)
        subprocess.run([VSID, "-console", "-sounddev", "wav", "-soundarg", os.path.abspath(f), "-soundrate", "48000",
                        "-limitcycles", str((s + EXTRA_S) * PAL_HZ), "-tune", "1", hvsc + p],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"path": p, "len": s, "wav": os.path.basename(f)}
    with ThreadPoolExecutor(8) as ex:
        meta = list(ex.map(job, range(count)))
    json.dump(meta, open(os.path.join(out, "set.json"), "w"), indent=1)


def evaluate(out):
    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from c64jukebox.loopfind import LoopFinder
    n = {"ok": 0, "BAD": 0, "NONE": 0}
    for m in json.load(open(os.path.join(out, "set.json"))):
        w = wave.open(os.path.join(out, m["wav"]))
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2")
        if w.getnchannels() == 2:
            x = x.reshape(-1, 2).mean(axis=1)
        lf = LoopFinder()
        for i in range(0, len(x), 4800):
            if lf.feed(x[i:i + 4800]):
                break
        r = lf.result()
        tag = "NONE" if not r else ("ok" if abs(r["len"] - m["len"]) <= 3 else "BAD")
        n[tag] += 1
        print("%-4s HVSC %3d s  found %-58s %s" % (tag, m["len"], r, m["path"]))
    print("right %(ok)d, wrong %(BAD)d, none %(NONE)d" % n)


if __name__ == "__main__":
    if sys.argv[1] == "render":
        render(sys.argv[2], sys.argv[3], *[int(a) for a in sys.argv[4:6]])
    else:
        evaluate(sys.argv[2])
