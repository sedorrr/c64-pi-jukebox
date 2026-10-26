#!/bin/bash
# C64-Jukebox: install or update on Raspberry Pi OS Lite (64 bit, Bookworm or Trixie). From the project folder on the Pi:
#   sudo ./install/install.sh                    host name becomes c64pi -> http://c64pi.local/
#   sudo ./install/install.sh --keep-hostname    keep the host name
#   sudo ./install/install.sh --name=wohnzimmer  another host name
# Settings, lists and song lengths in /var/lib/c64jukebox stay as they are.
set -euo pipefail

APP=/opt/c64jukebox
DATA=/var/lib/c64jukebox
SVC=c64jukebox
HOST=c64pi
KEEP=0
for a in "$@"; do
    case "$a" in
        --keep-hostname) KEEP=1 ;;
        --name=*) HOST="${a#*=}" ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $a"; exit 1 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo starten: sudo $0 $*"; exit 1; }
SRC=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$SRC/c64jukebox/__main__.py" ] || { echo "Projektordner nicht gefunden ($SRC)"; exit 1; }

echo "== Pakete (Python, mDNS)"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv avahi-daemon libnss-mdns \
    dnsmasq-base fonts-dejavu-core python3-pygame python3-numpy libegl1 libegl-mesa0 libgles2 >/dev/null
# (EGL/GLES from Mesa: SDL draws through them on KMS/DRM - Raspberry Pi OS Lite comes without)
# I2C for the small OLED, SPI for the 2.8" touch display (both take effect completely after the next restart)
if command -v raspi-config >/dev/null; then
    raspi-config nonint do_i2c 0 || true
    raspi-config nonint do_spi 0 || true
fi

echo "== Benutzer $SVC"
id "$SVC" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin "$SVC"
for g in i2c spi gpio video render audio; do
    getent group "$g" >/dev/null || groupadd --system "$g"
    usermod -aG "$g" "$SVC"
done

echo "== Programm nach $APP"
systemctl stop "$SVC" 2>/dev/null || true
mkdir -p "$APP" "$DATA" /media/usb
rm -rf "$APP/c64jukebox" "$APP/docs"
cp -r "$SRC/c64jukebox" "$SRC/docs" "$SRC/requirements.txt" "$APP/"
find "$APP/c64jukebox" -name __pycache__ -prune -exec rm -rf {} +
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"
chown -R root:root "$APP"
chown -R "$SVC:$SVC" "$DATA"
chmod 700 "$DATA"

echo "== Dienst und USB-Sticks"
install -m 644 "$SRC/install/c64jukebox.service" /etc/systemd/system/c64jukebox.service
install -m 644 "$SRC/install/c64pi-net.service" /etc/systemd/system/c64pi-net.service
install -m 644 "$SRC/install/c64pi-hdmi.service" /etc/systemd/system/c64pi-hdmi.service
install -m 644 "$SRC/install/99-c64jukebox-usb.rules" /etc/udev/rules.d/99-c64jukebox-usb.rules
udevadm control --reload-rules

# HDMI always 1920 x 1080 at 60 Hz (also on a 4K TV) - takes effect after the next restart
CMDLINE=/boot/firmware/cmdline.txt
[ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
if [ -f "$CMDLINE" ] && ! grep -q "video=HDMI-A-1:" "$CMDLINE"; then
    echo "== HDMI-Ausgang: 1920 x 1080 (nach dem nächsten Neustart)"
    sed -i '1 s/$/ video=HDMI-A-1:1920x1080@60/' "$CMDLINE"
fi

# the touch of the 2.8" display on its own SPI bus (no Y cables): SPI1, its CE0 on GPIO16 (GPIO18 is the backlight)
CONFIG=/boot/firmware/config.txt
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt
if [ -f "$CONFIG" ] && ! grep -q "^dtoverlay=spi1-1cs" "$CONFIG"; then
    echo "== Zweiter SPI-Bus für den Touch (nach dem nächsten Neustart)"
    printf '\n[all]\n# C64-Jukebox: touch of the 2.8" display\ndtoverlay=spi1-1cs,cs0_pin=16\n' >> "$CONFIG"
fi

if [ "$KEEP" = 0 ] && [ "$(hostname)" != "$HOST" ]; then
    echo "== Rechnername $HOST"
    hostnamectl set-hostname "$HOST"
    if grep -q '^127\.0\.1\.1' /etc/hosts; then
        sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOST/" /etc/hosts
    else
        printf '127.0.1.1\t%s\n' "$HOST" >> /etc/hosts
    fi
    systemctl restart avahi-daemon
fi

systemctl daemon-reload
systemctl enable --quiet c64pi-net "$SVC" c64pi-hdmi
systemctl restart c64pi-net
systemctl restart "$SVC"
systemctl restart c64pi-hdmi
for i in $(seq 1 30); do                    # up to a minute: loading the HVSC song lengths takes a while on a Pi 3B
    sleep 1
    if "$APP/venv/bin/python" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1/', timeout=2)" 2>/dev/null; then
        echo
        echo "Fertig: http://$(hostname).local/  (erstes Passwort: commodore64)"
        exit 0
    fi
done
echo "Der Dienst antwortet nicht - Protokoll:"
journalctl -u "$SVC" -n 30 --no-pager
exit 1
