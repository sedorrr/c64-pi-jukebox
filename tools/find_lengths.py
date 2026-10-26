#!/usr/bin/env python3
"""Find the song lengths of SID files the length databases do not know - on the Mac, for whole folders.

For every .sid below the given folders whose MD5 is not in the HVSC Songlengths.md5 (nor in an own lengths file):
  1. by name: the same tune in another version in the HVSC (c64jukebox/namematch.py) - with --hvsc-dir the music data
     behind the header is compared too ("hvsc-same": byte-equal, the length is sure; "hvsc-other": another version)
  2. by listening: every sub-song is played with libsidplayfp (tools/sidlen/sidrender, ~80 x real time) and
     - "end": the tune stops (4 s of silence after it played) - the length is where the silence began
     - "loop": it starts again from the beginning (c64jukebox/loopfind.py, right about 4 times in 5)
Writes a user_songlengths.txt (the PC jukebox's format, one line "md5=m:ss m:ss ..." per file, all sub-songs) for the
web page of the Pi (Einstellungen -> Songlängen -> eigene Längen hinzufügen) or the PC jukebox, and a CSV report with
how each length was found. Files with a sub-song left unknown are only in the report.

    python3 tools/find_lengths.py <folder> [...] --hvsc .../DOCUMENTS/Songlengths.md5 [--hvsc-dir .../C64Music]
        [--known user_songlengths.txt] [--out user_songlengths.txt] [--report lengths.csv] [--max-min 10]
        [--kinds hvsc-same,end,loop] [--jobs 8]

Needs numpy and tools/sidlen/sidrender (build: see tools/sidlen/sidrender.cpp)."""
import argparse
import csv
import hashlib
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from c64jukebox import imports, namematch, sidfile, songlengths  # noqa: E402

RENDER = os.path.join(ROOT, "tools", "sidlen", "sidrender")
VICE_ROMS = "/Applications/vice-arm64-sdl2-3.9/VICE.app/Contents/Resources/share/vice/C64"
ROMS = [os.path.join(VICE_ROMS, f) for f in ("kernal-901227-03.bin", "basic-901226-01.bin", "chargen-906143-02.bin")]
RATE = 48000
SILENT_SPAN = 40              # peak-to-peak of a 0.1 s piece below this: silence (the SID's DC offset is no sound)
END_SILENCE_S = 4.0           # this long silent after it played: the tune has ended
KINDS = ("hvsc-same", "hvsc-other", "end", "loop")


def body(data):
    return data[int.from_bytes(data[6:8], "big"):]


def listen(path, song, max_s):
    """play one sub-song -> ("end"|"loop", seconds) or (None, why)"""
    import numpy as np
    from c64jukebox.loopfind import LoopFinder
    args = [RENDER, path, str(song), str(max_s)] + (ROMS if all(os.path.exists(r) for r in ROMS) else [])
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lf = LoopFinder(max_s=max_s + 5)
    t = 0.0                    # seconds read
    loud_at = None             # end of the last piece with sound
    heard = False
    try:
        while True:
            raw = p.stdout.read(RATE * 2)                     # one second
            if not raw:
                break
            x = np.frombuffer(raw[:len(raw) // 2 * 2], "<i2")
            for k in range(0, len(x), RATE // 10):
                piece = x[k:k + RATE // 10]
                if len(piece) and int(piece.max()) - int(piece.min()) >= SILENT_SPAN:
                    heard, loud_at = True, t + (k + len(piece)) / RATE
            t += len(x) / RATE
            if heard and t - loud_at >= END_SILENCE_S:
                return "end", round(loud_at)
            r = lf.feed(x)
            if r:
                return "loop", round(r["len"])
    finally:
        p.kill()
        p.wait()
    err = p.stderr.read().decode("utf-8", "replace").strip().splitlines()
    bad = [e for e in err if e.startswith("error")]
    if bad:
        return None, bad[0]
    return None, "nichts in %d min" % (max_s // 60) if heard else "kein Ton"


def work(job):
    """one file -> dict for the report"""
    path, md5, head, hv, hv_dir, kinds, max_s = job
    n = max(1, head.get("songs") or 1)
    out = {"path": path, "md5": md5, "title": head.get("title", ""), "author": head.get("author", ""), "songs": n}
    if hv:                                                    # 1. by name
        hpath, hmd5, lens = hv
        kind = "hvsc-other"
        if hv_dir:
            try:
                with open(path, "rb") as f1, open(os.path.join(hv_dir, hpath.lstrip("/")), "rb") as f2:
                    kind = "hvsc-same" if body(f1.read()) == body(f2.read()) else "hvsc-other"
            except OSError:
                pass
        if kind in kinds and len(lens) == n:
            return dict(out, lens=list(lens), how=[kind] * n, note=hpath)
    lens, how, notes = [], [], []                            # 2. by listening
    for s in range(1, n + 1):
        kind, v = listen(path, s, max_s)
        if kind in kinds:
            lens.append(v)
            how.append(kind)
        else:
            lens.append(None)
            how.append(kind or "-")
            if not kind:
                notes.append("Lied %d: %s" % (s, v))
    return dict(out, lens=lens, how=how, note="; ".join(notes) or (hv[0] if hv else ""))


def fmt(s):
    return "%d:%02d" % (s // 60, s % 60)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--hvsc", help="Songlengths.md5 of the HVSC")
    ap.add_argument("--hvsc-dir", help="the HVSC folder (C64Music) - compares the music data of name matches")
    ap.add_argument("--known", help="own lengths already there (user_songlengths.txt): those files are skipped")
    ap.add_argument("--out", default="user_songlengths.txt")
    ap.add_argument("--report", default="lengths.csv")
    ap.add_argument("--max-min", type=float, default=10, help="listen this long at most per sub-song")
    ap.add_argument("--kinds", default="hvsc-same,end,loop", help="which findings go into the file: " + ",".join(KINDS))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    a = ap.parse_args()
    if not os.path.exists(RENDER):
        sys.exit("tools/sidlen/sidrender fehlt - bauen, siehe tools/sidlen/sidrender.cpp")
    kinds = set(a.kinds.split(","))
    sl = songlengths.SongLengths()
    ix = None
    if a.hvsc:
        text = open(a.hvsc, encoding="latin-1").read()
        sl.load("hvsc", text)
        ix = namematch.NameIndex(imports.hvsc_paths(text))
    if a.known:
        sl.load("custom", open(a.known, encoding="latin-1").read())

    jobs, known, seen = [], 0, set()
    for folder in a.folders:
        for d, _, files in os.walk(folder):
            for f in sorted(files):
                if not f.lower().endswith(".sid"):
                    continue
                p = os.path.join(d, f)
                data = open(p, "rb").read()
                md5 = hashlib.md5(data).hexdigest()
                head = sidfile.parse_header(data)
                if not head or md5 in seen:
                    continue
                seen.add(md5)
                if sl.lookup(md5, 1):
                    known += 1
                    continue
                hv = None
                if ix:
                    r = ix.find(f, head.get("title"), head.get("author"))
                    if r:
                        lens = sl.hvsc.get(bytes.fromhex(r[1]))
                        if lens:
                            hv = (r[0], r[1], lens)
                jobs.append((p, md5, head, hv, a.hvsc_dir, kinds, int(a.max_min * 60)))
    print("%d Dateien schon bekannt, %d zu ermitteln (%d Prozesse)" % (known, len(jobs), a.jobs), flush=True)

    rows, t0 = [], time.time()
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for k, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            rows.append(r)
            ok = all(x is not None for x in r["lens"])
            print("[%d/%d] %-9s %-28s %s" % (k, len(jobs), ",".join(sorted(set(r["how"]))),
                                            " ".join(fmt(x) if x is not None else "?" for x in r["lens"])[:28],
                                            os.path.basename(r["path"])) + ("" if ok else "  (unvollständig)"), flush=True)

    rows.sort(key=lambda r: r["path"])
    done = [r for r in rows if all(x is not None for x in r["lens"])]
    with open(a.out, "w", encoding="latin-1") as f:
        f.write("# song lengths found by tools/find_lengths.py (%s): %s\n" % (time.strftime("%Y-%m-%d"), ", ".join(sorted(kinds))))
        f.write("# Format: <md5>=<m:ss> per sub-song\n")
        for r in done:
            f.write("%s=%s\n" % (r["md5"], " ".join(fmt(x) for x in r["lens"])))
    with open(a.report, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Datei", "Titel", "Komponist", "Lieder", "Längen", "gefunden durch", "Hinweis", "MD5"])
        for r in rows:
            w.writerow([r["path"], r["title"], r["author"], r["songs"],
                        " ".join(fmt(x) if x is not None else "?" for x in r["lens"]), " ".join(r["how"]), r["note"], r["md5"]])
    by = {}
    for r in rows:
        for h in r["how"]:
            by[h] = by.get(h, 0) + 1
    print("\nfertig in %.0f s: %d Dateien vollständig -> %s, Bericht -> %s" % (time.time() - t0, len(done), a.out, a.report))
    print("Unterlieder: " + ", ".join("%s %d" % kv for kv in sorted(by.items())))


if __name__ == "__main__":
    main()
