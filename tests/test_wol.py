"""Waking an Ultimate over its WLAN: the MAC in any common spelling, the magic packet, where it is sent; the jukebox
learns the WLAN MAC from /v1/info, switches off with machine:poweroff, keeps the MAC when the page saves without it."""
import asyncio

from c64jukebox import wol
from c64jukebox.core import Jukebox
from fakes import FakeUltimate


def test_mac_and_packet():
    assert wol.normalize_mac("12-34-56-78-9a-bc") == wol.normalize_mac("123456789ABC") == "12:34:56:78:9A:BC"
    assert wol.normalize_mac("12:34:56:78:9A") is None and wol.normalize_mac("zz:34:56:78:9A:BC") is None
    p = wol.magic_packet("12:34:56:78:9A:BC")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("123456789ABC") and p[-6:] == p[6:12]


def test_send_everywhere(monkeypatch):
    monkeypatch.setattr(wol, "local_ip", lambda towards="": "192.168.1.78")
    monkeypatch.setattr(wol, "prefix_of", lambda ip: 24)
    out = []

    class S:
        def setsockopt(self, *a):
            pass

        def sendto(self, d, a):
            out.append((len(d), a))

        def close(self):
            pass
    assert wol.send("12:34:56:78:9A:BC", opener=S) == ["192.168.1.255:9", "192.168.1.255:7", "255.255.255.255:9",
                                                         "255.255.255.255:7"]
    assert all(n == 102 for n, _ in out)


def test_own_network_not_a_fixed_one(monkeypatch):
    out = """1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
2: eth0    inet 10.0.7.20/16 brd 10.0.255.255 scope global dynamic eth0\\       valid_lft 85000sec
3: wlan0    inet 192.168.178.44/24 brd 192.168.178.255 scope global wlan0\\       valid_lft forever"""
    assert wol.prefix_of("10.0.7.20", out) == 16 and wol.prefix_of("192.168.178.44", out) == 24
    assert wol.prefix_of("10.0.7.2", out) == 24 and wol.prefix_of("10.0.7.20", "") == 24     # unknown -> /24
    asked = []
    monkeypatch.setattr(wol, "local_ip", lambda towards="192.0.2.1": asked.append(towards) or "10.0.7.20")
    monkeypatch.setattr(wol, "prefix_of", lambda ip: 16)
    assert wol.targets() == ["10.0.255.255", "255.255.255.255"] and asked == ["192.0.2.1"]   # default route
    assert wol.targets("10.0.3.9") == ["10.0.255.255", "255.255.255.255"] and asked[-1] == "10.0.3.9"
    monkeypatch.setattr(wol, "local_ip", lambda towards="": "127.0.0.1")
    assert wol.targets() == ["255.255.255.255"]                                  # no network: only the limited one


def test_learn_switch_off_and_keep(tmp_path):
    async def t():
        u = await FakeUltimate(wifi_mac="12:34:56:78:9a:bc").start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "Elite II", "addr": u.addr, "pw": ""}]
        await jb.start()
        try:
            msg = await jb.u64_power(0, False)
            assert "ausgeschaltet" in msg and u.find("PUT", "/v1/machine:poweroff")
            assert jb.config["ultimates"][0]["wmac"] == "12:34:56:78:9A:BC"     # learnt on the way out
        finally:
            await jb.close()
            await u.stop()
    asyncio.run(t())
