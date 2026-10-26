""""Now playing" for the Pico visualizers and receivers: POST /jb/np with the Pico's web password (HTTP digest), or
without a password as UDP "C64NP1 <same query>" to the Pico's stream port 11001.

The Pico takes the UDP way only while its "use the audio stream" option is on and no other device is streaming to
it - so UDP fits Picos that get their stream from this Pi. Each Pico has its own queue: a switched-off Pico never
delays the others or the player.

The same two ways carry the retro news headlines for the Picos' idle texts: POST /news resp. "C64NEWS1\n<lines>"."""
import asyncio
import hashlib
import os
import re
import time
import unicodedata
from urllib.parse import quote

import aiohttp
from yarl import URL

NP_PORT = 11001
HEARTBEAT_S = 30
NEWS_MAGIC = b"C64NEWS1\n"
NEWS_EVERY_S = 900                # the Pico forgets news after 3 h (and on a restart): sent again every 15 min
NEWS_N, NEWS_W, NEWS_BYTES = 6, 88, 760   # headlines, characters each (a matrix text line holds ~100), all together
FOLD = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "„": '"', "“": '"', "”": '"',
        "‚": "'", "‘": "'", "’": "'", "´": "'", "`": "'", "–": "-", "—": "-", "…": "...", "«": '"', "»": '"',
        "{": "(", "}": ")", "[": "(", "]": ")", "\n": " ", "\t": " "}
MATRIX = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !.-:,?'\"/&()+#%")


def fold(text):
    """a headline in the characters of the Pico's matrix font: umlauts spelt out, accents dropped, the rest a space"""
    out = []
    for ch in str(text):
        ch = FOLD.get(ch, ch)
        if len(ch) == 1 and ch not in MATRIX:
            ch = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()[:1]
            ch = ch if ch in MATRIX else " "
        out.append(ch)
    return re.sub(r" +", " ", "".join(out)).strip()


def news_body(items, n=NEWS_N, width=NEWS_W, limit=NEWS_BYTES):
    """the newest headlines as "<source>: <title>" lines, each cut at a word to `width`, together at most `limit` bytes"""
    lines, size = [], 0
    for it in items:
        if len(lines) >= n:
            break
        t = fold("%s: %s" % (it.get("src", ""), it.get("title", "")) if it.get("src") else it.get("title", ""))
        if len(t) > width:
            t = t[:width - 3].rsplit(" ", 1)[0].rstrip(" ,:-") + "..."
        if not t or size + len(t) + 1 > limit:
            continue
        lines.append(t)
        size += len(t) + 1
    return "\n".join(lines).encode("ascii")


def np_query(params):
    """the Pico cuts the request path at ~400 characters: "new" first, title/author at most 32 characters"""
    order = ("new", "stop", "title", "author", "secs", "el", "song", "songs", "sid")
    return "&".join("%s=%s" % (k, quote(str(params[k]), safe=",")) for k in order if k in params)


def np_params(info, secs, el=0, new=False):
    p = {"new": 1} if new else {}
    p.update({
        "title": (info.get("title") or info.get("name") or "")[:32],
        "author": (info.get("author") or "")[:32],
        "secs": int(secs) if secs and secs > 0 else 0,
        "el": max(0, int(el)),
        "song": int(info.get("song") or 1),
        "songs": int(info.get("songs") or 1),
        "sid": ",".join(info.get("sids") or ["D400"]),
    })
    return p


def _md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class Digest:
    """client side of HTTP digest (qop=auth, MD5) - the Picos' login; user name is free"""

    def __init__(self, user, pw):
        self.user, self.pw = user, pw
        self.ch = None
        self.nc = 0

    def take(self, header):
        ch = dict(re.findall(r'(\w+)="?([^",]*)"?', header or ""))
        if "nonce" not in ch:
            return False
        self.ch, self.nc = ch, 0
        return True

    def header(self, method, uri):
        if not self.ch:
            return None
        self.nc += 1
        nc = "%08x" % self.nc
        cnonce = os.urandom(8).hex()
        realm, nonce = self.ch.get("realm", ""), self.ch["nonce"]
        ha1 = _md5("%s:%s:%s" % (self.user, realm, self.pw))
        ha2 = _md5("%s:%s" % (method, uri))
        resp = _md5("%s:%s:%s:%s:%s:%s" % (ha1, nonce, nc, cnonce, "auth", ha2))
        h = ('Digest username="%s", realm="%s", nonce="%s", uri="%s", algorithm=MD5, qop=auth, nc=%s, '
             'cnonce="%s", response="%s"' % (self.user, realm, nonce, uri, nc, cnonce, resp))
        if "opaque" in self.ch:
            h += ', opaque="%s"' % self.ch["opaque"]
        return h


def host_port(addr):
    a = addr.strip()
    for p in ("http://", "https://"):
        if a.lower().startswith(p):
            a = a[len(p):]
    a = a.split("/", 1)[0]
    if a.count(":") == 1:
        h, port = a.split(":")
        return h, int(port)
    return a, 80


class PicoLink:
    def __init__(self, notifier, addr):
        self.n = notifier
        self.addr = addr
        self.q = asyncio.Queue(maxsize=16)
        self.task = None
        self.digest = None
        self.status = ""          # "ok", "auth", "error ..." for the page

    def start(self):
        if self.task is None:
            self.task = asyncio.get_running_loop().create_task(self.run())

    def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None

    async def run(self):
        while True:
            mode, pw, params = await self.q.get()
            try:
                if isinstance(params, bytes):                   # retro news
                    if mode == "udp":
                        await self.send_udp_raw(NEWS_MAGIC + params)
                    else:
                        await self.send_http(pw, None, uri="/news", body=params)
                elif mode == "udp":
                    await self.send_udp(params)
                else:
                    await self.send_http(pw, params)
            except asyncio.CancelledError:
                raise
            except Exception as e:                      # never let one Pico end its sender
                self.status = "Fehler: %s" % type(e).__name__

    async def send_udp(self, params):
        await self.send_udp_raw(b"C64NP1 " + np_query(params).encode())

    async def send_udp_raw(self, data):
        host, _port = host_port(self.addr)
        ip = await self.n.resolve(host)
        if not ip:
            self.status = "Name nicht gefunden"
            return
        self.n.send_udp(data[:767], (ip, self.n.udp_port))
        self.status = "ok (UDP)"

    async def send_http(self, pw, params, uri=None, body=None):
        host, port = host_port(self.addr)
        uri = uri or "/jb/np?" + np_query(params)
        if self.digest is None or self.digest.pw != pw:
            self.digest = Digest("c64pi", pw)
        url = "http://%s:%d%s" % (host, port, uri)
        for _ in range(8):
            h = self.digest.header("POST", uri)
            headers = {"Authorization": h} if h else {}
            async with self.n.session.post(URL(url, encoded=True), headers=headers, data=body,
                                           timeout=aiohttp.ClientTimeout(total=4)) as r:
                await r.read()
                if r.status == 401:
                    www = r.headers.get("WWW-Authenticate", "")
                    refused = h and "stale=true" not in www.lower()
                    if not self.digest.take(www):
                        self.status = "keine Anmeldung möglich"
                        return
                    if refused:                       # our answer was wrong, not just an old nonce
                        self.status = "Passwort falsch"
                        return
                    continue
                if r.status == 409:                   # the previous message not taken over yet
                    await asyncio.sleep(0.15)
                    continue
                self.status = "ok" if r.status == 200 else "Fehler %d" % r.status
                return
        self.status = "keine Antwort"


class Notifier:
    """sends the current tune to every Pico whose "np" is not "off"; resends the clock every 30 s"""

    def __init__(self, config, session, udp_send, resolve):
        self.config, self.session = config, session
        self.send_udp, self.resolve = udp_send, resolve
        self.udp_port = NP_PORT
        self.links = {}
        self.cur = None           # (info, secs)
        self.el_fn = None
        self.next_beat = 0.0
        self.news_body = b""      # the headlines sent last (b"" = none)
        self.news_next = 0.0

    def _targets(self):
        out = []
        for p in self.config["picos"]:
            mode = p.get("np", "udp")
            if p.get("addr") and mode in ("udp", "http"):
                out.append((p["addr"], mode, p.get("pw", "")))
        return out

    def _send(self, params):
        for addr, mode, pw in self._targets():
            link = self.links.get(addr)
            if link is None:
                link = self.links[addr] = PicoLink(self, addr)
            link.start()
            try:
                link.q.put_nowait((mode, pw, params if isinstance(params, bytes) else dict(params)))
            except asyncio.QueueFull:
                link.status = "antwortet nicht"

    def playing(self, info, secs, el_fn):
        self.cur, self.el_fn = (info, secs), el_fn
        self._send(np_params(info, secs, el_fn(), new=True))
        self.next_beat = time.monotonic() + HEARTBEAT_S

    def stopped(self):
        if self.cur is not None:
            self.cur = None
            self._send({"stop": 1})

    def tick(self):
        if self.cur and time.monotonic() >= self.next_beat:
            self.next_beat = time.monotonic() + HEARTBEAT_S
            info, secs = self.cur
            self._send(np_params(info, secs, self.el_fn()))

    def news(self, body):
        """the retro news for the Picos: sent when they change, again every 15 min; b"" clears them once"""
        now = time.monotonic()
        if body == self.news_body and (not body or now < self.news_next):
            return
        self.news_body, self.news_next = body, now + NEWS_EVERY_S
        self._send(body)

    def status(self):
        return {a: l.status for a, l in self.links.items()}

    def close(self):
        for l in self.links.values():
            l.stop()
