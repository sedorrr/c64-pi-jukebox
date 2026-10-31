"""SMB 2/3 with smbprotocol (SMB 2.0.2 up to 3.1.1, signing and encryption as the server wants them) - many servers
(Samba with "server min protocol = SMB3", recent NAS) refuse the SMB 1/2.1 of pysmb.

smbprotocol cannot list the shares of a server, so that is done here by hand: DCE/RPC over the named pipe
\\PIPE\\srvsvc, NetrShareEnum (opnum 15) at level 1 - what "net view" and every file manager do."""
import struct
import uuid

from .i18n import tr

SRVSVC = uuid.UUID("4b324fc8-1670-01d3-1278-5a47bf6ee188")
NDR = uuid.UUID("8a885d04-1ceb-11c9-9fe8-08002b104860")
FRAG = 4280
STYPE_MASK = 0xFFFF            # low bits: 0 = disk, 1 = printer, 3 = IPC; 0x80000000 = special ($ shares)


class SmbFailed(Exception):
    """connection or login refused - message for the page; login=True: the server refused the user/password"""

    def __init__(self, msg, login=False, smb1=False):
        super().__init__(msg)
        self.login = login
        self.smb1 = smb1        # the server answers, but not with SMB 2/3: worth trying SMB 1


def _hdr(ptype, body_len, call_id):
    return struct.pack("<BBBBBBBBHHI", 5, 0, ptype, 0x03, 0x10, 0, 0, 0, 16 + body_len, 0, call_id)


def bind_pdu(call_id=1):
    ctx = struct.pack("<HBB", 0, 1, 0) + SRVSVC.bytes_le + struct.pack("<HH", 3, 0) + NDR.bytes_le + struct.pack("<I", 2)
    body = struct.pack("<HHIBBH", FRAG, FRAG, 0, 1, 0, 0) + ctx
    return _hdr(11, len(body), call_id) + body


def _wstr(s):
    """NDR conformant varying string (with terminating zero), padded to 4 bytes"""
    raw = (s + "\0").encode("utf-16-le")
    n = len(raw) // 2
    out = struct.pack("<III", n, 0, n) + raw
    return out + b"\0" * (-len(out) % 4)


def share_enum_pdu(server, call_id=2):
    stub = struct.pack("<I", 0x00020000) + _wstr("\\\\" + server)       # ServerName (unique pointer)
    stub += struct.pack("<IIII", 1, 1, 0x00020004, 0) + struct.pack("<I", 0)   # level 1, container: 0 entries, no buffer
    stub += struct.pack("<I", 0xFFFFFFFF)                                       # PreferedMaximumLength
    stub += struct.pack("<II", 0x00020008, 0)                                   # ResumeHandle
    body = struct.pack("<IHH", len(stub), 0, 15) + stub
    return _hdr(0, len(body), call_id) + body


def split_fragments(data):
    """response PDUs -> (stub bytes, last fragment seen)"""
    stub, pos, last = b"", 0, False
    while pos + 24 <= len(data):
        ptype, flags = data[pos + 2], data[pos + 3]
        frag_len, auth_len = struct.unpack_from("<HH", data, pos + 8)
        if pos + frag_len > len(data):
            break                                                               # rest of this fragment still to come
        if ptype == 3:                                                          # fault
            raise SmbFailed(tr("Server lehnt die Abfrage der Freigaben ab (Fehler 0x%08x)")
                            % struct.unpack_from("<I", data, pos + 24)[0])
        if ptype != 2 or frag_len < 24:
            raise SmbFailed(tr("Unerwartete Antwort beim Abfragen der Freigaben"))
        stub += data[pos + 24:pos + frag_len - (auth_len + 8 if auth_len else 0)]
        last = bool(flags & 0x02)
        pos += frag_len
    return stub, last


def parse_share_enum(stub):
    """NetrShareEnum level-1 answer -> [(name, type, comment)]"""
    pos = 0

    def u32():
        nonlocal pos
        v = struct.unpack_from("<I", stub, pos)[0]
        pos += 4
        return v

    def wstr():
        nonlocal pos
        _max, _off, actual = struct.unpack_from("<III", stub, pos)
        pos += 12
        s = stub[pos:pos + 2 * actual].decode("utf-16-le", "replace").rstrip("\0")
        pos += 2 * actual
        pos += -pos % 4
        return s

    level, _switch, cont_ptr = u32(), u32(), u32()
    if level != 1 or not cont_ptr:
        return []
    count, buf_ptr = u32(), u32()
    if not buf_ptr or not count:
        return []
    if u32() != count:
        raise SmbFailed(tr("Antwort mit den Freigaben ist beschädigt"))
    heads = [(u32(), u32(), u32()) for _ in range(count)]
    out = []
    for name_ptr, typ, remark_ptr in heads:
        name = wstr() if name_ptr else ""
        remark = wstr() if remark_ptr else ""
        out.append((name, typ, remark))
    return out


class Smb2:
    """one server: connection + session (smbprotocol, low level), tree connects per share"""

    def __init__(self, host, user="", pw="", timeout=10):
        from smbprotocol.connection import Connection
        from smbprotocol.exceptions import SMBException
        from smbprotocol.session import Session
        self.host = host
        self.trees = {}
        self.conn = Connection(uuid.uuid4(), host, 445)
        try:
            self.conn.connect(timeout=timeout)
        except OSError as e:
            raise SmbFailed(tr("SMB-Server %s nicht erreichbar (%s)") % (host, e))
        except (SMBException, ValueError, struct.error) as e:
            raise SmbFailed(tr("SMB-Server %s spricht kein SMB 2/3 (%s)") % (host, e), smb1=True)
        try:
            self.session = Session(self.conn, user or "guest", pw or "", require_encryption=False)
            self.session.connect()
        except Exception as e:
            self.close()
            msg = str(e)
            if any(k in msg.lower() for k in ("logon_failure", "logonfailure", "0xc000006d", "0xc000006e",
                                              "account_restriction", "access_denied")):
                raise SmbFailed(tr("SMB-Anmeldung abgelehnt (Benutzer/Passwort)"), login=True)
            raise SmbFailed(tr("SMB-Anmeldung fehlgeschlagen (%s)") % msg.splitlines()[0][:120])

    def close(self):
        try:
            self.conn.disconnect(True)
        except Exception:
            pass

    def tree(self, share):
        from smbprotocol.tree import TreeConnect
        t = self.trees.get(share)
        if t is None:
            t = TreeConnect(self.session, "\\\\%s\\%s" % (self.host, share))
            t.connect()
            self.trees[share] = t
        return t

    def _open(self, share, path, directory):
        from smbprotocol.open import (CreateDisposition, CreateOptions, DirectoryAccessMask, FileAttributes,
                                      FilePipePrinterAccessMask, ImpersonationLevel, Open, ShareAccess)
        o = Open(self.tree(share), path.strip("\\/").replace("/", "\\"))
        if directory:
            access, opts = DirectoryAccessMask.FILE_LIST_DIRECTORY | DirectoryAccessMask.FILE_READ_ATTRIBUTES, \
                CreateOptions.FILE_DIRECTORY_FILE
        else:
            access, opts = FilePipePrinterAccessMask.GENERIC_READ, CreateOptions.FILE_NON_DIRECTORY_FILE
        o.create(ImpersonationLevel.Impersonation, access, FileAttributes.FILE_ATTRIBUTE_NORMAL,
                 ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE, CreateDisposition.FILE_OPEN, opts)
        return o

    def listdir(self, share, path):
        """-> [(name, is_dir, size)]"""
        from smbprotocol.exceptions import NoMoreFiles
        from smbprotocol.file_info import FileInformationClass
        from smbprotocol.open import QueryDirectoryFlags
        d = self._open(share, path, True)
        out = []
        try:
            first = True
            while True:
                try:
                    flags = QueryDirectoryFlags.SMB2_RESTART_SCANS if first else 0
                    entries = d.query_directory("*", FileInformationClass.FILE_ID_FULL_DIRECTORY_INFORMATION,
                                                flags=flags)
                except NoMoreFiles:
                    break
                first = False
                if not entries:
                    break
                for e in entries:
                    name = e["file_name"].get_value().decode("utf-16-le")
                    if name in (".", ".."):
                        continue
                    is_dir = bool(e["file_attributes"].get_value() & 0x10)
                    out.append((name, is_dir, 0 if is_dir else e["end_of_file"].get_value()))
        finally:
            d.close()
        return out

    def read(self, share, path, limit):
        f = self._open(share, path, False)
        try:
            size = f.end_of_file
            if size > limit:
                return None
            data, pos = b"", 0
            step = min(self.conn.max_read_size, 1 << 20)
            while pos < size:
                chunk = f.read(pos, min(step, size - pos))
                if not chunk:
                    break
                data += chunk
                pos += len(chunk)
            return data
        finally:
            f.close()

    def head(self, share, path, n):
        f = self._open(share, path, False)
        try:
            return f.read(0, min(n, f.end_of_file)) if f.end_of_file else b""
        finally:
            f.close()

    def shares(self):
        """[(name, type, comment)] through \\PIPE\\srvsvc"""
        from smbprotocol.open import (CreateDisposition, CreateOptions, FilePipePrinterAccessMask, ImpersonationLevel,
                                      Open, ShareAccess)
        pipe = Open(self.tree("IPC$"), "srvsvc")
        pipe.create(ImpersonationLevel.Impersonation,
                    FilePipePrinterAccessMask.GENERIC_READ | FilePipePrinterAccessMask.GENERIC_WRITE, 0,
                    ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE | ShareAccess.FILE_SHARE_DELETE,
                    CreateDisposition.FILE_OPEN, CreateOptions.FILE_NON_DIRECTORY_FILE)
        try:
            pipe.write(bind_pdu(), 0)
            ack = pipe.read(0, FRAG)
            if len(ack) < 3 or ack[2] != 12:                                    # bind_ack
                raise SmbFailed(tr("Server lehnt die Abfrage der Freigaben ab"))
            pipe.write(share_enum_pdu(self.host), 0)
            data, last = b"", False
            for _ in range(200):
                data += pipe.read(0, FRAG)
                stub, last = split_fragments(data)
                if last:
                    return parse_share_enum(stub)
            raise SmbFailed(tr("Antwort mit den Freigaben unvollständig"))
        finally:
            pipe.close()
