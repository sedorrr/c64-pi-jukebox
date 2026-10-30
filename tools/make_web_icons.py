"""Home-screen icons of the web page (iPhone/iPad "Zum Home-Bildschirm", Android) from the note of icon.svg:
    .venv/bin/python tools/make_web_icons.py c64jukebox/web"""
import sys
from playwright.sync_api import sync_playwright
out = sys.argv[1]
# full square (iOS rounds the corners itself, Android "maskable" crops a circle): note (x 6..40, y 12..52) scaled to 70 % and centred
svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="#352879"/>'
       '<g transform="translate(15.9 9.6) scale(0.7)"><path d="M40 12v28a8 8 0 1 1-4-6.9V18l-14 3v23a8 8 0 1 1-4-6.9V17z" fill="#9fe2ff"/></g></svg>')
with sync_playwright() as p:
    b = p.chromium.launch()
    for n, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        pg = b.new_page(viewport={"width": n, "height": n})
        pg.set_content('<html><body style="margin:0">' + svg.replace("<svg ", '<svg width="%d" height="%d" ' % (n, n)) + "</body></html>")
        pg.screenshot(path="%s/%s" % (out, name), omit_background=False)
    b.close()
