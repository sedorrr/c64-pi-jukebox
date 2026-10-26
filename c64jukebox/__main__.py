"""python3 -m c64jukebox --data /var/lib/c64jukebox --port 80"""
import argparse
import logging

from aiohttp import web

from .core import Jukebox
from .web import make_app


def main():
    ap = argparse.ArgumentParser(description="C64 SID jukebox for the Ultimates (web page on the given port)")
    ap.add_argument("--data", default="data", help="folder for settings, play lists and cache")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--no-local-admin", action="store_true",
                    help="require the web password also for requests from this computer (127.0.0.1)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    jb = Jukebox(a.data)
    app = make_app(jb, trust_local=not a.no_local_admin)

    async def up(app):
        await jb.start()

    async def down(app):
        await jb.close()
    app.on_startup.append(up)
    app.on_cleanup.append(down)
    web.run_app(app, host=a.host, port=a.port, access_log=None, print=lambda *x: None)


if __name__ == "__main__":
    main()
