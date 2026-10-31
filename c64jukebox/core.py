"""Everything together: settings, sources, cache, song lengths, player, stream distributor, device list, the
background clock and the jobs the page starts (folder scans, search, network search)."""
import asyncio
import io
import json
import os
import re
import secrets
import time

import aiohttp

from . import VERSION, sidfile
from .catalog import Catalog
from .config import Config
from .devices import DEV_PORT, Devices
from .display import Display
from .hdmi.modes import AUDIO_PORT as HDMI_AUDIO_PORT, BACKGROUNDS, MODES as HDMI_MODES, VIDEO_PORT as HDMI_VIDEO_PORT
from .hdmi.modes import SID_PORT as HDMI_SID_PORT, SOUND_PORT as HDMI_SOUND_PORT
from . import imports
from .netscan import scan, subnet_hosts
from .news import DEFAULT_FEEDS, News
from . import schedule, smartlist
from .cec import KEY_NAMES, CecLink, CecProtocol
from .sidaddr import SidAddressing
from .stil import Stil
from . import arpfix, bt, events, loopwatch, namematch, plug, tvmenu, wol
from .nowplaying import Notifier, news_body
from .player import LIST_MAX, Player
from .songlengths import SongLengths, parse as parse_lengths
from .stats import History, Stats
from .sources import Sources, SourceError, host_of, norm, smb_shares
from .stream import StreamHub, local_ip
from .ultimate import STREAM_PORT, Ultimate, UltimateError

SEARCH_MAX = 500
# the published program: its VERSION is compared with ours once a day (a hint; installed only on request)
UPDATE_URL = "https://raw.githubusercontent.com/sedorrr/c64-pi-jukebox/main/c64jukebox/__init__.py"
UPDATE_EVERY_S = 86400
UPDATE_UNIT = "c64jukebox-update.service"   # root, from install.sh: downloads the program and runs install.sh (update.sh)
UPDATE_NOTE_S = 3600                        # its result shown on the page and the TV this long after it ended
TV_BOOT_S = 90             # TV on at the start (cec.tv_on_boot): only this long after it - later, the TV seen
                           # for the first time is someone switching it on, not to be pulled to the Pi
PI_OFF_S = 60               # TV to standby -> Pi off (cec.pi_off); the TV on again within it keeps the Pi on
TV_ASK_S = 30               # how often the TV is asked whether it is on (some do not announce their standby)


def version_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))
INFO_SONGS_MAX = 64
HDMI_IMAGES_MAX = 300
HDMI_IMAGE_SIZE = (1920, 1080)
HDMI_IMAGE_BYTES = 40 << 20                   # a picture file larger than this is skipped
HDMI_IMAGE_EXT = (".jpg", ".jpeg", ".png")
HDMI_SYNC_S = 600                             # pictures from a source: compared again every 10 min


def compact(head, md5, sl):
    """header data for the page, with the length of each sub-song"""
    n = min(head["songs"], INFO_SONGS_MAX)
    return {"t": head["title"], "a": head["author"], "r": head["released"], "y": head["year"], "n": head["songs"],
            "st": head["start"], "c": head["chips"], "sid": head["sids"], "m": head.get("models", []),
            "md5": md5, "lens": [sl.lookup(md5, s) for s in range(1, n + 1)]}


class Job:
    def __init__(self, kind):
        self.id = secrets.token_hex(6)
        self.kind = kind
        self.done = False
        self.progress = ""
        self.pct = None           # 0-100 when known
        self.info = {}            # details for the page (network search: addresses being checked, found so far)
        self.result = None
        self.error = ""
        self.task = None
        self.t = time.monotonic()

    def json(self):
        return {"id": self.id, "kind": self.kind, "done": self.done, "progress": self.progress, "pct": self.pct,
                "info": self.info,
                "result": self.result, "error": self.error}


class Jukebox:
    def __init__(self, data_dir, stream_port=STREAM_PORT, dev_port=DEV_PORT, bcast="255.255.255.255",
                 scan_hosts=None, scan_ports=None, clock=time.monotonic, run_dir="/run/c64pi"):
        self.data_dir = data_dir
        self.run_dir = run_dir                 # network watcher (netwatch.py): net.json, request.json, web
        self._web_touch = 0.0
        self.config = Config(data_dir)
        self.sources = Sources(self.config)
        self.catalog = Catalog(os.path.join(data_dir, "cache.db"))
        self.stats = Stats(os.path.join(data_dir, "stats.json"))
        self.history = History(os.path.join(data_dir, "history.json"))
        self.display = Display(lambda: self.config["display"], on_touch=self._touch,
                               save=lambda: self._in_loop(self.config.save))
        self._aloop = None
        self._disp_busy = False
        self.songlengths = SongLengths()
        self.stream_port, self.dev_port, self.bcast = stream_port, dev_port, bcast
        self.scan_hosts, self.scan_ports = scan_hosts, scan_ports
        self.scan_timeout = 0.7
        self.clock = clock
        self.jobs = {}
        self.list_sort = {}
        self._head_cache = (None, 0, 0)
        self.started = time.time()
        self._names = {}
        self.stream_msg = ""
        self._stream_req_at = -1e9
        self._stream_asked = ""          # the Ultimate we asked for the stream
        self._foreign_stop_at = -1e9     # last "audio:stop" to an entered Ultimate that streams but is not chosen
        self.session = None
        self.hub = self.devices = self.notifier = self.player = None
        self.bg = None
        self.hdmi_audio_port, self.hdmi_video_port, self.hdmi_sid_port = HDMI_AUDIO_PORT, HDMI_VIDEO_PORT, HDMI_SID_PORT
        self.hdmi_sound_port = HDMI_SOUND_PORT
        self._arp_at = -1e9                 # last time the Pi announced itself to a hanging Ultimate (arpfix.py)
        self._ev_active, self._ev_foreign, self._ev_foreign_at = None, 0, -1e9   # events.py: what was logged last
        self._ev_weak_at = -1e9
        self._ev_drop = {}                  # target IP -> (dropped count logged, time)
        self.arp_log = []                   # (time, Ultimate, result) of those, for the page
        self._sid_asked = ""                # the Ultimate we asked for the debug stream (SID voices on the TV)
        self._sid_req_at = -1e9
        self.sid_msg = ""
        self._hdmi_was_on = True            # write hdmi-in.json once at start even when off
        self._video_asked = ""              # the Ultimate we asked for the video stream
        self._video_req_at = -1e9
        self.video_msg = ""
        self._hdmi_sync_at = -1e9
        self.hdmi_sync_job = None
        self._thumbs = {}                    # (src, path) -> small JPEG for the folder picker, the last 300
        self.news = News(os.path.join(data_dir, "news-img"), clock=clock)
        self.sidaddr = SidAddressing(os.path.join(data_dir, "sid-socket.json"))
        self.side = {}                                   # name -> task: what the clock started and must not start twice
        self.cec = None                                  # CecLink while the TV's remote is on
        self.sched_fired = set()                         # (entry id, minute) that ran
        self._hvsc_list = (None, [])                     # (mtime of the stored Songlengths.md5, smartlist.parse_hvsc)
        self._hvsc_hay = (None, [])                      # (that mtime, [(path, md5, text to search)]) - hvsc_hay()
        self.update = None                               # {"ver", "newer", "at"} of the last look at GitHub
        self._update_at = time.monotonic() - UPDATE_EVERY_S + 60      # the first look a minute after the start
        self.sched_msg = ""                              # what the timer did last (for the page)
        self.cec_ready = False
        self.cec_retry_at = -1e9
        self.cec_was_playing = False
        self.cec_stopped_at = None                       # since when nothing plays (TV to standby after tv_off_min)
        self.tv_seen_on = False                          # the TV was on while the Pi ran (pi_off needs it)
        self.tv_off_at = None                            # since when it is off (Pi off after PI_OFF_S)
        self.tv_ask_at = -1e9
        self.tv_boot_until = None                        # cec.tv_on_boot: TV on until then (set at the start)
        self.stil = Stil()
        self.menu = tvmenu.TvMenu(self, self.clock)       # the menu on the TV (remote keys over HDMI-CEC)
        self.bt = bt.Bluetooth()                          # headphones for the TV sound
        self.plug = plug.Plug()                           # the smart plug the Pi hangs on (switched off after shutdown)
        self.power_cmd = ["systemctl", "poweroff"]        # allowed to the service by polkit (install.sh)
        self.power_can_cmd = ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                              "org.freedesktop.login1.Manager", "CanPowerOff"]
        self.powering_off = False
        # the update on request: the service may start this one unit (polkit rule from install.sh), nothing else
        self.update_cmd = ["systemctl", "start", "--no-block", UPDATE_UNIT]
        self.update_can_cmd = ["systemctl", "show", "-p", "LoadState", "--value", UPDATE_UNIT]
        self.updating = False
        self._update_mtime = None
        self.bt_conn = False                              # the chosen headphones are connected
        self.bt_at = 0.0
        self.power_msg = ""                               # what switching an Ultimate on/off did last
        # repeat of a tune without a length (loopwatch.py): the tune looked at, since when, and what was found
        self.loops = None
        self._loop_cur, self._loop_id, self._loop_el0 = None, 0, 0.0
        self.loop_hint = None                             # {"len", "lag", "cur"} for the tune that plays
        self.name_hint = None                             # {"len", "songs", "path", "cur"}: same name in the HVSC
        self.list_hits = []                               # "Längen prüfen": [(md5, songs, hvsc path)] not taken yet
        self._name_seen = None
        self.hvsc_by_md5 = {}                # md5 -> HVSC path (from Songlengths.md5): STIL for files outside the HVSC

    # ------------------------------------------------------------ start / stop
    async def start(self):
        t0 = time.monotonic()
        self._aloop = asyncio.get_running_loop()
        self.session = aiohttp.ClientSession()
        self.hub = await StreamHub(self.stream_port, clock=self.clock).start()
        self.devices = await Devices(self.self_beacon, self.dev_port, self.bcast).start()
        self._my_ips()                                   # before our own beacon comes back (else "Gerät da: c64pi")
        self.notifier = Notifier(self.config, self.session, self.hub.send, self.resolve)
        self.player = Player(self, clock=self.clock)
        self.player.load_from(self._current_path())
        self.loops = loopwatch.LoopWatch(self._loop_found, python=loopwatch.PYTHON, log=events.log)
        t1 = time.monotonic()
        await self._load_songlengths()
        t_sl = time.monotonic() - t1
        self._my_ips()
        self.apply_targets()
        # the Picos' names beside: a switched-off one costs 5 s each (mDNS), the page waited for it (2026-10-23: 25 s)
        self._resolve_task = asyncio.get_running_loop().create_task(self.hub.resolve_all())
        self._side("nameix", self._name_index)           # the HVSC name index ready before the first tune needs it
        self.bg = asyncio.get_running_loop().create_task(self._loop())
        if self.sidaddr.pending:                         # switched before a restart/power cut: back to normal
            await self.sid_release()
        self.tv_boot_until = self.clock() + TV_BOOT_S
        self.cec_apply()
        events.log("Jukebox gestartet in %.1f s (Songlängen %.1f s)" % (time.monotonic() - t0, t_sl))
        return self

    async def sid_refresh(self):
        """read the SID addresses of the Ultimate for the marking in the list (every minute, quietly)"""
        try:
            u = self.ultimate()
        except UltimateError:
            return
        before = (self.sidaddr.known_addr, sorted(self.sidaddr.base().items()))
        gen = self.sidaddr.gen
        try:
            cfg = await self.sidaddr.read(u, keep=False)
        except UltimateError:
            cfg = {}
        try:
            if self.ultimate().addr != u.addr or self.sidaddr.gen != gen:
                return                                   # another Ultimate chosen, or a socket switched meanwhile
        except UltimateError:
            return
        self.sidaddr.known, self.sidaddr.known_addr = cfg, u.addr if cfg else ""
        if (self.sidaddr.known_addr, sorted(self.sidaddr.base().items())) != before:
            self.player.lver += 1                        # the page reloads its rows
            self.player.version += 1

    async def close(self):
        self._cec_close()
        self.stats.save(force=True)
        self.history.save()
        self.display.close()
        if self.bg:
            self.bg.cancel()
        for t in self.side.values():
            t.cancel()
        for j in self.jobs.values():
            if j.task and not j.done:
                j.task.cancel()
        if self.player and self.player.dirty:
            self.player.save_to(self._current_path())
        if self.notifier:
            self.notifier.close()
        if self.devices:
            self.devices.close()
        if self.hub:
            self.hub.close()
        self.sources.close()
        self.catalog.close()
        if self.loops:
            await self.loops.close()
        if self.session:
            await self.session.close()

    def _current_path(self):
        return os.path.join(self.data_dir, "current.json")

    def my_ip(self):
        """the address phones reach the Pi at (in party mode there is no router: the access point's address)"""
        ip = local_ip()
        if ip.startswith("127."):
            ip = ((self.net_state().get("ap") or {}).get("ip")) or ip
        return ip

    def _my_ips(self):
        u = host_of(self.config.ultimate().get("addr"))
        ips = {"127.0.0.1", local_ip(), local_ip(self._names.get(u, ("", 0))[0] or "192.0.2.1")}
        self.hub.my_ips = ips
        self.devices.my_ips = ips

    def _side(self, name, fn):
        """run fn() beside the clock, at most once at a time"""
        t = self.side.get(name)
        if t and not t.done():
            return

        async def run():
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as e:                       # like in the clock: show it, keep going
                self.stream_msg = "Interner Fehler: %s" % e
        self.side[name] = asyncio.get_running_loop().create_task(run())

    async def _loop(self):
        n = 0
        while True:
            t0 = time.monotonic()
            await asyncio.sleep(0.25)
            late = time.monotonic() - t0 - 0.25
            if late > 0.2:                                   # the loop stood still: the stream waited too
                events.log("Jukebox stand %.1f s still (Stream wartete)" % late)
            n += 1
            try:
                self.player.tick()
                self.notifier.tick()
                if self.display.page == "level":                # the level page: 4 pictures a second
                    self._levels_tick()
                    if n % 4:
                        self._display_tick()
                if n % 4 == 0:
                    self._display_tick()
                    self.hub.per_second()
                    self._stream_events()
                    self._pico_news()
                    self._side("stream", self._stream_keep)          # requests to the Ultimate: never in the
                    self._hdmi_write()                                # clock (an Ultimate that is off would
                    self._side("video", self._video_keep)            # stop it for seconds)
                    self._side("sid", self._sid_keep)
                    self._side("loop", self._loop_keep)
                    if (self.config.data.get("bt") or {}).get("mac") and time.monotonic() - self.bt_at >= 5:
                        self._side("bt", self._bt_keep)
                    self._hdmi_sync_due()
                    self._news_due()
                    self._update_due()
                    self._update_watch()
                    self._cec_tick()
                    self._party_check()
                    for e in schedule.due(self.config["schedule"], time.localtime(self.wall()), self.sched_fired):
                        self._side("sched_" + e["id"], lambda e=e: self.schedule_run(e))
                if n % 20 == 0:
                    self.stats.save()
                    self.history.save()
                if n % 20 == 0 and self.player.dirty:
                    self.player.save_to(self._current_path())
                if (n % 240 == 0 or n == 8) and self.player.items and self.player.state != "load":
                    self._side("sid", self.sid_refresh)
                if n % 240 == 0:
                    self.sources.idle()
                    self.catalog.flush()
                    self._my_ips()
                    await self.hub.resolve_all()
                    self._prune_jobs()
            except asyncio.CancelledError:
                raise
            except Exception as e:                       # the clock must keep running
                self.stream_msg = "Interner Fehler: %s" % e

    # ------------------------------------------------------------ party mode (netwatch.py runs the network)
    def _party_check(self):
        """while the party mode runs with the Ultimate on the cable, the chosen Ultimate is that one"""
        p = (self.net_state().get("party") or {}) if self.config["party"].get("on") else {}
        addr = p.get("u64", "") if p.get("state") == "aktiv" else ""
        if addr != self.config.party_u64:
            self.config.party_u64 = addr
            self._stream_req_at = -1e9                   # ask it for the stream at once
            self._my_ips()

    def party_set(self, d):
        p = self.config.data["party"]
        if "on" in d:
            p["on"] = bool(d["on"])
        if "ssid" in d:
            p["ssid"] = str(d["ssid"]).strip()[:32]
        if d.get("pw") is not None and d.get("pw") != "":
            if len(str(d["pw"])) < 8:
                raise ValueError("WLAN-Passwörter haben mindestens 8 Zeichen")
            p["pw"] = str(d["pw"])[:63]
        if d.get("pw_clear"):
            p["pw"] = ""
        if p["on"] and not p["ssid"]:
            raise ValueError("Bitte den Namen des Heim-WLANs angeben")
        self.config.save()
        return self.party_state()

    def party_state(self):
        p = self.config["party"]
        n = self.net_state()
        return {"on": p.get("on", False), "ssid": p.get("ssid", ""), "pw_set": bool(p.get("pw")),
                "saved": n.get("saved", []), "state": n.get("party") or {"state": "aus"}}

    # ------------------------------------------------------------ lists put together (smartlist.py)
    async def hvsc_list(self):
        p = self._sl_path("hvsc")
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return []
        if self._hvsc_list[0] != mt:
            def read():
                with open(p, encoding="latin-1") as f:
                    return smartlist.parse_hvsc(f.read())
            self._hvsc_list = (mt, await asyncio.get_running_loop().run_in_executor(None, read))
        return self._hvsc_list[1]

    async def smart_info(self):
        root = smartlist.hvsc_root(self.config["songlengths"].get("hvsc"))
        src = self.config.source(root[0]) if root else None
        return {"hvsc": len(await self.hvsc_list()) if root else 0,
                "root": "%s: %s" % (src.get("label", root[0]), root[1]) if root and src else "",
                "presets": smartlist.PRESETS, "favs": len(self.stats.fav)}

    async def smart_items(self, f):
        """the filters (or a preset) -> list items"""
        if f.get("preset"):
            f = dict(smartlist.preset(f["preset"]), preset=f["preset"])
        plays = {k[4:]: n for k, n in self.stats.plays.items() if k.startswith("md5:")}
        favs = {k[4:] for k in self.stats.fav if k.startswith("md5:")}
        blocked = self.stats.blocked_md5s()
        if f.get("preset") == "fav":                    # every favourite, also outside the HVSC
            return [{"src": v.get("src", ""), "path": v.get("path", ""), "name": v.get("name") or v.get("path", "").rsplit("/", 1)[-1],
                     "title": v.get("title", ""), "author": v.get("author", "")}
                    for v in self.stats.fav.values() if v.get("src") and v.get("path")]
        root = smartlist.hvsc_root(self.config["songlengths"].get("hvsc"))
        hv = await self.hvsc_list() if root else []
        if f.get("preset") == "top":                    # counts by MD5 (HVSC path) or by path (other files)
            by_md5 = {m: p for p, m, _ in hv}
            out = []
            for k, n in sorted(self.stats.plays.items(), key=lambda x: -x[1]):
                if k in self.stats.block:
                    continue
                if k.startswith("md5:") and k[4:] in by_md5:
                    out.append(dict(smartlist.item(root[0], root[1], by_md5[k[4:]]), md5=k[4:]))
                elif k.startswith("path:") and k.count(":") >= 2:
                    src, path = k[5:].split(":", 1)
                    out.append({"src": src, "path": path, "name": path.rsplit("/", 1)[-1]})
                if len(out) >= int(f.get("n") or 50):
                    break
            return out
        if not root or not self.config.source(root[0]):
            raise ValueError("Dafür zuerst die Songlängen der HVSC aus einer Quelle laden (Tab „Dateien“)")
        # the whole HVSC (~60 000 entries) in a thread: the stream distributor and the TV keep going
        return await asyncio.get_running_loop().run_in_executor(
            None, smartlist.pick, hv, root, f, plays, favs, self.stil if f.get("stil") else None, blocked)

    async def smart(self, f, mode="play", name=""):
        items = await self.smart_items(f)
        if not items:
            raise ValueError("Keine Stücke passen zu dieser Auswahl")
        label = smartlist.PRESETS.get(f.get("preset"), "Zusammengestellt")
        if mode == "save":
            if not name.strip():
                raise ValueError("Bitte einen Namen für die Liste angeben")
            self.playlist_write(name, items)
        elif mode == "add":
            await self.player.add_items(items)
            self.auto_check()
        else:
            await self.player.set_items(items, 0, play=True, source=label)
            self.auto_check()
        return len(items)

    # ------------------------------------------------------------ timer (schedule.py)
    def wall(self):
        return time.time()                               # the tests set the clock of the timer here

    def schedule_set(self, entries):
        self.config.data["schedule"] = schedule.clean(entries, {p["name"] for p in self.playlists()})
        self.config.save()
        return self.schedule_state()

    def schedule_state(self):
        nxt = schedule.next_run(self.config["schedule"], time.localtime(self.wall()))
        return {"entries": self.config["schedule"], "next": schedule.describe(*nxt) if nxt else "",
                "last": self.sched_msg, "lists": [p["name"] for p in self.playlists()]}

    async def schedule_run(self, e):
        """one timer entry is due: play (a saved list or the current one) or stop, the TV with it if wanted"""
        p = self.player
        try:
            if e["do"] == "play":
                if e.get("list"):
                    items = self.playlist_read(e["list"]).get("items", [])
                    start = None if items and self.config["player"].get("shuffle") else 0
                    await p.set_items(items, start, play=True, source="Zeitplan: Liste „%s“" % e["list"])
                    self.auto_check()
                elif p.state != "play":
                    await p.play()
                if e.get("tv") and self.cec and self.cec_ready:
                    self.cec_tv("on")
            else:
                await p.stop()
                if e.get("tv") and self.cec and self.cec_ready:
                    self.cec_tv("standby")
            self.sched_msg = time.strftime("%H:%M ", time.localtime(self.wall())) + schedule.describe(e)
        except (ValueError, OSError) as err:
            self.sched_msg = "%s: %s" % (schedule.describe(e), err)

    # ------------------------------------------------------------ the TV's remote control (HDMI-CEC, cec.py)
    def cec_apply(self):
        """after a change of the settings (and at the start): open or close /dev/cec0"""
        on = bool(self.config["cec"].get("on"))
        if on and not self.cec:
            link = CecLink(CecProtocol("C64-Jukebox", clock=self.clock))
            link.proto.on_key = lambda k, cmd: events.log("Fernbedienung: Taste 0x%02X (%s) -> %s" % (
                k, KEY_NAMES.get(k, "?"), cmd or "nicht belegt"))
            self.cec, self.cec_ready = link, False
            self.cec_retry_at = self.clock()
            if link.open():
                asyncio.get_running_loop().add_reader(link.fd, self._cec_read)
        elif not on and self.cec:
            self._cec_close()

    def _cec_close(self):
        if self.cec and self.cec.fd is not None:
            try:
                asyncio.get_running_loop().remove_reader(self.cec.fd)
            except (RuntimeError, ValueError):
                pass
            self.cec.close()
        self.cec, self.cec_ready = None, False

    def cec_set(self, d):
        c = self.config.data["cec"]
        for k in ("on", "claim", "tv_on", "pi_off", "tv_on_boot"):
            if k in d:
                c[k] = bool(d[k])
        if "tv_off_min" in d:
            c["tv_off_min"] = int(max(0, min(240, float(d["tv_off_min"] or 0))))
        self.config.save()
        self.cec_apply()
        return c

    def cec_send(self, msgs):
        for to, data in msgs:
            self.cec.send(to, data)

    def cec_tv(self, what):
        """the buttons on the page: TV on and to the Pi, or to standby"""
        if not (self.cec and self.cec_ready):
            raise ValueError(self.cec.err if self.cec and self.cec.err else "HDMI-CEC ist nicht bereit")
        self.cec_send(self.cec.proto.tv_on() if what == "on" else self.cec.proto.tv_standby())

    def _cec_read(self):
        link = self.cec
        for frm, to, data in link.receive():
            cmd, out = link.proto.handle(frm, to, data)
            self.cec_send(out)
            if cmd:
                asyncio.get_running_loop().create_task(self._cec_cmd(cmd))
        if link.broken:                                  # e.g. the adapter went away: no reader firing for ever
            asyncio.get_running_loop().remove_reader(link.fd)
            link.close()
            self.cec_ready, self.cec_retry_at = False, self.clock()     # _cec_tick opens it again after 30 s

    async def _cec_cmd(self, cmd):
        p = self.player
        if self.config["hdmi"].get("on"):
            if await self.menu.key(cmd):                     # the TV menu took it
                self._hdmi_write()
                return
        cmd = {"up": "mode_next", "down": "mode_prev", "left": "prev", "right": "next",
               "select": "toggle"}.get(cmd, cmd)            # menu closed (or no picture on the TV): as before
        # play/pause keys stop (like the middle button of the touch display) and play when stopped - many remotes
        # have one play/pause key that always sends "play"
        if cmd in ("play", "pause", "toggle"):
            if p.state in ("play", "load", "pause"):
                await p.stop()
            else:
                await p.play()
        elif cmd == "stop":
            await p.stop()
        elif cmd == "next":
            await p.next()
        elif cmd == "prev":
            await p.prev()
        elif cmd in ("song_next", "song_prev") and p.cur and (p.cur["info"].get("songs") or 1) > 1:
            song, songs = p.cur["song"], p.cur["info"].get("songs") or 1   # (one sub-tune only: not from the start)
            await p.set_song((song % songs) + 1 if cmd == "song_next" else (song - 2) % songs + 1)
        elif cmd in ("mode_next", "mode_prev"):
            modes = list(HDMI_MODES)
            i = modes.index(self.config["hdmi"].get("mode")) if self.config["hdmi"].get("mode") in modes else 0
            self.hdmi_set({"mode": modes[(i + (1 if cmd == "mode_next" else -1)) % len(modes)]})

    def _cec_tick(self):
        """once a second: wait for the logical address, open again after an error, TV on/standby with the music"""
        c = self.config["cec"]
        if not c.get("on") or not self.cec:
            return
        link = self.cec
        if link.fd is None:
            if self.clock() - self.cec_retry_at >= 30:              # e.g. no TV at the start: try again
                self._cec_close()
                self.cec_apply()
            return
        playing = self.player.state in ("play", "load", "pause")
        started = playing and not self.cec_was_playing           # only this tick: not later, when the TV appears
        if playing:
            self.cec_stopped_at = None
        elif self.cec_was_playing or self.cec_stopped_at is None:
            self.cec_stopped_at = self.clock()
        self.cec_was_playing = playing
        # every second: the TV may give the Pi another address (other input, standby, another player took ours)
        self.cec_ready = link.configured()
        self._tv_off_check(link)
        if not self.cec_ready:
            return
        link.proto.playing = self.player.state == "play"
        if self.tv_boot_until is not None:
            if c.get("tv_on_boot") and self.clock() <= self.tv_boot_until:
                self.cec_send(link.proto.tv_on())
                events.log("Fernseher eingeschaltet (Start des Pi)")
            self.tv_boot_until = None                            # once
        if started and c.get("tv_on"):
            self.cec_send(link.proto.tv_on())
        elif started and c.get("claim", True) and not link.proto.active:
            self.cec_send([link.proto.active_source()])         # the remote's keys come to the Pi from now on
        mins = c.get("tv_off_min") or 0
        if (mins and not playing and link.proto.active and self.cec_stopped_at is not None
                and self.clock() - self.cec_stopped_at >= mins * 60):
            self.cec_send(link.proto.tv_standby())                   # once: standby makes us inactive

    def _tv_off_check(self, link):
        """pi_off: the TV went from on to standby -> the Pi off PI_OFF_S later (on again in between: not). Only a change
        seen while the Pi runs: a Pi started by the plug while the TV stays off keeps running (music on the Picos)."""
        if not self.config["cec"].get("pi_off"):
            self.tv_seen_on, self.tv_off_at = False, None
            return
        now = self.clock()
        if self.cec_ready and now - self.tv_ask_at >= TV_ASK_S:
            self.tv_ask_at = now
            self.cec_send(link.proto.ask_tv_power())
        power = link.proto.tv_power
        if power == "on":
            if self.tv_off_at is not None:
                events.log("Fernseher wieder an – Pi bleibt an")
            self.tv_seen_on, self.tv_off_at = True, None
        elif power == "standby" and self.tv_seen_on and self.tv_off_at is None:
            self.tv_off_at = now
            events.log("Fernseher ist aus – Pi wird in %d s ausgeschaltet" % PI_OFF_S)
        if self.tv_off_at is not None and now - self.tv_off_at >= PI_OFF_S:
            self.tv_seen_on, self.tv_off_at = False, None
            if self.bt_active():
                events.log("Fernseher aus, aber Kopfhörer verbunden – Pi bleibt an")
            elif not self.powering_off:
                asyncio.get_running_loop().create_task(self._tv_power_off())

    async def _tv_power_off(self):
        try:
            await self.power_off()
        except ValueError as e:
            events.log("Pi nicht ausgeschaltet: %s" % e)

    def cec_status(self):
        c = self.cec
        if not c:
            return {"on": False}
        p = c.proto
        return {"on": True, "ready": self.cec_ready, "adapter": c.adapter, "err": c.err, "la": p.la if self.cec_ready else None,
                "phys": "%d.%d.%d.%d" % tuple((p.phys >> s) & 15 for s in (12, 8, 4, 0)) if p.phys != 0xFFFF else "",
                "active": p.active, "last": p.last, "recent": list(p.recent), "tv": p.tv_power,
                "pi_off_in": max(0, int(PI_OFF_S - (self.clock() - self.tv_off_at))) if self.tv_off_at is not None else None}

    # ------------------------------------------------------------ the Ultimate(s)
    def ultimate_by_addr(self, addr, pw=None):
        """the client for one of the entered Ultimates (by its address), also when it is not the selected one;
        pw: the password to use (a restore uses the one the switch was made with)"""
        u = next((x for x in self.config["ultimates"] if x.get("addr") == addr), {"addr": addr, "pw": ""})
        return Ultimate(self.session, addr, u.get("pw", "") if pw is None else pw)

    async def sid_prepare(self, u, needed):
        await self.sidaddr.prepare(u, needed, bool(self.config["player"].get("sidauto", True)), self.ultimate_by_addr)

    async def sid_release(self):
        """switched sockets back: the selected Ultimate's at once, the others' beside (one that is off would hold the
        player for seconds), not again within 5 minutes after a failure"""
        cur = self.config.ultimate().get("addr") or ""
        if cur in self.sidaddr.pending:
            await self.sidaddr.release(self.ultimate_by_addr, cur)
        if any(a != cur for a in self.sidaddr.pending):
            self._side("sid_others", lambda: self.sidaddr.release(self.ultimate_by_addr, others_of=cur, wait_s=300))

    async def sid_config_change(self, new_ultimates):
        """before the list of Ultimates is replaced (page, restore): an entry whose address changed takes its record
        along; a removed entry is restored first (still with its old password) and then forgotten"""
        old = self.config["ultimates"]
        for i, o in enumerate(old):
            a = o.get("addr")
            if a not in self.sidaddr.pending:
                continue
            if i < len(new_ultimates) and new_ultimates[i].get("addr") and not any(
                    n.get("addr") == a for n in new_ultimates):
                self.sidaddr.rekey(a, new_ultimates[i]["addr"], new_ultimates[i].get("pw", ""))
            elif not any(n.get("addr") == a for n in new_ultimates):
                await self.sidaddr.release(self.ultimate_by_addr, a)
                self.sidaddr.drop_unknown({n.get("addr") for n in new_ultimates if n.get("addr")})

    def ultimate(self, i=None):
        u = self.config.ultimate(i)
        if not u.get("addr"):
            raise UltimateError("Kein Ultimate eingetragen (Tab „Geräte“)")
        return Ultimate(self.session, u["addr"], u.get("pw", ""))

    # ---- switching an Ultimate on (over its WLAN) and off
    async def u64_learn_mac(self, i=None):
        """the Ultimate's WLAN MAC from /v1/info, kept in its entry (waking needs it while the device is off)"""
        i = self.config["u64_sel"] if i is None else i
        u = self.config["ultimates"][i]
        try:
            d = await self.ultimate(i).info(timeout=3)
        except UltimateError:
            return u.get("wmac", "")
        mac = wol.normalize_mac((d or {}).get("wifi_mac"))
        if mac and mac != u.get("wmac"):
            u["wmac"] = mac
            self.config.save()
            events.log("WLAN-MAC von %s gemerkt: %s" % (u.get("label") or u.get("addr"), mac))
        return u.get("wmac", "")

    async def u64_power(self, i, on):
        """on: the magic packet to its WLAN MAC, then wait (beside) until it answers; off: SID sockets back, playing
        stopped, PUT /v1/machine:poweroff"""
        us = self.config["ultimates"]
        if not 0 <= i < len(us) or not us[i].get("addr"):
            raise ValueError("Kein Ultimate an dieser Stelle")
        u, name = us[i], us[i].get("label") or us[i]["addr"]
        if on:
            mac = wol.normalize_mac(u.get("wmac"))
            if not mac:
                raise ValueError("Die WLAN-MAC von \u201e%s\u201c ist unbekannt – im Tab \u201eGeräte\u201c eintragen "
                                 "(oder das Ultimate einmal eingeschaltet lassen, dann merkt die Jukebox sie sich)" % name)
            try:
                await asyncio.get_running_loop().run_in_executor(None, wol.send, mac, host_of(u["addr"]))
            except OSError as e:
                raise ValueError("Weckruf ging nicht hinaus: %s" % e)
            self.power_msg = "Weckruf an \u201e%s\u201c gesendet (WLAN %s) – warte auf Antwort …" % (name, mac)
            events.log("Ultimate %s: Weckruf an WLAN-MAC %s" % (name, mac))
            self._side("power", lambda: self._u64_wait_awake(i, name))
            return self.power_msg
        await self.u64_learn_mac(i)
        if i == self.config["u64_sel"] and self.player.state != "stop":
            await self.player.stop()
        await self.sid_release()
        try:
            await self.ultimate(i).machine("poweroff")
        except UltimateError as e:
            raise ValueError(str(e))
        self.power_msg = "\u201e%s\u201c ausgeschaltet" % name
        events.log("Ultimate %s: ausgeschaltet (machine:poweroff)" % name)
        return self.power_msg

    async def _u64_wait_awake(self, i, name, limit_s=60):
        t0 = self.clock()
        while self.clock() - t0 < limit_s:
            await asyncio.sleep(2)
            try:
                await self.ultimate(i).info(timeout=2)
            except UltimateError:
                continue
            self.power_msg = "\u201e%s\u201c ist wach (nach %.0f s)" % (name, self.clock() - t0)
            events.log("Ultimate %s: wach nach %.0f s" % (name, self.clock() - t0))
            self._stream_req_at = -1e9                   # ask for the stream at once
            return
        self.power_msg = "\u201e%s\u201c antwortet nach %d s noch nicht – WLAN-MAC richtig? „Wake-Up on WiFi“ an?" % (name, limit_s)
        events.log("Ultimate %s: nach %d s keine Antwort auf den Weckruf" % (name, limit_s))

    async def resolve(self, host):
        """IPv4 of a name, remembered for a minute (".local" names via the system's mDNS)"""
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
            return host
        hit = self._names.get(host)
        if hit and time.monotonic() - hit[1] < 60:
            return hit[0]
        ip = ""
        try:
            info = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, None, family=2), 5)
            ip = info[0][4][0]
        except (OSError, asyncio.TimeoutError, IndexError):
            pass
        self._names[host] = (ip, time.monotonic())
        return ip

    async def select_ultimate(self, i):
        if not 0 <= i < len(self.config["ultimates"]) or i == self.config["u64_sel"]:
            return
        if self.player.state != "stop":
            await self.player.stop()
        old = self.config.ultimate()
        await self.sid_release()                          # a socket switched on the old one goes back first
        self.config.data["u64_sel"] = i
        self.config.save()
        await self.sid_refresh()
        if self.config["stream"]["on"] or self.config["hdmi"].get("on"):
            if self._stream_asked:
                try:
                    await Ultimate(self.session, old["addr"], old.get("pw", "")).stream_stop()
                except UltimateError:
                    pass
            self._stream_asked = ""
            self._stream_req_at = -1e9
        self._sid_req_at = self._video_req_at = -1e9
        self._my_ips()

    # ------------------------------------------------------------ stream distributor
    def apply_targets(self):
        self.hub.set_targets([p["addr"] for p in self.config["picos"] if p.get("addr") and p.get("stream", True)])
        h = self.config["hdmi"]
        self.hub.local = [("127.0.0.1", self.hdmi_audio_port)] if h.get("on") else []
        if h.get("on") and self.sound_wanted():                 # the TV sound: its own process (hdmi/soundproc.py)
            self.hub.local.append(("127.0.0.1", self.hdmi_sound_port))
        if self._loop_cur is not None and self.loops and self.loops.port:
            self.hub.local.append(("127.0.0.1", self.loops.port))

    # ------------------------------------------------------------ Bluetooth headphones (bt.py)
    def bt_active(self):
        """the sound goes to the headphones now: switched on and connected"""
        b = self.config.data.get("bt") or {}
        return bool(b.get("on") and b.get("mac") and self.bt_conn)

    def sound_wanted(self):
        return bool(self.config["hdmi"].get("sound")) or self.bt_active()

    async def _bt_keep(self):
        """every few seconds: are the chosen headphones connected? (they connect by themselves when switched on)"""
        b = self.config.data.get("bt") or {}
        if not b.get("mac") or not self.bt.present:
            conn = False
        else:
            if not self.bt_at:
                await self.bt.power()                       # Bluetooth stays off after a start otherwise
            i = await self.bt.info(b["mac"])
            conn = bool(i and i["connected"])
        self.bt_at = time.monotonic()
        if conn != self.bt_conn:
            self.bt_conn = conn
            events.log("Kopfhörer %s %s" % (b.get("name") or b.get("mac"), "verbunden" if conn else "getrennt"))
            self.apply_targets()

    def bt_status(self):
        b = self.config.data.get("bt") or {}
        return {"present": self.bt.present, "on": bool(b.get("on")), "mac": b.get("mac", ""), "name": b.get("name", ""),
                "connected": self.bt_conn, "active": self.bt_active()}

    async def bt_devices(self):
        return await self.bt.devices()

    async def bt_scan(self, job):
        job.progress = "Suche %d s … (Kopfhörer in den Kopplungsmodus bringen)" % bt.SCAN_S
        found = await self.bt.scan()
        events.log("Bluetooth-Suche: %s" % (", ".join("%s %s" % (d["mac"], d["name"]) for d in found) or "nichts gefunden"))
        return found

    def _bt_choose(self, mac, name):
        b = self.config.data.setdefault("bt", {})
        b.update(mac=mac, name=name or (b.get("name") if b.get("mac") == mac else "") or mac, on=True)
        self.config.save()

    async def bt_pair(self, job, mac):
        job.progress = "Kopple … (Kopfhörer im Kopplungsmodus lassen)"
        try:
            i = await self.bt.pair(mac)
        except ValueError as e:
            events.log("Bluetooth: Koppeln mit %s fehlgeschlagen: %s" % (mac, e))
            raise
        events.log("Bluetooth: %s gekoppelt (%s), verbunden" % (mac, i["name"]))
        self._bt_choose(mac, i["name"])
        await self._bt_keep()
        return i

    async def bt_connect(self, mac):
        i = await self.bt.connect(mac)
        self._bt_choose(mac, i["name"])
        await self._bt_keep()
        return i

    async def bt_disconnect(self, mac):
        await self.bt.disconnect(mac)
        await self._bt_keep()

    async def bt_forget(self, mac):
        await self.bt.remove(mac)
        b = self.config.data.setdefault("bt", {})
        if b.get("mac") == mac:
            b.update(mac="", name="", on=False)
            self.config.save()
        await self._bt_keep()

    def bt_set(self, on):
        b = self.config.data.setdefault("bt", {})
        b["on"] = bool(on) and bool(b.get("mac"))
        self.config.save()
        self.apply_targets()

    # ------------------------------------------------------------ switching the Pi off (with the smart plug, plug.py)
    async def _cmd(self, cmd, timeout=10):
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL,
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            out, _ = await asyncio.wait_for(p.communicate(), timeout)
        except (OSError, asyncio.TimeoutError) as e:
            return False, str(e) or "keine Antwort"
        return p.returncode == 0, out.decode("utf-8", "replace").strip()

    async def can_power_off(self):
        """logind lets the service switch the Pi off (polkit rule from install.sh): 's "yes"'"""
        ok, out = await self._cmd(self.power_can_cmd, timeout=5)
        return ok and '"yes"' in out

    async def power_state(self):
        c = self.config["plug"]
        return {"can": await self.can_power_off(), "plug": plug.configured(c), "off_s": c.get("off_s", 30)}

    async def plug_check(self, job=None):
        """the plug answers? A plug found by its id keeps the address and version it announced"""
        if job:
            job.progress = "Frage die Steckdose …"
        c = self.config["plug"]
        st = await self.plug.status(c)
        if st["ip"] != c.get("ip") or st["ver"] != c.get("ver"):
            c.update(ip=st["ip"], ver=st["ver"])
            self.config.save()
        return st

    async def power_off(self, force=False):
        """set the plug's timer, then shut down (in a moment: the page gets its answer first). Without the timer
        (plug not answering) only with force - the Pi must never lose its power while it runs."""
        if self.powering_off:
            raise ValueError("Der Pi wird schon ausgeschaltet")
        if not await self.can_power_off():
            raise ValueError("Der Pi darf sich nicht selbst ausschalten – Installationsskript noch einmal ausführen")
        c = self.config["plug"]
        secs = max(20, min(int(c.get("off_s") or 30), 600))
        timer = False
        if plug.configured(c):
            try:
                await self.plug.countdown(c, secs)
                timer = True
            except ValueError as e:
                if not force:
                    raise ValueError("Steckdose antwortet nicht (%s) – der Pi bleibt an" % e)
        self.powering_off = True
        events.log("Pi wird ausgeschaltet" + (" – Steckdose schaltet in %d s ab" % secs if timer else ""))
        try:
            await self.player.stop()
        except Exception:                                  # noqa: BLE001 - switching off goes on regardless
            pass
        asyncio.get_running_loop().call_later(1.5, lambda: asyncio.ensure_future(self._power_off_now(timer)))
        return {"timer": timer, "secs": secs}

    async def _power_off_now(self, timer):
        ok, out = await self._cmd(self.power_cmd)
        if ok:
            return
        events.log("Ausschalten fehlgeschlagen: %s" % out[-120:])
        self.powering_off = False
        if timer:                                          # the Pi stays on: the plug must not cut it
            try:
                await self.plug.countdown(self.config["plug"], 0)
            except ValueError as e:
                events.log("Steckdosen-Timer nicht zurückgesetzt: %s" % e)

    # ------------------------------------------------------------ repeat of a tune without a length (loopfind.py)
    def _loop_wanted(self):
        p = self.player
        c = p.cur
        return (self.config["player"].get("loopfind", "suggest") != "off" and p.state == "play" and c is not None
                and not c["secs"] and self.loops is not None and self.loops.available())

    async def _name_index(self):
        """namematch.NameIndex of the loaded HVSC file, from hvsc_by_md5 (there since the start), kept until that
        changes. Built here in small steps: in a thread it held Python's lock, the jukebox stood still for 1.3 s
        (2026-10-24) and with it the stream"""
        src = self.hvsc_by_md5
        if not src:
            return None
        if getattr(self, "_name_ix", (None,))[0] is not src:
            t = getattr(self, "_name_ix_task", None)
            if t is None or t.get_name() != str(id(src)):
                async def build():
                    ix = namematch.NameIndex({})
                    turn = time.monotonic()
                    for md5, path in list(src.items()):
                        ix.add(path, md5)
                        if time.monotonic() - turn > 0.02:
                            await asyncio.sleep(0)
                            turn = time.monotonic()
                    self._name_ix = (src, ix)
                t = self._name_ix_task = asyncio.get_running_loop().create_task(build(), name=str(id(src)))
            await asyncio.shield(t)
        return self._name_ix[1]

    async def _name_keep(self):
        """a tune without a length that starts: the same tune by name in the HVSC (another version of the file)?"""
        p = self.player
        c = p.cur
        if self.name_hint and self.name_hint["cur"] is not c:
            self.name_hint = None
            p.version += 1
        mode = self.config["player"].get("hvsc_name", "suggest")
        if mode == "off" or c is None or c["secs"] or c is self._name_seen or p.state != "play":
            return
        self._name_seen = c
        ix = await self._name_index()
        info = c["info"]
        r = ix.find(c["item"].get("name") or "", info.get("title"), info.get("author")) if ix else None
        if not r or p.cur is not c:
            return
        songs = self.songlengths.hvsc.get(bytes.fromhex(r[1]))
        if not songs or not 1 <= c["song"] <= len(songs):
            return
        secs = songs[c["song"] - 1]
        name = info.get("title") or c["item"].get("name")
        events.log("Länge über den Namen in der HVSC: %s = %d:%02d (%s)" % (name, secs // 60, secs % 60, r[0]))
        if mode == "auto":
            self.set_user_length(c["item"], secs, songs)
            return
        self.name_hint = {"len": secs, "songs": songs, "path": r[0], "cur": c}
        p.version += 1

    def name_take(self):
        h = self.name_hint
        if not h or h["cur"] is not self.player.cur:
            raise ValueError("Keine HVSC-Länge für das laufende Stück")
        self.name_hint = None
        self.set_user_length(h["cur"]["item"], h["len"], h["songs"])
        name = h["cur"]["info"].get("title") or h["cur"]["item"].get("name")
        events.log("Länge übernommen: %s = %d:%02d (HVSC %s)" % (name, h["len"] // 60, h["len"] % 60, h["path"]))
        return h["len"]

    def name_reject(self):
        if self.name_hint:
            self.name_hint = None
            self.player.version += 1

    async def _loop_keep(self):
        """once a second: look at the tune that plays when it has no length - from its start only (a repeat back to
        "the start" must be the tune's start); stop looking when it ends, pauses or gets a length. The name search
        afterwards: building its index takes ~5 s on the Pi the first time - the repeat search would miss its 3 s"""
        await self._loop_keep_repeat()
        await self._name_keep()

    async def _loop_keep_repeat(self):
        p = self.player
        if self.loop_hint and self.loop_hint["cur"] is not p.cur:
            self.loop_hint = None
            p.version += 1
        if self._loop_cur is not None and (p.cur is not self._loop_cur or not self._loop_wanted()):
            self._loop_cur = None
            self.loops.end()
            self.apply_targets()
        if self._loop_cur is None and self._loop_wanted() and p.cur is not self._loop_seen:
            self._loop_seen = p.cur                       # each tune once (after a pause: not again)
            if p.elapsed() > 3 or not await self.loops.ensure() or p.cur is not self._loop_seen:
                return
            self._loop_id += 1
            self._loop_cur, self._loop_el0 = p.cur, p.elapsed()
            self.loops.begin(str(self._loop_id))
            self.apply_targets()

    _loop_seen = None

    def _loop_found(self, d):
        p = self.player
        if d.get("id") != str(self._loop_id) or self._loop_cur is None or p.cur is not self._loop_cur:
            return
        secs = max(1, int(round(d["len"] + self._loop_el0)))
        cur = self._loop_cur
        self._loop_cur = None
        self.apply_targets()
        name = cur["info"].get("title") or cur["item"].get("name")
        events.log("Wiederholung erkannt: %s fängt nach %d:%02d von vorn an (gefunden bei %d:%02d)"
                   % (name, secs // 60, secs % 60, int(d["at"] + self._loop_el0) // 60, int(d["at"] + self._loop_el0) % 60))
        if self.config["player"].get("loopfind", "suggest") == "auto":
            try:
                self.set_user_length(cur["item"], secs)
                events.log("Länge übernommen: %s = %d:%02d" % (name, secs // 60, secs % 60))
            except ValueError:
                pass
            return
        self.loop_hint = {"len": secs, "lag": d.get("lag"), "cur": cur}
        p.version += 1

    def loop_take(self):
        """the length found becomes the tune's own length (it then ends at once - it has come round already)"""
        h = self.loop_hint
        if not h or h["cur"] is not self.player.cur:
            raise ValueError("Keine erkannte Länge für das laufende Stück")
        self.loop_hint = None
        self.set_user_length(h["cur"]["item"], h["len"])
        name = h["cur"]["info"].get("title") or h["cur"]["item"].get("name")
        events.log("Länge übernommen: %s = %d:%02d" % (name, h["len"] // 60, h["len"] % 60))
        return h["len"]

    def loop_reject(self):
        if self.loop_hint:
            self.loop_hint = None
            self.player.version += 1

    def _stream_events(self):
        """once a second: the stream came / went, packets from other senders - into the event log"""
        h = self.hub
        act = h.active()
        if act != self._ev_active:
            if act:
                events.log("Stream kommt: von %s" % h.lock_ip)
            elif self._ev_active is not None:
                events.log("Stream weg: letztes Paket vor %.1f s von %s" % (self.clock() - h.last_rx, h.lock_ip or "?"))
            self._ev_active = act
        if act and h.rx_pps and h.rx_pps < 200 and self.clock() - self._ev_weak_at >= 10:
            events.log("Stream schwach: %d Pakete/s von %s" % (h.rx_pps, h.lock_ip))
            self._ev_weak_at = self.clock()
        for t in h.targets:
            n = h.dropped(t.ip)
            was, at = self._ev_drop.get(t.ip, (0, -1e9))
            if t.ip and n > was and self.clock() - at >= 10:
                events.log("%d Pakete an %s (%s) verworfen - Gerät aus?" % (n - was, t.addr, t.ip))
                self._ev_drop[t.ip] = (n, self.clock())
        if h.foreign != self._ev_foreign and self.clock() - self._ev_foreign_at >= 10:
            events.log("%d Pakete von %s verworfen (keine Kabeladresse eines Ultimate)" % (h.foreign - self._ev_foreign,
                                                                                            h.foreign_ip))
            self._ev_foreign, self._ev_foreign_at = h.foreign, self.clock()

    async def _allowed_senders(self):
        """the entered Ultimates' addresses (as entered: their Ethernet addresses) - stream data only from those"""
        out = set()
        for x in list(self.config["ultimates"]) + ([{"addr": self.config.party_u64}] if self.config.party_u64 else []):
            if x.get("addr"):
                ip = await self.resolve(host_of(x["addr"]))
                if ip:
                    out.add(ip)
        return out

    async def _stream_keep(self):
        self.hub.allow = await self._allowed_senders()
        # the HDMI output needs the sound too (its effects), also without the stream distributor
        on = self.config["stream"]["on"] or bool(self.config["hdmi"].get("on"))
        now = self.clock()
        if not on:
            if self._stream_asked:
                addr = self._stream_asked
                self._stream_asked = ""
                try:
                    await Ultimate(self.session, addr, self.config.ultimate().get("pw", "")).stream_stop()
                    self.stream_msg = "Stream beim Ultimate abgemeldet"
                except UltimateError:
                    pass
            return
        if self.hub.active() and not await self._stream_foreign(now):
            return
        if now - self._stream_req_at < 10:
            return
        self._stream_req_at = now
        try:
            u = self.ultimate()
            host = host_of(u.addr)
            me = local_ip(await self.resolve(host) or "192.0.2.1")
            await u.stream_start(me, self.hub.port)
            self._stream_asked = u.addr
            if not self.config.ultimate().get("wmac"):            # for waking it later over its WLAN
                self._side("learnmac", self.u64_learn_mac)
            self.stream_msg = "Stream angefordert (an %s:%d)" % (me, self.hub.port)
            events.log("audio:start bei %s an %s:%d -> ok" % (u.addr, me, self.hub.port))
        except UltimateError as e:
            self.stream_msg = str(e)
            events.log("audio:start bei %s -> %s" % (u.addr, e))
            if "Network Host Resolve" in str(e):
                await self._arp_fix(u)

    async def _arp_fix(self, u):
        """the Ultimate cannot find the Pi ("Network Host Resolve Error"): announce the Pi's address to it again, over
        the cable only - what a restart of the Pi did (2026-10-23, twice). At most every 30 s."""
        now = self.clock()
        if now - self._arp_at < 30:
            return
        self._arp_at = now
        ip = await self.resolve(host_of(u.addr))
        if not ip:
            return
        why = await asyncio.get_running_loop().run_in_executor(None, arpfix.announce, ip)
        self.arp_log = (self.arp_log + [(time.strftime("%d.%m. %H:%M:%S"), ip, why or "ok")])[-10:]
        events.log("Pi meldet sich per ARP bei %s neu -> %s" % (ip, why or "ok"))
        self.stream_msg += " – Pi hat sich beim Ultimate neu gemeldet" if not why else " (%s)" % why

    async def _stream_foreign(self, now):
        """the stream comes from another of the entered Ultimates than the chosen one (asked before a restart of the
        Pi, which forgets whom it asked, or before a switch): tell that one to stop -> True, then ask the chosen one.
        A sender that is not one of the entered Ultimates (e.g. something forwarding the stream) is left alone."""
        src = self.hub.lock_ip
        try:
            want = await self.resolve(host_of(self.ultimate().addr))
        except UltimateError:
            return False
        if not src or src == want:
            return False
        for x in self.config["ultimates"]:
            if x.get("addr") and await self.resolve(host_of(x["addr"])) == src:
                if now - self._foreign_stop_at >= 10:
                    self._foreign_stop_at = now
                    try:
                        await Ultimate(self.session, x["addr"], x.get("pw", "")).stream_stop()
                        self.stream_msg = "Stream bei „%s“ abgemeldet – Ton kommt vom gewählten Ultimate" % (
                            x.get("label") or x["addr"])
                    except UltimateError as e:
                        self.stream_msg = str(e)
                return True
        return False

    async def set_stream(self, on):
        self.config.data["stream"]["on"] = bool(on)
        self.config.save()
        self._stream_req_at = -1e9
        await self._stream_keep()

    # ------------------------------------------------------------ HDMI output (service c64pi-hdmi, hdmi/)
    def hdmi_dir(self):
        return os.path.join(self.data_dir, "hdmi-bilder")

    def _hdmi_write(self):
        """settings + what plays for the HDMI service (every second while it is on, once more when switched off)"""
        on = bool(self.config["hdmi"].get("on"))
        if not on and not self._hdmi_was_on:
            return
        self._hdmi_was_on = on
        cfg = dict(self.config["hdmi"], sound=self.sound_wanted(),
                   sound_dev=bt.alsa_device(self.config["bt"]["mac"]) if self.bt_active() else "")
        d = {"t": time.time(), "cfg": cfg, "img_dir": self.hdmi_img_dir(), "name": self.config["name"],
             "ip": self.my_ip(), "player": self._player_for_screen(),
             "news": self.news.for_screen() if self.news_wanted() else [], "sid_msg": self.sid_msg,
             "menu": self.menu.view(),
             "senders": sorted(self.hub.allow)}
        p = os.path.join(self.run_dir, "hdmi-in.json")
        try:
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(p + ".tmp", p)
        except OSError:
            pass

    def _player_for_screen(self):
        if not self.player:
            return {}
        pl = self.player.state_json()
        if pl.get("now"):
            pl["now"]["stil"] = self.stil_for(pl["now"])
        return pl

    def hdmi_status(self):
        try:
            with open(os.path.join(self.run_dir, "hdmi.json"), encoding="utf-8") as f:
                d = json.load(f)
            d["age"] = round(time.time() - d.get("t", 0), 1)
        except (OSError, ValueError):
            d = {"age": None}
        d["video_msg"] = self.video_msg
        d["sid_msg"] = self.sid_msg
        return d

    def hdmi_set(self, d):
        h = self.config.data["hdmi"]
        if d.get("img_src") and self.config.source(str(d["img_src"])) is None:
            raise ValueError("Quelle nicht gefunden")
        old_src = (h.get("img_src"), h.get("img_path"), h.get("img_sub"))
        news_before = (h.get("news_idle") or h.get("news_ticker"), json.dumps(h.get("news_feeds")))
        for k in ("on", "auto", "shuffle", "osd", "osd_stil", "osd_big", "osd_qr", "sound", "fade", "img_sub", "idle_hide", "news_idle",
                  "news_ticker"):
            if k in d:
                h[k] = bool(d[k])
        if d.get("mode") in HDMI_MODES:
            h["mode"] = d["mode"]
        if d.get("bg") in BACKGROUNDS:
            h["bg"] = d["bg"]
        if isinstance(d.get("auto_modes"), list):
            h["auto_modes"] = [m for m in d["auto_modes"] if m in HDMI_MODES]
        if isinstance(d.get("news_feeds"), list):
            feeds = []
            for f in d["news_feeds"][:20]:
                url = str((f or {}).get("url", "")).strip()
                if not re.match(r"^https?://[^\s]+$", url):
                    raise ValueError("Keine gültige Adresse: %s" % (url or "(leer)"))
                feeds.append({"label": str(f.get("label") or "").strip()[:40] or url.split("/")[2], "url": url[:300],
                              "on": bool(f.get("on", True))})
            h["news_feeds"] = feeds
        for k, lo, hi in (("auto_s", 10, 3600), ("img_s", 3, 3600), ("opacity", 0, 100), ("idle_s", 5, 3600),
                          ("news_s", 5, 300), ("volume", 0, 100), ("osd_big_s", 2, 30)):
            if k in d:
                h[k] = int(max(lo, min(hi, float(d[k]))))
        if "fade_s" in d:
            h["fade_s"] = round(max(0.2, min(15.0, float(d["fade_s"]))), 1)
        if "img_src" in d:
            h["img_src"] = str(d["img_src"] or "")
        if "img_path" in d:
            h["img_path"] = norm(str(d["img_path"] or "/"))
        new_folder = (h.get("img_src"), h.get("img_path"), h.get("img_sub")) != old_src
        if (h.get("news_idle") or h.get("news_ticker"), json.dumps(h.get("news_feeds"))) != news_before:
            self.news.at = -1e9                               # other feeds or just switched on: fetch now
        self.config.save()
        self.apply_targets()
        self._video_req_at = -1e9
        self._hdmi_was_on = True
        self._hdmi_write()
        if new_folder and h.get("img_src"):
            self.hdmi_sync()                              # another folder: fetch its pictures now
        return h

    async def _video_keep(self):
        """the C64 picture: asks the selected Ultimate for its video stream (to the HDMI service on this Pi) while
        it is wanted and nothing comes; gives it back when no longer wanted"""
        h = self.config["hdmi"]
        want = bool(h.get("on")) and h.get("bg") == "video"
        now = self.clock()
        if not want:
            if self._video_asked:
                addr, self._video_asked = self._video_asked, ""
                try:
                    await Ultimate(self.session, addr, self.config.ultimate().get("pw", "")).video_stop()
                    self.video_msg = "Bild beim Ultimate abgemeldet"
                except UltimateError:
                    pass
            return
        st = self.hdmi_status()
        va = st.get("video_age")
        if (st.get("age") is not None and st["age"] < 5 and va is not None and va < 3) or now - self._video_req_at < 10:
            return
        self._video_req_at = now
        try:
            u = self.ultimate()
            me = local_ip(await self.resolve(host_of(u.addr)) or "192.0.2.1")
            await u.video_start(me, self.hdmi_video_port)
            self._video_asked = u.addr
            self.video_msg = "Bild angefordert (an %s:%d)" % (me, self.hdmi_video_port)
        except UltimateError as e:
            self.video_msg = str(e)

    async def _sid_keep(self):
        """the SID voices on the TV: asks the selected Ultimate for its debug stream (every bus cycle, 32 Mbit/s)
        while the HDMI service shows them and nothing comes; gives it back when no longer wanted - and before asking
        another Ultimate (two at once would be 64 Mbit/s for nothing)"""
        st = self.hdmi_status()
        want = bool(self.config["hdmi"].get("on")) and st.get("age") is not None and st["age"] < 5 \
            and bool(st.get("sid_want"))
        cur = self.config.ultimate().get("addr", "")
        if self._sid_asked and (not want or self._sid_asked != cur):
            addr, self._sid_asked = self._sid_asked, ""
            try:
                await self.ultimate_by_addr(addr).debug_stop()
                events.log("debug:stop bei %s (SID-Stimmen)" % addr)
            except UltimateError as e:
                events.log("debug:stop bei %s -> %s" % (addr, e))
        if not want:
            self.sid_msg = ""
            return
        sa = st.get("sid_age")
        if (sa is not None and sa < 3) or self.clock() - self._sid_req_at < 10:
            return
        self._sid_req_at = self.clock()
        try:
            u = self.ultimate()
            mode = await u.debug_mode()
            if mode and "6510" not in mode:
                self.sid_msg = "Am Ultimate „Debug Stream Mode“ auf „6510 Only“ stellen (jetzt „%s“)" % mode
                return
            me = local_ip(await self.resolve(host_of(u.addr)) or "192.0.2.1")
            await u.debug_start(me, self.hdmi_sid_port)
            events.log("debug:start bei %s an %s:%d (SID-Stimmen)" % (u.addr, me, self.hdmi_sid_port))
            self._sid_asked = u.addr
            self.sid_msg = "Beim Ultimate angefordert (an %s:%d) …" % (me, self.hdmi_sid_port)
        except UltimateError as e:
            self.sid_msg = str(e)
            events.log("debug:start bei %s -> %s" % (u.addr, e))

    # ---- retro news for the TV
    def news_wanted(self):
        h = self.config["hdmi"]
        return bool(h.get("on") and (h.get("news_idle") or h.get("news_ticker"))) or bool(self.config["pico_news"])

    def _pico_news(self):
        """the headlines for the Picos' idle texts (sent on change and every 15 min; switched off: cleared once)"""
        self.notifier.news(news_body(self.news.items) if self.config["pico_news"] else b"")

    def news_feeds(self):
        """all sources of the page (the known ones, or the user's list), each with its on/off switch"""
        return [dict(f, on=f.get("on", True)) for f in (self.config["hdmi"].get("news_feeds") or DEFAULT_FEEDS)]

    def news_active(self):
        return [f for f in self.news_feeds() if f["on"]]

    def _update_due(self):
        if self.config.data.get("updates", True) and UPDATE_URL and self.session and \
                time.monotonic() - self._update_at >= UPDATE_EVERY_S:
            self._update_at = time.monotonic()
            self._side("update", self.update_check)

    async def update_check(self):
        """the VERSION of the published program; newer than ours -> a hint on the page and in the TV menu (installed
        only on request: update_install)"""
        try:
            async with self.session.get(UPDATE_URL, timeout=aiohttp.ClientTimeout(total=15)) as r:
                text = await r.text() if r.status == 200 else ""
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            text = ""
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
        if not m:
            events.log("Update-Prüfung: GitHub nicht erreichbar")
            return None                                  # the last answer stays in self.update
        self.update = {"ver": m.group(1), "newer": version_key(m.group(1)) > version_key(VERSION), "at": int(time.time())}
        if self.update["newer"]:
            events.log("Neue Version %s auf GitHub (installiert: %s)" % (m.group(1), VERSION))
        return self.update

    def _update_path(self):
        return os.path.join(self.data_dir, "update.json")

    def update_file(self):
        """what update.sh wrote: {"state": "run"|"ok"|"fail", "ver", "from", "msg", "at", "seen"?} or None"""
        try:
            with open(self._update_path(), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) else None

    def update_running(self):
        st = self.update_file()
        return self.updating or bool(st and st.get("state") == "run" and time.time() - st.get("at", 0) < 3600)

    async def update_install(self):
        """install the newer version from GitHub: the root unit from install.sh downloads it and runs install.sh,
        which restarts this service; a failed install puts the old program back (update.sh)"""
        if self.update_running():
            raise ValueError("Das Update läuft schon")
        if not (self.update and self.update["newer"]):
            raise ValueError("Keine neuere Version bekannt – zuerst nach einem Update sehen")
        ok, out = await self._cmd(self.update_can_cmd, timeout=5)
        if not (ok and out.strip() == "loaded"):
            raise ValueError("Das Update auf Befehl ist noch nicht eingerichtet – dieses eine Mal von Hand "
                             "aktualisieren (Installationsskript)")
        ok, out = await self._cmd(self.update_cmd)
        if not ok:
            raise ValueError("Update ließ sich nicht starten: " + out[-120:])
        self.updating = True
        events.log("Update auf %s gestartet (installiert: %s)" % (self.update["ver"], VERSION))
        return {"ver": self.update["ver"]}

    def _update_watch(self):
        """the end of an update (update.json changed): reported once - in the log and in the menu on the TV"""
        try:
            m = os.stat(self._update_path()).st_mtime
        except OSError:
            return
        if m == self._update_mtime:
            return
        self._update_mtime = m
        st = self.update_file()
        if not st or st.get("state") not in ("ok", "fail"):
            return
        self.updating = False
        if st.get("seen") or time.time() - st.get("at", 0) > UPDATE_NOTE_S:
            return
        msg = "Update auf %s installiert" % st.get("ver", "?") if st["state"] == "ok" else \
            "Update fehlgeschlagen: %s" % (st.get("msg") or "?")
        events.log(msg)
        self.menu.open()                                 # whoever started it is waiting in front of the TV
        self.menu.note = msg
        st["seen"] = True
        try:
            tmp = self._update_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f)
            os.replace(tmp, self._update_path())
            self._update_mtime = os.stat(self._update_path()).st_mtime
        except OSError:
            pass

    def update_state(self):
        """for the page: the last update's result (within UPDATE_NOTE_S) and whether one runs"""
        st = self.update_file()
        last = {k: st.get(k) for k in ("state", "ver", "from", "msg", "at")} \
            if st and time.time() - st.get("at", 0) < UPDATE_NOTE_S else None
        return {"running": self.update_running(), "last": last}

    def _news_due(self):
        if self.news_wanted() and self.news.due() and self.session:
            self.news.start(self.session, self.news_active())

    def news_refresh(self):
        return self.news.start(self.session, self.news_active())

    def news_state(self):
        st = self.news.state
        return {"n": len(self.news.items), "busy": bool(self.news.task and not self.news.task.done()),
                "feeds": [dict({"label": f.get("label"), "url": f["url"], "on": f["on"]},
                               **({k: st.get(f["url"], {}).get(k) for k in ("n", "err")} if f["on"] else {}))
                          for f in self.news_feeds()],
                "default": not self.config["hdmi"].get("news_feeds")}

    def hdmi_cache_dir(self):
        return os.path.join(self.data_dir, "hdmi-quelle")

    def hdmi_img_dir(self):
        """the folder the slide show shows: uploaded pictures, or the copies from a source"""
        return self.hdmi_cache_dir() if self.config["hdmi"].get("img_src") else self.hdmi_dir()

    def _hdmi_sync_due(self):
        h = self.config["hdmi"]
        if not (h.get("on") and h.get("bg") == "images" and h.get("img_src")):
            return
        if self.hdmi_sync_job and not self.hdmi_sync_job.done:
            return
        if self.clock() - self._hdmi_sync_at < HDMI_SYNC_S:
            return
        self.hdmi_sync()

    def hdmi_sync(self):
        """start fetching the pictures of the chosen source folder (a job; the page shows its progress)"""
        self._hdmi_sync_at = self.clock()
        self.hdmi_sync_job = self.start_job("hdmi_sync", self._hdmi_sync)
        return self.hdmi_sync_job

    async def _hdmi_sync(self, job):
        import hashlib
        h = self.config["hdmi"]
        src_id, path, sub = h.get("img_src"), h.get("img_path") or "/", bool(h.get("img_sub"))
        if not src_id:
            return {"n": 0}
        src = self.sources.get(src_id)
        found = []
        async for d, entries in self.walk(src_id, path, sub, job=job):
            for e in entries:
                if not e["d"] and e["n"].lower().endswith(HDMI_IMAGE_EXT) and e.get("s", 0) <= HDMI_IMAGE_BYTES:
                    found.append((d.rstrip("/") + "/" + e["n"], e.get("s", 0)))
            job.progress = "%d Ordner, %d Bilder gefunden" % (job.dirs, len(found))
            if len(found) >= HDMI_IMAGES_MAX:
                found = found[:HDMI_IMAGES_MAX]
                break
        cache = self.hdmi_cache_dir()
        os.makedirs(cache, exist_ok=True)
        want = {}
        for p, size in found:
            key = hashlib.sha1(("%s|%s|%d" % (src_id, p, size)).encode()).hexdigest()[:16]
            name = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(p))[0])[:40]
            want["%s-%s.jpg" % (name, key)] = p
        have = set(os.listdir(cache))
        for n in have - set(want):                          # gone from the source (or another folder chosen)
            try:
                os.remove(os.path.join(cache, n))
            except OSError:
                pass
        new = [(n, p) for n, p in want.items() if n not in have]
        done = failed = 0
        loop = asyncio.get_running_loop()
        for n, p in new:
            job.progress = "Bild %d von %d: %s" % (done + failed + 1, len(new), os.path.basename(p))
            job.pct = int(100 * (done + failed) / len(new))
            try:
                data = await src.read(p, HDMI_IMAGE_BYTES)
                await loop.run_in_executor(None, self._hdmi_fit_save, data, os.path.join(cache, n))
                done += 1
            except (SourceError, ValueError, OSError):
                failed += 1
        job.pct = 100
        job.progress = "%d Bilder, %d neu übernommen%s" % (len(want), done, ", %d unlesbar" % failed if failed else "")
        return {"n": len(want), "new": done, "failed": failed}

    @staticmethod
    def _hdmi_fit_save(data, path):
        from PIL import Image, ImageOps
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        except Exception:
            raise ValueError("kein Bild")
        ImageOps.fit(img, HDMI_IMAGE_SIZE, Image.LANCZOS).save(path + ".tmp", "JPEG", quality=88)
        os.replace(path + ".tmp", path)

    async def hdmi_thumb(self, src_id, path):
        """a small preview of a picture in a source (for choosing the slide show's folder like the SIDs)"""
        key = (src_id, norm(path))
        if key in self._thumbs:
            return self._thumbs[key]
        if not path.lower().endswith(HDMI_IMAGE_EXT):
            raise ValueError("kein Bild")
        data = await self.sources.get(src_id).read(key[1], HDMI_IMAGE_BYTES)

        def small():
            from PIL import Image, ImageOps
            try:
                img = Image.open(io.BytesIO(data))
                img.draft("RGB", (480, 270))                 # JPEG: decode at a fraction of the size (fast on the Pi)
                img = ImageOps.exif_transpose(img).convert("RGB")
            except Exception:
                raise ValueError("kein Bild")
            out = io.BytesIO()
            ImageOps.fit(img, (240, 135), Image.BILINEAR).save(out, "JPEG", quality=80)
            return out.getvalue()
        jpg = await asyncio.get_running_loop().run_in_executor(None, small)
        if len(self._thumbs) >= 300:
            self._thumbs.pop(next(iter(self._thumbs)))
        self._thumbs[key] = jpg
        return jpg

    def hdmi_images(self):
        try:
            names = sorted(n for n in os.listdir(self.hdmi_dir()) if n.lower().endswith((".jpg", ".jpeg", ".png")))
        except OSError:
            names = []
        return [{"name": n, "size": os.path.getsize(os.path.join(self.hdmi_dir(), n))} for n in names]

    def hdmi_add_image(self, filename, data):
        """a picture from the page, made 1920 x 1080 (filled, centred) as JPEG - the Pi 3B then only has to show it"""
        from PIL import Image, ImageOps
        if len(self.hdmi_images()) >= HDMI_IMAGES_MAX:
            raise ValueError("Höchstens %d Bilder" % HDMI_IMAGES_MAX)
        try:
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception:
            raise ValueError("„%s“ ist kein Bild (JPEG oder PNG)" % filename)
        img = ImageOps.fit(img, HDMI_IMAGE_SIZE, Image.LANCZOS)
        stem = re.sub(r"[^A-Za-z0-9äöüÄÖÜß_-]+", "_", os.path.splitext(os.path.basename(filename))[0]).strip("_")[:60]
        os.makedirs(self.hdmi_dir(), exist_ok=True)
        name, k = (stem or "bild") + ".jpg", 2
        while os.path.exists(os.path.join(self.hdmi_dir(), name)):
            name, k = "%s-%d.jpg" % (stem or "bild", k), k + 1
        img.save(os.path.join(self.hdmi_dir(), name), "JPEG", quality=88)
        return name

    def hdmi_image_path(self, name):
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("Unbekanntes Bild")
        p = os.path.join(self.hdmi_dir(), name)
        if not os.path.isfile(p):
            raise ValueError("Unbekanntes Bild")
        return p

    def hdmi_del_image(self, name):
        os.remove(self.hdmi_image_path(name))

    # ------------------------------------------------------------ device list
    def self_beacon(self):
        u = self.config.ultimate()
        st = self.hub.state() if self.hub else {"pps": 0, "from": "", "targets": []}
        tg = [t for t in st["targets"]]
        now = self.player.cur["info"] if self.player and self.player.cur else None
        d = {"t": "pi", "n": self.config["name"], "ip": local_ip(), "b": VERSION, "img": "",
             "up": int(time.time() - self.started), "st": 1 if self.config["stream"]["on"] else 0, "sm": 0,
             "rx": st["pps"], "from": st["from"],
             "fw": ",".join(t["addr"].replace(".local", "") for t in tg),
             "fwip": tg[0]["ip"] if tg else "", "fp": max([t["pps"] for t in tg] or [0]),
             "src": host_of(u.get("addr")), "srcl": u.get("label", "")}
        if now:
            d["title"] = (now.get("title") or now.get("name") or "")[:40]
        return d

    # ------------------------------------------------------------ files
    def remember_info(self, src, path, size, md5, head):
        self.catalog.put_info(src, path, size, md5, head)

    async def ls(self, src_id, path):
        path = norm(path)
        src = self.sources.get(src_id)
        entries = await src.list(path)
        self.catalog.put_dir(src_id, path, entries)
        return entries

    def annotate(self, src_id, path, entries):
        """header data of files read before, so a folder shown again is complete at once"""
        out = []
        for e in entries:
            e = dict(e)
            if not e["d"] and sidfile.is_sid_name(e["n"]):
                p = path.rstrip("/") + "/" + e["n"]
                c = self.catalog.get_info(src_id, p, e.get("s"))
                if c:
                    e["i"] = compact(c, c["md5"], self.songlengths)
            out.append(e)
        return out

    async def info(self, src_id, path):
        c = self.catalog.get_info(src_id, path)
        if c:
            return compact(c, c["md5"], self.songlengths)
        data = await self.sources.get(src_id).read(path)
        head = sidfile.parse_header(data)
        if head is None:
            raise SourceError("keine SID-Datei")
        md5 = sidfile.md5(data)
        self.catalog.put_info(src_id, path, len(data), md5, head)
        return compact(head, md5, self.songlengths)

    async def _ls_cached(self, src_id, path, max_age):
        hit = self.catalog.get_dir(src_id, path, max_age) if max_age else None
        return hit if hit is not None else await self.ls(src_id, path)

    async def walk(self, src_id, path, recursive=True, max_age=None, job=None):
        """yields (folder, entries) depth first, folders in name order"""
        stack = [norm(path)]
        dirs = 0
        turn = time.monotonic()
        while stack:
            d = stack.pop()
            try:
                entries = await self._ls_cached(src_id, d, max_age)
            except SourceError:
                if d == norm(path):
                    raise
                continue
            dirs += 1
            if job:
                job.dirs = dirs
            if time.monotonic() - turn > 0.02:           # from the cache nothing waits: the HVSC has thousands of
                await asyncio.sleep(0)                   # folders, the stream distributor must not stand still
                turn = time.monotonic()
            yield d, entries
            if recursive:
                subs = [d.rstrip("/") + "/" + e["n"] for e in entries if e["d"]]
                stack.extend(reversed(subs))

    def item_of(self, src_id, path, name):
        it = {"src": src_id, "path": path, "name": name}
        c = self.catalog.get_info(src_id, path)
        if c:
            it["title"], it["author"] = c["title"], c["author"]
        return it

    async def play_folder(self, job, src, path, rec=False, mode="replace", shuffle=None):
        """a folder (with its sub-folders) as the play list, or added at its end (page: "Ordner abspielen", TV menu)"""
        items = await self.collect(job, src, path, rec)
        if not items:
            raise ValueError("Keine SID-Dateien gefunden")
        if shuffle is not None and bool(shuffle) != bool(self.config["player"].get("shuffle")):
            self.config.data["player"]["shuffle"] = bool(shuffle)
            self.config.save()
        if mode == "replace":
            start = None if self.config["player"].get("shuffle") else 0
            label = (self.config.source(src) or {}).get("label", src)
            await self.player.set_items(items, start, play=True,
                                        source="%s %s%s" % (label, path, " + Unterordner" if rec else ""))
        else:
            await self.player.add_items(items)
        self.auto_check()
        return {"n": len(items), "trunc": len(items) >= LIST_MAX}

    async def find_ultimates(self, job):
        """the network search, Ultimates only (page: tab "Geräte"; TV menu "Im Netzwerk suchen")"""
        return [e for e in await self.net_scan(job) if e.get("u64")]

    def add_ultimate(self, addr, label=""):
        """a found Ultimate into the list (into an empty row if there is one) -> its index"""
        u = self.config.data["ultimates"]
        for i, x in enumerate(u):
            if x.get("addr") == addr:
                return i
        for i, x in enumerate(u):
            if not x.get("addr"):
                x.update(addr=addr, label=x.get("label") or label)
                break
        else:
            u.append({"label": label, "addr": addr, "pw": ""})
            i = len(u) - 1
        self.config.save()
        events.log("Ultimate hinzugefügt: %s (%s)" % (label or addr, addr))
        return i

    async def collect(self, job, src_id, path, recursive):
        items = []
        async for d, entries in self.walk(src_id, path, recursive, job=job):
            for e in entries:
                if not e["d"] and sidfile.is_sid_name(e["n"]):
                    items.append(self.item_of(src_id, d.rstrip("/") + "/" + e["n"], e["n"]))
            job.progress = "%d Ordner, %d SIDs" % (job.dirs, len(items))
            job.info = {"dir": d}
            if len(items) >= LIST_MAX:
                break
        return items

    def hvsc_root(self):
        """(source, folder of C64Music) when the HVSC song lengths were loaded from a source, else None"""
        root = smartlist.hvsc_root(self.config["songlengths"].get("hvsc"))
        return root if root and self.config.source(root[0]) else None

    def in_hvsc(self, src_id, path):
        root = self.hvsc_root()
        return bool(root) and src_id == root[0] and \
            (norm(path).rstrip("/") + "/").startswith(norm(root[1]).rstrip("/") + "/")

    async def hvsc_hay(self):
        """the whole HVSC to search without reading a folder: paths and MD5 from Songlengths.md5, titles, composers and
        release lines from the header cache (filled by hvsc_titles). Built once, a batch at a time"""
        root = self.hvsc_root()
        hv = await self.hvsc_list() if root else []
        if not hv:
            return []
        if self._hvsc_hay[0] == self._hvsc_list[0]:
            return self._hvsc_hay[1]
        base = norm(root[1]).rstrip("/")
        heads = {}
        for rows in self.catalog.under(root[0], base):
            for p, d in rows:
                heads[p] = (d.get("title", "") + "\n" + d.get("author", "") + "\n" + d.get("released", "")).lower()
            await asyncio.sleep(0)
        out = []
        for k, (rel, md5, _) in enumerate(hv):
            p = base + rel
            out.append((p, md5, rel.lower() + "\n" + heads.get(p, "")))
            if k % 5000 == 4999:
                await asyncio.sleep(0)
        self._hvsc_hay = (self._hvsc_list[0], out)
        return out

    def hvsc_titles_state(self):
        """how much of the HVSC the search knows by title: {"n": with header, "of": all}"""
        root = self.hvsc_root()
        hv = self._hvsc_list[1] if root else []
        hay = self._hvsc_hay[1] if self._hvsc_hay[0] == self._hvsc_list[0] else []
        return {"of": len(hv), "n": sum(1 for x in hay if x[2].count("\n") > 1) if hay else None}

    async def hvsc_titles(self, job):
        """read the header (124 bytes) of every HVSC file not in the cache yet - once, in the background; the search
        then also finds titles, composers and release lines"""
        root = self.hvsc_root()
        if not root:
            raise ValueError("Dafür zuerst die Songlängen der HVSC aus einer Quelle laden (Tab „Dateien“)")
        hv = await self.hvsc_list()
        base = norm(root[1]).rstrip("/")
        have = set()
        for rows in self.catalog.under(root[0], base):
            have.update(p for p, _ in rows)
            await asyncio.sleep(0)
        todo = [(base + rel, md5) for rel, md5, _ in hv if base + rel not in have]
        src = self.sources.get(root[0])
        done = fails = 0
        t0 = time.monotonic()
        try:
            for k, (p, md5) in enumerate(todo):
                if k % 25 == 0:
                    job.pct = int(100 * k / max(1, len(todo)))
                    left = (time.monotonic() - t0) / k * (len(todo) - k) if k > 20 else None
                    job.progress = "%d von %d Titeln gelesen%s" % (
                        k, len(todo), ", noch etwa %d min" % max(1, round(left / 60)) if left else "")
                try:
                    head = sidfile.parse_header(await src.head(p, sidfile.HEADER_LEN))
                except SourceError:
                    head = None
                if head:
                    self.catalog.put_info(root[0], p, 0, md5, head)        # size unknown: matches any size
                    done += 1
                else:
                    fails += 1
        finally:
            self.catalog.flush()
            self._hvsc_hay = (None, [])
        events.log("HVSC-Titel gelesen: %d neu, %d nicht lesbar, %d schon bekannt" % (done, fails, len(have)))
        return {"n": done, "fails": fails, "known": len(have), "of": len(hv)}

    async def hvsc_find(self, q, limit=SEARCH_MAX):
        """the whole HVSC by words (TV menu): search hits like the page's, at most limit"""
        root = self.hvsc_root()
        if not root or not await self.hvsc_hay():
            raise ValueError("Dafür zuerst die Songlängen der HVSC aus einer Quelle laden")
        return await self._search_hvsc(None, root[1], q.lower().split(), limit)

    async def _search_hvsc(self, job, path, terms, limit=SEARCH_MAX):
        base = norm(path).rstrip("/") + "/"
        hits = []
        hay = await self.hvsc_hay()
        for k, (p, md5, text) in enumerate(hay):
            if k % 5000 == 4999:
                await asyncio.sleep(0)
            if not p.startswith(base) or not all(t in text for t in terms):
                continue
            hit = {"n": p.rsplit("/", 1)[-1], "d": False, "s": 0, "p": p}
            c = self.catalog.get_info(self.hvsc_root()[0], p)
            if c:
                hit["i"] = compact(c, c["md5"], self.songlengths)
            hits.append(hit)
            if len(hits) >= limit:
                if job:
                    job.progress = "%d Treffer (gekürzt)" % len(hits)
                return hits
        if job:
            job.progress = "%d Treffer im HVSC-Verzeichnis" % len(hits)
        return hits

    async def search(self, job, src_id, path, q):
        terms = q.lower().split()
        if self.in_hvsc(src_id, path) and await self.hvsc_hay():      # the whole HVSC is known: no folder to read
            return await self._search_hvsc(job, path, terms)
        hits = []
        base = norm(path).rstrip("/")
        async for d, entries in self.walk(src_id, path, True, max_age=86400, job=job):
            for e in entries:
                if e["d"] or not sidfile.is_sid_name(e["n"]):
                    continue
                p = d.rstrip("/") + "/" + e["n"]
                hay = p[len(base):].lower()
                c = self.catalog.get_info(src_id, p)
                if c:
                    hay += " " + (c["title"] + " " + c["author"] + " " + c["released"]).lower()
                if all(t in hay for t in terms):
                    hit = {"n": e["n"], "d": False, "s": e.get("s", 0), "p": p}
                    if c:
                        hit["i"] = compact(c, c["md5"], self.songlengths)
                    hits.append(hit)
            job.progress = "%d Ordner durchsucht, %d Treffer" % (job.dirs, len(hits))
            job.info = {"dir": d}
            if len(hits) >= SEARCH_MAX:
                job.progress += " (gekürzt)"
                break
        return hits

    # ------------------------------------------------------------ jobs
    def start_job(self, kind, fn):
        for j in self.jobs.values():                     # one job of a kind at a time
            if j.kind == kind and not j.done and j.task:
                j.task.cancel()
        job = Job(kind)
        job.dirs = 0

        async def run():
            try:
                job.result = await fn(job)
            except asyncio.CancelledError:
                job.error = "abgebrochen"
            except (SourceError, UltimateError, ValueError, OSError) as e:
                job.error = str(e)
            finally:
                job.done = True
        job.task = asyncio.get_running_loop().create_task(run())
        self.jobs[job.id] = job
        return job

    def _prune_jobs(self):
        now = time.monotonic()
        for k in [k for k, j in self.jobs.items() if j.done and now - j.t > 600]:
            del self.jobs[k]

    async def net_scan(self, job):
        hosts = self.scan_hosts or subnet_hosts(local_ip())

        def prog(st):
            job.pct = st["pct"]
            job.info = {"busy": st["busy"], "found": st["found"], "phase": st["phase"]}
            job.progress = "%d %%" % st["pct"]
        kw = {"ports": self.scan_ports} if self.scan_ports else {}
        pws = tuple(sorted({u.get("pw", "") for u in self.config["ultimates"] if u.get("pw")}))
        return await scan(self.session, hosts, progress=prog, passwords=pws, timeout=self.scan_timeout, **kw)

    async def shares(self, host, user, pw):
        return await asyncio.get_running_loop().run_in_executor(None, smb_shares, host, user, pw)

    # ------------------------------------------------------------ song lengths
    def _sl_path(self, kind):
        return os.path.join(self.data_dir, "songlengths-%s.txt" % kind)

    async def _load_songlengths(self):
        loop = asyncio.get_running_loop()
        for kind in ("hvsc", "custom"):
            p = self._sl_path(kind)
            if os.path.exists(p):
                with open(p, encoding="latin-1") as f:
                    text = f.read()
                await loop.run_in_executor(None, self.songlengths.load, kind, text)
                if kind == "hvsc":
                    self.hvsc_by_md5 = await loop.run_in_executor(None, self._md5_paths, text)
        if os.path.exists(self._stil_path()):
            with open(self._stil_path(), encoding="latin-1") as f:
                text = f.read()
            await loop.run_in_executor(None, self.stil.load, text)

    @staticmethod
    def _md5_paths(text):
        return {m: p for p, m in imports.hvsc_paths(text).items()}

    # ---- STIL.txt of the HVSC: background to a tune (page and TV)
    def _stil_path(self):
        return os.path.join(self.data_dir, "stil.txt")

    async def set_stil(self, data, origin):
        text = data.decode("latin-1")
        n = await asyncio.get_running_loop().run_in_executor(None, self.stil.load, text)
        if not n:
            raise ValueError("Keine STIL-Einträge in der Datei gefunden")
        with open(self._stil_path(), "w", encoding="latin-1") as f:
            f.write(text)
        self.config.data["songlengths"]["stil"] = origin
        self.config.save()
        return n

    def clear_stil(self):
        self.stil.load("")
        try:
            os.remove(self._stil_path())
        except OSError:
            pass
        self.config.data["songlengths"]["stil"] = ""
        self.config.save()

    def stil_for(self, now):
        """STIL lines for the playing tune: by its HVSC path, else by its MD5"""
        if not self.stil.db or not now:
            return []
        song = now.get("song") or 1
        return (self.stil.lookup(imports.hvsc_rel(now.get("path") or ""), song) or
                self.stil.lookup(self.hvsc_by_md5.get(now.get("md5") or ""), song))

    async def set_songlengths(self, kind, data, origin):
        if kind not in ("hvsc", "custom"):
            raise ValueError("kind")
        text = data.decode("latin-1")
        n = await asyncio.get_running_loop().run_in_executor(None, self.songlengths.load, kind, text)
        if not n:
            raise ValueError("Keine Songlängen in der Datei gefunden")
        if kind == "hvsc":
            self.hvsc_by_md5 = await asyncio.get_running_loop().run_in_executor(None, self._md5_paths, text)
        with open(self._sl_path(kind), "w", encoding="latin-1") as f:
            f.write(text)
        self.config.data["songlengths"][kind] = origin
        self.config.save()
        return n

    def clear_songlengths(self, kind):
        self.songlengths.load(kind, "")
        try:
            os.remove(self._sl_path(kind))
        except OSError:
            pass
        self.config.data["songlengths"][kind] = ""
        self.config.save()

    # ------------------------------------------------------------ play lists
    def _pl_dir(self):
        return os.path.join(self.data_dir, "playlists")

    @staticmethod
    def _pl_file(name):
        s = re.sub(r"[^\w\-. ]+", "_", name.strip(), flags=re.UNICODE).strip(" .")[:60]
        if not s:
            raise ValueError("Name fehlt")
        return s + ".json"

    def playlists(self):
        out = []
        for fn in sorted(os.listdir(self._pl_dir()), key=str.lower):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._pl_dir(), fn), encoding="utf-8") as f:
                    d = json.load(f)
                out.append({"name": d.get("name") or fn[:-5], "n": len(d.get("items", [])), "saved": d.get("saved", "")})
            except (OSError, ValueError):
                continue
        return out

    def playlist_read(self, name):
        try:
            with open(os.path.join(self._pl_dir(), self._pl_file(name)), encoding="utf-8") as f:
                return json.load(f)
        except OSError:
            raise ValueError("Liste nicht gefunden")

    def playlist_write(self, name, items):
        d = {"name": name.strip()[:60], "saved": time.strftime("%Y-%m-%d %H:%M"), "items": items}
        p = os.path.join(self._pl_dir(), self._pl_file(name))
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)

    def playlist_delete(self, name):
        try:
            os.remove(os.path.join(self._pl_dir(), self._pl_file(name)))
        except OSError:
            raise ValueError("Liste nicht gefunden")
        self._schedule_list_renamed(name, None)

    def playlist_rename(self, old, new):
        """-> the new name; timer entries that play the list follow it"""
        new = str(new or "").strip()[:60]
        d = self.playlist_read(old)
        if not new:
            raise ValueError("Bitte einen neuen Namen angeben")
        same_file = self._pl_file(new) == self._pl_file(old)
        if not same_file and os.path.exists(os.path.join(self._pl_dir(), self._pl_file(new))):
            raise ValueError("Es gibt schon eine Liste \u201e%s\u201c" % new)
        d["name"] = new
        p = os.path.join(self._pl_dir(), self._pl_file(new))
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
        if not same_file:
            os.remove(os.path.join(self._pl_dir(), self._pl_file(old)))
        self._schedule_list_renamed(old, new)
        if self.player.source == "Liste \u201e%s\u201c" % old:
            self.player.source = "Liste \u201e%s\u201c" % new
        return new

    def _schedule_list_renamed(self, old, new):
        """timer entries playing list `old`: now `new` - or (deleted) switched off, so they never play something else"""
        changed = False
        for e in self.config.data.get("schedule") or []:
            if e.get("list") == old:
                if new:
                    e["list"] = new
                else:
                    e["on"] = False
                changed = True
        if changed:
            self.config.save()

    # ------------------------------------------------------------ backup
    def backup(self):
        cfg = json.loads(json.dumps(self.config.data))
        cfg.get("web", {}).pop("secret", None)
        lists = {}
        for p in self.playlists():
            try:
                lists[p["name"]] = self.playlist_read(p["name"]).get("items", [])
            except ValueError:
                pass
        custom = ""
        if os.path.exists(self._sl_path("custom")):
            with open(self._sl_path("custom"), encoding="latin-1") as f:
                custom = f.read()
        return {"fmt": "c64pi-backup", "ver": 1, "build": VERSION, "saved": time.strftime("%Y-%m-%d %H:%M"),
                "config": cfg, "playlists": lists, "current": self.player.items, "songlengths_custom": custom,
                "stats": self.stats.backup()}

    async def restore(self, d):
        if not isinstance(d, dict) or d.get("fmt") != "c64pi-backup" or not isinstance(d.get("config"), dict):
            raise ValueError("Das ist keine Sicherung der C64-Jukebox")
        cfg = d["config"]
        secret = self.config.data["web"]["secret"]
        await self.player.stop()
        from .config import DEFAULTS, _merge
        self.config.data = _merge(DEFAULTS, cfg)
        self.config.data["web"]["secret"] = secret
        self.config.save()
        for name, items in (d.get("playlists") or {}).items():
            self.playlist_write(name, items)
        await self.player.set_items(d.get("current") or [], play=False)
        if d.get("stats"):
            self.stats.restore(d["stats"])
        if d.get("songlengths_custom"):
            await self.set_songlengths("custom", d["songlengths_custom"].encode("latin-1", "replace"),
                                       self.config["songlengths"].get("custom") or "Sicherung")
        self.sources.close()
        self.apply_targets()
        await self.hub.resolve_all()
        return len(d.get("playlists") or {})

    # ------------------------------------------------------------ the small display
    def _levels_tick(self):
        """levels for the touch display's level page: now, held peaks (falling slowly), the last 15 s"""
        self.hub.want_levels = True
        lv = self.hub.take_levels()
        pk = getattr(self, "_lv_peak", [0.0, 0.0])
        self._lv_peak = [max(lv[i], pk[i] - 0.04) for i in (0, 1)]
        hist = getattr(self, "_lv_hist", [])
        self._lv_hist = (hist + [max(lv)])[-60:]
        self._lv_now = lv

    def display_state(self):
        d = self.state()
        if self.display.page == "level":
            d["level"] = {"now": list(getattr(self, "_lv_now", (0, 0))), "peak": list(getattr(self, "_lv_peak", (0, 0))),
                          "hist": list(getattr(self, "_lv_hist", []))}
        else:
            self.hub.want_levels = False
        d["net"] = self.net_state()
        d["ip"] = local_ip()
        return d

    def _display_tick(self):
        if self._disp_busy or self.config["display"].get("type") == "off" and not self.display.dev:
            return
        self._disp_busy = True
        st = self.display_state()
        fut = asyncio.get_running_loop().run_in_executor(None, self.display.tick, st)
        fut.add_done_callback(lambda f: setattr(self, "_disp_busy", False))

    def display_reconfigure(self):
        self.display.reopen = True                 # done by the worker thread itself (it may be writing right now)

    def _in_loop(self, fn):
        """run fn in the event loop (called from the display's threads)"""
        if self._aloop:
            self._aloop.call_soon_threadsafe(fn)

    def _touch(self, what):
        """a button on the touch display (touch thread)"""
        self._in_loop(lambda: asyncio.ensure_future(self.touch_cmd(what)))

    async def touch_cmd(self, what):
        p = self.player
        if what == "stop":                               # the middle button: stop, or play when stopped
            if p.state in ("play", "load", "pause"):
                await p.stop()
            else:
                await p.play()
        elif what == "next":
            await p.next()
        elif what == "prev":
            await p.prev()

    # ------------------------------------------------------------ the network of the Pi (netwatch.py, as root)
    def net_state(self):
        try:
            with open(os.path.join(self.run_dir, "net.json"), encoding="utf-8") as f:
                d = json.load(f)
            d["age"] = int(time.time() - d.get("t", 0))
            return d
        except (OSError, ValueError):
            return {"mode": "unknown"}

    def net_request(self, action, ssid="", pw=""):
        rid = secrets.token_hex(4)
        p = os.path.join(self.run_dir, "request.json")
        try:
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"id": rid, "action": action, "ssid": ssid, "pw": pw}, f)
            os.replace(p + ".tmp", p)
        except OSError:
            raise ValueError("Der Netzwerk-Dienst des Pi läuft nicht (c64pi-net)")
        return rid

    def web_used(self):
        """tells the network watcher that the page is in use (it then leaves the access point alone)"""
        now = time.monotonic()
        if now - self._web_touch > 30:
            self._web_touch = now
            try:
                with open(os.path.join(self.run_dir, "web"), "w"):
                    pass
            except OSError:
                pass

    # ------------------------------------------------------------ the play list as a table
    def default_secs(self):
        return int(float(self.config["player"].get("limit_min") or 0) * 60) or 180

    def fill_meta(self, item):
        """header data of a list entry from the cache (title, author, md5, sub-songs, SIDs)"""
        if item.get("md5") or item.get("_nc") == self.player.lver:
            return item
        c = self.catalog.get_info(item.get("src", ""), item.get("path", ""))
        if c:
            self.stats.migrate("path:%s:%s" % (item.get("src", ""), item.get("path", "")), dict(item, md5=c["md5"]))
            item.setdefault("title", c["title"])
            item.setdefault("author", c["author"])
            item.update(md5=c["md5"], songs=c["songs"], start=c["start"], chips=c["chips"], sids=c["sids"],
                        year=c.get("year", ""))
            self.player.dirty = True
        else:
            item["_nc"] = self.player.lver          # not in the cache: do not ask again until the list changes
        return item

    def item_len(self, item):
        """(seconds, kind): kind "user" (own length, *), "hvsc", "default" (no length known) or "" (not read yet)"""
        md5 = item.get("md5")
        if not md5:
            return None, ""
        song = item.get("song") or item.get("start") or 1
        try:
            key = bytes.fromhex(md5)
        except ValueError:
            return None, ""
        t = self.songlengths.custom.get(key)
        if t:
            return (t[0] if len(t) == 1 else (t[song - 1] if song <= len(t) else None)), "user"
        t = self.songlengths.hvsc.get(key)
        if t and song <= len(t):
            return t[song - 1], "hvsc"
        return self.default_secs(), "default"

    def row(self, i, item, cur):
        self.fill_meta(item)
        secs, kind = self.item_len(item)
        return {"i": i, "name": item.get("name", ""), "title": item.get("title", ""), "author": item.get("author", ""),
                "year": item.get("year", ""), "song": item.get("song") or item.get("start") or 0,
                "songs": item.get("songs", 0), "chips": item.get("chips", 0), "sids": item.get("sids", []),
                "len": secs, "lk": kind, "plays": self.stats.count(item), "fav": self.stats.is_fav(item),
                "blk": self.stats.is_blocked(item),
                "src": item.get("src", ""), "path": item.get("path", ""), "cur": i == cur,
                "sfit": self.sidaddr.fit(item.get("sids")) if item.get("sids") else None}

    def _filtered(self, q="", fav=False):
        items = self.player.items
        q = (q or "").strip().lower()
        if not q and not fav:
            return None
        out = []
        for i, it in enumerate(items):
            if fav and not self.stats.is_fav(it):
                continue
            if q and q not in (it.get("name", "") + "\n" + it.get("title", "") + "\n" + it.get("author", "")).lower():
                continue
            out.append(i)
        return out

    def list_rows(self, start=0, n=200, q="", fav=False, ids=False):
        p = self.player
        items, cur = p.items, p.current_index()
        sel = self._filtered(q, fav)
        if ids:                                    # "select all" / a shift range over rows not loaded yet
            return {"ids": list(range(len(items))) if sel is None else sel, "over": p.over}
        count = len(items) if sel is None else len(sel)
        start = max(0, min(start, max(0, count - 1)))
        idx = range(start, min(count, start + n)) if sel is None else sel[start:start + n]
        rows = [self.row(i, items[i], cur) for i in idx]
        if sel is None:
            cur_row = cur
        else:
            cur_row = sel.index(cur) if cur in sel else -1
        key = (p.lver, len(items), len(self.songlengths.custom), len(self.songlengths.hvsc), self.default_secs())
        if self._head_cache[0] != key:
            total, est = 0, 0
            for it in items:
                s, kind = self.item_len(it)
                if s is None or kind == "default":
                    est += 1
                    s = self.default_secs()
                total += s
            self._head_cache = (key, total, est)
        total, est = self._head_cache[1], self._head_cache[2]
        return {"count": count, "total": len(items), "start": start, "rows": rows, "cur": cur, "cur_row": cur_row,
                "lver": p.lver, "over": p.over, "secs": total, "est": est, "source": p.source, "sort": self.list_sort,
                "upnext": p.order[p.pos + 1] if 0 <= p.pos < len(p.order) - 1 else (p.order[0] if p.order and
                                                                                         self.config["player"].get("repeat", True) else -1)}

    SORT_KEYS = ("name", "title", "author", "song", "sids", "len", "plays", "fav")

    async def sort_list(self, col):
        if col not in self.SORT_KEYS:
            raise ValueError("unbekannte Spalte")
        rev = self.list_sort.get("col") == col and not self.list_sort.get("rev")
        for it in self.player.items:
            self.fill_meta(it)

        def key(it):
            if col == "name":
                return it.get("name", "").lower()
            if col in ("title", "author"):
                return (it.get(col) or "").lower()
            if col == "song":
                return it.get("song") or it.get("start") or 0
            if col == "sids":
                return it.get("chips", 0)
            if col == "len":
                s, _ = self.item_len(it)
                return -1 if s is None else s
            if col == "plays":
                return self.stats.count(it)
            return 1 if self.stats.is_fav(it) else 0
        await self.player.sort(key, rev)
        self.list_sort = {"col": col, "rev": rev}

    def auto_check(self):
        """read the headers of new list entries in the background (the PC program does it when loading)"""
        if any(not it.get("md5") for it in self.player.items):
            busy = any(jb.kind == "check" and not jb.done for jb in self.jobs.values())
            if not busy:
                self.start_job("check", self.check_list)

    async def dedupe(self):
        """like "Find Duplicates" of the PC program: the same file (MD5) only once, the first stays"""
        def pick(items):
            seen, drop = set(), []
            for i, it in enumerate(items):
                m = self.fill_meta(it).get("md5")
                if m:
                    if m in seen:
                        drop.append(i)
                    seen.add(m)
            return drop
        return await self.player.remove_where(pick)

    async def with_md5(self, it):
        """a list entry with its MD5 if it can be read (star and block belong to the file, like in the PC program)"""
        self.fill_meta(it)
        if not it.get("md5"):
            try:
                await self.info(it["src"], it["path"])
                it.pop("_nc", None)
                self.fill_meta(it)
            except (SourceError, OSError):
                pass
        return it

    async def block(self, i=None):
        """'nicht mehr spielen': on the blocked list; the playing tune is left at once"""
        p = self.player
        cur = p.current_index()
        i = cur if i is None else i
        if not 0 <= i < len(p.items):
            raise ValueError("Kein Titel gewählt")
        it = await self.with_md5(p.items[i])
        self.stats.block_item(it)
        self.stats.save(force=True)
        p.lver += 1
        events.log("gesperrt: %s" % (it.get("title") or it.get("name")))
        if i == cur and p.cur:
            await p.next()
        return it

    def unblock(self, key):
        ok = self.stats.unblock(key)
        if ok:
            self.stats.save(force=True)
            self.player.lver += 1
        return ok

    def statistics(self):
        """like the PC program's statistics: starts, listening time, top composers, SID chips (of the list)"""
        items = self.player.items
        per_author, chips, listened = {}, {1: 0, 2: 0, 3: 0}, 0
        for it in items:
            self.fill_meta(it)
            n = self.stats.count(it)
            a = (it.get("author") or "").strip()
            if a and n:
                per_author[a] = per_author.get(a, 0) + n
            if it.get("chips") in chips:
                chips[it["chips"]] += 1
            s, kind = self.item_len(it)
            if s and kind != "default":
                listened += s * n
        top = sorted(per_author.items(), key=lambda x: -x[1])[:10]
        return {"plays": sum(self.stats.plays.values()), "tunes": len(self.stats.plays), "favs": len(self.stats.fav),
                "listened": listened, "top": top, "chips": chips, "list": len(items), "blocked": len(self.stats.block)}

    async def check_list(self, job):
        """like "Check Lengths": read the header of every entry not known yet"""
        items = list(self.player.items)
        todo = [it for it in items if not self.fill_meta(it).get("md5")]
        bad = 0
        for k, it in enumerate(todo):
            job.progress = "%d von %d Dateien gelesen" % (k, len(todo))
            job.pct = int(100 * k / max(1, len(todo)))
            try:
                await self.info(it["src"], it["path"])
                it.pop("_nc", None)
                self.fill_meta(it)
            except (SourceError, OSError):
                bad += 1
            if k % 100 == 99:
                self.player.lver += 1                    # the page shows the titles read so far
        self.player.lver += 1
        self.player.dirty = True
        return dict({"read": len(todo) - bad, "bad": bad}, **await self._names_for_list(job))

    async def _names_for_list(self, job):
        """titles of the list still without a length: the same tune by name in the HVSC (namematch.py) - kept in
        list_hits for "übernehmen", taken at once with the setting "auto" """
        self.list_hits = []
        mode = self.config["player"].get("hvsc_name", "suggest")
        todo, seen = [], set()
        for it in self.player.items:
            m = it.get("md5")
            if m and m not in seen and self.songlengths.lookup(m, 1) is None:
                seen.add(m)
                todo.append(it)
        if mode == "off" or not todo:
            return {"nolen": len(todo), "found": 0, "taken": 0}
        job.progress, job.pct = "HVSC-Namensverzeichnis …", None
        ix = await self._name_index()
        if ix is None:
            return {"nolen": len(todo), "found": 0, "taken": 0}
        turn = time.monotonic()
        for k, it in enumerate(todo):
            job.progress = "Titel ohne Länge in der HVSC suchen: %d von %d" % (k, len(todo))
            job.pct = int(100 * k / len(todo))
            r = ix.find(it.get("name") or it.get("path", "").rsplit("/", 1)[-1], it.get("title"), it.get("author"))
            songs = self.songlengths.hvsc.get(bytes.fromhex(r[1])) if r else None
            if songs:
                self.list_hits.append((it["md5"], songs, r[0]))
            if time.monotonic() - turn > 0.02:
                await asyncio.sleep(0)
                turn = time.monotonic()
        found = len(self.list_hits)
        taken = self.take_list_hits() if mode == "auto" else 0
        return {"nolen": len(todo), "found": found, "taken": taken}

    def take_list_hits(self):
        """the lengths found by "Längen prüfen" become own lengths (all sub-songs), saved once"""
        hits, self.list_hits = self.list_hits, []
        if not hits:
            return 0
        for md5, songs, _ in hits:
            self.songlengths.custom[bytes.fromhex(md5)] = tuple(max(1, min(int(s), 65535)) for s in songs)
        self._save_custom_lengths()
        cur = self.player.cur
        if cur and cur["item"].get("md5") in {h[0] for h in hits}:
            cur["secs"] = self.songlengths.lookup(cur["item"]["md5"], cur["song"])
            self.player.version += 1
        self.player.lver += 1
        events.log("%d Längen über den Namen in der HVSC übernommen (Längen prüfen)" % len(hits))
        return len(hits)

    def set_user_length(self, item, secs, songs=None):
        """own length of a file (MD5), like the PC program; None removes it. songs: one length per sub-song (taken
        from the HVSC entry of the same tune)"""
        self.fill_meta(item)
        if not item.get("md5"):
            raise ValueError("Länge erst nach dem Lesen der Datei möglich (Längen prüfen)")
        key = bytes.fromhex(item["md5"])
        if songs:
            self.songlengths.custom[key] = tuple(max(1, min(int(s), 65535)) for s in songs)
        elif secs:
            self.songlengths.custom[key] = (max(1, min(int(secs), 65535)),)
        else:
            self.songlengths.custom.pop(key, None)
        self._save_custom_lengths()
        cur = self.player.cur
        if cur and cur["item"].get("md5") == item["md5"]:      # the tune that plays now ends there too
            cur["secs"] = self.songlengths.lookup(item["md5"], cur["song"])
            self.player.version += 1
        self.player.lver += 1

    async def remember_end(self):
        """the tune that plays ends here (it is over or starts again): its time so far becomes its own length (by MD5,
        like a length typed in), then on to the next one - for tunes no song length file knows"""
        p = self.player
        if p.state != "play" or not p.cur:
            raise ValueError("Es läuft gerade nichts")
        secs = int(round(p.elapsed()))
        if secs < 5:
            raise ValueError("Zu kurz – das Stück läuft erst %d s" % secs)
        name = p.cur["info"].get("title") or p.cur["item"].get("name")
        self.set_user_length(p.cur["item"], secs)
        events.log("Länge gemerkt: %s = %d:%02d" % (name, secs // 60, secs % 60))
        await p.next()
        return secs

    def _save_custom_lengths(self):
        with open(self._sl_path("custom"), "w", encoding="latin-1") as f:
            f.write(imports.user_lengths_text(self.songlengths.custom))
        if not self.config["songlengths"].get("custom"):
            self.config.data["songlengths"]["custom"] = {"label": "eigene Längen"}
            self.config.save()

    def merge_custom_lengths(self, text, overwrite=False):
        """import of a user_songlengths.txt: new MD5s are added; differing ones only with overwrite"""
        new = parse_lengths(text)
        if not new:
            raise ValueError("Keine Songlängen in der Datei gefunden")
        added = changed = kept = 0
        for k, v in new.items():
            old = self.songlengths.custom.get(k)
            if old is None:
                self.songlengths.custom[k] = v
                added += 1
            elif old != v:
                if overwrite:
                    self.songlengths.custom[k] = v
                    changed += 1
                else:
                    kept += 1
        self._save_custom_lengths()
        self.player.lver += 1
        return {"added": added, "changed": changed, "kept": kept}

    # ------------------------------------------------------------ play lists of the PC program
    async def _hvsc_map(self):
        """HVSC path -> MD5 from the loaded Songlengths.md5 - read and parsed in a thread (several MB: on the Pi 3B
        seconds in which the stream distributor would stand still), kept until the file changes"""
        p = self._sl_path("hvsc")
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return {}
        if getattr(self, "_hvsc_map_c", (None,))[0] != mt:
            def read():
                with open(p, encoding="latin-1") as f:
                    return imports.hvsc_paths(f.read())
            self._hvsc_map_c = (mt, await asyncio.get_running_loop().run_in_executor(None, read))
        return self._hvsc_map_c[1]

    async def index_folder(self, job, src_id, path, need_md5=True):
        """all .sid below a folder, with MD5 (cache, HVSC song length file, else read)"""
        idx = imports.FolderIndex()
        async for d, entries in self.walk(src_id, path, True, job=job):
            for e in entries:
                if not e["d"] and sidfile.is_sid_name(e["n"]):
                    idx.add(d.rstrip("/") + "/" + e["n"])
            job.progress = "Ordner erfassen: %d Ordner, %d SIDs" % (job.dirs, len(idx.paths))
        if not need_md5:
            return idx
        hv = await self._hvsc_map()
        unknown = []
        turn = time.monotonic()
        for p in idx.paths:
            if time.monotonic() - turn > 0.02:           # tens of thousands of files: let the stream distributor run
                await asyncio.sleep(0)
                turn = time.monotonic()
            c = self.catalog.get_info(src_id, p)
            m = c["md5"] if c else None
            if not m and hv:
                rel = imports.hvsc_rel(p)
                m = hv.get(rel) if rel else None
            if m:
                idx.add_md5(p, m)
            else:
                unknown.append(p)
        for k, p in enumerate(unknown):
            job.progress = "MD5 der übrigen Dateien: %d von %d" % (k, len(unknown))
            job.pct = int(100 * k / max(1, len(unknown)))
            try:
                data = await self.sources.get(src_id).read(p)
            except SourceError:
                continue
            m = sidfile.md5(data)
            head = sidfile.parse_header(data)
            if head:
                self.catalog.put_info(src_id, p, len(data), m, head)
            idx.add_md5(p, m)
        self.catalog.flush()
        return idx

    def _store_import(self, name, items, save):
        saved = ""
        if save and items:
            nm = name
            k = 2
            while any(pl["name"] == nm for pl in self.playlists()):
                nm = "%s (%d)" % (name, k)
                k += 1
            self.playlist_write(nm, items)
            saved = nm
        return saved

    async def import_shared(self, job, data, src_id, path, save=True):
        name, songs = imports.parse_shared(data)
        idx = await self.index_folder(job, src_id, path)
        job.progress = "Abgleich …"
        found, missing = imports.match_shared(songs, idx)
        items = [self.fill_meta({"src": src_id, "path": p, "name": p.rsplit("/", 1)[-1]}) for p in found]
        if items:
            await self.player.set_items(items, 0, play=False, source="Import „%s“" % name)
        return {"name": name, "found": len(found), "total": len(songs), "missing": missing,
                "check": self.auto_check(),
                "saved": self._store_import(name, items, save)}

    async def import_u64pl(self, job, text, name, src_id, path, save=True):
        entries = imports.parse_u64pl(text)
        if not entries:
            raise ValueError("Die Playlist enthält keine Einträge")
        idx = await self.index_folder(job, src_id, path, need_md5=False) if src_id else imports.FolderIndex()
        items, missing = [], []
        for e in entries:
            dev = imports.parse_device_path(e)
            if dev:
                ip, rpath = dev
                s = next((s for s in self.config["sources"] if s.get("kind") == "u64" and
                          host_of(self.config.ultimate(self.sources.ultimate_index(s)).get("addr")) == ip), None)
                if s:
                    items.append({"src": s["id"], "path": rpath, "name": rpath.rsplit("/", 1)[-1]})
                else:
                    missing.append(e)
                continue
            p = imports.match_u64pl_path(e, idx)
            if p:
                items.append(self.fill_meta({"src": src_id, "path": p, "name": p.rsplit("/", 1)[-1]}))
            else:
                missing.append(e.replace("\\", "/").rsplit("/", 1)[-1])
        if items:
            await self.player.set_items(items, 0, play=False, source="Import „%s“" % name)
            self.auto_check()
        return {"name": name, "found": len(items), "total": len(entries), "missing": missing,
                "saved": self._store_import(name, items, save)}

    async def export_shared(self, job, name):
        """the current list (or a saved one) as the PC program's shared playlist; MD5s are read where missing"""
        items = list(self.player.items) if not name else [self.fill_meta(i) for i in self.playlist_read(name).get("items", [])]
        for k, it in enumerate(items):
            self.fill_meta(it)
            if not it.get("md5"):
                job.progress = "lese %d von %d" % (k, len(items))
                try:
                    await self.info(it["src"], it["path"])
                    it.pop("_nc", None)
                    self.fill_meta(it)
                except (SourceError, OSError):
                    pass
        data, skipped = imports.export_shared(name or self.player.source or "playlist", items)
        return {"json": data, "skipped": skipped}

    # ------------------------------------------------------------ state for the page
    def state(self):
        u = self.config["ultimates"]
        st = self.hub.state()
        targets = st["targets"]
        np = self.notifier.status()
        for p in self.config["picos"]:
            p_np = np.get(p.get("addr"))
            if p_np:
                for t in targets:
                    if t["addr"] == p.get("addr"):
                        t["np"] = p_np
        pl = self.player.state_json()
        if pl.get("now"):
            pl["now"]["stil"] = self.stil_for(pl["now"])
        return {
            "player": pl,
            "ultimates": [{"label": x.get("label", ""), "addr": x.get("addr", "")} for x in u],
            "sel": self.config["u64_sel"],
            "stream": dict(st, on=self.config["stream"]["on"], msg=self.stream_msg),
            "power_msg": self.power_msg,
            "np": np,
            "arp": self.arp_log,
            "pico_news": {"n": len(self.notifier.news_body.split(b"\n")) if self.notifier.news_body else 0},
            "pwdefault": self.config.password_default(),
            "sl": dict(self.songlengths.counts(), stil=len(self.stil.db)),
            "hvsc": dict(zip(("src", "path"), self.hvsc_root())) if self.hvsc_root() else None,
            "opts": self.config["player"],
            "sidaddr": self.sidaddr.msg,
            "name": self.config["name"],
            "version": VERSION,
            "update": self.update["ver"] if self.update and self.update["newer"] and self.config.data.get("updates", True)
            else None,
            "upd": self.update_state(),
            "display": self.display.msg,
        }
