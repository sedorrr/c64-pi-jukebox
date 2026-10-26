import hashlib

from c64jukebox import sidfile
from c64jukebox.songlengths import SongLengths, parse, parse_times
from fakes import make_sid


def test_header_basic():
    h = sidfile.parse_header(make_sid("Commando", "Rob Hubbard", "1985 Elite", songs=3, start=2))
    assert h["title"] == "Commando" and h["author"] == "Rob Hubbard"
    assert h["year"] == "1985" and h["songs"] == 3 and h["start"] == 2
    assert h["chips"] == 1 and h["sids"] == ["D400"] and h["models"] == ["6581"]


def test_header_two_and_three_sids():
    h = sidfile.parse_header(make_sid(version=3, second=0x42, flags=0x10 | 0x80))
    assert h["sids"] == ["D400", "D420"] and h["chips"] == 2 and h["models"] == ["6581", "8580"]
    h = sidfile.parse_header(make_sid(version=4, second=0x50, third=0xE0))
    assert h["sids"] == ["D400", "D500", "DE00"]
    # invalid addresses ($D800-$DFFF range, odd values) count as no SID
    h = sidfile.parse_header(make_sid(version=4, second=0x80, third=0x43))
    assert h["sids"] == ["D400"]
    # version 2 has no second SID field
    assert sidfile.parse_header(make_sid(version=2, second=0x42))["chips"] == 1


def test_header_rejects_other_files():
    assert sidfile.parse_header(b"PK\x03\x04" + b"\0" * 200) is None
    assert sidfile.parse_header(b"PSID") is None
    assert sidfile.parse_header(make_sid(rsid=True))["type"] == "RSID"
    # a start song beyond the songs falls back to 1, zero songs count as 1
    assert sidfile.parse_header(make_sid(songs=2, start=7))["start"] == 1
    assert sidfile.parse_header(make_sid(songs=0, start=0))["songs"] == 1


def test_latin1_title():
    assert sidfile.parse_header(make_sid("Rêve"))["title"] == "Rêve"


def test_md5_whole_file():
    d = make_sid()
    assert sidfile.md5(d) == hashlib.md5(d).hexdigest()


def test_times():
    assert parse_times("3:57 1:02.600(G) 0:45.499 12") == [237, 63, 45, 12]
    assert parse_times("1:02.5") == [63]


def test_parse_formats_and_precedence():
    a, b, c = "0123456789abcdef0123456789abcdef", "f" * 32, "a" * 32
    hvsc = "[Database]\n; /MUSICIANS/H/Hubbard_Rob/Commando.sid\n%s=3:57 1:02\n; old format\n%s\n=2:00\n" % (a.upper(), b)
    db = parse(hvsc)
    assert db[bytes.fromhex(a)] == (237, 62) and db[bytes.fromhex(b)] == (120,)
    sl = SongLengths()
    assert sl.load("hvsc", hvsc) == 2
    assert sl.lookup(a, 2) == 62 and sl.lookup(a, 3) is None and sl.lookup(c) is None
    sl.load("custom", "%s=200\n" % a)
    assert sl.lookup(a, 1) == 200 and sl.lookup(a, 2) == 200      # one value per file in the PC player's file
    assert sl.lookup("nonsense") is None
    assert sl.counts() == {"hvsc": 2, "custom": 1}
