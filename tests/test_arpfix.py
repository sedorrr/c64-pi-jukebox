"""arpfix: the ARP reply that tells a hanging Ultimate where the Pi is - built right, sent only to the Ultimate's
MAC, and asked for by the jukebox when the Ultimate answers "Network Host Resolve Error" (at most every 30 s)."""
import asyncio
import socket
import struct

from c64jukebox import arpfix
from c64jukebox.core import Jukebox
from fakes import FakeUltimate

ARP = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.168    0x1         0x2         02:15:41:11:22:33     *        eth0
192.168.1.202    0x1         0x2         12:34:56:78:9a:bc     *        eth0
192.168.1.99     0x1         0x0         00:00:00:00:00:00     *        eth0
"""


def test_frame():
    f = arpfix.arp_reply(arpfix.mac_bytes("b8:27:eb:00:00:01"), "192.168.1.78",
                         arpfix.mac_bytes("02:15:41:11:22:33"), "192.168.1.168")
    assert len(f) == 42
    assert f[0:6] == bytes.fromhex("021541112233")   # to the Ultimate's cable only
    assert f[6:12] == bytes.fromhex("b827eb000001") and f[12:14] == b"\x08\x06"
    htype, ptype, hlen, plen, op = struct.unpack("!HHBBH", f[14:22])
    assert (htype, ptype, hlen, plen, op) == (1, 0x0800, 6, 4, 2)          # a reply
    assert f[22:28] == bytes.fromhex("b827eb000001") and socket.inet_ntoa(f[28:32]) == "192.168.1.78"
    assert f[32:38] == bytes.fromhex("021541112233") and socket.inet_ntoa(f[38:42]) == "192.168.1.168"


def test_neighbour_and_announce(tmp_path, monkeypatch):
    p = tmp_path / "arp"
    p.write_text(ARP)
    assert arpfix.neighbour("192.168.1.168", str(p)) == ("02:15:41:11:22:33", "eth0")
    assert arpfix.neighbour("192.168.1.99", str(p)) == (None, None)        # incomplete: no MAC
    assert "unbekannt" in arpfix.announce("192.168.1.1", arp_path=str(p))
    sent = []

    class Sock:
        def bind(self, a):
            sent.append(("bind", a))

        def send(self, d):
            sent.append(d)

        def close(self):
            pass
    monkeypatch.setattr(arpfix, "my_address", lambda iface, peer: ("b8:27:eb:00:00:01", "192.168.1.78"))
    assert arpfix.announce("192.168.1.168", opener=Sock, arp_path=str(p)) == ""
    assert sent[0] == ("bind", ("eth0", 0)) and len(sent) == 3 and sent[1] == sent[2] and sent[1][:6] == bytes.fromhex("021541112233")

    def refuse():
        raise PermissionError(1, "Operation not permitted")
    assert "not permitted" in arpfix.announce("192.168.1.168", opener=refuse, arp_path=str(p))


def test_jukebox_announces_when_the_ultimate_hangs(tmp_path, monkeypatch):
    async def t():
        u = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "Elite II", "addr": u.addr, "pw": ""}]
        jb.config.data["stream"]["on"] = True
        calls = []
        monkeypatch.setattr(arpfix, "announce", lambda ip: calls.append(ip) or "")
        await jb.start()
        try:
            u.resolve_error = True
            jb._stream_req_at = -1e9
            await jb._stream_keep()
            assert calls == ["127.0.0.1"] and "neu gemeldet" in jb.stream_msg and jb.arp_log[-1][2] == "ok"
            jb._stream_req_at = -1e9
            await jb._stream_keep()
            assert calls == ["127.0.0.1"]                                  # not again within 30 s
            u.resolve_error = False
            jb._stream_req_at = jb._arp_at = -1e9
            await jb._stream_keep()
            assert calls == ["127.0.0.1"] and jb.stream_msg.startswith("Stream angefordert")
        finally:
            await jb.close()
            await u.stop()
    asyncio.run(t())
