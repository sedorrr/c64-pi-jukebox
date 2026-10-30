"""Stand-ins for the tests: SID files, an Ultimate (REST), an FTP server (like the Ultimate's: no MLSD, no EPSV,
Unix LIST) and pysmb's SMBConnection over an in-memory tree."""
import io
import json
import socket
import socketserver
import struct
import threading
import time

from aiohttp import web


def make_sid(title="Tune", author="Composer", released="1987 Label", songs=1, start=1, version=2,
             second=0, third=0, flags=0x10, body=b"\x60" * 32, rsid=False):
    h = bytearray(0x7C)
    h[0:4] = b"RSID" if rsid else b"PSID"
    h[4:6] = struct.pack(">H", version)
    h[6:8] = struct.pack(">H", 0x7C)
    h[0x0E:0x10] = struct.pack(">H", songs)
    h[0x10:0x12] = struct.pack(">H", start)
    h[0x16:0x16 + len(title)] = title.encode("latin-1")
    h[0x36:0x36 + len(author)] = author.encode("latin-1")
    h[0x56:0x56 + len(released)] = released.encode("latin-1")
    h[0x76:0x78] = struct.pack(">H", flags)
    h[0x7A] = second
    h[0x7B] = third
    return bytes(h) + body


def free_port(kind=socket.SOCK_DGRAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------------------ Ultimate REST

class FakeUltimate:
    def __init__(self, pw="", product="Ultimate 64 Elite II", uid="abc123", wifi_mac=""):
        self.pw, self.product, self.uid, self.wifi_mac = pw, product, uid, wifi_mac
        self.calls = []            # (method, path, query dict, extra)
        self.fail_play = 0
        self.lose_sid_put = 0      # apply a SID address but answer 500 (a lost answer)
        self.debug_mode = "6510 Only"
        self.resolve_error = False  # answer stream starts like a hanging Elite II
        # like an Ultimate 64 Elite II with two SID sockets (only RAM; GET/PUT /v1/configs/SID Addressing)
        self.sid_cfg = {"SID Socket 1 Address": "$D400", "SID Socket 2 Address": "$D500",
                        "UltiSID 1 Address": "Unmapped", "UltiSID 2 Address": "Unmapped"}
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.app = app
        self.runner = None
        self.port = None

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        await self.runner.cleanup()

    @property
    def addr(self):
        return "127.0.0.1:%d" % self.port

    def find(self, method, path):
        return [c for c in self.calls if c[0] == method and c[1] == path]

    async def handle(self, req):
        if self.pw and req.headers.get("X-Password") != self.pw:
            return web.Response(status=403)
        q = dict(req.query)
        extra = None
        if req.path == "/v1/runners:sidplay" and req.method == "POST":
            reader = await req.multipart()
            part = await reader.next()
            extra = {"field": part.name, "filename": part.filename, "data": await part.read()}
        self.calls.append((req.method, req.path, q, extra))
        if req.path == "/v1/runners:sidplay" and self.fail_play:
            self.fail_play -= 1
            return web.Response(status=500)
        if req.path == "/v1/configs/SID Addressing" and req.method == "GET":
            return web.json_response({"SID Addressing": dict(self.sid_cfg), "errors": []})
        if req.path.startswith("/v1/configs/SID Addressing/") and req.method == "PUT":
            item = req.path.split("/", 4)[4]
            if item not in self.sid_cfg:
                return web.json_response({"errors": ["unknown item"]}, status=404)
            self.sid_cfg[item] = q.get("value", "")
            if self.lose_sid_put:
                self.lose_sid_put -= 1
                return web.json_response({"errors": ["lost"]}, status=500)
            return web.json_response({"errors": []})
        if self.resolve_error and req.path.startswith("/v1/streams/") and req.path.endswith(":start"):
            return web.json_response({"errors": ["Network Host Resolve Error"]}, status=404)
        if req.path == "/v1/configs/Data Streams/Debug Stream Mode":
            return web.json_response({"Data Streams": {"Debug Stream Mode": {"current": self.debug_mode}}, "errors": []})
        if req.path == "/v1/info":
            d = {"product": self.product, "hostname": "Ultimate-64-II", "unique_id": self.uid, "firmware_version": "3.15a"}
            if self.wifi_mac:
                d["wifi_mac"] = self.wifi_mac
            return web.json_response(d)
        return web.json_response({"errors": []})


# ------------------------------------------------------------------ FTP

class _FtpHandler(socketserver.StreamRequestHandler):
    def send(self, line):
        self.wfile.write((line + "\r\n").encode(self.server.enc))

    def node(self, path):
        cur = self.server.tree
        for p in [x for x in path.split("/") if x]:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur

    def absolute(self, arg):
        if not arg:
            return self.cwd
        p = arg if arg.startswith("/") else self.cwd.rstrip("/") + "/" + arg
        parts = []
        for x in p.split("/"):
            if x == "..":
                parts and parts.pop()
            elif x and x != ".":
                parts.append(x)
        return "/" + "/".join(parts)

    def data_conn(self):
        c, _ = self.pasv.accept()
        self.pasv.close()
        self.pasv = None
        return c

    def handle(self):
        try:
            self.session()
        except (ConnectionError, BrokenPipeError):
            pass                     # a port check of the network search: connect and gone again

    def session(self):
        self.cwd, self.pasv, self.user = "/", None, ""
        self.send("220 fake FTP")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode(self.server.enc).rstrip("\r\n")
            cmd, _, arg = line.partition(" ")
            cmd = cmd.upper()
            self.server.log.append(line)
            if cmd == "USER":
                self.user = arg
                self.send("331 password")
            elif cmd == "PASS":
                if self.server.login and (self.user, arg) != self.server.login:
                    self.send("530 Login incorrect")
                else:
                    self.send("230 ok")
            elif cmd == "FEAT":
                if self.server.utf8:
                    self.send("211-Features:")
                    self.send(" UTF8")
                    self.send("211 End")
                else:
                    self.send("502 not implemented")
            elif cmd == "OPTS":
                self.send("200 ok")
            elif cmd in ("TYPE", "NOOP"):
                self.send("200 ok")
            elif cmd == "PWD":
                self.send('257 "%s"' % self.cwd)
            elif cmd == "CWD":
                p = self.absolute(arg)
                if isinstance(self.node(p), dict):
                    self.cwd = p
                    self.send("250 ok")
                else:
                    self.send("550 no such directory")
            elif cmd == "PASV":
                self.pasv = socket.socket()
                self.pasv.bind(("127.0.0.1", 0))
                self.pasv.listen(1)
                port = self.pasv.getsockname()[1]
                self.send("227 Entering Passive Mode (127,0,0,1,%d,%d)" % (port >> 8, port & 255))
            elif cmd in ("EPSV", "MLSD"):
                self.send("502 not implemented")
            elif cmd == "LIST":
                d = self.node(self.absolute(arg))
                self.send("150 listing")
                c = self.data_conn()
                if isinstance(d, dict):
                    for name, v in d.items():
                        if isinstance(v, dict):
                            ln = "drw-rw-rw-   1 user     ftp            0 Oct 10 12:00 %s" % name
                        else:
                            ln = "-rw-rw-rw-   1 user     ftp     %8d Oct 10 12:00 %s" % (len(v), name)
                        c.sendall((ln + "\r\n").encode(self.server.enc))
                c.close()
                self.send("226 done")
            elif cmd == "RETR":
                f = self.node(self.absolute(arg))
                if not isinstance(f, bytes):
                    if self.pasv:
                        self.pasv.close()
                        self.pasv = None
                    self.send("550 no such file")
                    continue
                self.send("150 sending")
                c = self.data_conn()
                c.sendall(f)
                c.close()
                self.send("226 done")
            elif cmd == "QUIT":
                self.send("221 bye")
                return
            else:
                self.send("502 not implemented")


class FakeFTP(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, tree, login=None, utf8=False, enc="latin-1"):
        super().__init__(("127.0.0.1", 0), _FtpHandler)
        self.tree, self.login, self.utf8, self.enc = tree, login, utf8, ("utf-8" if utf8 else enc)
        self.log = []
        self.port = self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def stop(self):
        self.shutdown()
        self.server_close()


# ------------------------------------------------------------------ SMB (pysmb's interface)

class FakeSMBServer:
    def __init__(self, shares, user="", pw="", smb2=True):
        self.shares, self.user, self.pw = shares, user, pw     # {share: tree}
        self.smb2 = smb2                                        # False: an old device that speaks only SMB 1
        self.connects = 0


SMB_SERVERS = {}               # host -> FakeSMBServer


def fake_smb_class():
    from smb.base import SharedDevice, SharedFile
    from smb.smb_structs import OperationFailure

    class FakeSMBConnection:
        def __init__(self, username, password, my_name, remote_name, domain="", use_ntlm_v2=True, sign_options=2,
                     is_direct_tcp=False):
            self.username, self.password = username, password
            self.is_direct_tcp = is_direct_tcp
            self.srv = None

        def connect(self, ip, port=139, sock_family=None, timeout=60):
            srv = SMB_SERVERS.get(ip)
            if srv is None:
                raise ConnectionRefusedError("no SMB server at %s" % ip)
            assert port == 445 and self.is_direct_tcp
            srv.connects += 1
            if srv.user and (self.username, self.password) != (srv.user, srv.pw):
                return False
            self.srv = srv
            return True

        def listShares(self, timeout=30):
            out = [SharedDevice(0, name, "Musik" if name == "Musik" else "") for name in self.srv.shares]
            out.append(SharedDevice(3, "IPC$", "IPC"))
            out.append(SharedDevice(0, "C$", "admin"))
            return out

        def _node(self, share, path):
            if share not in self.srv.shares:
                raise OperationFailure("no share", [])
            cur = self.srv.shares[share]
            for p in [x for x in path.split("/") if x]:
                if not isinstance(cur, dict) or p not in cur:
                    raise OperationFailure("not found", [])
                cur = cur[p]
            return cur

        def listPath(self, service_name, path, search=65591, pattern="*", timeout=30):
            d = self._node(service_name, path)
            if not isinstance(d, dict):
                raise OperationFailure("not a dir", [])
            t = time.time()
            out = [SharedFile(t, t, t, t, 0, 0, 0x10, "", "."), SharedFile(t, t, t, t, 0, 0, 0x10, "", "..")]
            for name, v in d.items():
                if isinstance(v, dict):
                    out.append(SharedFile(t, t, t, t, 0, 0, 0x10, "", name))
                else:
                    out.append(SharedFile(t, t, t, t, len(v), len(v), 0x20, "", name))
            return out

        def retrieveFileFromOffset(self, service_name, path, file_obj, offset=0, max_length=-1, timeout=30,
                                   show_progress=False, tqdm_kwargs={}):
            f = self._node(service_name, path)
            if not isinstance(f, bytes):
                raise OperationFailure("not a file", [])
            data = f[offset:] if max_length < 0 else f[offset:offset + max_length]
            file_obj.write(data)
            return 0x20, len(data)

        def close(self):
            pass

    return FakeSMBConnection


class FakeSmb2:
    """stands in for c64jukebox.smb2.Smb2 (smbprotocol): same tree, SMB 2/3 servers only"""

    def __init__(self, host, user="", pw="", timeout=10):
        from c64jukebox.smb2 import SmbFailed
        srv = SMB_SERVERS.get(host)
        if srv is None:
            raise SmbFailed("SMB-Server %s nicht erreichbar (fake)" % host)
        if not srv.smb2:
            raise SmbFailed("SMB-Server %s spricht kein SMB 2/3 (fake)" % host, smb1=True)
        srv.connects += 1
        if srv.user and ((user or "guest"), pw) != (srv.user, srv.pw):
            raise SmbFailed("SMB-Anmeldung abgelehnt (Benutzer/Passwort)", login=True)
        self.srv = srv

    def _node(self, share, path):
        if share not in self.srv.shares:
            raise FileNotFoundError("BadNetworkName " + share)
        cur = self.srv.shares[share]
        for p in [x for x in path.replace("\\", "/").split("/") if x]:
            if not isinstance(cur, dict) or p not in cur:
                raise FileNotFoundError("ObjectNameNotFound " + path)
            cur = cur[p]
        return cur

    def listdir(self, share, path):
        d = self._node(share, path)
        if not isinstance(d, dict):
            raise NotADirectoryError("NotADirectory " + path)
        return [(n, isinstance(v, dict), 0 if isinstance(v, dict) else len(v)) for n, v in d.items()]

    def read(self, share, path, limit):
        f = self._node(share, path)
        if not isinstance(f, bytes):
            raise IsADirectoryError("FileIsADirectory " + path)
        return None if len(f) > limit else f

    def head(self, share, path, n):
        f = self._node(share, path)
        if not isinstance(f, bytes):
            raise IsADirectoryError("FileIsADirectory " + path)
        return f[:n]

    def shares(self):
        return [(n, 0, "Musik" if n == "Musik" else "") for n in self.srv.shares] + [("IPC$", 3, "IPC"), ("C$", 0x80000000, "")]

    def close(self):
        pass


def install_fake_smb(monkeypatch):
    import smb.SMBConnection
    import c64jukebox.sources
    monkeypatch.setattr(smb.SMBConnection, "SMBConnection", fake_smb_class())
    monkeypatch.setattr(c64jukebox.sources, "Smb2", FakeSmb2)
    SMB_SERVERS.clear()
    return SMB_SERVERS


# ------------------------------------------------------------------ a Pico (/jb/np with digest login)

class FakePico:
    def __init__(self, pw="geheim", busy=0):
        import hashlib
        self.pw, self.busy = pw, busy
        self.got = []
        self.news = []             # bodies of POST /news
        self.nonce = "n0nce%d" % int(time.time())
        self.md5 = lambda s: hashlib.md5(s.encode()).hexdigest()
        app = web.Application()
        app.router.add_post("/jb/np", self.np)
        app.router.add_post("/news", self.np)
        self.app = app

    def check(self, req):
        import re
        h = req.headers.get("Authorization", "")
        if not h.startswith("Digest "):
            return False
        d = dict(re.findall(r'(\w+)="?([^",]*)"?', h[7:]))
        if d.get("nonce") != self.nonce:
            return False
        ha1 = self.md5("%s:%s:%s" % (d["username"], "C64 Visualizer", self.pw))
        ha2 = self.md5("POST:%s" % d["uri"])
        want = self.md5("%s:%s:%s:%s:auth:%s" % (ha1, d["nonce"], d["nc"], d["cnonce"], ha2))
        return want == d.get("response") and d["uri"] == req.path_qs

    async def np(self, req):
        if not self.check(req):
            return web.Response(status=401, headers={
                "WWW-Authenticate": 'Digest realm="C64 Visualizer", qop="auth", algorithm=MD5, nonce="%s"' % self.nonce})
        if self.busy:
            self.busy -= 1
            return web.json_response({"ok": False}, status=409)
        if req.path == "/news":
            self.news.append(await req.read())
        else:
            self.got.append(dict(req.query))
        return web.json_response({"ok": True})

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        await self.runner.cleanup()


class UdpSink:
    """a UDP socket that collects what arrives (a Pico's stream port)"""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]

    def drain(self, wait=0.3):
        out, end = [], time.time() + wait
        while time.time() < end:
            try:
                out.append(self.sock.recvfrom(2048))
            except socket.timeout:
                continue
        return out

    def close(self):
        self.sock.close()


def jdump(o):
    return json.dumps(o)


__all__ = ["make_sid", "FakeUltimate", "FakeFTP", "install_fake_smb", "FakePico", "UdpSink", "free_port", "io"]
