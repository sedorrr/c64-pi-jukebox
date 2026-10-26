"""Looks for the repeat of a tune without a known length (loopfind.py) in its own process: numpy and the comparisons
stay out of the jukebox (its loop must not stall - the stream waits for it), and a second core of the Pi does the work.

The process: python3 -m c64jukebox.loopwatch - the system's Python (python3-numpy, like the HDMI service; the
jukebox's venv has no numpy). It takes the audio packets on a UDP port of 127.0.0.1 (the stream distributor sends
them there only while a tune is looked at), commands on stdin ("start <id>" - a tune begins, "stop") and answers
on stdout, one JSON object per line: {"ready": port} once, then {"id", "len", "lag", "from", "at"} per repeat found.

LoopWatch is the jukebox's side: starts the process when it is first needed, keeps it, reads its answers."""
import asyncio
import json
import os
import socket
import sys

PYTHON = "/usr/bin/python3"              # None: switched off (the tests)
AUDIO_LEN = 770                          # 2 bytes sequence + 192 stereo frames int16 (stream.py)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LoopWatch:
    def __init__(self, on_found, python=None, log=None):
        self.on_found, self.python, self.log = on_found, python, log or (lambda t: None)
        self.proc = None
        self.port = None
        self.failed = ""                 # why it does not work (shown once in the event log)
        self._reader = None
        self._starting = None

    def available(self):
        return bool(self.python) and not self.failed

    async def ensure(self):
        """start the process if it does not run -> True when it runs"""
        if self.proc and self.proc.returncode is None and self.port:
            return True
        if not self.available():
            return False
        if self._starting is None:
            self._starting = asyncio.get_running_loop().create_task(self._start())
        try:
            return await asyncio.shield(self._starting)
        finally:
            if self._starting and self._starting.done():
                self._starting = None

    async def _start(self):
        try:
            self.proc = await asyncio.create_subprocess_exec(
                self.python, "-m", "c64jukebox.loopwatch", cwd=HERE, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            line = await asyncio.wait_for(self.proc.stdout.readline(), 30)
            self.port = int(json.loads(line)["ready"])
        except (OSError, ValueError, KeyError, asyncio.TimeoutError) as e:
            err = b""
            if self.proc and self.proc.returncode is None:
                self.proc.kill()
            if self.proc:
                try:
                    err = await asyncio.wait_for(self.proc.stderr.read(), 2)
                except asyncio.TimeoutError:
                    pass
            last = err.decode("utf-8", "replace").strip().splitlines()[-1:] or [str(e) or type(e).__name__]
            self.failed = last[0][:200]
            self.log("Wiederholungssuche nicht verfügbar: %s" % self.failed)
            self.proc, self.port = None, None
            return False
        self._reader = asyncio.get_running_loop().create_task(self._read())
        return True

    async def _read(self):
        proc = self.proc
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "id" in d:
                self.on_found(d)
        if self.proc is proc:                # ended by itself: started again when next needed
            self.proc, self.port = None, None

    def send(self, cmd):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.write((cmd + "\n").encode())
            except (OSError, RuntimeError):
                pass

    def begin(self, tid):
        self.send("start %s" % tid)

    def end(self):
        self.send("stop")

    async def close(self):
        if self._reader:
            self._reader.cancel()
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            try:
                await asyncio.wait_for(self.proc.wait(), 2)
            except asyncio.TimeoutError:
                pass
        self.proc = None


# ------------------------------------------------------------ the process
NICE = 15                                # the process' priority: below the HDMI service (nice 5), whose TV sound must
                                         # not wait - the jukebox runs at -5 and its child would inherit that (2026-10-24:
                                         # the TV sound went away for seconds while a tune without a length played)


def main():
    import select
    try:
        os.setpriority(os.PRIO_PROCESS, 0, NICE)
    except (OSError, AttributeError):
        pass
    import numpy as np
    from .loopfind import LoopFinder

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    s.bind(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 0))
    s.setblocking(False)
    print(json.dumps({"ready": s.getsockname()[1]}), flush=True)
    fd = sys.stdin.fileno()
    pending = b""
    lf, tid = None, None
    last = None                                          # sequence number of the last packet (both byte orders)
    silence = bytes(192 * 4)
    while True:
        r, _, _ = select.select([s, fd], [], [], 1.0)
        if fd in r:
            chunk = os.read(fd, 4096)
            if not chunk:
                return                                   # the jukebox has gone
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                cmd = line.decode("utf-8", "replace").split()
                if cmd and cmd[0] == "start" and len(cmd) > 1:
                    lf, tid, last = LoopFinder(), cmd[1], None
                elif cmd and cmd[0] == "stop":
                    lf, tid = None, None
        if s in r:
            data = []
            while True:
                try:
                    p = s.recv(2048)
                except BlockingIOError:
                    break
                if lf is not None and len(p) == AUDIO_LEN:
                    # packets lost while the search lagged behind (it runs at a low priority, the socket's buffer is
                    # small): silence in their place, else the tune's time would shrink and the length come out short
                    seq = (p[0] | p[1] << 8, p[1] | p[0] << 8)
                    if last is not None:
                        gaps = [(s - l) & 0xFFFF for s, l in zip(seq, last)]
                        gap = next((g for g in gaps if 1 <= g <= 2500), 1)       # the byte order that counts on
                        data.extend([silence] * (gap - 1))
                    last = seq
                    data.append(p[2:])
            if lf is not None and data:
                x = np.frombuffer(b"".join(data), "<i2").reshape(-1, 2).astype(np.float32).mean(axis=1)
                found = lf.feed(x)
                if found:
                    print(json.dumps(dict(found, id=tid)), flush=True)
                    lf = None


if __name__ == "__main__":
    main()
