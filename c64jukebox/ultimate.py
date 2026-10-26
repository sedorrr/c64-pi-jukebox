"""REST client for the Ultimate 64 / Ultimate II+ / C64 Ultimate (network password as header X-Password)."""
import asyncio
import json
from urllib.parse import quote

import aiohttp
from yarl import URL

STREAM_PORT = 11001


def error_text(status, body):
    """the Ultimate's answer to a failed request, for the page. "Network Host Resolve Error" for every stream target
    is a state the Elite II (firmware 3.15a) gets stuck in: only switching it off and on helps (2026-10-20/22)"""
    try:
        errs = [str(e) for e in json.loads(body.decode("utf-8", "replace")).get("errors") or []]
    except (ValueError, AttributeError):
        errs = []
    if any("Resolve" in e for e in errs):
        return "Ultimate hängt (\u201eNetwork Host Resolve Error\u201c) – Ultimate einmal aus- und wieder einschalten"
    return "Ultimate antwortet mit Fehler %d" % status + (" (%s)" % "; ".join(errs)[:120] if errs else "")


class UltimateError(Exception):
    """message for the page (German)"""


def base_url(addr):
    a = (addr or "").strip().rstrip("/")
    if not a:
        raise UltimateError("Kein Ultimate eingetragen")
    return a if "://" in a else "http://" + a


class Ultimate:
    def __init__(self, session, addr, pw=""):
        self.session, self.addr, self.pw = session, addr, pw

    async def request(self, method, path, query=None, data=None, timeout=10, want_json=False):
        q = "&".join("%s=%s" % (k, quote(str(v), safe="/:$")) for k, v in (query or {}).items() if v is not None)
        url = URL(base_url(self.addr) + path + ("?" + q if q else ""), encoded=True)
        headers = {"X-Password": self.pw} if self.pw else {}
        try:
            async with self.session.request(method, url, data=data, headers=headers,
                                            timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                body = await r.read()
                if r.status == 403 or r.status == 401:
                    raise UltimateError("Ultimate lehnt ab: Netzwerk-Passwort falsch?")
                if r.status >= 300:
                    raise UltimateError(error_text(r.status, body))
                if want_json:
                    try:
                        return json.loads(body.decode("utf-8", "replace") or "{}")
                    except ValueError:
                        return {}
                return body
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            raise UltimateError("Ultimate %s nicht erreichbar (%s)" % (self.addr, type(e).__name__))

    async def play_path(self, path, song=None):
        """the file lies on the Ultimate (its USB stick or SD card)"""
        await self.request("PUT", "/v1/runners:sidplay", {"file": path, "songnr": song})

    async def play_data(self, name, data, song=None):
        """the file comes from the Pi: upload (multipart, field "file")"""
        form = aiohttp.FormData()
        form.add_field("file", data, filename=name or "tune.sid", content_type="application/octet-stream")
        await self.request("POST", "/v1/runners:sidplay", {"songnr": song}, data=form, timeout=30)

    async def machine(self, cmd):
        """reset, pause, resume"""
        await self.request("PUT", "/v1/machine:" + cmd)

    async def stream_start(self, ip, port=STREAM_PORT):
        await self.request("PUT", "/v1/streams/audio:start", {"ip": "%s:%d" % (ip, port)})

    async def stream_stop(self):
        await self.request("PUT", "/v1/streams/audio:stop")

    async def video_start(self, ip, port=11000):
        await self.request("PUT", "/v1/streams/video:start", {"ip": "%s:%d" % (ip, port)})

    async def video_stop(self):
        await self.request("PUT", "/v1/streams/video:stop")

    async def debug_start(self, ip, port=11003):
        """every bus cycle of the C64 (32 Mbit/s) - the SID voices on the TV"""
        await self.request("PUT", "/v1/streams/debug:start", {"ip": "%s:%d" % (ip, port)})

    async def debug_stop(self):
        await self.request("PUT", "/v1/streams/debug:stop")

    async def debug_mode(self):
        """"6510 Only", "VIC Only", ... ("" when the Ultimate does not say)"""
        d = await self.request("GET", "/v1/configs/Data%20Streams/Debug%20Stream%20Mode", timeout=6, want_json=True)
        v = ((d or {}).get("Data Streams") or {}).get("Debug Stream Mode")
        return str(v.get("current", "") if isinstance(v, dict) else v or "")

    async def info(self, timeout=3):
        return await self.request("GET", "/v1/info", timeout=timeout, want_json=True)
