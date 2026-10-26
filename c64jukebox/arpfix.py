"""Tell an Ultimate again where the Pi is: an ARP reply sent straight to the Ultimate's Ethernet MAC.

The Ultimate 64 Elite II (firmware 3.15a) sometimes answers every stream request to the Pi with "Network Host Resolve
Error" and sends what little it sends over its WLAN; a restart of the Pi cured it at once, twice (2026-10-23). The
restart announces the Pi's address afresh. This does the same, but only towards the Ultimate's cable: a unicast ARP
reply (a broadcast would also reach the Ultimate's WLAN side through the router). Needs CAP_NET_RAW (service unit)."""
import socket
import struct

ETH_P_ARP = 0x0806


def mac_bytes(text):
    return bytes(int(x, 16) for x in text.split(":"))


def arp_reply(my_mac, my_ip, peer_mac, peer_ip):
    """Ethernet frame: "my_ip is at my_mac", addressed to peer_mac / peer_ip"""
    eth = peer_mac + my_mac + struct.pack("!H", ETH_P_ARP)
    arp = struct.pack("!HHBBH", 1, 0x0800, 6, 4, 2) + my_mac + socket.inet_aton(my_ip) + peer_mac + socket.inet_aton(peer_ip)
    return eth + arp


def neighbour(ip, path="/proc/net/arp"):
    """-> (MAC of ip, interface) from the kernel's ARP table, or (None, None)"""
    try:
        with open(path) as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if len(p) >= 6 and p[0] == ip and p[3] != "00:00:00:00:00:00":
                    return p[3], p[5]
    except OSError:
        pass
    return None, None


def my_address(iface, peer_ip):
    """-> (own MAC, own IPv4 towards peer_ip) on iface"""
    with open("/sys/class/net/%s/address" % iface) as f:
        mac = f.read().strip()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((peer_ip, 9))
        return mac, s.getsockname()[0]
    finally:
        s.close()


def announce(peer_ip, opener=None, arp_path="/proc/net/arp"):
    """send the ARP reply to peer_ip's MAC (twice) -> "" or why not"""
    peer_mac, iface = neighbour(peer_ip, arp_path)
    if not peer_mac:
        return "Hardware-Adresse von %s unbekannt" % peer_ip
    try:
        my_mac, my_ip = my_address(iface, peer_ip)
        frame = arp_reply(mac_bytes(my_mac), my_ip, mac_bytes(peer_mac), peer_ip)
        s = (opener or (lambda: socket.socket(socket.AF_PACKET, socket.SOCK_RAW)))()
        try:
            s.bind((iface, 0))
            for _ in range(2):
                s.send(frame)
        finally:
            s.close()
    except (OSError, AttributeError) as e:                 # AttributeError: no AF_PACKET (not Linux)
        return "ARP: %s" % (getattr(e, "strerror", None) or e)
    return ""


if __name__ == "__main__":                                # by hand: python -m c64jukebox.arpfix 192.168.1.168
    import sys
    print(announce(sys.argv[1]) or "gesendet")
