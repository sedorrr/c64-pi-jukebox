"""Stream distributor: the Ultimate streams its audio by unicast to this Pi (UDP 11001), the Pi passes every packet
on unchanged to each Pico in the list - over Ethernet, so the Ultimate's one destination feeds any number of
visualizers and receivers without multicast.

Like the Picos: one sender at a time (another is ignored until the first is quiet for 0.5 s), never back to the
sender or to the Pi itself, "C64NP1 ..." titles pass through as well. While switched on, the Pi asks the selected
Ultimate for the stream again whenever nothing has come for 5 s. The sound level of each packet gives the player
its "next tune after N s of silence"."""
import array
import asyncio
import socket
import sys
import time

from .ultimate import STREAM_PORT

LOCK_S = 0.5
AUDIO_LEN = 770               # 2 bytes sequence + 192 stereo frames int16
SILENT_SPAN = 400             # peak-to-peak below this (of 65536) counts as silence


def local_ip(towards="192.0.2.1"):
    """the address other devices reach us at (no packet is sent)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((towards, 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def peaks(data):
    """highest level of the left and the right channel in one stream packet, 0..1"""
    n = (len(data) - 2) // 4
    if n <= 0:
        return 0.0, 0.0
    a = array.array("h")
    a.frombytes(data[2:2 + 4 * n])
    if sys.byteorder == "big":
        a.byteswap()
    left, right = a[0::2], a[1::2]
    return max(max(left), -min(left)) / 32768, max(max(right), -min(right)) / 32768


def span(data):
    """peak-to-peak of the samples in one stream packet"""
    n = (len(data) - 2) // 2
    if n <= 0:
        return 0
    a = array.array("h")
    a.frombytes(data[2:2 + 2 * n])
    if sys.byteorder == "big":
        a.byteswap()
    return max(a) - min(a)


class Sender:
    """a UDP socket of its own for one destination. Packets for a device that is switched off wait in the kernel for its
    address (ARP) and count against the sending socket's buffer: with one socket for all, a single switched-off Pico
    filled it (Send-Q 212 KB) and the TV got ~18 instead of 250 packets/s (2026-10-23). Now a full buffer only drops
    that destination's packets."""
    SNDBUF = 1 << 16

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.SNDBUF)
        except OSError:
            pass
        self.dropped = 0

    def send(self, data, addr):
        try:
            self.sock.sendto(data, addr)
            return True
        except OSError:                         # BlockingIOError (buffer full), unreachable ...
            self.dropped += 1
            return False

    def close(self):
        self.sock.close()


class Target:
    def __init__(self, addr):
        self.addr = addr
        host, _, port = addr.partition(":")        # a port only in tests: the Picos listen on 11001
        self.host, self.port = host, int(port) if port.isdigit() else STREAM_PORT
        self.ip = ""
        self.pkts = 0
        self.pps = 0
        self._prev = 0


class StreamHub(asyncio.DatagramProtocol):
    def __init__(self, port=STREAM_PORT, clock=time.monotonic):
        self.port = port
        self.clock = clock
        self.transport = None
        self.targets = []
        self.my_ips = {"127.0.0.1"}
        self.lock_ip, self.lock_t = "", 0.0
        self.rx = 0
        self.rx_pps = 0
        self._rx_prev = 0
        self.rejected = 0
        # stream data only from the entered Ultimates' own (Ethernet) addresses: a hanging Elite II sent bursts over
        # its WLAN address (2026-10-23). Empty = no Ultimate entered: anything goes
        self.allow = set()
        self.foreign = 0               # packets dropped for that
        self.foreign_ip = ""
        self.last_rx = 0.0
        self.last_loud = 0.0
        self.since = 0.0               # packets come without a gap (> 1 s) since then
        self.np_relayed = 0
        self.local = []                # (ip, port) on this Pi that get every audio packet: the HDMI service
        self.want_levels = False       # the level page of the touch display is shown: measure the packets
        self.lvl = [0.0, 0.0]          # highest left / right since take_levels()
        self.out = {}                  # destination IP -> Sender

    async def start(self, host="0.0.0.0"):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=(host, self.port))
        sock = self.transport.get_extra_info("socket")
        self.port = sock.getsockname()[1]
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        except OSError:
            pass
        return self

    def close(self):
        if self.transport:
            self.transport.close()
            self.transport = None
        for s in self.out.values():
            s.close()
        self.out.clear()

    def sender(self, ip):
        s = self.out.get(ip)
        if s is None:
            if len(self.out) >= 32:                      # devices come and go: forget the oldest
                old = next(iter(self.out))
                self.out.pop(old).close()
            s = self.out[ip] = Sender()
        return s

    def dropped(self, ip):
        s = self.out.get(ip)
        return s.dropped if s else 0

    # ---- targets
    def set_targets(self, addrs):
        old = {t.addr: t for t in self.targets}
        self.targets = [old.get(a) or Target(a) for a in addrs if a]

    async def resolve_all(self):
        loop = asyncio.get_running_loop()
        for t in list(self.targets):
            try:
                info = await asyncio.wait_for(loop.getaddrinfo(t.host, None, family=socket.AF_INET,
                                                               type=socket.SOCK_DGRAM), 5)
                t.ip = info[0][4][0]
            except (OSError, asyncio.TimeoutError, IndexError):
                t.ip = ""

    def send(self, data, addr):
        """titles and news for the Picos - each destination on its own socket, like the stream"""
        if self.transport:
            self.sender(addr[0]).send(data, addr)

    # ---- packets
    def datagram_received(self, data, addr):
        ip = addr[0]
        now = self.clock()
        if ip in self.my_ips:
            return
        is_np = data.startswith(b"C64NP1 ") and len(data) != AUDIO_LEN
        if not is_np and self.allow and ip not in self.allow:
            self.foreign += 1
            self.foreign_ip = ip
            return
        if not is_np:
            if ip != self.lock_ip:
                if self.lock_ip and now - self.lock_t < LOCK_S:
                    self.rejected += 1
                    return
                self.lock_ip = ip
            self.lock_t = now
            if self.rx == 0 or now - self.last_rx >= 1.0:
                self.since = now
            self.rx += 1
            self.last_rx = now
            if len(data) >= 6 and span(data) >= SILENT_SPAN:
                self.last_loud = now
            if self.want_levels and len(data) >= 6:
                pl, pr = peaks(data)
                self.lvl = [max(self.lvl[0], pl), max(self.lvl[1], pr)]
        else:
            self.np_relayed += 1
        for t in self.targets:
            if t.ip and (t.ip, t.port) != (ip, addr[1]) and t.ip not in self.my_ips:
                if self.sender(t.ip).send(data, (t.ip, t.port)) and not is_np:
                    t.pkts += 1
        if not is_np:
            for a in self.local:
                self.sender(a[0] + ":%d" % a[1]).send(data, a)

    def error_received(self, exc):
        pass

    # ---- state
    def per_second(self):
        """called once a second: packet rates"""
        self.rx_pps, self._rx_prev = self.rx - self._rx_prev, self.rx
        for t in self.targets:
            t.pps, t._prev = t.pkts - t._prev, t.pkts

    def active(self):
        return self.rx > 0 and self.clock() - self.last_rx < 1.0

    def take_levels(self):
        """(left, right) highest since the last call, 0..1; zero while no packets come"""
        lv = self.lvl if self.active() else [0.0, 0.0]
        self.lvl = [0.0, 0.0]
        return lv[0], lv[1]

    def silent_for(self):
        """seconds without sound while the stream runs, None without stream. Counted from when the stream came back
        at the latest: a hanging Ultimate (Elite II, "Network Host Resolve Error") answers each request with a second
        of silent packets over its WLAN - counted from the start of the tune, that skipped every tune after ~10 s"""
        if not self.active():
            return None
        return self.clock() - max(self.last_loud, self.since)

    def mark_loud(self):
        """a new tune starts: the silence count starts again"""
        self.last_loud = self.clock()

    def state(self):
        return {
            "active": self.active(),
            "from": self.lock_ip if self.active() else "",
            "pps": self.rx_pps,
            "rejected": self.rejected,
            "foreign": self.foreign, "foreign_ip": self.foreign_ip,
            "targets": [{"addr": t.addr, "ip": t.ip, "pps": t.pps, "dropped": self.dropped(t.ip)} for t in self.targets],
        }
