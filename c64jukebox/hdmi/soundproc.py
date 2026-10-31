"""The TV sound in a process of its own (2026-10-24): in the HDMI service it shared Python's lock with the pictures -
with the Pi warm (1.2 GHz) that process needed a whole core, packets for aplay waited, were dropped (1424 in 10 min)
and the sound went away now and then. Now the jukebox sends the stream straight to this process (SOUND_PORT); it only
puts the packets through the fade/volume and into aplay, on a core of its own.

    python3 -m c64jukebox.hdmi.soundproc <port> [aplay command as JSON]

stdin: "fade <target 0..1> <seconds>", "vol <0..1>"; stdout: {"ready": port} once, then every second
{"ok": aplay runs, "msg", "gaps": [...], "dropped": n}. SoundProc is the HDMI service's side, with the interface of
Sound (fade_to, gain/target/step, volume, msg, gaps, dropped, close)."""
import json
import os
import queue
import re
import select
import socket
import subprocess
import sys
import threading
import time
from collections import deque

import numpy as np

from ..i18n import tr
from .modes import SOUND_DEVICE, SOUND_PORT

AUDIO_LEN = 770                                    # 2 bytes sequence + 192 stereo frames int16

QUIET_SPAN = 64                                    # peak-to-peak below this in a packet: nothing to hear
QUIET_S = 1.0                                      # this long quiet after sound: logged
FILL_S = 0.04                                      # no packet this long: as much silence to aplay instead
FILL_MAX_S = 2.0                                   # ... but only this long (the stream has stopped: let it rest)
SILENCE = bytes(192 * 4 * 10)                      # 10 packets' worth = 40 ms: what the card plays meanwhile
STUCK_S = 0.5                                      # aplay takes nothing this long (its buffer is 150 ms): restarted
GAP_S = 0.12                                       # a pause this long between packets to aplay: logged


def sound_device(cards="/proc/asound/cards"):
    """the ALSA device of the HDMI output: the Pi 3 calls its card "vc4hdmi", the Pi 4 "vc4hdmi0" / "vc4hdmi1"
    (the first is the port next to the power socket)"""
    try:
        with open(cards) as f:
            ids = [line.split("[", 1)[1].split("]", 1)[0].strip() for line in f if "[" in line and "]:" in line]
    except OSError:
        return SOUND_DEVICE
    hdmi = sorted(i for i in ids if i.startswith("vc4hdmi"))
    return "default:CARD=%s" % hdmi[0] if hdmi else SOUND_DEVICE


class Sound:
    """the Ultimate's sound over HDMI to the TV: every packet to aplay (ALSA converts 47983 Hz for the output).
    A queue + thread of its own, so the receiving never waits for the sound card; if the queue grows (clocks drift
    apart, the card hung) packets are dropped instead of delaying the sound more and more."""
    QUEUE = 12                                     # packets (4 ms each): at most ~50 ms on top of aplay's buffer

    def __init__(self, cmd=None):
        self.custom = cmd is not None                  # tests: something instead of aplay
        self.device = ""                               # "" = the HDMI card, else e.g. Bluetooth headphones (bt.py)
        self.cmd = cmd or self._aplay(sound_device())
        self.opened_at = 0.0
        self.q = queue.Queue(self.QUEUE)
        self.proc = None
        self.dropped = 0
        # fade between songs (like the PC jukebox's "Fade between songs"): a factor ramped per sample in _run
        self.gain, self.target, self.step = 1.0, 1.0, 0.0
        self.volume = 1.0                              # the page's volume (0..1), on top of the fade
        self.msg = ""
        # diagnosis (2026-10-24, the TV sound went away now and then): pauses between two packets to aplay while
        # packets keep coming - longer than aplay's buffer they are heard as a gap
        self.gaps = deque(maxlen=12)
        self.last_put = self.last_write = None
        # silence in the stream itself (the Ultimate sent nothing to hear) - against a gap behind aplay (TV, HDMI)
        self.quiet_since, self.loud = None, False
        self.restarts = 0
        self.filled = 0                                    # silence pieces put in to keep the card going
        self.stop_ev = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="sound")
        self.thread.start()

    @staticmethod
    def _aplay(dev):
        return ["aplay", "-q", "-D", dev, "-f", "S16_LE", "-c", "2", "-r", "47983", "-t", "raw",
                "--buffer-time=150000", "--period-time=30000", "-"]

    def set_device(self, dev):
        """another output ("" = HDMI): the running aplay ends, the next packet starts one there"""
        if dev == self.device:
            return
        self.device = dev
        if not self.custom:
            self.cmd = self._aplay(dev or sound_device())
        self.gaps.append("%s Ausgabe: %s" % (time.strftime("%H:%M:%S"), dev or "HDMI"))
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def fade_to(self, target, secs):
        """ramp the volume to target (0..1) over secs; secs <= 0 sets it at once"""
        target = max(0.0, min(1.0, float(target)))
        if secs and secs > 0:
            self.step = abs(target - self.gain) / max(1.0, secs * 47983)
        else:
            self.gain, self.step = target, 0.0
        self.target = target

    def _apply_gain(self, frames):
        vol = self.volume
        if self.step == 0.0 and self.gain >= 1.0 and vol >= 1.0:
            return frames
        a = np.frombuffer(frames, dtype="<i2").reshape(-1, 2).astype(np.float32)
        n = len(a)
        if self.step:
            d = self.step if self.target > self.gain else -self.step
            ramp = self.gain + d * np.arange(1, n + 1, dtype=np.float32)
            ramp = np.minimum(ramp, self.target) if d > 0 else np.maximum(ramp, self.target)
            self.gain = float(ramp[-1])
            if self.gain == self.target:
                self.step = 0.0
        else:
            ramp = np.full(n, self.gain, dtype=np.float32)
        return (a * (ramp * vol)[:, None]).astype("<i2").tobytes()

    def feed(self, frames):
        self.last_put = now = time.monotonic()
        a = np.frombuffer(frames, dtype="<i2")
        if len(a) and int(a.max()) - int(a.min()) < QUIET_SPAN:
            if self.quiet_since is None:
                self.quiet_since = now
        else:
            if self.quiet_since is not None and self.loud and now - self.quiet_since >= QUIET_S:
                self.gaps.append("%s Stille im Stream %.1f s (vom Ultimate)" % (
                    time.strftime("%H:%M:%S", time.localtime(time.time() - (now - self.quiet_since))),
                    now - self.quiet_since))
            self.quiet_since, self.loud = None, True
        try:
            self.q.put_nowait(frames)
        except queue.Full:
            self.dropped += 1
            self._stuck(now)

    def _stuck(self, now):
        """aplay takes nothing while packets keep coming: the HDMI sound hung (2026-10-26, 22:14: ~4 s, then aplay
        reported an underrun) - end it, the sound thread starts a new one with the next packet"""
        p, w = self.proc, self.last_write
        if p is None or w is None or now - w < STUCK_S or p.poll() is not None:
            return
        self.gaps.append("%s aplay hing %.1f s - neu gestartet" % (time.strftime("%H:%M:%S"), now - w))
        self.restarts += 1
        self.last_write = now                              # one restart per hang
        try:
            p.kill()
        except OSError:
            pass

    def _open(self):
        self.opened_at = time.monotonic()
        try:
            self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.PIPE)
            self.msg = ""
            threading.Thread(target=self._errors, args=(self.proc,), daemon=True, name="aplay-err").start()
        except OSError as e:
            self.proc, self.msg = None, "Ton: %s" % e

    def _errors(self, proc):
        """aplay's own complaints (underrun: the card ran empty behind us) into the gaps"""
        for line in proc.stderr:
            text = line.decode("utf-8", "replace").strip()
            if text and not re.match(r"^\[\d+\] D: ", text):          # bluez-alsa's debug lines
                self.gaps.append("%s aplay: %s" % (time.strftime("%H:%M:%S"), text[:80]))

    def _run(self):
        while not self.stop_ev.is_set():
            try:
                frames = self.q.get(timeout=FILL_S)
            except queue.Empty:
                # no packet for a moment: keep the card fed with a bit of silence. An underrun restarts the HDMI
                # sound, and many TVs then mute for 2-3 s (2026-10-26: aplay "underrun" each time the sound was gone)
                w = self.last_write
                if self.proc is None or self.proc.poll() is not None or w is None or \
                        time.monotonic() - w > FILL_MAX_S:
                    continue
                frames = SILENCE
                self.filled += 1
            if self.proc is None or self.proc.poll() is not None:
                if time.monotonic() - self.opened_at < 1.0:   # aplay ended at once (headphones away): not 250 a second
                    continue
                self._open()
                if self.proc is None:
                    time.sleep(2)
                    continue
            t = time.monotonic()
            if frames is not SILENCE and self.last_write is not None and t - self.last_write > GAP_S and \
                    self.last_put and t - self.last_put < 1.0:
                self.gaps.append("%s %d ms (Warteschlange %d, verworfen %d)" % (time.strftime("%H:%M:%S"),
                                                                                 (t - self.last_write) * 1000,
                                                                                 self.q.qsize(), self.dropped))
            if frames is not SILENCE:
                self.last_write = t
            try:
                self.proc.stdin.write(self._apply_gain(frames))
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self.proc = None                       # aplay ended: start it again with the next packet

    def close(self):
        self.stop_ev.set()
        self.thread.join(1)
        if self.proc:
            try:
                self.proc.stdin.close()                    # aplay plays what it has and ends
                self.proc.wait(1)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.proc.kill()
        self.proc = None


class SoundProc:
    """the HDMI service's handle on the sound process: commands down, state up; the fade is followed here by the
    clock (gain/step), the process ramps the same way"""

    def __init__(self, port=SOUND_PORT, cmd=None, python=None, clock=time.monotonic):
        self.clock = clock
        self.port = None
        self.msg, self.gaps, self.dropped, self.ok = "", [], 0, False
        self.filled = self.restarts = 0
        self._ramp = (1.0, 1.0, 0.0, 0.0)              # from, to, start, seconds
        self._vol = 1.0
        self._dev = ""
        self.dev = ""                                  # what the process plays to now (its report)
        args = [python or sys.executable, "-m", "c64jukebox.hdmi.soundproc", str(port)] + ([json.dumps(cmd)] if cmd else [])
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            self.proc = subprocess.Popen(args, cwd=here, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as e:
            self.proc, self.msg = None, tr("Ton: %s") % e
            return
        line = self.proc.stdout.readline()
        try:
            self.port = json.loads(line)["ready"]
        except (ValueError, KeyError):
            self.msg = tr("Ton: Prozess startet nicht")
            return
        threading.Thread(target=self._read, daemon=True, name="sound-state").start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("msg", "")                    # the process knows no language: "Ton: <error>" from it
            self.ok, self.msg = d.get("ok", False), tr("Ton: %s") % msg[5:] if msg.startswith("Ton: ") else msg
            self.gaps, self.dropped = d.get("gaps", []), d.get("dropped", 0)
            self.filled, self.restarts = d.get("filled", 0), d.get("restarts", 0)
            self.dev = d.get("dev", "")

    def _send(self, text):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write((text + "\n").encode())
            except (OSError, ValueError):
                pass

    # ---- what the fade logic reads (like Sound)
    @property
    def gain(self):
        g0, g1, t0, secs = self._ramp
        if secs <= 0:
            return g1
        f = (self.clock() - t0) / secs
        return g1 if f >= 1 else g0 + (g1 - g0) * max(0.0, f)

    @property
    def target(self):
        return self._ramp[1]

    @property
    def step(self):
        g0, g1, t0, secs = self._ramp
        return 1.0 if secs > 0 and self.clock() - t0 < secs and g0 != g1 else 0.0

    def fade_to(self, target, secs):
        target = max(0.0, min(1.0, float(target)))
        self._ramp = (self.gain, target, self.clock(), max(0.0, float(secs or 0)))
        self._send("fade %.4f %.3f" % (target, max(0.0, float(secs or 0))))

    @property
    def volume(self):
        return self._vol

    @volume.setter
    def volume(self, v):
        if abs(v - self._vol) > 1e-4:
            self._vol = v
            self._send("vol %.4f" % v)

    @property
    def device(self):
        return self._dev

    @device.setter
    def device(self, dev):
        """the ALSA output: "" = the HDMI card, else Bluetooth headphones (bt.alsa_device)"""
        if dev != self._dev and " " not in dev:
            self._dev = dev
            self._send("dev %s" % (dev or "-"))

    def alive(self):
        return bool(self.proc and self.proc.poll() is None and self.ok)

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()                    # the process plays what it has and ends
                self.proc.wait(2)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.proc.kill()
        self.proc = None


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else SOUND_PORT
    cmd = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 18)
    s.bind(("127.0.0.1", port))
    snd = Sound(cmd)
    print(json.dumps({"ready": s.getsockname()[1]}), flush=True)
    fd = sys.stdin.fileno()
    pending, report = b"", 0.0
    while True:
        r, _, _ = select.select([s, fd], [], [], 0.5)
        if s in r:
            p = s.recv(2048)
            if len(p) == AUDIO_LEN:
                snd.feed(p[2:])
        if fd in r:
            chunk = os.read(fd, 1024)
            if not chunk:
                break                                      # the HDMI service closed us
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                c = line.decode("ascii", "replace").split()
                try:
                    if c and c[0] == "fade" and len(c) == 3:
                        snd.fade_to(float(c[1]), float(c[2]))
                    elif c and c[0] == "vol" and len(c) == 2:
                        snd.volume = max(0.0, min(1.0, float(c[1])))
                    elif c and c[0] == "dev" and len(c) == 2:
                        snd.set_device("" if c[1] == "-" else c[1])
                except ValueError:
                    pass
        now = time.monotonic()
        if now - report >= 1.0:
            report = now
            ok = bool(snd.proc and snd.proc.poll() is None)
            print(json.dumps({"ok": ok, "msg": snd.msg, "gaps": list(snd.gaps), "dropped": snd.dropped,
                              "filled": snd.filled, "restarts": snd.restarts, "dev": snd.device}), flush=True)
    snd.close()


if __name__ == "__main__":
    main()
