"""Wake an Ultimate over WLAN ("Wake-Up on WiFi" of the Ultimate 64-II): a Wake-on-LAN magic packet (6 x 0xFF, then the
MAC 16 times) to the device's WLAN MAC, sent like the PC jukebox does it - to the broadcast address of our own network
and to 255.255.255.255, on the ports 9 and 7. Switched off with PUT /v1/machine:poweroff it was back after 12 s
(Elite II, 2026-10-23). There is no answer: whether it woke shows only when it answers on the network again."""
import ipaddress
import re
import socket
import subprocess

from .stream import local_ip


def normalize_mac(text):
    """"12-34-56-78-9a-bc", "123456789ABC" ... -> "12:34:56:78:9A:BC", or None"""
    h = re.sub(r"[^0-9A-Fa-f]", "", str(text or ""))
    if len(h) != 12 or re.sub(r"[0-9A-Fa-f:\-. ]", "", str(text)):
        return None
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper()


def magic_packet(mac):
    m = normalize_mac(mac)
    if not m:
        raise ValueError("Keine gültige MAC-Adresse: %s" % mac)
    return b"\xff" * 6 + bytes.fromhex(m.replace(":", "")) * 16


def prefix_of(ip, ip_output=None):
    """the prefix length of our own address, from "ip -o -4 addr" (Linux); /24 (like the PC jukebox) when unknown"""
    if ip_output is None:
        try:
            ip_output = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True,
                                       timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            ip_output = ""
    for m in re.finditer(r"\binet (\d+\.\d+\.\d+\.\d+)/(\d+)", ip_output or ""):
        if m.group(1) == ip and 8 <= int(m.group(2)) <= 30:
            return int(m.group(2))
    return 24


def targets(towards=None):
    """the broadcast addresses: our own network's and the limited one. Our network is the one on the way to the
    Ultimate (towards = its last address), else the one of the default route - never a fixed address"""
    out = []
    me = local_ip(towards) if towards else local_ip()
    if not me.startswith("127."):
        out.append(str(ipaddress.ip_network("%s/%d" % (me, prefix_of(me)), strict=False).broadcast_address))
    out.append("255.255.255.255")
    return out


def send(mac, towards=None, opener=None):
    """send the magic packet everywhere it may help -> ["addr:port", ...] (OSError only when none went out)"""
    pkt = magic_packet(mac)
    sent, err = [], None
    for addr in targets(towards):
        for port in (9, 7):
            s = (opener or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)))()
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(pkt, (addr, port))
                sent.append("%s:%d" % (addr, port))
            except OSError as e:
                err = e
            finally:
                s.close()
    if not sent:
        raise err or OSError("Weckruf konnte nicht gesendet werden")
    return sent
