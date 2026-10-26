"""python3 -m c64jukebox.hdmi --run /run/c64pi   (service c64pi-hdmi; system Python with python3-pygame/-numpy)"""
import argparse
import signal
import sys
import time

from .app import HdmiApp
from .screen import open_screen


def main():
    ap = argparse.ArgumentParser(description="HDMI output of the C64 jukebox: visualizer + C64 picture in 1080p")
    ap.add_argument("--run", default="/run/c64pi", help="exchange folder with the jukebox")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--soft", action="store_true", help="without the graphics chip (slow)")
    ap.add_argument("--windowed", action="store_true", help="in a window (for trying it out on a PC)")
    a = ap.parse_args()
    app = HdmiApp(a.run, lambda: open_screen(prefer_gpu=not a.soft, windowed=a.windowed), fps=a.fps)

    def bye(*_):
        app.stop()
        sys.exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    while True:
        time.sleep(app.tick())


if __name__ == "__main__":
    main()
