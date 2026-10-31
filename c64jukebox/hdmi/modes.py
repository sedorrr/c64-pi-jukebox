"""The styles and their German names - without pygame, so the jukebox (web page, settings) can use them too. The
names are marked with tr() for tools/i18n_check.py (at import the language is still German, so they stay German here);
where a name is shown it goes through tr(name) again."""
from ..i18n import tr

MODES = {
    "none": tr("Nur Hintergrund (z. B. nur das C64-Bild)"),
    "bars": tr("Balken"),
    "net": tr("Netz"),
    "cloud": tr("Wolke"),
    "oscilloscope": tr("Oszilloskop"),
    "radial": tr("Strahlen"),
    "rain": tr("Regen / Matrix"),
    "c64": tr("C64 Retro"),
    "kaleidoscope": tr("Kaleidoskop"),
    "vu": tr("Stereo-VU-Meter"),
    "waveform_history": tr("Wellenverlauf"),
    "vinyl": tr("Schallplatte"),
    "sid3voice": tr("3-Stimmen-SID"),
    "sidvoices": tr("SID-Stimmen (Noten, vom Ultimate)"),
    "neon_grid": tr("Neon-Gitter"),
    "cyberpunk": tr("Night City Glitch"),
    "shadowrun": tr("Cyberdeck-Matrix"),
    "milkdrop": tr("Milkdrop"),
}
BACKGROUNDS = ("none", "images", "video")
DEFAULTS = {"on": False, "mode": "bars", "auto": False, "auto_s": 180, "auto_modes": [], "bg": "none",
            "img_s": 20, "shuffle": False, "opacity": 100, "osd": True, "osd_stil": True, "osd_big": True, "osd_big_s": 6, "osd_qr": True, "sound": False, "volume": 100,
            "fade": False, "fade_s": 2.0,
            "img_src": "", "img_path": "/", "img_sub": False,   # pictures from a source ("" = uploaded on the page)
            "idle_hide": True, "idle_s": 20,                    # effects fade out after N s without music
            "news_idle": False, "news_ticker": False, "news_s": 15, "news_feeds": []}   # [] = news.DEFAULT_FEEDS
SOUND_DEVICE = "default:CARD=vc4hdmi"          # the Pi's HDMI output (vc4-hdmi wants IEC958: "default" converts)
AUDIO_PORT, VIDEO_PORT = 11002, 11000
SID_PORT = 11003                               # the Ultimate's debug stream (SID voices)
SOUND_PORT = 11004                             # the TV sound's own process (soundproc.py): the stream once more
