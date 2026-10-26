"""Ultimate REST client, "now playing" to the Picos (digest / UDP), stream distributor, device beacons."""
import asyncio
import json
import socket
import time
from urllib.parse import parse_qs

import aiohttp
import pytest

from c64jukebox.config import Config
from c64jukebox.devices import Devices, fit_json
from c64jukebox.nowplaying import Notifier, fold, news_body, np_params, np_query
from c64jukebox.stream import StreamHub, peaks, span
from c64jukebox.ultimate import Ultimate, UltimateError
from fakes import FakePico, FakeUltimate, UdpSink, make_sid


def run(c):
    return asyncio.run(c)


def test_ultimate_rest():
    async def t():
        u64 = await FakeUltimate(pw="netz").start()
        async with aiohttp.ClientSession() as s:
            u = Ultimate(s, u64.addr, "netz")
            await u.play_path("/USB2/SID-Tunes/HVSC 78/A b+c.sid", 2)
            await u.play_data("tune.sid", make_sid(), 1)
            await u.machine("reset")
            await u.stream_start("192.168.1.5")
            await u.stream_stop()
            assert (await u.info())["product"].startswith("Ultimate")
            m, path, q, _ = u64.calls[0]
            assert (m, path, q) == ("PUT", "/v1/runners:sidplay", {"file": "/USB2/SID-Tunes/HVSC 78/A b+c.sid", "songnr": "2"})
            m, path, q, up = u64.calls[1]
            assert m == "POST" and up["field"] == "file" and up["filename"] == "tune.sid" and up["data"] == make_sid()
            assert u64.calls[2][1] == "/v1/machine:reset"
            assert u64.calls[3][2] == {"ip": "192.168.1.5:11001"}
            assert u64.calls[4][1] == "/v1/streams/audio:stop"
            with pytest.raises(UltimateError, match="Passwort"):
                await Ultimate(s, u64.addr, "falsch").machine("pause")
            with pytest.raises(UltimateError, match="nicht erreichbar"):
                await Ultimate(s, "127.0.0.1:1", "").machine("pause")
        await u64.stop()
    run(t())


def test_np_query_format():
    p = np_params({"title": "Ä" * 40, "author": "Rob & Co", "song": 2, "songs": 3, "sids": ["D400", "D420"]}, 117, 31.7, new=True)
    q = np_query(p)
    assert q.startswith("new=1&title=")
    d = parse_qs(q)
    assert d["title"] == ["Ä" * 32] and d["author"] == ["Rob & Co"] and d["secs"] == ["117"] and d["el"] == ["31"]
    assert d["sid"] == ["D400,D420"] and d["song"] == ["2"] and d["songs"] == ["3"]
    assert np_query({"stop": 1}) == "stop=1"


def test_notifier_digest_and_udp(tmp_path):
    async def t():
        pico = await FakePico(pw="geheim", busy=1).start()
        sink = UdpSink()
        cfg = Config(str(tmp_path))
        cfg.data["picos"] = [{"addr": "127.0.0.1:%d" % pico.port, "pw": "geheim", "np": "http"},
                             {"addr": "127.0.0.1", "np": "udp"},
                             {"addr": "127.0.0.1:9", "np": "off"}]
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        async def resolve(h):
            return "127.0.0.1"
        async with aiohttp.ClientSession() as s:
            n = Notifier(cfg, s, lambda d, a: udp.sendto(d, a), resolve)
            n.udp_port = sink.port
            info = {"title": "Commando", "author": "Rob Hubbard", "song": 1, "songs": 3, "sids": ["D400"]}
            n.playing(info, 200, lambda: 0)
            await asyncio.sleep(0.6)
            assert pico.got and pico.got[0]["new"] == "1" and pico.got[0]["title"] == "Commando"
            got = sink.drain(0.2)
            assert got and got[0][0].startswith(b"C64NP1 new=1&title=Commando&author=Rob%20Hubbard&secs=200")
            # the clock every 30 s
            n.next_beat = 0
            n.tick()
            await asyncio.sleep(0.4)
            assert "new" not in pico.got[-1] and pico.got[-1]["el"] == "0"
            n.stopped()
            await asyncio.sleep(0.4)
            assert pico.got[-1] == {"stop": "1"}
            assert sink.drain(0.2)[-1][0] == b"C64NP1 stop=1"
            assert n.status()["127.0.0.1:%d" % pico.port] == "ok"
            # a wrong password is reported, not retried for ever
            cfg.data["picos"] = [{"addr": "127.0.0.1:%d" % pico.port, "pw": "falsch", "np": "http"}]
            n.links.clear()
            n.playing(info, 0, lambda: 0)
            await asyncio.sleep(0.5)
            assert n.status()["127.0.0.1:%d" % pico.port] == "Passwort falsch"
            n.close()
        sink.close()
        udp.close()
        await pico.stop()
    run(t())


def test_news_for_the_matrix():
    assert fold("Neues Spiel für den C64 – „Übermütig“ … {rot} Café") == \
        'Neues Spiel fuer den C64 - "Uebermuetig" ... (rot) Cafe'
    assert fold("日本語 X") == "X" and fold("a\tb\nc") == "a b c"
    items = [{"src": "Lemon64", "title": "Ä" * 120}] + [{"src": "CSDb", "title": "Demo %d" % i} for i in range(9)]
    b = news_body(items)
    lines = b.decode().split("\n")
    assert len(lines) == 6 and lines[1] == "CSDb: Demo 0" and len(b) <= 760
    assert len(lines[0]) <= 88 and lines[0].endswith("...")
    words = news_body([{"src": "CSDb", "title": "Ein sehr langer Titel " * 8}])
    assert words.endswith(b" sehr...") and len(words) <= 88       # cut at a word
    assert news_body([]) == b""


def test_news_to_the_picos(tmp_path):
    async def t():
        pico = await FakePico(pw="geheim", busy=1).start()
        sink = UdpSink()
        cfg = Config(str(tmp_path))
        cfg.data["picos"] = [{"addr": "127.0.0.1:%d" % pico.port, "pw": "geheim", "np": "http"},
                             {"addr": "127.0.0.1", "np": "udp"}, {"addr": "127.0.0.1:9", "np": "off"}]
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        async def resolve(h):
            return "127.0.0.1"
        async with aiohttp.ClientSession() as s:
            n = Notifier(cfg, s, lambda d, a: udp.sendto(d, a), resolve)
            n.udp_port = sink.port
            n.news(b"")                                          # nothing yet: nothing sent
            await asyncio.sleep(0.2)
            assert not pico.news and not sink.drain(0.1)
            body = news_body([{"src": "CSDb", "title": "Neue Demo"}, {"src": "Lemon64", "title": "Neues Spiel"}])
            n.news(body)
            await asyncio.sleep(0.6)
            assert pico.news == [body]                           # over the web page, after one "busy"
            got = sink.drain(0.2)
            assert got and got[0][0] == b"C64NEWS1\nCSDb: Neue Demo\nLemon64: Neues Spiel"
            n.news(body)                                         # the same again: only every 15 min
            await asyncio.sleep(0.3)
            assert len(pico.news) == 1
            n.news_next = 0
            n.news(body)
            await asyncio.sleep(0.4)
            assert len(pico.news) == 2
            n.news(b"")                                          # switched off: cleared once
            await asyncio.sleep(0.4)
            assert pico.news[-1] == b"" and sink.drain(0.2)[-1][0] == b"C64NEWS1\n"
            n.news(b"")
            await asyncio.sleep(0.2)
            assert len(pico.news) == 3
            n.close()
        sink.close()
        udp.close()
        await pico.stop()
    run(t())


def audio(seq, level=0):
    import struct
    frames = b"".join(struct.pack("<hh", level if i % 2 else -level, 0) for i in range(192))
    return struct.pack("<H", seq) + frames


def test_span():
    assert span(audio(1, 0)) == 0 and span(audio(1, 3000)) == 6000


def test_peaks():
    assert peaks(audio(1, 16384)) == (0.5, 0.0)                    # left only
    assert peaks(b"\0\0") == (0.0, 0.0)


def test_stream_hub_forwards():
    async def t():
        clock = [100.0]
        hub = await StreamHub(0, clock=lambda: clock[0]).start(host="127.0.0.1")
        hub.my_ips = set()
        a, b = UdpSink(), UdpSink()
        hub.set_targets(["127.0.0.1:%d" % a.port, "127.0.0.1:%d" % b.port, "nicht-da.invalid"])
        await hub.resolve_all()
        assert [t.ip for t in hub.targets] == ["127.0.0.1", "127.0.0.1", ""]
        ult = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ult.bind(("127.0.0.1", 0))
        ult.settimeout(0.05)
        pk = audio(7, 5000)
        hub.want_levels = True                                       # the level page is shown
        for i in range(5):
            ult.sendto(pk, ("127.0.0.1", hub.port))
        ult.sendto(b"C64NP1 new=1&title=X", ("127.0.0.1", hub.port))
        await asyncio.sleep(0.2)
        ga, gb = a.drain(0.2), b.drain(0.1)
        assert [d for d, _ in ga[:5]] == [pk] * 5 and len(gb) == 6
        assert ga[5][0] == b"C64NP1 new=1&title=X"
        assert hub.rx == 5 and hub.np_relayed == 1 and hub.active()
        assert hub.silent_for() == 0.0
        assert hub.take_levels() == (5000 / 32768, 0.0) and hub.take_levels() == (0.0, 0.0)
        hub.per_second()
        assert hub.state()["pps"] == 5 and hub.state()["targets"][0]["pps"] == 5
        # a second sender is ignored while the first is live
        other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        other.bind(("127.0.0.1", 0))
        hub.lock_ip = "10.9.9.9"
        hub.lock_t = clock[0]
        other.sendto(pk, ("127.0.0.1", hub.port))
        await asyncio.sleep(0.1)
        assert hub.rejected == 1 and not a.drain(0.1)
        # silence: quiet packets do not count as sound
        hub.lock_ip = ""
        clock[0] += 2
        ult.sendto(audio(8, 10), ("127.0.0.1", hub.port))
        await asyncio.sleep(0.1)
        assert hub.silent_for() == 0.0                                 # the stream just came back: no silence yet
        clock[0] += 0.5
        ult.sendto(audio(9, 10), ("127.0.0.1", hub.port))
        await asyncio.sleep(0.1)
        assert hub.silent_for() == 0.5
        hub.mark_loud()
        clock[0] += 0.9
        ult.sendto(audio(10, 10), ("127.0.0.1", hub.port))
        await asyncio.sleep(0.1)
        assert abs(hub.silent_for() - 0.9) < 1e-9                      # quiet packets without a gap: silence counts
        a.drain(0.1)
        # only from the entered Ultimates' addresses: a burst from another (e.g. its WLAN address) is dropped
        hub.allow = {"10.9.9.8"}
        n0, f0 = hub.rx, len(a.drain(0.05))
        ult.sendto(pk, ("127.0.0.1", hub.port))
        await asyncio.sleep(0.1)
        assert hub.rx == n0 and hub.foreign == 1 and hub.foreign_ip == "127.0.0.1" and not a.drain(0.1)
        assert hub.state()["foreign"] == 1
        hub.allow = {"127.0.0.1"}
        # never back to the sender
        hub.set_targets(["127.0.0.1:%d" % a.port, "127.0.0.1:%d" % ult.getsockname()[1]])
        await hub.resolve_all()
        ult.sendto(pk, ("127.0.0.1", hub.port))
        await asyncio.sleep(0.1)
        assert len(a.drain(0.1)) == 1
        with pytest.raises(socket.timeout):
            ult.recvfrom(2048)
        hub.close()
        for s in (a, b):
            s.close()
        ult.close()
        other.close()
    run(t())


def test_beacon_fits():
    d = {"t": "pi", "n": "c64pi", "ip": "192.168.1.50", "b": "1.0", "fw": ",".join(["c64viz%d" % i for i in range(60)]),
         "title": "x" * 40}
    s = fit_json(d)
    assert len(s.encode()) <= 419 and json.loads(s)["t"] == "pi" and "fw" not in json.loads(s)


def test_devices():
    async def t():
        listen = UdpSink()
        me = {"t": "pi", "n": "c64pi", "ip": "127.0.0.1"}
        dev = await Devices(lambda: me, 0, "127.0.0.1", bcast_port=listen.port).start(host="127.0.0.1")
        dev.my_ips = set()
        await asyncio.sleep(0.3)
        first = listen.drain(0.05)
        assert first[0][0] == b"C64DEV1?" and first[1][0].startswith(b"C64DEV1 {")   # asks, then says who it is
        assert json.loads(first[1][0][8:])["t"] == "pi"
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        beacon = {"t": "viz", "n": "c64viz", "ip": "127.0.0.1", "rx": 250}
        s.sendto(b"C64DEV1 " + json.dumps(beacon).encode() + b"\n", ("127.0.0.1", dev.port))
        s.sendto(b"C64DEV1 kaputt", ("127.0.0.1", dev.port))
        s.sendto(b"C64DEV1?", ("127.0.0.1", dev.port))
        await asyncio.sleep(0.6)
        got = listen.drain(0.05)
        assert any(d.startswith(b"C64DEV1 {") for d, _ in got)         # answered the question
        lst = dev.listing()["list"]
        assert lst[0]["self"] and json.loads(lst[1]["j"])["n"] == "c64viz" and len(lst) == 2
        dev.clock = lambda: time.monotonic() + 40                         # 35 s silent: forgotten
        dev.tick()
        assert len(dev.listing()["list"]) == 1
        dev.close()
        listen.close()
        s.close()
    run(t())


def test_scan_progress():
    from c64jukebox.netscan import scan

    async def t():
        u64 = await FakeUltimate(product="Ultimate 64 Elite II").start()
        states = []
        async with aiohttp.ClientSession() as s:
            hosts = ["127.0.0.1"] + ["192.0.2.%d" % i for i in range(1, 6)]     # TEST-NET: no answer
            found = await scan(s, hosts, ports={"smb": 1, "ftp": 1, "http": u64.port}, timeout=0.3,
                               parallel=4, progress=states.append, arp=lambda: {})
        assert [e["ip"] for e in found] == ["127.0.0.1"]
        pcts = [st["pct"] for st in states]
        assert pcts == sorted(pcts) and pcts[-1] == 100            # only goes up, ends at 100
        assert max(len(st["busy"]) for st in states) == 4           # four at a time, shown while being checked
        busy = next(st["busy"] for st in states if len(st["busy"]) == 4)
        assert busy == sorted(busy, key=lambda ip: [int(x) for x in ip.split(".")])
        assert any("127.0.0.1 (Ultimate 64 Elite II)" in st["found"] for st in states if st["phase"] == "ports")
        assert states[-1]["phase"] == "names" and states[-1]["busy"] == []
        await u64.stop()
    run(t())


def test_ultimate_error_texts():
    from c64jukebox.ultimate import error_text
    assert "aus- und wieder einschalten" in error_text(404, b'{ "errors" : [ "Network Host Resolve Error" ] }')
    assert error_text(500, b'{"errors": ["file not found"]}') == "Ultimate antwortet mit Fehler 500 (file not found)"
    assert error_text(404, b"<html>") == "Ultimate antwortet mit Fehler 404"


def test_a_stuck_target_does_not_hold_up_the_others():
    """a switched-off Pico: its packets wait in the kernel (ARP) and fill the send buffer - with one socket for all,
    the TV got ~18 instead of 250 packets/s (2026-10-23). Each destination has its own socket now."""
    async def t():
        hub = await StreamHub(0).start(host="127.0.0.1")
        hub.my_ips = set()
        good, tv = UdpSink(), UdpSink()
        hub.set_targets(["10.9.9.9:11001", "127.0.0.1:%d" % good.port])
        hub.targets[0].ip = "10.9.9.9"                         # the switched-off one
        hub.targets[1].ip = "127.0.0.1"
        hub.local = [("127.0.0.1", tv.port)]

        class Full:
            def sendto(self, data, addr):
                raise BlockingIOError(11, "Resource temporarily unavailable")

            def close(self):
                pass
        hub.sender("10.9.9.9").sock = Full()
        snd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for i in range(20):
            snd.sendto(audio(i, 3000), ("127.0.0.1", hub.port))
        await asyncio.sleep(0.3)
        assert len(good.drain(0.2)) == 20 and len(tv.drain(0.2)) == 20     # nobody else waits for it
        st = hub.state()["targets"]
        assert st[0]["dropped"] == 20 and st[1]["dropped"] == 0
        snd.close()
        hub.close()
        good.close()
        tv.close()
    run(t())
