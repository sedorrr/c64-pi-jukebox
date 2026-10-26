"""HDMI output of the jukebox (service c64pi-hdmi): the visualizer styles of the PC jukebox (Ultimate64 SID Player,
"Spectrum Analyzer") in 1920 x 1080, over a background - a slide show of pictures or the live picture of the C64
(the Ultimate's video stream). Runs as its own process with the system's Python (python3-pygame, python3-numpy), so
neither the stream distributor nor the web page wait for it; it must not import aiohttp & co.

Exchange with the jukebox through files in /run/c64pi: hdmi-in.json (settings + what plays, written by the jukebox
every second), hdmi.json (state of this service). Audio comes from the jukebox's stream distributor (a copy of every
packet to 127.0.0.1:11002), video straight from the Ultimate (UDP 11000, requested by the jukebox)."""
