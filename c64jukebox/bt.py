"""Bluetooth headphones for the TV sound: bluetoothctl (BlueZ) finds, pairs and connects them, bluez-alsa
(package bluez-alsa-utils) carries the sound - the sound process (hdmi/soundproc.py) then plays to the ALSA device
alsa_device(mac) instead of the HDMI card. Every call is a short bluetoothctl run of its own (no shell, no session),
so nothing waits on a Bluetooth stack that hangs: each run has a time limit."""
import asyncio
import os
import re
import signal
import shutil

MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
AUDIO_ICONS = ("audio-headset", "audio-headphones", "audio-card")
SCAN_S = 12
FIND_S = 15


def alsa_device(mac):
    """bluez-alsa's PCM for a device; "plug" converts the Ultimate's 47983 Hz to what the headphones take"""
    return "plug:'bluealsa:DEV=%s,PROFILE=a2dp'" % mac


def parse_devices(text):
    """'Device AA:BB:… Name' lines -> [(mac, name)]"""
    out = []
    for line in text.splitlines():
        m = re.search(r"Device ([0-9A-F:]{17}) ?(.*)$", line.strip())
        if m and MAC_RE.match(m.group(1)) and (m.group(1), m.group(2)) not in out:
            out.append((m.group(1), m.group(2).strip()))
    return out


def parse_info(text):
    """'bluetoothctl info' -> {"name", "icon", "paired", "bonded", "connected", "trusted"}"""
    d = {}
    for line in text.splitlines():
        k, _, v = line.strip().partition(": ")
        if k in ("Name", "Alias", "Icon", "Paired", "Bonded", "Connected", "Trusted"):
            d[k.lower()] = v.strip()
    yes = lambda k: d.get(k) == "yes"        # noqa: E731
    return {"name": d.get("alias") or d.get("name") or "", "icon": d.get("icon", ""), "paired": yes("paired"),
            "bonded": yes("bonded"), "connected": yes("connected"), "trusted": yes("trusted")}


class Bluetooth:
    def __init__(self, tool="bluetoothctl"):
        self.tool = tool if shutil.which(tool) else None
        self.msg = ""

    @property
    def present(self):
        return self.tool is not None

    async def run(self, *args, timeout=15, until=None):
        """(ok, output) of one bluetoothctl call; with until (a regex) it ends as soon as a line matches - with
        --timeout bluetoothctl would wait out the whole time even after the answer"""
        if not self.tool:
            return False, "bluetoothctl fehlt (Paket bluez)"
        try:
            p = await asyncio.create_subprocess_exec(self.tool, *args, stdin=asyncio.subprocess.DEVNULL,
                                                     stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return False, str(e)
        if until:
            return await self._run_until(p, until, timeout)
        try:
            out, _ = await asyncio.wait_for(p.communicate(), timeout)
        except asyncio.TimeoutError:
            p.kill()
            await p.wait()
            return False, "keine Antwort von Bluetooth"
        return p.returncode == 0, _clean(out)

    async def _run_until(self, p, until, timeout):
        out, hit = b"", None
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        try:
            while hit is None:
                line = await asyncio.wait_for(p.stdout.readline(), max(0.1, end - loop.time()))
                if not line:
                    break
                out += line
                hit = re.search(until, _clean(line))
        except asyncio.TimeoutError:
            pass
        if p.returncode is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)        # with anything it started that still holds the output
            except OSError:
                pass
        await p.wait()
        return (hit is not None or p.returncode == 0), _clean(out) or "keine Antwort von Bluetooth"

    async def power(self):
        ok, out = await self.run("power", "on")
        return ok or "succeeded" in out

    async def _need_power(self):
        if not await self.power():
            raise ValueError("Bluetooth lässt sich nicht einschalten – gesperrt (rfkill)? Das Installationsskript "
                             "hebt die Sperre auf: noch einmal ausführen")

    async def info(self, mac):
        ok, out = await self.run("info", mac, timeout=5)
        return parse_info(out) if ok and "not available" not in out and ("Device " + mac in out or "Name:" in out) \
            else None

    async def devices(self, paired_only=True):
        """[{"mac", "name", "icon", "paired", "connected", "trusted"}] - only headphones and speakers"""
        ok, out = await self.run("devices", *(["Paired"] if paired_only else []), timeout=5)
        res = []
        for mac, name in parse_devices(out):
            i = await self.info(mac)
            if i is None or (i["icon"] and i["icon"] not in AUDIO_ICONS):
                continue
            res.append(dict(i, mac=mac, name=i["name"] or name))
        return res

    async def scan(self, secs=SCAN_S):
        """search for secs, then every audio device seen that is not paired yet"""
        await self._need_power()
        await self.run("--timeout", str(secs), "scan", "on", timeout=secs + 10)
        return [d for d in await self.devices(paired_only=False) if not d["paired"]]

    async def find(self, mac, secs=None):
        """search until mac is seen again: BlueZ forgets a device found by scan() 30 s after that search ended,
        and pair() can only pair one it knows. The search stops before pairing (it would slow pairing down)."""
        secs = secs or FIND_S
        p = await asyncio.create_subprocess_exec(self.tool, "--timeout", str(secs + 5), "scan", "on",
                                                 stdin=asyncio.subprocess.DEVNULL,
                                                 stdout=asyncio.subprocess.DEVNULL,
                                                 stderr=asyncio.subprocess.DEVNULL)
        try:
            for _ in range(secs):
                if await self.info(mac) is not None:
                    return True
                await asyncio.sleep(1)
            return False
        finally:
            if p.returncode is None:
                p.kill()
                await p.wait()

    async def pair(self, mac):
        """pair + trust (it may connect by itself later) + connect; headphones need no PIN ("just works")"""
        await self._need_power()
        if not await self.find(mac):
            raise ValueError("Kopfhörer %s nicht mehr gefunden – noch im Kopplungsmodus? Danach noch einmal suchen" % mac)
        # trusted first: BlueZ then keeps the device - a found one is "temporary" and gone 30 s after pairing if
        # the headphones did not bond (seen with Beats Fit Pro: "Pairing successful", then "not available")
        await self.run("trust", mac)
        # without "pairable" BlueZ pairs but stores no key (Paired yes, Bonded no): the headphones refuse the Pi
        # after the next switch-off ("Permission denied")
        await self.run("pairable", "on")
        ok, out = await self.run("--agent", "NoInputNoOutput", "--timeout", "30", "pair", mac, timeout=40,
                                 until=r"Pairing successful|Failed to pair|AlreadyExists|not available")
        self.msg = _last(out)
        i = await self.info(mac)
        if not i or not i["paired"]:
            raise ValueError("Koppeln fehlgeschlagen – ist der Kopfhörer im Kopplungsmodus? (%s)" % _last(out))
        return await self.connect(mac)

    async def connect(self, mac):
        await self._need_power()
        ok, out = await self.run("connect", mac, timeout=25,
                                 until=r"Connection successful|Failed to connect|not available")
        i = await self.info(mac)
        if not i or not i["connected"]:
            raise ValueError("Verbinden fehlgeschlagen – ist der Kopfhörer eingeschaltet? (%s)" % _last(out))
        return i

    async def disconnect(self, mac):
        await self.run("disconnect", mac)

    async def remove(self, mac):
        await self.run("remove", mac)


def _clean(raw):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02", "", raw.decode("utf-8", "replace"))


def _last(out):
    """bluetoothctl's answer to the command - not the [NEW]/[DEL]/[CHG] lines a running search adds"""
    lines = [x.strip() for x in out.splitlines() if x.strip() and not re.match(r"\[(NEW|DEL|CHG)\]", x.strip())]
    key = [x for x in lines if re.search(r"Fail|Error|succe|not available", x)]
    return (key or lines or ["keine Meldung"])[-1][:100]
