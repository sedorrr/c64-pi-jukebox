"""HDMI output: video packets -> picture, audio -> spectrum, the 17 styles (time per picture), slide show with
cross-fade, auto style change, the service's main loop (in memory instead of on a screen), and the jukebox's side:
hdmi-in.json, audio copy to the service, video request at the Ultimate, settings and pictures through the web API.
Previews in 1920 x 1080: tests/web/hdmi_*.png."""
import asyncio
import io
import json
import os
import socket
import struct
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np                                                      # noqa: E402
import pygame                                                           # noqa: E402
from aiohttp.test_utils import TestClient, TestServer                   # noqa: E402
from PIL import Image                                                   # noqa: E402

from c64jukebox.core import Jukebox                                     # noqa: E402
from c64jukebox.hdmi import receivers                                   # noqa: E402
from c64jukebox.hdmi.analyzer import BANDS, Analyzer                    # noqa: E402
from c64jukebox.hdmi.app import HdmiApp, Slideshow, TitleCard                     # noqa: E402
from c64jukebox.hdmi.modes import MODES                                 # noqa: E402
from c64jukebox.hdmi.screen import SoftScreen                           # noqa: E402
from c64jukebox.hdmi.styles import Info, Styles                         # noqa: E402
from c64jukebox.web import make_app                                     # noqa: E402
from fakes import FakeUltimate                                          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
H = {"X-C64": "1"}


def c64_picture(seed=0):
    rs = np.random.RandomState(seed)
    return rs.randint(0, 16, (272, 384)).astype(np.uint8)


def packets(img, frame=0, lines=272):
    out = []
    for y in range(0, lines, 4):
        rows = img[y:y + 4].reshape(-1)
        packed = (rows[0::2] | (rows[1::2] << 4)).astype(np.uint8)
        lr = y | (0x8000 if y == lines - 4 else 0)
        out.append(struct.pack("<HHHHBBH", y // 4, frame, lr, 384, 4, 4, 0) + packed.tobytes())
    return out


def audio_packet(k, f1=440.0, f2=2500.0, amp=(9000, 5000)):
    t = np.arange(192) + 192 * k
    x = (amp[0] * np.sin(2 * np.pi * t * f1 / 47983) + amp[1] * np.sin(2 * np.pi * t * f2 / 47983)).astype("<i2")
    return struct.pack("<H", k & 0xFFFF) + np.stack([x, (x * 0.5).astype("<i2")], 1).tobytes()


# ---------------------------------------------------------------- receiving
def test_decode_video_packets():
    img = c64_picture()
    pk = np.frombuffer(b"".join(packets(img)), dtype=np.uint8).reshape(-1, receivers.VIDEO_PKT)
    out = np.zeros((272, 384), dtype=np.uint8)
    assert receivers.decode_packets(pk, out) == 272 and (out == img).all()
    img2 = c64_picture(1)
    pk2 = np.frombuffer(b"".join(packets(img2)), dtype=np.uint8).reshape(-1, receivers.VIDEO_PKT)
    lost = np.delete(pk2, [10, 11], axis=0)                          # two packets lost: their lines stay
    receivers.decode_packets(lost, out)
    assert (out[40:48] == img[40:48]).all() and (out[:40] == img2[:40]).all() and (out[48:] == img2[48:]).all()
    ntsc = np.frombuffer(b"".join(packets(img, lines=240)), dtype=np.uint8).reshape(-1, receivers.VIDEO_PKT)
    assert receivers.decode_packets(ntsc, out) == 240
    bad = pk.copy()
    bad[:, 9] = 8                                                    # 8 bits per pixel: not understood, ignored
    assert receivers.decode_packets(bad, out) == 0


def test_receivers_over_udp():
    v = receivers.VideoReceiver(0, "127.0.0.1")
    a = receivers.AudioReceiver(0)
    v.start()
    a.start()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        img = c64_picture(2)
        for p in packets(img):
            s.sendto(p, ("127.0.0.1", v.port))
        for k in range(50):
            s.sendto(audio_packet(k), ("127.0.0.1", a.port))
        s.sendto(b"C64NP1 t=x", ("127.0.0.1", a.port))                  # a title: not sound
        for _ in range(100):
            if v.frames and a.pkts >= 50:
                break
            time.sleep(0.02)
        pic = v.picture()
        assert pic is not None and pic.shape == (272, 384) and (pic == img).all()
        assert v.picture() is None                                       # nothing new
        assert a.pkts == 50
        snap = a.snapshot(4096)
        assert snap.shape == (4096, 2)
        last = np.frombuffer(audio_packet(49), dtype="<i2", offset=2).reshape(192, 2)
        assert (snap[-192:] == last).all()                               # newest last
        assert v.age() < 1 and a.age() < 1
    finally:
        v.close()
        a.close()
        s.close()


def stereo_of(packets_n=43, **kw):
    return np.concatenate([np.frombuffer(audio_packet(k, **kw), dtype="<i2", offset=2).reshape(192, 2)
                           for k in range(packets_n)]).astype(np.float32)


def test_analyzer_bands_peaks_calm():
    a = Analyzer()
    st = stereo_of(f1=1000.0, f2=1000.0)
    for _ in range(8):
        a.update(st, chips=2)
    edges = np.logspace(np.log10(40), np.log10(16000), BANDS + 1)
    band = int(np.searchsorted(edges, 1000.0)) - 1
    assert int(np.argmax(a.smoothed)) == band
    assert a.smoothed[band] > 0.5 and a.smoothed[0] < a.smoothed[band]
    assert a.smoothed_l[band] > a.smoothed_r[band] > 0                # the right channel is half as loud
    assert len(a.history) == 6 and a.lr_levels[0] > a.lr_levels[1]
    top = float(a.peak[band])
    for _ in range(3):
        a.calm()
    assert a.peak[band] == top                                          # peak hold
    for _ in range(30):
        a.calm()
    assert a.smoothed.max() < 0.01 and a.peak.max() < 0.05


# ---------------------------------------------------------------- drawing
def test_all_styles_render_and_are_fast():
    pygame.init()
    a = Analyzer()
    st = stereo_of()
    for _ in range(5):
        a.update(st, chips=2)
    styles = Styles((960, 540), seed=3)
    surf = pygame.Surface((960, 540), pygame.SRCALPHA)
    times = {}
    for chips in (1, 2):
        info = Info(chips, ["$D400", "$D420"], "Crazy Comets", "Rob Hubbard")
        for mode in MODES:
            t0 = time.perf_counter()
            for i in range(10):
                surf.fill((0, 0, 0, 0))
                styles.draw(mode, surf, a, info, bg=bool(i % 2), now=1000 + i / 30)
            times[(mode, chips)] = (time.perf_counter() - t0) / 10 * 1000
            drawn = pygame.mask.from_surface(surf).count()
            assert (drawn == 0) == (mode == "none"), mode
    worst = max(times.values())
    print("ms per picture (this PC):", {"%s/%d" % k: round(v, 2) for k, v in times.items()})
    assert worst < 15, times           # the Pi 3B is ~10-15x slower: still within 1/30 s for the drawing


def preview_items(app):
    scr = SoftScreen()
    scr.present(app.compose(app.clock()))
    return scr.snapshot()


def write_in(run, cfg, player=None, img_dir=""):
    p = os.path.join(run, "hdmi-in.json")
    with open(p + ".tmp", "w") as f:
        json.dump({"t": time.time(), "cfg": cfg, "player": player or {}, "img_dir": img_dir, "name": "c64pi"}, f)
    os.replace(p + ".tmp", p)


PLAYER = {"state": "play", "el": 83, "now": {"title": "Crazy Comets", "author": "Rob Hubbard", "year": "1985",
                                             "models": ["MOS6581", "MOS8580"], "sids": ["D400", "D420"], "chips": 2,
                                             "secs": 276, "song": 1, "songs": 17}}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_pictures(folder, n=2):
    os.makedirs(folder, exist_ok=True)
    for i in range(n):
        img = pygame.Surface((800, 600))
        img.fill(((i * 120) % 256, 80, 200 - i * 60))
        pygame.draw.circle(img, (255, 220, 120), (400, 300), 200)
        pygame.image.save(img, os.path.join(folder, "bild%d.png" % i))


def test_slideshow_crossfade():
    pygame.init()
    folder = os.path.join(HERE, "..", ".pytest_cache", "hdmi_slides")
    make_pictures(folder, 3)
    s = Slideshow()
    s.configure(folder, False, 0)
    assert len(s.files) == 3

    def until(now, cond):
        for _ in range(200):
            items = s.items(now, 10, 255)
            if cond(items):
                return items
            time.sleep(0.01)
        raise AssertionError("slide show stuck")
    first = until(0, lambda it: len(it) == 1)
    assert first[0].surf.get_size() == (1920, 1080) and first[0].key == "bg_a"
    until(5, lambda it: s.nxt is not None)                              # the next one is loaded ahead
    assert [i.key for i in s.items(10.0, 10, 200)] == ["bg_a", "bg_b"]       # the fade starts
    mid = s.items(10.32, 10, 200)
    assert [i.key for i in mid] == ["bg_a", "bg_b"] and 100 < mid[1].alpha < 160 and mid[1].light == 200
    after = s.items(11.0, 10, 255)
    assert [i.key for i in after] == ["bg_a", "bg_b"] and after[1].alpha == 255
    assert [i.key for i in s.items(11.1, 10, 255)] == ["bg_a"] and s.switch_at == 21.0


def test_service_loop_in_memory(tmp_path):
    pygame.init()
    run = str(tmp_path)
    clock = Clock()
    screens = []

    def opener():
        screens.append(SoftScreen())
        return screens[-1], "Test"
    app = HdmiApp(run, opener, audio_port=0, video_port=0, clock=clock, seed=5)
    assert app.tick() == 0.5 and not app.screen                        # off: the display stays free
    write_in(run, {"on": True, "mode": "c64", "bg": "video", "opacity": 80}, PLAYER)
    clock.t += 1
    app.tick()
    assert app.screen and app.audio and app.video
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for k in range(43):
        s.sendto(audio_packet(k), ("127.0.0.1", app.audio.port))
    img = c64_picture(4)
    img[:16, :16] = 10                                                # a plain corner (scaling blends neighbours)
    for p in packets(img):
        s.sendto(p, ("127.0.0.1", app.video.port))
    for _ in range(100):
        if app.video.frames and app.audio.pkts >= 43:
            break
        time.sleep(0.02)
    keys = [i.key for i in app.compose(clock.t)]
    assert keys == ["video", "viz", "osd_top", "osd_time"]
    st = json.load(open(os.path.join(run, "hdmi.json")))
    assert st["on"] and st["screen"] == "Test"
    pygame.image.save(preview_items(app), os.path.join(HERE, "web", "hdmi_c64_video.png"))
    # the C64 picture alone, in 4:3 with borders
    write_in(run, {"on": True, "mode": "none", "bg": "video", "opacity": 100, "osd": False}, PLAYER)
    clock.t += 1
    app.read_input(clock.t)
    for p in packets(img, frame=1):
        s.sendto(p, ("127.0.0.1", app.video.port))
    time.sleep(0.2)
    shot = preview_items(app)
    assert shot.get_at((100, 540))[:3] == (0, 0, 0)                    # border
    assert shot.get_at((240 + 8, 8))[:3] == receivers.VIC_PALETTE[10]
    pygame.image.save(shot, os.path.join(HERE, "web", "hdmi_c64_only.png"))
    # pictures + effects, auto change of the style while a tune plays
    folder = str(tmp_path / "bilder")
    make_pictures(folder, 2)
    write_in(run, {"on": True, "mode": "neon_grid", "bg": "images", "opacity": 60, "auto": True, "auto_s": 60,
                   "auto_modes": ["bars", "milkdrop"]}, PLAYER, folder)
    clock.t += 1
    app.read_input(clock.t)
    assert app.video is None or app.compose(clock.t) is not None
    for _ in range(100):
        items = app.compose(clock.t)
        if items and items[0].key == "bg_a":
            break
        time.sleep(0.02)
    assert app.video is None and app.mode == "neon_grid"
    pygame.image.save(preview_items(app), os.path.join(HERE, "web", "hdmi_neon_pictures.png"))
    clock.t += 61
    app.compose(clock.t)
    assert app.mode in ("bars", "milkdrop")
    first = app.mode
    clock.t += 61
    app.compose(clock.t)
    assert app.mode in ("bars", "milkdrop") and app.mode != first
    for mode in ("bars", "milkdrop", "vinyl", "c64", "cloud"):
        write_in(run, {"on": True, "mode": mode, "bg": "none"}, PLAYER)
        clock.t += 1
        app.read_input(clock.t)
        for _ in range(3):
            for k in range(8):
                s.sendto(audio_packet(k), ("127.0.0.1", app.audio.port))
            time.sleep(0.03)
            app.compose(clock.t)
        pygame.image.save(preview_items(app), os.path.join(HERE, "web", "hdmi_%s.png" % mode))
    # nothing plays: a hint instead of an (almost) black screen
    write_in(run, {"on": True, "mode": "bars", "bg": "none"}, {"state": "stop", "total": 3})
    clock.t += 1
    app.read_input(clock.t)
    assert [i.key for i in app.compose(clock.t)] == ["viz", "osd_idle"]
    write_in(run, {"on": False}, PLAYER)
    clock.t += 1
    assert app.tick() == 0.5 and app.screen is None and app.audio is None
    s.close()


# ---------------------------------------------------------------- the jukebox's side
def test_jukebox_side(tmp_path):
    async def t():
        u64 = await FakeUltimate().start()
        run = tmp_path / "run"
        run.mkdir()
        now = [1000.0]
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(run),
                     clock=lambda: now[0])
        jb.config.data["ultimates"] = [{"label": "Elite", "addr": u64.addr, "pw": ""}]
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(2)
        jb.hdmi_audio_port = rx.getsockname()[1]
        app = make_app(jb)
        app.on_startup.append(lambda a: jb.start())
        app.on_cleanup.append(lambda a: jb.close())
        c = TestClient(TestServer(app))
        await c.start_server()
        try:
            await c.post("/api/login", json={"pw": "commodore64"}, headers=H)
            r = await c.get("/api/hdmi")
            d = await r.json()
            assert d["cfg"]["on"] is False and "milkdrop" in d["modes"] and d["images"] == []
            r = await c.post("/api/hdmi", json={"on": True, "mode": "milkdrop", "bg": "video", "opacity": 250,
                                                 "auto_modes": ["bars", "nonsense"], "img_s": 1}, headers=H)
            cfg = (await r.json())["cfg"]
            assert cfg["on"] and cfg["mode"] == "milkdrop" and cfg["opacity"] == 100 and cfg["img_s"] == 3
            assert cfg["auto_modes"] == ["bars"]
            hin = json.load(open(run / "hdmi-in.json"))
            assert hin["cfg"]["mode"] == "milkdrop" and hin["img_dir"].endswith("hdmi-bilder")
            # audio: requested although the stream distributor is off, and every packet is copied to the service
            await asyncio.sleep(1.2)
            assert u64.find("PUT", "/v1/streams/audio:start")
            v = u64.find("PUT", "/v1/streams/video:start")
            assert v and v[0][2]["ip"].endswith(":11000")
            jb.hub.my_ips = {"192.0.2.99"}               # here the "Ultimate" sends from 127.0.0.1 too
            snd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            snd.sendto(audio_packet(1), ("127.0.0.1", jb.hub.port))
            got = await asyncio.get_running_loop().run_in_executor(None, rx.recv, 2048)
            assert got == audio_packet(1)
            snd.close()
            # the service reports pictures from the C64: no new request; switched to pictures: video given back
            json.dump({"t": time.time(), "video_age": 0.1}, open(run / "hdmi.json", "w"))
            now[0] += 11
            await asyncio.sleep(1.2)
            assert len(u64.find("PUT", "/v1/streams/video:start")) == 1
            await c.post("/api/hdmi", json={"bg": "images"}, headers=H)
            await asyncio.sleep(1.2)
            assert u64.find("PUT", "/v1/streams/video:stop")
            # pictures: made 1920 x 1080, listed, served, deleted
            buf = io.BytesIO()
            Image.new("RGB", (4000, 1000), (200, 50, 50)).save(buf, "JPEG")
            r = await c.post("/api/hdmi/upload?name=Sonnen%20untergang.jpg", data=buf.getvalue(), headers=H)
            d = await r.json()
            assert d["name"] == "Sonnen_untergang.jpg" and len(d["images"]) == 1
            with Image.open(os.path.join(jb.hdmi_dir(), d["name"])) as im:
                assert im.size == (1920, 1080)
            r = await c.post("/api/hdmi/upload?name=x.txt", data=b"kein Bild", headers=H)
            assert r.status == 400 and "kein Bild" in (await r.json())["msg"]
            r = await c.get("/api/hdmi/image?name=Sonnen_untergang.jpg")
            assert r.status == 200 and (await r.read())[:2] == b"\xff\xd8"
            r = await c.get("/api/hdmi/image?name=../config.json")
            assert r.status == 400
            r = await c.post("/api/hdmi/delete", json={"name": "Sonnen_untergang.jpg"}, headers=H)
            assert (await r.json())["images"] == []
            # off: no more copies, the service is told once
            await c.post("/api/hdmi", json={"on": False}, headers=H)
            assert jb.hub.local == [] and json.load(open(run / "hdmi-in.json"))["cfg"]["on"] is False
        finally:
            rx.close()
            await c.close()
            await u64.stop()
    asyncio.run(t())


def test_sound_over_hdmi(tmp_path):
    """sound on: a process of its own (soundproc.py) takes the packets the jukebox sends it and puts their frames into
    the player program (aplay on the Pi); the fade goes down to it; off: it is stopped"""
    import sys
    pygame.init()
    run = str(tmp_path)
    out = tmp_path / "ton.raw"
    clock = Clock()
    app = HdmiApp(run, lambda: (SoftScreen(), "Test"), audio_port=0, video_port=0, clock=clock)
    app.sound_cmd = [sys.executable, "-c", "import sys; open(%r, 'wb').write(sys.stdin.buffer.read())" % str(out)]
    app.sound_port = 0
    write_in(run, {"on": True, "mode": "bars", "bg": "none", "sound": True}, PLAYER)
    app.tick()
    assert app.sound and app.sound.port
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for k in range(10):
        s.sendto(audio_packet(k), ("127.0.0.1", app.sound.port))
        time.sleep(0.005)
    s.sendto(b"x" * 20, ("127.0.0.1", app.sound.port))           # no audio packet: ignored
    for _ in range(100):
        if app.sound.alive():
            break
        time.sleep(0.05)
    app.write_status(clock.t + 5)
    st = json.load(open(os.path.join(run, "hdmi.json")))
    assert st["sound"] is True and st["sound_dropped"] == 0
    app.sound.fade_to(0.0, 2.0)                                   # followed by the clock here
    assert app.sound.step and app.sound.target == 0.0
    clock.t += 1
    assert 0.4 < app.sound.gain < 0.6
    clock.t += 2
    assert app.sound.gain == 0.0 and not app.sound.step
    write_in(run, {"on": True, "mode": "bars", "bg": "none", "sound": False}, PLAYER)
    clock.t += 1
    app.read_input(clock.t)
    app.compose(clock.t)
    assert app.sound is None
    for _ in range(100):
        if out.exists() and out.stat().st_size == 10 * 768:
            break
        time.sleep(0.02)
    assert out.read_bytes() == b"".join(audio_packet(k)[2:] for k in range(10))
    app.stop()


def test_fade_ramp_and_timing(tmp_path):
    from c64jukebox.hdmi.app import Sound
    s = Sound(cmd=["true"])
    loud = (np.ones((192, 2)) * 10000).astype("<i2").tobytes()
    assert s._apply_gain(loud) == loud                                   # full volume: untouched
    s.fade_to(0.0, 192 * 2 / 47983)                                      # to silence over two packets
    a = np.frombuffer(s._apply_gain(loud), dtype="<i2").reshape(-1, 2)
    assert 4000 < a[-1, 0] < 6000 and a[0, 0] > a[-1, 0]                 # half way, falling sample by sample
    b = np.frombuffer(s._apply_gain(loud), dtype="<i2").reshape(-1, 2)
    assert b[-1, 0] == 0 and s.step == 0.0
    assert not np.frombuffer(s._apply_gain(loud), dtype="<i2").any()     # stays silent until faded in
    s.fade_to(1.0, 0)
    assert s._apply_gain(loud) == loud
    s.volume = 0.25                                                      # the page's volume on top
    assert np.frombuffer(s._apply_gain(loud), dtype="<i2")[0] == 2500
    s.close()

    class Rec:
        def __init__(self):
            self.calls, self.gain, self.target, self.step = [], 1.0, 1.0, 0.0

        def fade_to(self, t, secs):
            self.calls.append((t, round(secs, 2)))
            self.gain = self.target = t
    clock = Clock()
    app = HdmiApp(str(tmp_path), lambda: (SoftScreen(), "Test"), clock=clock)
    app.sound = Rec()
    app.cfg = dict(app.cfg, fade=True, fade_s=3.0)
    t0 = clock.t

    def at(dt, player, read=0):
        """the state as read at t0 + read (the jukebox writes it every second), the clock at t0 + dt"""
        app.player, app.player_at = player, t0 + read
        app.fade(t0 + dt)
        return app.sound.calls
    one = {"state": "play", "el": 1, "now": {"src": "nas", "path": "/a.sid", "song": 1, "secs": 10}}
    assert at(0, one) == [(0.0, 0), (1.0, 3.0)]                           # a song just begun: fade in
    assert len(at(4, one)) == 2                                           # 5 s left: not yet
    assert at(7.5, one)[-1] == (0.0, 1.5)                                 # the rest of the song
    assert len(at(8, one)) == 3                                           # only once
    assert len(at(8.5, {})) == 3                                          # no data for a moment: volume left alone
    assert len(at(9, {"state": "stop"})) == 3
    two = {"state": "play", "el": 0, "now": {"src": "nas", "path": "/b.sid", "song": 1, "secs": 200}}
    assert at(10, two, 10)[-2:] == [(0.0, 0), (1.0, 3.0)]                 # the next one fades in
    assert len(at(11, {}, 11)) == 5 and len(at(12, two, 10)) == 5         # the data comes back: nothing
    app.sound.target = 0.5
    late = {"state": "play", "el": 50, "now": {"src": "nas", "path": "/c.sid", "song": 1, "secs": 200}}
    assert at(13, late, 13)[-1] == (1.0, 0)                                   # first seen in its middle: full at once
    assert any("Titel schon" in n for n in app.fade_log)
    # length unknown: the jukebox moves on at the time limit (the "default" length) - faded out before it as well
    lim = {"state": "play", "el": 0, "now": {"src": "nas", "path": "/d.sid", "song": 1, "secs": None, "end": 180}}
    n = len(at(20, lim, 20))
    assert len(at(196, lim, 20)) == n and at(197.5, lim, 20)[-1] == (0.0, 2.5)   # el 177.5: the last 2.5 s
    app.cfg["fade"] = False
    app.sound.gain = 0.5
    assert at(214, late, 213)[-1] == (1.0, 0)                                 # switched off: full volume again


def test_title_card(tmp_path):
    """a large card when a new tune starts, fading out after osd_big_s; none for a tune that has long been playing"""
    pygame.init()
    tc = TitleCard()
    new = dict(PLAYER, el=0.5, now=dict(PLAYER["now"], src="pi", path="/a.sid",
                                          stil=["Original von: Tamayo Kawamoto", "Titel: BGM1"]))
    assert tc.items(new, 100.0, 6) and tc.items(new, 100.0, 6)[0].alpha == 0       # fades in
    it = tc.items(new, 101.0, 6)[0]
    assert it.alpha == 255 and abs(it.rect.centerx - 960) <= 1 and abs(it.rect.centery - 540) <= 1 and it.rect.width == 1200
    assert 0 < tc.items(new, 105.6, 6)[0].alpha < 255                                 # fades out
    assert tc.items(new, 106.1, 6) == [] and tc.items(new, 107, 6) == []
    nxt = dict(new, now=dict(new["now"], song=2))                                     # next sub-tune: again
    assert tc.items(nxt, 108, 6)
    old = dict(PLAYER, now=dict(PLAYER["now"], src="pi", path="/b.sid"))              # el 83: playing for long
    assert tc.items(old, 110, 6) == []
    # in the service: the card above the effects, under the small text; switched off -> none
    run = str(tmp_path)
    clock = Clock()
    app = HdmiApp(run, lambda: (SoftScreen(), "Test"), audio_port=0, video_port=0, clock=clock, seed=5)
    write_in(run, {"on": True, "mode": "bars", "bg": "none"}, new)
    app.tick()
    clock.t += 1.5
    keys = [i.key for i in app.compose(clock.t)]
    assert keys.index("titlecard") > keys.index("viz") and keys.index("titlecard") < keys.index("osd_top")
    pygame.image.save(preview_items(app), os.path.join(HERE, "web", "hdmi_titlecard.png"))
    write_in(run, {"on": True, "mode": "bars", "bg": "none", "osd_big": False}, dict(new, now=dict(new["now"], path="/c.sid")))
    clock.t += 1
    app.read_input(clock.t)
    assert "titlecard" not in [i.key for i in app.compose(clock.t)]
    app.stop()


def test_qr_code(tmp_path):
    """the QR code for the TV: like the reference package module by module (if it is installed), on the idle screen"""
    import pytest
    from c64jukebox.hdmi import qr
    from c64jukebox.hdmi.app import Osd
    ref = None
    try:
        import qrcode
        import qrcode.util
        ref = qrcode
    except ImportError:
        pass
    for text in ("http://192.168.1.78/", "http://c64pi.local/", "x" * 106):
        for mask in range(8):
            mine = qr.encode(text, mask)
            v = (len(mine) - 17) // 4
            assert 1 <= v <= 6
            if ref:
                q = ref.QRCode(version=v, error_correction=ref.constants.ERROR_CORRECT_M, border=0, mask_pattern=mask)
                q.add_data(ref.util.QRData(text.encode(), mode=ref.util.MODE_8BIT_BYTE))
                q.make(fit=False)
                assert q.get_matrix() == mine, (text, mask)
    with pytest.raises(ValueError):
        qr.encode("x" * 107)
    pygame.init()
    items = Osd().items({"state": "stop"}, "", "c64pi", ip="192.168.1.78")
    keys = [i.key for i in items]
    assert keys == ["osd_idle", "osd_qr"]
    idle, code = items
    assert code.rect.right < idle.rect.left and code.rect.top == idle.rect.top
    assert code.rect.bottom < (1080 - 560) // 2 + 40                    # above the news card of the idle screen
    scr = SoftScreen()
    scr.present(items)
    pygame.image.save(scr.snapshot(), os.path.join(HERE, "web", "hdmi_idle_qr.png"))
    assert [i.key for i in Osd().items({"state": "stop"}, "", "c64pi")] == ["osd_idle"]      # switched off / no address


# ---------------------------------------------------------------- SID voices (the Ultimate's debug stream)
def tune_writes(frames, base=0xD400, shift=0, at=200):
    """a little tune: melody, bass and an arpeggio, one register set per frame as players do"""
    from test_sidtrace import A4
    out = []
    mel, bass = [0, 2, 4, 5, 7, 5, 4, 2], [-24, -24, -19, -17]
    for f in range(frames):
        notes = (mel[f // 12 % 8] + shift, bass[f // 50 % 4] + shift, [0, 4, 7][f % 3] + 12 + shift)
        c = f * 19656 + at
        for v, n in enumerate(notes):
            reg = round(A4 * 2 ** (n / 12))
            gate = 0 if f % 12 == 11 and v == 0 else 1
            out += [(c, base + v * 7, reg & 255), (c + 1, base + v * 7 + 1, reg >> 8),
                    (c + 2, base + v * 7 + 2, 0x00), (c + 3, base + v * 7 + 3, 0x08),
                    (c + 4, base + v * 7 + 5, 0x09), (c + 5, base + v * 7 + 6, 0xA4),
                    (c + 6, base + v * 7 + 4, (0x40, 0x20, 0x10)[v] | gate)]
            c += 8
        out += [(c, base + 0x15, 0x00), (c + 1, base + 0x16, 0x60), (c + 2, base + 0x17, 0xF2), (c + 3, base + 0x18, 0x1F)]
    return out


def test_sid_voices_style_and_service(tmp_path):
    from test_sidtrace import stream
    pygame.init()
    run = str(tmp_path)
    clock = Clock()
    app = HdmiApp(run, lambda: (SoftScreen(), "Test"), audio_port=0, video_port=0, sid_port=0, clock=clock, seed=5)
    player = dict(PLAYER, now=dict(PLAYER["now"], sids=["D400", "D500"]))
    write_in(run, {"on": True, "mode": "sidvoices", "bg": "none"}, player)
    clock.t += 1
    app.tick()
    assert app.sid and app.sid_want
    shot = preview_items(app)                                         # nothing yet: a hint
    # the receive path: a few real packets over UDP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for p in stream(tune_writes(2), 2 * 19656):
        s.sendto(p, ("127.0.0.1", app.sid.port))
    for _ in range(100):
        if app.sid.trace.pkts >= 100:
            break
        time.sleep(0.02)
    assert app.sid.trace.pkts == 110 and app.sid.trace.lost == 0 and app.sid.age() < 1
    # 5 s of a 2SID tune straight into the trace (faster than 13 000 packets over UDP)
    ws = sorted(tune_writes(250) + tune_writes(250, 0xD500, shift=-5, at=300))
    with app.sid.lock:
        app.sid.trace.feed(stream(ws, 250 * 19656, start_seq=app.sid.trace.seq + 1))
    app.sid.last = time.monotonic()
    frames = app.sid.frames(["D400", "D500"])
    assert sorted(frames[-1][1]) == [0xD400, 0xD500] and len(frames) >= 250
    t0 = time.perf_counter()
    shot = preview_items(app)
    ms = (time.perf_counter() - t0) * 1000
    pygame.image.save(shot, os.path.join(HERE, "web", "hdmi_sidvoices.png"))
    assert ms < 40, ms
    clock.t += 2
    app.write_status(clock.t)
    st = json.load(open(os.path.join(run, "hdmi.json")))
    assert st["sid_want"] is True and st["sid"]["chips"] == ["$D400", "$D500"]
    # the C64 picture as background: no debug stream (both together are too much for the Ultimate's network)
    write_in(run, {"on": True, "mode": "sidvoices", "bg": "video"}, player)
    clock.t += 1
    app.read_input(clock.t)
    app.compose(clock.t)
    assert app.sid is None and not app.sid_want
    write_in(run, {"on": False}, player)
    clock.t += 1
    app.tick()
    s.close()


def test_sid_voices_jukebox_asks_the_ultimate(tmp_path):
    async def t():
        a, b = await FakeUltimate().start(), await FakeUltimate().start()
        run = tmp_path / "run"
        run.mkdir()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(run))
        jb.config.data["ultimates"] = [{"label": "Elite II", "addr": a.addr, "pw": ""},
                                       {"label": "Elite", "addr": b.addr, "pw": ""}]
        jb.config.data["hdmi"]["on"] = True
        await jb.start()
        try:
            def status(**kw):
                json.dump(dict({"t": time.time()}, **kw), open(run / "hdmi.json", "w"))
            status(sid_want=False)
            await jb._sid_keep()
            assert not a.find("PUT", "/v1/streams/debug:start")
            status(sid_want=True)
            a.debug_mode = "VIC Only"
            await jb._sid_keep()
            assert not a.find("PUT", "/v1/streams/debug:start") and "6510 Only" in jb.sid_msg
            a.debug_mode = "6510 Only"
            jb._sid_req_at = -1e9
            await jb._sid_keep()
            r = a.find("PUT", "/v1/streams/debug:start")
            assert r and r[0][2]["ip"].endswith(":11003") and jb._sid_asked == a.addr
            status(sid_want=True, sid_age=0.1)                       # data comes: no new request
            jb._sid_req_at = -1e9
            await jb._sid_keep()
            assert len(a.find("PUT", "/v1/streams/debug:start")) == 1
            # another Ultimate chosen: the old one stops first, the new one is asked
            jb.config.data["u64_sel"] = 1
            status(sid_want=True)
            await jb._sid_keep()
            assert a.find("PUT", "/v1/streams/debug:stop") and b.find("PUT", "/v1/streams/debug:start")
            # no longer shown: given back
            status(sid_want=False)
            await jb._sid_keep()
            assert jb._sid_asked == "" and jb.sid_msg == ""
        finally:
            await jb.close()
            await a.stop()
            await b.stop()
    asyncio.run(t())


def test_receivers_take_only_the_ultimates():
    """the C64 picture and the SID data only from the entered Ultimates' (Ethernet) addresses"""
    v, sd = receivers.VideoReceiver(0, host="127.0.0.1"), receivers.SidReceiver(0, host="127.0.0.1")
    v.allow, sd.allow = {"10.64.64.2"}, {"10.64.64.2"}
    v.start()
    sd.start()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for p in packets(c64_picture(1)):
            s.sendto(p, ("127.0.0.1", v.port))
        s.sendto(b"\0" * 1444, ("127.0.0.1", sd.port))
        for _ in range(50):
            if v.foreign >= 68 and sd.foreign:
                break
            time.sleep(0.02)
        assert v.frames == 0 and v.foreign == 68 and sd.foreign == 1 and sd.trace.pkts == 0
        v.allow.add("127.0.0.1")
        for p in packets(c64_picture(1), frame=1):
            s.sendto(p, ("127.0.0.1", v.port))
        for _ in range(50):
            if v.frames:
                break
            time.sleep(0.02)
        assert v.frames == 1
        s.close()
    finally:
        v.close()
        sd.close()
