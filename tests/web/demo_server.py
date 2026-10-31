"""The jukebox with stand-ins for everything around it - for the browser tests and to look at the page:

    python3 tests/web/demo_server.py [port]      (then http://127.0.0.1:<port>/, password commodore64)

A fake Ultimate (REST, records what it is told), a fake FTP server as the Ultimate's USB stick, a fake SMB server
"nas.local" with a share "Musik", and a local folder with a few SID files."""
import asyncio
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from aiohttp import web  # noqa: E402

from c64jukebox import sidfile  # noqa: E402
from c64jukebox.core import Jukebox  # noqa: E402
from c64jukebox.web import make_app  # noqa: E402
from fakes import FakeFTP, FakeSMBServer, FakeUltimate, SMB_SERVERS, fake_smb_class, free_port, make_sid  # noqa: E402

TUNES = [
    ("MUSICIANS/H/Hubbard_Rob/Commando.sid", make_sid("Commando", "Rob Hubbard", "1985 Elite", songs=3)),
    ("MUSICIANS/H/Hubbard_Rob/Delta.sid", make_sid("Delta", "Rob Hubbard", "1987 Thalamus", songs=12)),
    ("MUSICIANS/H/Huelsbeck_Chris/Shades.sid", make_sid("Shades", "Chris Hülsbeck", "1986 Rainbow Arts")),
    ("MUSICIANS/G/Galway_Martin/Wizball.sid", make_sid("Wizball", "Martin Galway", "1987 Ocean", songs=2)),
    ("DEMOS/A-F/Dual_Core.sid", make_sid("Dual Core", "Jammer", "2015 Maniacs", version=3, second=0x42)),
    ("DEMOS/A-F/Edge_of_Disgrace.sid", make_sid("Edge of Disgrace", "Jeroen Tel", "2008 Booze Design")),
    ("GAMES/S-Z/Turrican.sid", make_sid("Turrican", "Chris Hülsbeck", "1990 Rainbow Arts", songs=4)),
]


def write_tree(root):
    for p, data in TUNES:
        f = os.path.join(root, *p.split("/"))
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "wb") as fh:
            fh.write(data)
    os.makedirs(os.path.join(root, "DOCUMENTS"), exist_ok=True)
    with open(os.path.join(root, "DOCUMENTS", "Songlengths.md5"), "w") as f:
        f.write("[Database]\n")
        for i, (p, data) in enumerate(TUNES):
            h = sidfile.parse_header(data)
            f.write("; /%s\n%s=%s\n" % (p, sidfile.md5(data), " ".join("%d:%02d" % (2 + i % 3, 7 * (k + i) % 60) for k in range(h["songs"]))))


def tree_of(path):
    out = {}
    for name in os.listdir(path):
        p = os.path.join(path, name)
        out[name] = tree_of(p) if os.path.isdir(p) else open(p, "rb").read()
    return out


class FakeNetwatch:
    """answers the jukebox's requests in /run/c64pi like netwatch.py would (cable, three WLANs in the air)"""

    def __init__(self, run_dir):
        self.dir = run_dir
        self.state = {"mode": "lan", "eth": True, "eth_ip": "192.168.1.78", "radio": False, "ap": None, "last": None,
                      "scan": [], "t": 0}
        self.requests = []
        self.write()
        threading.Thread(target=self.loop, daemon=True).start()

    def write(self):
        import json
        import time
        self.state["t"] = time.time()
        with open(os.path.join(self.dir, "net.json.tmp"), "w") as f:
            json.dump(self.state, f)
        os.replace(os.path.join(self.dir, "net.json.tmp"), os.path.join(self.dir, "net.json"))

    def loop(self):
        import json
        import time
        while True:
            time.sleep(0.2)
            p = os.path.join(self.dir, "request.json")
            if not os.path.exists(p):
                continue
            with open(p) as f:
                req = json.load(f)
            os.remove(p)
            self.requests.append(req)
            if req["action"] == "scan":
                self.state["scan"] = [{"ssid": "MeinWLAN", "signal": 82, "sec": "WPA2"},
                                      {"ssid": "C64-Visualizer", "signal": 60, "sec": "WPA2"},
                                      {"ssid": "Gast", "signal": 35, "sec": ""}]
                self.state["last"] = {"id": req["id"], "ok": True, "msg": "3 WLANs gefunden"}
            elif req["action"] == "connect":
                ok = req.get("pw") != "falsch123"
                self.state["last"] = {"id": req["id"], "ok": ok,
                                      "msg": "verbunden mit " + req["ssid"] if ok else "Verbinden ging nicht: Passwort falsch"}
            else:
                self.state["last"] = {"id": req["id"], "ok": True, "msg": "vergessen"}
            self.write()


class Demo:
    def __init__(self, port=0, tmp=None):
        self.port = port or free_port(1)
        self.tmp = tmp or tempfile.mkdtemp(prefix="c64pi-demo-")
        self.ready = threading.Event()
        self.loop = None

    def start(self):
        threading.Thread(target=self._thread, daemon=True).start()
        if not self.ready.wait(15):
            raise RuntimeError("demo server did not start")
        return self

    def _thread(self):
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self._up())
        self.ready.set()
        self.loop.run_forever()

    async def _up(self):
        import smb.SMBConnection
        import c64jukebox.sources
        from fakes import FakeSmb2
        smb.SMBConnection.SMBConnection = fake_smb_class()
        c64jukebox.sources.Smb2 = FakeSmb2
        sids = os.path.join(self.tmp, "C64Music")
        write_tree(sids)
        self.u64 = await FakeUltimate().start()
        self.ftp = FakeFTP({"USB2": {"SID-Tunes": tree_of(sids)}})
        SMB_SERVERS["nas.local"] = FakeSMBServer({"Musik": {"C64Music": tree_of(sids)}, "Fotos": {}}, user="nutzer", pw="geheim")
        SMB_SERVERS["127.0.0.1"] = SMB_SERVERS["localhost"] = SMB_SERVERS["nas.local"]
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir, exist_ok=True)
        self.net = FakeNetwatch(self.run_dir)
        self.jb = Jukebox(os.path.join(self.tmp, "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=self.run_dir,
                          scan_hosts=["127.0.0.1"] + ["192.0.2.%d" % i for i in range(1, 30)],   # TEST-NET: never answers
                          scan_ports={"smb": self.ftp.port, "ftp": self.ftp.port, "http": self.u64.port})
        self.jb.scan_timeout = 1.5                  # long enough to watch the progress
        # switching off: never the real computer; a fake smart plug (tests/test_plug.py)
        from test_plug import FakeTuya
        from c64jukebox.plug import Plug
        self.plug = FakeTuya(ip="192.168.1.60")
        self.jb.plug = Plug(lib=self.plug)
        self.jb.power_can_cmd = [sys.executable, "-c", "print('s \"yes\"')"]
        self.jb.power_cmd = [sys.executable, "-c", "pass"]
        self.jb.update_can_cmd = [sys.executable, "-c", "print('loaded')"]           # the update: nothing installed
        self.jb.update_cmd = [sys.executable, "-c", "pass"]
        c = self.jb.config.data
        if c["ultimates"][0]["addr"] == "":
            c["ultimates"] = [{"label": "Elite II", "addr": self.u64.addr, "pw": ""}]
            c["sources"] = [{"id": "u64", "kind": "u64", "label": "USB-Stick am Ultimate", "path": "/", "port": self.ftp.port},
                            {"id": "pi", "kind": "local", "label": "Ordner am Pi", "path": sids}]
            c["picos"] = [{"addr": "c64viz.local", "np": "udp", "stream": True}]
        app = make_app(self.jb)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await self.jb.start()
        await web.TCPSite(self.runner, "127.0.0.1", self.port).start()

    def call(self, coro, timeout=10):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self):
        async def down():
            await self.runner.cleanup()
            await self.jb.close()
            await self.u64.stop()
        try:
            self.call(down())
        finally:
            self.ftp.stop()
            self.loop.call_soon_threadsafe(self.loop.stop)

    @property
    def url(self):
        return "http://127.0.0.1:%d/" % self.port


if __name__ == "__main__":
    d = Demo(int(sys.argv[1]) if len(sys.argv) > 1 else 8099).start()
    print("C64-Jukebox demo on", d.url, "(Passwort commodore64), data in", d.tmp, flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        d.stop()
