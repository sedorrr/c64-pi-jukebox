#!/bin/bash
# From the Mac/PC: copy the project to the Pi and run the installer there (asks for the Pi's sudo password).
#   ./install/deploy.sh pi@c64pi.local [installer options, e.g. --keep-hostname]
set -euo pipefail
[ $# -ge 1 ] || { echo "Aufruf: $0 benutzer@rechner [Optionen für install.sh]"; exit 1; }
TARGET=$1; shift
SRC=$(cd "$(dirname "$0")/.." && pwd)
echo "== Kopiere nach $TARGET:c64jukebox-src"
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -C "$SRC" --exclude .venv --exclude .git --exclude __pycache__ --exclude '*.png' --exclude .pytest_cache \
    -czf - c64jukebox docs install requirements.txt | ssh "$TARGET" 'rm -rf c64jukebox-src && mkdir c64jukebox-src && tar -xzf - -C c64jukebox-src'
echo "== Installiere"
ssh -t "$TARGET" "sudo ./c64jukebox-src/install/install.sh $*"
