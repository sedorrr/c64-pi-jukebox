"""Where the SID files come from: a share on another computer or NAS (SMB, without mounting), an FTP server, the
USB stick of an Ultimate (its FTP service) or a folder / USB stick on the Pi itself.

Paths inside a source are POSIX style and start with "/" (relative to the source's root folder). FTP and SMB run
in worker threads; each source keeps one connection, used by one call at a time, closed after a minute idle."""
import asyncio
import ftplib
import io
import json
import os
import socket
import threading
import time

from .smb2 import Smb2, SmbFailed

SID_MAX = 1 << 20            # a SID file is at most ~64 KB, anything this big is not one
IDLE_S = 60


class SourceError(Exception):
    """message for the page (German)"""


def norm(path):
    parts = [p for p in (path or "/").replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        raise SourceError("Ungültiger Pfad")
    return "/" + "/".join(parts)


def join(root, path):
    root = (root or "/").replace("\\", "/").rstrip("/")
    return (root + norm(path)) if root else norm(path)


def parent(path):
    p = norm(path)
    return p.rsplit("/", 1)[0] or "/"


def tidy(entries):
    """hide dot files (macOS ._ files look like SIDs), folders first, then by name"""
    out = [e for e in entries if e["n"] and not e["n"].startswith(".")]
    out.sort(key=lambda e: (not e["d"], e["n"].lower()))
    return out


class Source:
    kind = ""

    def __init__(self, sid, label):
        self.id = sid
        self.label = label

    async def list(self, path):
        raise NotImplementedError

    async def read(self, path, limit=SID_MAX):
        raise NotImplementedError

    async def head(self, path, n):
        """the first n bytes (a SID header) - where the source cannot stop early, the whole file"""
        return (await self.read(path))[:n]

    def close(self):
        pass

    def idle_close(self):
        pass


class LocalSource(Source):
    kind = "local"

    def __init__(self, sid, label, root):
        super().__init__(sid, label)
        self.root = os.path.abspath(root or "/")

    def _abs(self, path):
        return os.path.join(self.root, *[x for x in norm(path).split("/") if x])

    def _list(self, path):
        p = self._abs(path)
        if not os.path.isdir(p):
            if p == self.root:
                raise SourceError("Ordner %s gibt es nicht (USB-Stick eingesteckt?)" % self.root)
            raise SourceError("Ordner nicht gefunden")
        out = []
        with os.scandir(p) as it:
            for e in it:
                try:
                    d = e.is_dir()
                    out.append({"n": e.name, "d": d, "s": 0 if d else e.stat().st_size})
                except OSError:
                    continue
        return tidy(out)

    def _read(self, path, limit):
        p = self._abs(path)
        try:
            if os.path.getsize(p) > limit:
                raise SourceError("Datei zu groß")
            with open(p, "rb") as f:
                return f.read()
        except OSError:
            raise SourceError("Datei nicht lesbar: " + norm(path))

    async def list(self, path):
        return await asyncio.get_running_loop().run_in_executor(None, self._list, path)

    async def read(self, path, limit=SID_MAX):
        return await asyncio.get_running_loop().run_in_executor(None, self._read, path, limit)

    def _head(self, path, n):
        try:
            with open(self._abs(path), "rb") as f:
                return f.read(n)
        except OSError:
            raise SourceError("Datei nicht lesbar: " + norm(path))

    async def head(self, path, n):
        return await asyncio.get_running_loop().run_in_executor(None, self._head, path, n)


class _Threaded(Source):
    """one connection, one call at a time, reconnect once on a broken connection"""

    def __init__(self, sid, label):
        super().__init__(sid, label)
        self._lock = threading.Lock()
        self._c = None
        self._used = 0.0

    def _connect(self):
        raise NotImplementedError

    def _drop(self):
        c, self._c = self._c, None
        if c is not None:
            try:
                self._close_conn(c)
            except Exception:
                pass

    def _close_conn(self, c):
        pass

    def _call(self, fn, *args):
        with self._lock:
            for attempt in (0, 1):
                fresh = self._c is None
                try:
                    if fresh:
                        self._c = self._connect()
                    r = fn(self._c, *args)
                    self._used = time.monotonic()
                    return r
                except SourceError:
                    raise
                except Exception as e:             # sockets, ftplib, pysmb: each raises its own kinds
                    self._drop()
                    if fresh or attempt:
                        raise SourceError(self._explain(e))

    def _explain(self, e):
        return "Verbindung fehlgeschlagen: %s" % (e or type(e).__name__)

    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, self._call, fn, *args)

    def close(self):
        with self._lock:
            self._drop()

    def idle_close(self):
        if self._c is not None and time.monotonic() - self._used > IDLE_S and self._lock.acquire(blocking=False):
            try:
                self._drop()
            finally:
                self._lock.release()


# ------------------------------------------------------------------ FTP

def parse_list_line(line):
    """one LIST line (Unix or DOS style) -> entry or None"""
    parts = line.split(None, 8)
    if len(parts) >= 9 and parts[0][:1] in "-dl":
        name = parts[8]
        is_dir = parts[0][0] == "d"
        if parts[0][0] == "l":
            name = name.split(" -> ")[0]
            is_dir = not name.lower().endswith((".sid", ".md5", ".txt"))
        try:
            size = int(parts[4])
        except ValueError:
            size = 0
        return {"n": name, "d": is_dir, "s": 0 if is_dir else size}
    parts = line.split(None, 3)
    if len(parts) == 4 and parts[0][:1].isdigit():
        is_dir = parts[2].upper() == "<DIR>"
        return {"n": parts[3], "d": is_dir, "s": 0 if is_dir else int(parts[2]) if parts[2].isdigit() else 0}
    return None


class FtpSource(_Threaded):
    kind = "ftp"

    def __init__(self, sid, label, host, port=21, user="", pw="", root="/"):
        super().__init__(sid, label)
        self.host, self.port, self.user, self.pw, self.root = host, int(port or 21), user, pw, root or "/"

    def _connect(self):
        if not self.host:
            raise SourceError("Kein Server eingetragen")
        f = ftplib.FTP(encoding="latin-1")
        f.connect(self.host, self.port, timeout=10)
        f.login(self.user or "anonymous", self.pw or "")
        f.set_pasv(True)
        try:
            if "UTF8" in f.sendcmd("FEAT").upper():
                f.sendcmd("OPTS UTF8 ON")
                f.encoding = "utf-8"
        except ftplib.Error:
            pass
        return f

    def _close_conn(self, c):
        try:
            c.quit()
        except Exception:
            c.close()

    def _explain(self, e):
        if isinstance(e, ftplib.error_perm) and str(e)[:3] == "530":
            return "FTP-Anmeldung abgelehnt (Benutzer/Passwort)"
        if isinstance(e, (ConnectionRefusedError, socket.timeout, TimeoutError)):
            return "FTP-Server %s nicht erreichbar" % self.host
        return "FTP: %s" % e

    def _list(self, f, path):
        full = join(self.root, path)
        try:
            f.cwd(full)
        except ftplib.error_perm:
            raise SourceError("Ordner nicht gefunden: " + norm(path))
        out = []
        try:
            for name, facts in f.mlsd():
                t = facts.get("type", "")
                if t in ("cdir", "pdir") or name in (".", ".."):
                    continue
                d = t == "dir"
                out.append({"n": name, "d": d, "s": 0 if d else int(facts.get("size", 0) or 0)})
            return tidy(out)
        except ftplib.error_perm:
            pass                                   # no MLSD (the Ultimate): classic LIST
        lines = []
        try:
            f.retrlines("LIST", lines.append)
        except UnicodeDecodeError:
            f.encoding = "latin-1"                 # announced UTF-8, but the names are not
            lines = []
            f.retrlines("LIST", lines.append)
        for ln in lines:
            e = parse_list_line(ln)
            if e and e["n"] not in (".", ".."):
                out.append(e)
        return tidy(out)

    def _read(self, f, path, limit):
        buf = io.BytesIO()

        def take(b):
            buf.write(b)
            if buf.tell() > limit:
                raise SourceError("Datei zu groß")
        try:
            f.retrbinary("RETR " + join(self.root, path), take)
        except SourceError:
            self._drop()
            raise
        except ftplib.error_perm:
            raise SourceError("Datei nicht gefunden: " + norm(path))
        return buf.getvalue()

    async def list(self, path):
        return await self._run(self._list, path)

    async def read(self, path, limit=SID_MAX):
        return await self._run(self._read, path, limit)


# ------------------------------------------------------------------ SMB (port 445, nothing mounted)
# First smbprotocol (SMB 2.0.2-3.1.1, smb2.py), then pysmb for old devices that speak only SMB 1. Both behind the same
# small interface: listdir(share, path) -> [(name, is_dir, size)], read(share, path, limit) -> bytes or None (too big),
# shares() -> [(name, type, comment)], close().

class PysmbClient:
    def __init__(self, host, user, pw, domain="", timeout=10):
        from smb.SMBConnection import SMBConnection
        self.c = SMBConnection(user or "guest", pw or "", "c64pi", host, domain=domain or "", use_ntlm_v2=True,
                               is_direct_tcp=True)
        try:
            ok = self.c.connect(host, 445, timeout=timeout)
        except (OSError, socket.timeout) as e:
            raise SmbFailed("SMB-Server %s nicht erreichbar (%s)" % (host, e))
        except Exception as e:
            raise SmbFailed("SMB-Anmeldung fehlgeschlagen (%s)" % str(e).splitlines()[0][:120])
        if not ok:
            raise SmbFailed("SMB-Anmeldung abgelehnt (Benutzer/Passwort)", login=True)

    def listdir(self, share, path):
        from smb.smb_structs import OperationFailure
        try:
            items = self.c.listPath(share, path or "/", timeout=30)
        except OperationFailure:
            raise SourceError("Ordner nicht gefunden oder kein Zugriff: " + norm(path))
        return [(f.filename, bool(f.isDirectory), int(f.file_size)) for f in items if f.filename not in (".", "..")]

    def read(self, share, path, limit):
        from smb.smb_structs import OperationFailure
        buf = io.BytesIO()
        try:
            self.c.retrieveFileFromOffset(share, path, buf, 0, limit + 1, timeout=30)
        except OperationFailure:
            raise SourceError("Datei nicht gefunden oder kein Zugriff: " + norm(path))
        return None if buf.tell() > limit else buf.getvalue()

    def head(self, share, path, n):
        from smb.smb_structs import OperationFailure
        buf = io.BytesIO()
        try:
            self.c.retrieveFileFromOffset(share, path, buf, 0, n, timeout=30)
        except OperationFailure:
            raise SourceError("Datei nicht gefunden oder kein Zugriff: " + norm(path))
        return buf.getvalue()

    def shares(self):
        return [(s.name, s.type, s.comments or "") for s in self.c.listShares(timeout=15)]

    def close(self):
        self.c.close()


def smb_connect(host, user, pw, domain="", timeout=10):
    """SMB 2/3 first; SMB 1 (pysmb) only when the server does not speak SMB 2 at all - never after a refused login"""
    try:
        c = Smb2(host, user, pw, timeout=timeout)
        return Smb2Client(c)
    except SmbFailed as e:
        if not e.smb1:
            raise SourceError(str(e))
        first = e
    try:
        return PysmbClient(host, user, pw, domain, timeout)
    except SmbFailed as e:
        raise SourceError(str(e) if e.login else str(first))


class Smb2Client:
    """Smb2 with the errors of the page"""

    def __init__(self, c):
        self.c = c

    def listdir(self, share, path):
        try:
            return self.c.listdir(share, path)
        except SmbFailed as e:
            raise SourceError(str(e))
        except Exception as e:
            if _smb_missing(e):
                raise SourceError("Ordner nicht gefunden oder kein Zugriff: " + norm(path))
            raise

    def read(self, share, path, limit):
        try:
            return self.c.read(share, path, limit)
        except Exception as e:
            if _smb_missing(e):
                raise SourceError("Datei nicht gefunden oder kein Zugriff: " + norm(path))
            raise

    def head(self, share, path, n):
        try:
            return self.c.head(share, path, n)
        except Exception as e:
            if _smb_missing(e):
                raise SourceError("Datei nicht gefunden oder kein Zugriff: " + norm(path))
            raise

    def shares(self):
        return self.c.shares()

    def close(self):
        self.c.close()


def _smb_missing(e):
    """a missing file/folder, an unknown share, no access - not a broken connection"""
    t = type(e).__name__ + " " + str(e)
    return any(k in t for k in ("ObjectNameNotFound", "ObjectPathNotFound", "BadNetworkName", "AccessDenied",
                                "NotADirectory", "FileIsADirectory", "NotFound", "0xc0000034", "0xc000003a",
                                "0xc00000cc", "0xc0000022", "0xc0000103", "0xc00000ba"))


def smb_shares(host, user="", pw="", domain=""):
    """names of the disk shares of a server (blocking)"""
    c = smb_connect(host, user, pw, domain)
    try:
        try:
            raw = c.shares()
        except SmbFailed as e:
            raise SourceError(str(e))
        out = [{"name": n, "comment": r} for n, t, r in raw
               if (t & 0xFFFF) == 0 and not t & 0x80000000 and not n.endswith("$")]   # disk trees, no admin shares
        return sorted(out, key=lambda s: s["name"].lower())
    finally:
        c.close()


class SmbSource(_Threaded):
    kind = "smb"

    def __init__(self, sid, label, host, share, root="/", user="", pw="", domain=""):
        super().__init__(sid, label)
        self.host, self.share, self.root = host, share, root or "/"
        self.user, self.pw, self.domain = user, pw, domain

    def _connect(self):
        if not self.host or not self.share:
            raise SourceError("Server oder Freigabe fehlt")
        return smb_connect(self.host, self.user, self.pw, self.domain)

    def _close_conn(self, c):
        c.close()

    def _explain(self, e):
        return "SMB: %s" % (str(e).splitlines()[0] if str(e) else type(e).__name__)

    def _list(self, c, path):
        return tidy([{"n": n, "d": d, "s": 0 if d else s} for n, d, s in c.listdir(self.share, join(self.root, path))])

    def _read(self, c, path, limit):
        data = c.read(self.share, join(self.root, path), limit)
        if data is None:
            raise SourceError("Datei zu groß")
        return data

    async def list(self, path):
        return await self._run(self._list, path)

    async def read(self, path, limit=SID_MAX):
        return await self._run(self._read, path, limit)

    async def head(self, path, n):
        return await self._run(lambda c, p: c.head(self.share, join(self.root, p), n), path)


# ------------------------------------------------------------------ the set of sources from the settings

def host_of(addr):
    """'192.168.1.168:8080' or 'http://u64/' -> '192.168.1.168' / 'u64'"""
    a = (addr or "").strip()
    for p in ("http://", "https://"):
        if a.lower().startswith(p):
            a = a[len(p):]
    a = a.split("/", 1)[0]
    if a.count(":") == 1:
        a = a.split(":")[0]
    return a


class Sources:
    def __init__(self, config):
        self.config = config
        self._cache = {}          # id -> (settings json, Source)

    def ultimate_index(self, s):
        i = s.get("u64", -1)
        return self.config["u64_sel"] if i is None or i < 0 else i

    def _build(self, s):
        k = s.get("kind")
        sid, label = s.get("id"), s.get("label") or s.get("id")
        if k == "local":
            return LocalSource(sid, label, s.get("path") or "/")
        if k == "ftp":
            return FtpSource(sid, label, s.get("host", ""), s.get("port") or 21, s.get("user", ""), s.get("pw", ""),
                             s.get("path") or "/")
        if k == "smb":
            return SmbSource(sid, label, s.get("host", ""), s.get("share", ""), s.get("path") or "/",
                             s.get("user", ""), s.get("pw", ""), s.get("domain", ""))
        if k == "u64":
            u = self.config.ultimate(self.ultimate_index(s))
            src = FtpSource(sid, label, host_of(u.get("addr")), s.get("port") or 21, "anonymous", u.get("pw", ""),
                            s.get("path") or "/")
            src.kind = "u64"
            return src
        raise SourceError("Unbekannte Quelle")

    def get(self, sid):
        s = self.config.source(sid)
        if s is None:
            raise SourceError("Quelle nicht gefunden")
        key = json.dumps([s, self.config.ultimate(self.ultimate_index(s)) if s.get("kind") == "u64" else None],
                         sort_keys=True)
        hit = self._cache.get(sid)
        if hit and hit[0] == key:
            return hit[1]
        if hit:
            hit[1].close()
        src = self._build(s)
        self._cache[sid] = (key, src)
        return src

    def build_temp(self, s):
        """a source from the dialog, before it is saved (connection test)"""
        return self._build(s)

    def on_ultimate(self, sid, ultimate_index):
        """True when the files of this source lie on that Ultimate itself (play by path, no upload)"""
        s = self.config.source(sid)
        return bool(s) and s.get("kind") == "u64" and self.ultimate_index(s) == ultimate_index

    def idle(self):
        for _k, src in list(self._cache.values()):
            src.idle_close()

    def close(self):
        for _k, src in self._cache.values():
            src.close()
        self._cache.clear()
