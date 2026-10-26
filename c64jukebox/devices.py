"""Devices in the network, the same way as the Picos do it (see the visualizer's manual, "Netzwerk-Protokolle"):
"C64DEV1 {json}" every 10 s as broadcast to UDP 11064, "C64DEV1?" asks everybody, each answers within 0.4 s.
The Picos drop beacons of 420 bytes and more, so ours stays below."""
import asyncio
import json
import random
import socket
import time

from . import events

DEV_PORT = 11064
BEACON_S = 10.0
FORGET_S = 35.0
DEV_MAX = 32
JSON_MAX = 419


def fit_json(d):
    """JSON of the beacon, optional fields dropped until it fits"""
    d = dict(d)
    for drop in (None, "title", "fwl", "srcl", "fw"):
        if drop:
            d.pop(drop, None)
        s = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        if len(s.encode()) <= JSON_MAX:
            return s
    return s


def _name(j):
    try:
        return str(json.loads(j).get("n") or "?")
    except ValueError:
        return "?"


class Devices(asyncio.DatagramProtocol):
    def __init__(self, self_json, port=DEV_PORT, bcast="255.255.255.255", clock=time.monotonic, bcast_port=None):
        self.self_json = self_json            # function -> dict of our own beacon
        self.port, self.bcast, self.clock = port, bcast, clock
        self.bcast_port = bcast_port or port
        self.transport = None
        self.table = {}                       # ip -> (seen, json text)
        self.my_ips = {"127.0.0.1"}
        self.next_beacon = 0.0
        self.answer_at = None
        self.task = None

    async def start(self, host="0.0.0.0"):
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((host, self.port))
        self.port = sock.getsockname()[1]
        if not self.bcast_port:
            self.bcast_port = self.port
        self.transport, _ = await loop.create_datagram_endpoint(lambda: self, sock=sock)
        self.query()
        self.task = loop.create_task(self.run())
        return self

    def close(self):
        if self.task:
            self.task.cancel()
        if self.transport:
            self.transport.close()

    def datagram_received(self, data, addr):
        ip = addr[0]
        if ip in self.my_ips:
            return
        now = self.clock()
        if data == b"C64DEV1?":
            if self.answer_at is None:
                self.answer_at = now + 0.05 + random.random() * 0.35
            return
        if not data.startswith(b"C64DEV1 "):
            return
        text = data[8:].rstrip(b"\r\n")
        if len(text) > 1024:
            return
        try:
            s = text.decode("utf-8")
            if not isinstance(json.loads(s), dict):
                return
        except (UnicodeDecodeError, ValueError):
            return
        if ip not in self.table:
            events.log("Gerät da: %s (%s)" % (_name(s), ip))
        if ip not in self.table and len(self.table) >= DEV_MAX:
            oldest = min(self.table, key=lambda k: self.table[k][0])
            del self.table[oldest]
        self.table[ip] = (now, s)

    def error_received(self, exc):
        pass

    def _send(self, data):
        if self.transport:
            try:
                self.transport.sendto(data, (self.bcast, self.bcast_port))
            except OSError:
                pass

    def beacon(self):
        self._send(b"C64DEV1 " + fit_json(self.self_json()).encode())

    def query(self):
        """ask all devices now (and say who we are)"""
        self._send(b"C64DEV1?")
        self.answer_at = self.clock() + 0.02

    def tick(self):
        now = self.clock()
        if now >= self.next_beacon or (self.answer_at is not None and now >= self.answer_at):
            self.answer_at = None
            self.next_beacon = now + BEACON_S - 0.5 + random.random()
            self.beacon()
        for ip in [k for k, v in self.table.items() if now - v[0] > FORGET_S]:
            events.log("Gerät weg: %s (%s), %.0f s keine Meldung" % (_name(self.table[ip][1]), ip, FORGET_S))
            del self.table[ip]

    async def run(self):
        while True:
            await asyncio.sleep(0.05)
            try:
                self.tick()
            except Exception:
                pass

    def listing(self):
        """the same shape as GET /devices of the Picos"""
        now = self.clock()
        out = [{"self": True, "age": 0, "j": fit_json(self.self_json())}]
        for ip, (seen, s) in sorted(self.table.items()):
            out.append({"age": int(now - seen), "j": s})
        return {"list": out}
