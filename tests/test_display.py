"""OLED display: driver bytes for SSD1306 / SH1106 on a fake I2C bus, pages, sleep; previews as PNG."""
import os

from c64jukebox.display import INIT, Display, Oled, Screen

HERE = os.path.dirname(os.path.abspath(__file__))


class FakeBus:
    def __init__(self, present=(0x3C,)):
        self.present, self.writes = present, []

    def write(self, addr, data):
        if addr not in self.present:
            raise OSError(121, "Remote I/O error")
        self.writes.append((addr, bytes(data)))

    def close(self):
        pass


PLAY = {"name": "c64pi", "player": {"state": "play", "el": 83, "total": 96, "now": {
    "title": "Crazy Comets", "author": "Rob Hubbard", "released": "1985 Martech", "chips": 2, "secs": 276, "song": 1, "songs": 17, "md5": "x"}},
    "stream": {"on": True, "from": "192.168.1.168", "pps": 251, "targets": [{}, {}, {}]},
    "net": {"mode": "lan", "eth_ip": "192.168.1.78"}}
AP = {"name": "c64pi", "player": {"state": "stop", "total": 0}, "stream": {"on": False},
      "net": {"mode": "ap", "ap": {"ssid": "C64-Jukebox", "pw": "commodore64", "ip": "192.168.5.1"}}}


def preview(img, name):
    img.convert("L").resize((512, 256), 0).save(os.path.join(HERE, "web", name))


def test_ssd1306_bytes():
    bus = FakeBus()
    o = Oled(bus, "ssd1306")
    assert o.addr == 0x3C
    init = b"".join(w[1][1:] for w in bus.writes if w[1][0] == 0)
    assert INIT["ssd1306"][0] in init and init.endswith(bytes([0xAF]))
    bus.writes.clear()
    img = Screen().render(PLAY, "play")
    o.show(img)
    data = b"".join(w[1][1:] for w in bus.writes if w[1][0] == 0x40)
    assert len(data) == 1024 and any(data)
    assert all(len(w[1]) <= 256 for w in bus.writes)


def test_sh1106_pages_and_second_address():
    bus = FakeBus(present=(0x3D,))
    o = Oled(bus, "sh1106")
    assert o.addr == 0x3D
    bus.writes.clear()
    o.show(Screen().render(AP, "net"))
    pages = [w[1] for w in bus.writes if w[1][0] == 0 and 0xB0 <= w[1][1] <= 0xB7]
    assert [p[1] for p in pages] == list(range(0xB0, 0xB8)) and all(p[2] == 0x02 for p in pages)   # column 2
    assert sum(len(w[1]) - 1 for w in bus.writes if w[1][0] == 0x40) == 1024


def test_pages_previews_and_sleep():
    s = Screen()
    preview(s.render(PLAY, "play"), "oled_play.png")
    preview(s.render(PLAY, "net"), "oled_net.png")
    preview(s.render(AP, "net"), "oled_ap.png")
    t = [0.0]
    cfg = {"type": "auto", "off_min": 10}
    buses = []
    d = Display(lambda: cfg, bus_factory=lambda: buses.append(FakeBus()) or buses[-1], clock=lambda: t[0])
    d.tick(PLAY)
    assert d.dev and d.dev.kind == "ssd1306" and "0x3C" in d.msg
    assert d.page_for(PLAY) == "play"
    t[0] = 9
    assert d.page_for(PLAY) == "net"                                  # every 8 s in turn
    assert d.page_for(AP) == "net"                                    # access point: always the network
    n = len(buses[0].writes)
    d.tick(PLAY)
    assert len(buses[0].writes) > n                                   # picture changed (other page)
    n = len(buses[0].writes)
    d.tick(PLAY)
    assert len(buses[0].writes) == n                                  # nothing changed: nothing sent
    stopped = dict(PLAY, player={"state": "stop", "total": 3})
    d.tick(stopped)
    t[0] = 9 + 601
    d.tick(stopped)
    assert d.dev.on is False                                         # 10 min without a tune: dark
    t[0] += 1
    d.tick(AP)
    assert d.dev.on is True                                          # the access point wakes it
    cfg["type"] = "off"
    d.tick(PLAY)
    assert d.dev is None and d.msg == "aus"


def test_no_display():
    cfg = {"type": "auto"}
    d = Display(lambda: cfg, bus_factory=lambda: FakeBus(present=()), clock=lambda: 0)
    d.tick(PLAY)
    assert d.dev is None and d.msg.startswith("nicht gefunden")
