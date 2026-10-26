# Third-party notices – C64 Jukebox for the Raspberry Pi

This project is licensed under the GNU General Public License v3.0 (see `LICENSE`). It does **not** contain
copies of third-party code: the packages below are downloaded during installation (`install/install.sh` uses
`pip` for `requirements.txt` and `apt` for the Raspberry Pi OS packages) and keep their own licenses.

## Python packages (`requirements.txt`, installed with pip)

| Package | Used for | License |
|---|---|---|
| [aiohttp](https://github.com/aio-libs/aiohttp) | web server, REST client for the Ultimates and the Picos | Apache-2.0 (parts MIT) |
| [smbprotocol](https://github.com/jborean93/smbprotocol) | SMB shares (SMB 2/3) | MIT |
| [pysmb](https://github.com/miketeo/pysmb) | old devices with SMB 1, NetBIOS names | zlib/libpng |
| [Pillow](https://python-pillow.org/) | pictures for the small OLED and the touch display | MIT-CMU (HPND) |

Their own dependencies (e.g. yarl, multidict, frozenlist, cryptography, pyspnego, pyasn1) are under
Apache-2.0, BSD or MIT licenses.

## Raspberry Pi OS packages (installed with apt)

| Package | Used for | License |
|---|---|---|
| python3-pygame | picture on the TV (HDMI) | LGPL-2.1 |
| python3-numpy | spectrum analyser on the TV | BSD-3-Clause |
| fonts-dejavu-core | text on the TV and the displays | Bitstream Vera / DejaVu license (free) |
| avahi-daemon, libnss-mdns, dnsmasq-base | `c64pi.local`, own access point | LGPL-2.1 / GPL-2.0 |

## Only for development on the PC (`requirements-dev.txt`, not installed on the Pi)

| Package | License |
|---|---|
| pytest | MIT |
| Playwright | Apache-2.0 |

`tools/sidlen/sidrender.cpp` (song-length search on the PC) links against
[libsidplayfp](https://github.com/libsidplayfp/libsidplayfp) (GPL-2.0-or-later); it is not part of the
jukebox on the Pi. Build it yourself as described at the top of the file.

## News feeds

The jukebox can show headlines of public RSS/Atom feeds of retro-computing news pages (list in
`c64jukebox/news.py`, each can be switched off on the web page). Only title, date, a short text and a small
picture are shown, with the name of the source; the content belongs to the respective publishers.

## Trademarks

"Commodore", "C64", "SID" and "Ultimate 64" / "C64 Ultimate" are trademarks of their respective owners. This
project is not affiliated with or endorsed by them.
