#!/bin/bash
# C64-Jukebox: update from GitHub on request (page or TV menu -> systemctl start c64jukebox-update.service, allowed to
# the service by polkit). Downloads the published program, runs its install.sh (which restarts the services) and puts
# the old program back when that fails. Progress and result in /var/lib/c64jukebox/update.json for the jukebox.
# The whole script is read before it runs ({ ... }): install.sh replaces this file while it runs.
{
set -uo pipefail
URL=${C64JB_UPDATE_URL:-https://github.com/sedorrr/c64-pi-jukebox/archive/refs/heads/main.tar.gz}
APP=${C64JB_APP:-/opt/c64jukebox}
DATA=${C64JB_DATA:-/var/lib/c64jukebox}
SVC=c64jukebox
STATE=$DATA/update.json
LOG=$DATA/update.log
FROM=$(sed -n 's/^VERSION *= *"\(.*\)"/\1/p' "$APP/c64jukebox/__init__.py" 2>/dev/null)
VER=""

state() {                                   # state message -> update.json (the service reads it, may rewrite it)
    python3 - "$STATE" "$1" "$VER" "$FROM" "$2" <<'PY'
import json, os, sys, time
p, state, ver, frm, msg = sys.argv[1:]
with open(p + ".tmp", "w", encoding="utf-8") as f:
    json.dump({"state": state, "ver": ver, "from": frm, "msg": msg[-200:], "at": int(time.time())}, f)
os.replace(p + ".tmp", p)
PY
    chown "$SVC:$SVC" "$STATE" 2>/dev/null || true
}

WORK=$(mktemp -d /var/tmp/c64jukebox-update.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
exec >"$LOG" 2>&1
echo "== Update $(date '+%Y-%m-%d %H:%M:%S'), installiert: ${FROM:-?}"
state run "Lade das Programm von GitHub"

fail() {
    echo "FEHLER: $1"
    state fail "$1"
    exit 1
}

python3 - "$URL" "$WORK/src.tar.gz" <<'PY' || fail "GitHub nicht erreichbar"
import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=60) as r, open(sys.argv[2], "wb") as f:
    while True:
        b = r.read(1 << 16)
        if not b:
            break
        f.write(b)
PY
mkdir "$WORK/src"
tar -xzf "$WORK/src.tar.gz" -C "$WORK/src" --strip-components=1 || fail "Download unvollständig"
SRC=$WORK/src
[ -f "$SRC/c64jukebox/__main__.py" ] && [ -f "$SRC/install/install.sh" ] || fail "Download enthält das Programm nicht"
VER=$(sed -n 's/^VERSION *= *"\(.*\)"/\1/p' "$SRC/c64jukebox/__init__.py")
[ -n "$VER" ] || fail "Download ohne Versionsnummer"
echo "== Neue Version: $VER"
state run "Installiere Version $VER"

# the old program, to put back when install.sh fails half way (it stops the service and replaces these)
mkdir "$WORK/prev"
cp -a "$APP/c64jukebox" "$APP/docs" "$APP/requirements.txt" "$WORK/prev/" 2>/dev/null

if bash "$SRC/install/install.sh" --keep-hostname; then
    echo "== Fertig: Version $VER"
    state ok "Version $VER installiert"
    exit 0
fi
echo "== install.sh fehlgeschlagen - alter Stand zurück"
if [ -d "$WORK/prev/c64jukebox" ]; then
    rm -rf "$APP/c64jukebox" "$APP/docs"
    cp -a "$WORK/prev/." "$APP/"
fi
VER_FAILED=$VER
VER=$FROM                                   # what runs now
systemctl restart "$SVC" c64pi-hdmi || true
state fail "Installation von $VER_FAILED fehlgeschlagen, Version ${FROM:-?} läuft weiter (Protokoll: $LOG)"
exit 1
}
