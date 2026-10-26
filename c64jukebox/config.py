"""Settings in one JSON file in the data folder (written atomically, readable only by the service user)."""
import copy
import hashlib
import hmac
import json
import os
import secrets

from .hdmi.modes import DEFAULTS as HDMI_DEFAULTS

DEFAULT_PASSWORD = "commodore64"      # the same first password as on the Picos; the page asks to change it
MASK = "••••"     # passwords leave the Pi only as this; saving it back keeps the old one

DEFAULTS = {
    "version": 1,
    "name": "c64pi",
    "web": {"pw_hash": "", "secret": ""},
    "ultimates": [{"label": "Ultimate", "addr": "", "pw": ""}],
    "u64_sel": 0,
    "sources": [
        {"id": "u64", "kind": "u64", "label": "USB-Stick am Ultimate", "path": "/"},
        {"id": "pi", "kind": "local", "label": "USB-Stick am Pi", "path": "/media/usb"},
    ],
    "picos": [],                      # {"addr", "pw", "np": "udp"|"http"|"off", "stream": bool}
    "stream": {"on": False},
    "pico_news": False,               # retro news headlines to the Picos (idle texts), nowplaying.Notifier.news
    "player": {"limit_min": 5, "silence": True, "silence_s": 5, "subsongs": "start", "repeat": True,
               "shuffle": False, "sidauto": True,      # sidauto: switch a SID socket if a tune needs it (sidaddr.py)
               "loopfind": "suggest",                  # repeat of a tune without a length: off | suggest | auto
               "hvsc_name": "suggest"},                # the same tune by name in the HVSC (namematch.py): same
    "songlengths": {"hvsc": "", "custom": "", "stil": ""},   # where the files were loaded from (for the page)
    "wlan": {"ap": True, "ap_ssid": "", "ap_pw": ""},   # own access point when there is no network (netwatch.py)
    # display.py / tft.py: auto (0.96" OLED), sh1106, tft (2.8" touch), off; flip = picture turned by 180 degrees,
    # cal = touch calibration (set by the three crosses)
    # touch: "own" = touch on the second SPI bus (one cable per pin), "shared" = with Y cables on the display's bus;
    # dc: GPIO of the display's D/C line, 24 (pin 18), 23 (pin 16) or 6 (pin 31)
    "display": {"type": "auto", "off_min": 10, "flip": False, "cal": None, "touch": "own", "dc": 24},
    "schedule": [],                   # timer entries (schedule.py): weekdays + time -> play a list / stop
    # party mode (netwatch.py): away from home an access point under the home WLAN's name (pw empty = the saved one),
    # the Ultimate on the cable gets 10.64.64.2 and the jukebox uses that address while it runs
    "party": {"on": False, "ssid": "", "pw": ""},
    "hdmi": dict(HDMI_DEFAULTS),                  # HDMI output (hdmi/, service c64pi-hdmi), see hdmi/modes.py
    # the TV's remote control over HDMI-CEC (cec.py); claim: announce the Pi as the active source when playing starts
    # (TVs send the remote's keys only to it - also behind a Fire TV Cube); tv_on: TV on + to the Pi when playing starts,
    # tv_off_min: TV to standby after so many minutes without playing (0 = never)
    "cec": {"on": False, "claim": True, "tv_on": False, "tv_off_min": 0},
}

SECRET_KEYS = ("pw", "ap_pw")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def hash_password(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"pbkdf2${salt}${h}"


def check_hash(pw, stored):
    try:
        _, salt, _h = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pw, salt), stored)


class Config:
    def __init__(self, data_dir):
        self.dir = data_dir
        self.path = os.path.join(data_dir, "config.json")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(os.path.join(data_dir, "playlists"), exist_ok=True)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except (OSError, ValueError):
            self.data = copy.deepcopy(DEFAULTS)
        if not self.data["web"]["secret"]:
            self.data["web"]["secret"] = secrets.token_hex(16)
            self.save()

    def __getitem__(self, k):
        return self.data[k]

    def save(self):
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ---- web password
    def password_ok(self, pw):
        stored = self.data["web"]["pw_hash"]
        if not stored:
            return hmac.compare_digest(pw.encode(), DEFAULT_PASSWORD.encode())
        return check_hash(pw, stored)

    def password_default(self):
        return not self.data["web"]["pw_hash"]

    def set_password(self, pw):
        self.data["web"]["pw_hash"] = hash_password(pw)
        self.data["web"]["secret"] = secrets.token_hex(16)     # logs out every other browser
        self.save()

    # ---- the Ultimates
    party_u64 = ""                     # set by the jukebox while the party mode runs: the Ultimate on the Pi's cable

    def ultimate(self, i=None):
        u = self.data["ultimates"]
        i = self.data["u64_sel"] if i is None else i
        u = u[i] if 0 <= i < len(u) else (u[0] if u else {"label": "", "addr": "", "pw": ""})
        return dict(u, addr=self.party_u64) if self.party_u64 else u

    def source(self, sid):
        for s in self.data["sources"]:
            if s.get("id") == sid:
                return s
        return None

    # ---- what the page sees: passwords masked
    def public(self):
        d = copy.deepcopy(self.data)
        d.pop("web", None)

        def mask(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in SECRET_KEYS and isinstance(v, str):
                        o[k] = MASK if v else ""
                    else:
                        mask(v)
            elif isinstance(o, list):
                for v in o:
                    mask(v)
        mask(d)
        return d


def unmask_list(new, old, key="pw", match=("addr", "id")):
    """A list from the page: entries whose password is MASK get the old one back (matched by id/addr, else index)."""
    for i, e in enumerate(new):
        if not isinstance(e, dict) or e.get(key) != MASK:
            continue
        prev = None
        for m in match:
            if e.get(m):
                prev = next((o for o in old if o.get(m) == e.get(m)), None)
                if prev:
                    break
        if prev is None and i < len(old):
            prev = old[i]
        e[key] = (prev or {}).get(key, "")
    return new
