"""The styles and their German names - without pygame, so the jukebox (web page, settings) can use them too."""

MODES = {
    "none": "Nur Hintergrund (z. B. nur das C64-Bild)",
    "bars": "Balken",
    "net": "Netz",
    "cloud": "Wolke",
    "oscilloscope": "Oszilloskop",
    "radial": "Strahlen",
    "rain": "Regen / Matrix",
    "c64": "C64 Retro",
    "kaleidoscope": "Kaleidoskop",
    "vu": "Stereo-VU-Meter",
    "waveform_history": "Wellenverlauf",
    "vinyl": "Schallplatte",
    "sid3voice": "3-Stimmen-SID",
    "sidvoices": "SID-Stimmen (Noten, vom Ultimate)",
    "neon_grid": "Neon-Gitter",
    "cyberpunk": "Night City Glitch",
    "shadowrun": "Cyberdeck-Matrix",
    "milkdrop": "Milkdrop",
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
