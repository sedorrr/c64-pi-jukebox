"""PSID/RSID header: title, author, released, sub-songs, SID chips and their addresses."""
import hashlib
import re
import struct

HEADER_LEN = 0x7C
MODELS = ("", "6581", "8580", "6581/8580")


def _text(raw):
    return raw.split(b"\x00")[0].decode("latin-1", errors="replace").strip()


def _addr(byte):
    """second/third SID address byte -> "D420" (PSID spec: $D000 + value * 16, valid are even values in $42-$7F
    and $E0-$FE)"""
    if byte & 1 or not (0x42 <= byte <= 0x7F or 0xE0 <= byte <= 0xFE):
        return None
    return "%04X" % (0xD000 + (byte << 4))


def parse_header(data):
    """dict with the header fields, or None when the data is no SID file"""
    if len(data) < 0x76 or data[0:4] not in (b"PSID", b"RSID"):
        return None
    version = struct.unpack(">H", data[4:6])[0]
    songs = struct.unpack(">H", data[0x0E:0x10])[0] or 1
    start = struct.unpack(">H", data[0x10:0x12])[0] or 1
    if start > songs:
        start = 1
    released = _text(data[0x56:0x76])
    m = re.match(r"\s*(\d{4})", released)
    sids = ["D400"]
    flags = 0
    if version >= 2 and len(data) >= 0x78:
        flags = struct.unpack(">H", data[0x76:0x78])[0]
    if version >= 3 and len(data) >= HEADER_LEN:
        a2 = _addr(data[0x7A])
        if a2:
            sids.append(a2)
            if version >= 4:
                a3 = _addr(data[0x7B])
                if a3:
                    sids.append(a3)
    models = [MODELS[(flags >> (4 + 2 * i)) & 3] for i in range(len(sids))]
    return {
        "type": data[0:4].decode(),
        "title": _text(data[0x16:0x36]),
        "author": _text(data[0x36:0x56]),
        "released": released,
        "year": m.group(1) if m else "",
        "songs": songs,
        "start": start,
        "chips": len(sids),
        "sids": sids,
        "models": models,
    }


def md5(data):
    """the HVSC song length database uses the MD5 over the whole file"""
    return hashlib.md5(data).hexdigest()


def is_sid_name(name):
    return name.lower().endswith(".sid")


def is_songlengths_name(name):
    n = name.lower()
    return n.endswith(".md5") or (n.endswith(".txt") and "songlength" in n)
