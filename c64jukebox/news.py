"""Retro news for the TV (HDMI service): RSS 2.0 and Atom feeds of news pages, fetched every 30 minutes by the
jukebox, newest first, each with source, date, title, a short text and - where the feed has one - a picture (made
small here, so the Pi 3B only has to show it). The text of the feeds is shown, never followed or run."""
import asyncio
import hashlib
import html
import io
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import aiohttp

# the known news pages (checked 2026-10-20) - "on": shown unless the user chose otherwise on the page
DEFAULT_FEEDS = [
    {"label": "Indie Retro News", "url": "https://www.indieretronews.com/feeds/posts/default?alt=rss", "on": True},
    {"label": "amiga-news.de", "url": "https://www.amiga-news.de/de/backends/news/rss20.xml", "on": True},
    {"label": "Commodore News", "url": "https://commodore-news.com/rss/rss-de.xml", "on": True},
    {"label": "Cascade64", "url": "https://www.cascade64.de/csc.rss", "on": True},
    {"label": "The Oasis BBS", "url": "https://theoasisbbs.com/feed/", "on": True},
    {"label": "BrewOtaku", "url": "https://www.brewotaku.com/feed/", "on": False},
    {"label": "PDRoms", "url": "https://pdroms.de/feed", "on": False},       # its C64-only feed is empty
]
REFRESH_S = 1800
PER_FEED = 15
KEEP = 40
FEED_BYTES = 4 << 20
IMAGE_BYTES = 4 << 20
IMAGE_SIZE = (640, 400)
UA = "Mozilla/5.0 (compatible; C64-Jukebox/1.0)"       # some pages refuse anything that looks like a script
NS = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/",
      "content": "http://purl.org/rss/1.0/modules/content/"}


def text_of(markup, limit=320):
    """HTML of a feed -> plain text, shortened at a word"""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup or "", flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>", " ", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",.;:-") + " …"
    return t


def first_img(markup):
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)", markup or "", flags=re.I)
    return html.unescape(m.group(1)) if m else ""


def parse_date(s):
    if not s:
        return 0.0
    s = s.strip()
    try:
        return parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return 0.0


def _t(el, path):
    x = el.find(path, NS)
    return (x.text or "").strip() if x is not None and x.text else ""


def parse(data, label):
    """RSS 2.0 or Atom (bytes) -> [{"src", "title", "summary", "t", "link", "img"}], undated entries left out"""
    # control characters are not allowed in XML (one in a WordPress feed broke it): out with them
    data = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", data)
    root = ET.fromstring(data)
    out = []
    if root.tag.endswith("feed"):                                  # Atom
        for e in root.findall("atom:entry", NS):
            link = next((li.get("href", "") for li in e.findall("atom:link", NS)
                         if li.get("rel", "alternate") == "alternate"), "")
            content = _t(e, "atom:content") or _t(e, "atom:summary")
            thumb = e.find("media:thumbnail", NS)
            out.append({"title": html.unescape(_t(e, "atom:title")), "summary": text_of(content),
                        "t": parse_date(_t(e, "atom:published") or _t(e, "atom:updated")), "link": link,
                        "img": (thumb.get("url") if thumb is not None else "") or first_img(content)})
    else:                                                          # RSS 2.0
        for it in root.iter("item"):
            desc = _t(it, "content:encoded") or _t(it, "description") or _t(it, "atom:summary")
            img = ""
            thumb = it.find("media:thumbnail", NS)
            if thumb is not None:
                img = thumb.get("url", "")
            enc = it.find("enclosure")
            if not img and enc is not None and (enc.get("type") or "").startswith("image/"):
                img = enc.get("url", "")
            out.append({"title": html.unescape(_t(it, "title")), "summary": text_of(desc),
                        "t": parse_date(_t(it, "pubDate") or _t(it, "atom:updated")), "link": _t(it, "link"),
                        "img": img or first_img(desc)})
    out = [dict(x, src=label) for x in out if x["title"] and x["t"]]
    out.sort(key=lambda x: -x["t"])
    return out[:PER_FEED]


def interleave(per_feed):
    """the sources in turn: round k holds the k-th newest of every source (newest first within the round) - recent
    news stay in front, and one source with many news on one day does not fill the screen in a row"""
    out = []
    for k in range(max([len(x) for x in per_feed] + [0])):
        out += sorted((x[k] for x in per_feed if k < len(x)), key=lambda it: -it["t"])
    return out


def bigger_blogger(url):
    """Blogger's thumbnails are 72 px ("s72-..."): ask for 640 px wide instead"""
    return re.sub(r"/s72-([^/]*)/", "/w640/", url) if "googleusercontent.com" in url else url


class News:
    def __init__(self, img_dir, clock=time.monotonic):
        self.img_dir = img_dir
        self.clock = clock
        self.items = []
        self.state = {}               # url -> {"n": items, "err": text, "t": time}
        self.at = -1e9
        self.task = None

    def due(self):
        return self.clock() - self.at >= REFRESH_S and not (self.task and not self.task.done())

    def start(self, session, feeds):
        self.at = self.clock()
        self.task = asyncio.get_running_loop().create_task(self.refresh(session, feeds))
        return self.task

    async def _get(self, session, url, limit):
        async with session.get(url, headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status >= 300:
                raise ValueError("Fehler %d" % r.status)
            data = bytearray()
            async for chunk in r.content.iter_chunked(1 << 16):     # read() alone gives only what has arrived
                data += chunk
                if len(data) > limit:
                    raise ValueError("zu groß")
            return bytes(data)

    async def refresh(self, session, feeds):
        per_feed = []
        for f in feeds:
            url, label = f.get("url", ""), f.get("label") or f.get("url", "")
            try:
                got = parse(await self._get(session, url, FEED_BYTES), label)
                per_feed.append(got)
                self.state[url] = {"label": label, "n": len(got), "err": "", "t": time.time()}
            except (aiohttp.ClientError, asyncio.TimeoutError, ET.ParseError, ValueError, OSError) as e:
                err = str(e) or type(e).__name__
                if isinstance(e, aiohttp.ClientConnectorError):           # its text holds the whole SSL error
                    err = "keine Verbindung zu %s" % e.host + (" (Zertifikat)" if "CERTIFICATE" in err else "")
                self.state[url] = {"label": label, "n": 0, "err": err[:160], "t": time.time()}
        items = interleave(per_feed)[:KEEP]
        os.makedirs(self.img_dir, exist_ok=True)
        keep = set()
        for it in items:
            it["pic"] = ""
            if not it["img"].startswith(("http://", "https://")):
                continue
            name = hashlib.sha1(it["img"].encode()).hexdigest()[:16] + ".jpg"
            path = os.path.join(self.img_dir, name)
            if not os.path.exists(path):
                try:
                    data = await self._get(session, bigger_blogger(it["img"]), IMAGE_BYTES)
                    await asyncio.get_running_loop().run_in_executor(None, small_picture, data, path)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
                    continue
            it["pic"] = path
            keep.add(name)
        for n in os.listdir(self.img_dir):
            if n not in keep:
                try:
                    os.remove(os.path.join(self.img_dir, n))
                except OSError:
                    pass
        if items or not self.items:
            self.items = items
        return len(items)

    def for_screen(self):
        """what the HDMI service gets: no links, dates as text"""
        return [{"src": x["src"], "title": x["title"][:200], "summary": x["summary"], "pic": x.get("pic", ""),
                 "date": time.strftime("%d.%m.%Y", time.localtime(x["t"]))} for x in self.items]


def small_picture(data, path):
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(data))
        img.draft("RGB", (IMAGE_SIZE[0] * 2, IMAGE_SIZE[1] * 2))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        raise ValueError("kein Bild")
    img.thumbnail(IMAGE_SIZE)
    img.save(path + ".tmp", "JPEG", quality=85)
    os.replace(path + ".tmp", path)
