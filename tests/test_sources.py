import asyncio
import os

import pytest

from c64jukebox.sources import FtpSource, LocalSource, SmbSource, SourceError, norm, parse_list_line, smb_shares
from fakes import FakeFTP, FakeSMBServer, install_fake_smb, make_sid

SID = make_sid("Hello")


def run(c):
    return asyncio.run(c)


def test_norm():
    assert norm("") == "/" and norm("a//b/./c/") == "/a/b/c" and norm("\\x\\y") == "/x/y"
    with pytest.raises(SourceError):
        norm("/a/../../etc")


def test_list_lines():
    assert parse_list_line("drw-rw-rw-   1 user ftp 0 Oct 10 12:00 HVSC 78") == {"n": "HVSC 78", "d": True, "s": 0}
    assert parse_list_line("-rw-r--r-- 1 u g 4711 Jan  1  2020 a b.sid")["s"] == 4711
    assert parse_list_line("10-10-26  08:00PM       <DIR>          Musik")["d"]
    assert parse_list_line("10-10-26  08:00PM             1234 x.sid") == {"n": "x.sid", "d": False, "s": 1234}
    assert parse_list_line("total 12") is None


def test_local(tmp_path):
    (tmp_path / "Hubbard").mkdir()
    (tmp_path / "Hubbard" / "Commando.sid").write_bytes(SID)
    (tmp_path / "._Commando.sid").write_bytes(b"x")
    (tmp_path / "b.sid").write_bytes(SID)
    src = LocalSource("pi", "Pi", str(tmp_path))
    e = run(src.list("/"))
    assert [x["n"] for x in e] == ["Hubbard", "b.sid"]           # folders first, dot files hidden
    assert run(src.read("/Hubbard/Commando.sid")) == SID
    with pytest.raises(SourceError):
        run(src.list("/nope"))
    with pytest.raises(SourceError):
        run(src.read("/../etc/passwd"))
    missing = LocalSource("x", "x", str(tmp_path / "usb"))
    with pytest.raises(SourceError, match="USB-Stick"):
        run(missing.list("/"))


def test_ftp_like_ultimate():
    tree = {"USB2": {"SID-Tunes": {"HVSC 78": {"Ärger.sid": SID, "Sub": {}}, "x.txt": b"t"}}}
    srv = FakeFTP(tree)
    try:
        src = FtpSource("u64", "U", "127.0.0.1", srv.port, "anonymous", "netpw", "/")
        e = run(src.list("/USB2/SID-Tunes/HVSC 78"))
        assert e == [{"n": "Sub", "d": True, "s": 0}, {"n": "Ärger.sid", "d": False, "s": len(SID)}]
        assert run(src.read("/USB2/SID-Tunes/HVSC 78/Ärger.sid")) == SID
        assert any(l == "PASS netpw" for l in srv.log)
        # the connection is kept: a second listing needs no new login
        run(src.list("/USB2"))
        assert sum(1 for l in srv.log if l.startswith("USER")) == 1
        with pytest.raises(SourceError, match="nicht gefunden"):
            run(src.list("/nope"))
        with pytest.raises(SourceError, match="nicht gefunden"):
            run(src.read("/USB2/none.sid"))
        with pytest.raises(SourceError, match="zu groß"):
            run(src.read("/USB2/SID-Tunes/HVSC 78/Ärger.sid", limit=10))
        assert run(src.read("/USB2/SID-Tunes/x.txt")) == b"t"       # works again after the aborted transfer
        src.close()
        rooted = FtpSource("f", "F", "127.0.0.1", srv.port, "", "", "/USB2/SID-Tunes")
        assert [x["n"] for x in run(rooted.list("/"))] == ["HVSC 78", "x.txt"]
    finally:
        srv.stop()


def test_ftp_utf8_and_login():
    srv = FakeFTP({"Musik": {"Café.sid": SID}}, login=("nutzer", "pw"), utf8=True)
    try:
        ok = FtpSource("f", "F", "127.0.0.1", srv.port, "nutzer", "pw", "/")
        assert run(ok.list("/Musik"))[0]["n"] == "Café.sid"
        assert run(ok.read("/Musik/Café.sid")) == SID
        bad = FtpSource("f", "F", "127.0.0.1", srv.port, "nutzer", "falsch", "/")
        with pytest.raises(SourceError, match="abgelehnt"):
            run(bad.list("/"))
    finally:
        srv.stop()


def test_ftp_unreachable():
    src = FtpSource("f", "F", "127.0.0.1", 1, "", "", "/")
    with pytest.raises(SourceError):
        run(src.list("/"))


def test_smb(monkeypatch):
    servers = install_fake_smb(monkeypatch)
    servers["nas"] = FakeSMBServer({"Musik": {"C64": {"Tunes": {"a.sid": SID, ".DS_Store": b"x"}}}, "Fotos": {}},
                                   user="nutzer", pw="geheim")
    assert [s["name"] for s in smb_shares("nas", "nutzer", "geheim")] == ["Fotos", "Musik"]
    with pytest.raises(SourceError, match="abgelehnt"):
        smb_shares("nas", "nutzer", "falsch")
    with pytest.raises(SourceError, match="nicht erreichbar"):
        smb_shares("other", "", "")
    servers["nas"].connects = 0
    src = SmbSource("nas", "NAS", "nas", "Musik", "/C64", "nutzer", "geheim")
    assert run(src.list("/")) == [{"n": "Tunes", "d": True, "s": 0}]
    assert run(src.list("/Tunes")) == [{"n": "a.sid", "d": False, "s": len(SID)}]
    assert run(src.read("/Tunes/a.sid")) == SID
    assert servers["nas"].connects == 1                              # one connection for all calls
    with pytest.raises(SourceError, match="nicht gefunden"):
        run(src.list("/nope"))
    with pytest.raises(SourceError, match="zu groß"):
        run(src.read("/Tunes/a.sid", limit=5))
    src.close()


def test_smb_guest(monkeypatch):
    servers = install_fake_smb(monkeypatch)
    servers["pc"] = FakeSMBServer({"Public": {"x.sid": SID}})
    src = SmbSource("pc", "PC", "pc", "Public", "/", "", "")
    assert run(src.read("/x.sid")) == SID


def test_smb1_fallback_and_no_fallback_after_refused_login(monkeypatch):
    servers = install_fake_smb(monkeypatch)
    servers["oldnas"] = FakeSMBServer({"Musik": {"a.sid": SID}}, user="u", pw="p", smb2=False)
    src = SmbSource("o", "Old", "oldnas", "Musik", "/", "u", "p")
    assert run(src.read("/a.sid")) == SID                            # SMB 1 through pysmb
    assert [s["name"] for s in smb_shares("oldnas", "u", "p")] == ["Musik"]
    servers["nas3"] = FakeSMBServer({"Musik": {}}, user="u", pw="p")
    import smb.SMBConnection
    called = []
    monkeypatch.setattr(smb.SMBConnection, "SMBConnection", lambda *a, **k: called.append(1))
    with pytest.raises(SourceError, match="abgelehnt"):
        smb_shares("nas3", "u", "falsch")
    assert not called                                                # a refused login is final, no SMB 1 attempt


def _ndr_wstr(s):
    import struct
    raw = (s + "\0").encode("utf-16-le")
    n = len(raw) // 2
    out = struct.pack("<III", n, 0, n) + raw
    return out + b"\0" * (-len(out) % 4)


def _enum_answer(shares):
    import struct
    stub = struct.pack("<IIIII", 1, 1, 0x20000, len(shares), 0x20004) + struct.pack("<I", len(shares))
    for i, (n, t, r) in enumerate(shares):
        stub += struct.pack("<III", 0x20008 + 8 * i, t, (0x2000C + 8 * i) if r is not None else 0)
    for n, t, r in shares:
        stub += _ndr_wstr(n) + (_ndr_wstr(r) if r is not None else b"")
    return stub + struct.pack("<III", len(shares), 0, 0)


def _response_pdus(stub, frag_stub=100):
    import struct
    out = b""
    parts = [stub[i:i + frag_stub] for i in range(0, len(stub), frag_stub)]
    for k, part in enumerate(parts):
        flags = (1 if k == 0 else 0) | (2 if k == len(parts) - 1 else 0)
        body = struct.pack("<IHBB", len(stub), 0, 0, 0) + part
        out += struct.pack("<BBBBBBBBHHI", 5, 0, 2, flags, 0x10, 0, 0, 0, 16 + len(body), 0, 2) + body
    return out


def test_share_enum_rpc():
    import struct
    import uuid
    from c64jukebox import smb2
    b = smb2.bind_pdu()
    assert b[:4] == bytes([5, 0, 11, 3]) and struct.unpack_from("<H", b, 8)[0] == len(b)
    assert uuid.UUID("4b324fc8-1670-01d3-1278-5a47bf6ee188").bytes_le in b
    r = smb2.share_enum_pdu("nas")
    assert r[2] == 0 and struct.unpack_from("<H", r, 22)[0] == 15            # request, opnum 15 = NetrShareEnum
    assert "\\\\nas\0".encode("utf-16-le") in r
    shares = [("Musik", 0, "C64-Sammlung"), ("IPC$", 0x80000003, "IPC Service"), ("print$", 0x80000000, None),
              ("Öffentlich", 0, "")]
    stub = _enum_answer(shares)
    got, last = smb2.split_fragments(_response_pdus(stub))                  # spread over several fragments
    assert last and got == stub
    assert smb2.parse_share_enum(got) == [("Musik", 0, "C64-Sammlung"), ("IPC$", 0x80000003, "IPC Service"),
                                          ("print$", 0x80000000, ""), ("Öffentlich", 0, "")]
    partial, last = smb2.split_fragments(_response_pdus(stub)[:150])        # second fragment not complete yet
    assert not last
    fault = struct.pack("<BBBBBBBBHHI", 5, 0, 3, 3, 0x10, 0, 0, 0, 28, 0, 2) + struct.pack("<IHBBI", 0, 0, 0, 0, 5)
    with pytest.raises(smb2.SmbFailed, match="0x00000005"):
        smb2.split_fragments(fault)
