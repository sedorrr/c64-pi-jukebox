# C64-Jukebox – Raspberry Pi 3B als SID-Jukebox und Stream-Verteiler

*English version: [README.md](README.md)*

**Bedienungsanleitung:** [docs/HANDBUCH.md](docs/HANDBUCH.md) – Installation, Quellen, Wiedergabe, Songlängen,
Stream-Verteiler, Sicherung, Fehlersuche. Dasselbe Handbuch steht im Tab **Hilfe** der Weboberfläche.
**Bedienung mit Bildern** (Weboberfläche und Fernseher): [docs/Bedienung_Pi-Jukebox.pdf](docs/Bedienung_Pi-Jukebox.pdf) –
englisch: [docs/Operation_Pi-Jukebox.pdf](docs/Operation_Pi-Jukebox.pdf)

Ein Raspberry Pi 3B spielt rund um die Uhr SID-Musik auf den **Ultimates** (Ultimate 64, C64 Ultimate, Ultimate II+)
und wird komplett über eine **Weboberfläche** gesteuert – am Handy wie am PC, unter **http://c64pi.local/**.

- **SID-Dateien von überall:** Netzwerkfreigabe (SMB: NAS, Windows, Mac, Linux – ohne Einhängen), FTP-Server,
  USB-Stick am Ultimate (dessen FTP-Dienst) oder Ordner/USB-Stick am Pi
- **Einfache Auswahl:** Quellen als Kacheln, Ordner durchklicken wie im Dateimanager, Filter, Suche in allen
  Unterordnern; zu jeder Datei Titel, Komponist, Jahr, Unterlieder, Spielzeit und „2 SIDs“; Freigaben und Server
  findet **„Im Netz suchen“**, Freigaben eines Servers listet **„Freigaben anzeigen“**
- **Abspielen per Fingertipp**, „Ordner abspielen“ samt Unterordnern, Zufall, Liste wiederholen, Unterlieder,
  Pause/Fortsetzen/Stopp
- **Songlängen** aus der HVSC-Datei `Songlengths.md5` (MD5 über die ganze Datei, je Unterlied) für den Wechsel genau am
  Titelende, eigene Längen mit Vorrang; sonst Zeitlimit oder Wechsel nach Stille; „Ende hier merken“ (Webseite und
  TV-Menü) macht die bisherige Spielzeit eines Titels ohne Länge zu seiner eigenen Länge; **Wiederholung erkennen:**
  bei Titeln ohne Länge findet die Jukebox im Stream selbst, wo das Stück von vorn anfängt, und schlägt die Länge vor;
  **Länge über den Namen:** eine andere Fassung derselben Datei (andere MD5) findet sie über Dateiname/Titel und
  Komponist in der HVSC; **`tools/find_lengths.py`** ermittelt am Mac die Längen ganzer Ordner vorab (Name,
  Abspielen mit libsidplayfp: Ende/Wiederholung) als `user_songlengths.txt`
- **Fernbedienung des Fernsehers (HDMI-CEC, optional):** Wiedergabe/Pause/Stopp/Weiter, Effekt und Unterlied mit der
  TV-Fernbedienung; auf Wunsch Fernseher an beim Abspielen und aus, wenn nichts mehr läuft – ohne Zusatzprogramm
- **Party-Modus:** unterwegs spannt der Pi ein WLAN unter dem Namen des Heim-WLANs auf (Picos und Handys verbinden sich
  von selbst), das Ultimate hängt per Kabel am Pi; zu Hause bleibt der Modus still
- **Listen zusammenstellen:** aus der ganzen HVSC (Pfade und Längen aus der Songlängen-Datei): Favoriten,
  Meistgespielt, Nie gespielt, Zufällige, Kurze, Mehr-SID-Stücke, eigene Auswahl nach Bereich, Komponist, Länge, STIL
- **Zeitplan:** an gewählten Wochentagen zur gewählten Uhrzeit eine Liste abspielen oder stoppen, auf Wunsch mit dem
  Fernseher (HDMI-CEC)
- **Zuletzt gespielt:** die letzten 100 Titel mit Uhrzeit, erneut abspielen oder als neue Liste übernehmen
- **STIL der HVSC:** Hintergründe zum laufenden Stück („Original von“, Namen der Unterlieder, Anmerkungen) auf der
  Seite und am Fernseher; Stücke außerhalb der HVSC über ihre MD5
- **Wiedergabeliste als Tabellenfenster wie in der PC-Jukebox** (Ultimate64 SID Player): Dateiname, Titel, Komponist,
  Stück, SIDs, Länge (HVSC / eigene* / geschätzt), Gespielt, ★; Sortieren per Spaltenkopf, Suche über die ganze Liste,
  Mehrfachauswahl, „Als Nächstes“, Entfernen, Ziehen zum Umsortieren, Zeilenmenü, Tastenkürzel; der laufende Titel ist
  markiert und immer im Blick; flüssig auch mit einer ganzen HVSC (nur sichtbare Zeilen)
- **Wiedergabelisten** speichern, laden, anhängen; die aktuelle Liste übersteht einen Neustart
- **Playlists der PC-Jukebox importieren** (geteilte Playlist `.json` nach denselben Regeln: MD5 vor Dateiname; `.u64pl`
  mit Suche nach dem längsten Pfadende) und als geteilte Playlist exportieren; `play_counts.json`, `favorites.json`,
  `user_songlengths.txt` übernehmen
- **Zähler „Gespielt“, Favoriten, eigene Längen** je MD5 wie in der PC-Jukebox; Zufall bevorzugt selten Gespieltes;
  **Entdecken** (nie gespielter Titel / neuer Komponist), **Stopp nach** N Titeln oder Minuten, Doppelte entfernen,
  Statistik
- **Eigenes WLAN**, wenn weder Kabel noch bekanntes WLAN da ist – weicht den Zugangspunkten der Picos (192.168.4.1) aus;
  WLANs suchen und verbinden auf der Webseite
- **Display:** kleines OLED (0,96″ SSD1306 oder 1,3″ SH1106, I2C, 4 Kabel) oder **2,8″-Farbdisplay mit Touch**
  (ILI9341 + XPT2046, SPI, Steckkabel): laufender Titel, Netz, Zugangsdaten des eigenen WLANs; am Touch-Display Tasten
  ⏮ ■ ⏭, Pegelanzeige L/R, Seitenwechsel per Tipp, Einrichtung des Touch mit drei Kreuzen
- **Fernseher (HDMI, 1920 × 1080):** die 17 Effekte der PC-Jukebox (Spectrum Analyzer) zur laufenden Musik, die echten
  SID-Stimmen als Notenrolle (aus dem Debug-Stream des Ultimate), über einer
  Diashow eigener Bilder (Überblenden; hochladen oder von USB-Stick, Netzwerkfreigabe, FTP) oder über dem **Live-Bild des C64** (Video-Stream des
  Ultimate, 4:3); Titel, SID-Chips und Spielzeit eingeblendet, automatischer Effektwechsel, auf Wunsch der Ton über HDMI mit Aus-/Einblenden am Titelwechsel; ohne Musik blenden die Effekte aus; **Retro-News**
  (Indie Retro News, amiga-news.de, Commodore News, Cascade64, The Oasis BBS u. a., eigene RSS-Feeds) als Karte im
  Leerlauf oder als Laufband (die Schlagzeilen laufen auf Wunsch auch im Leerlauf über die Matrizen der Picos); eigener Dienst, der
  Grafikchip vergrößert und überblendet
- **Gehäuse „Brotkasten“ mit Mini-Monitor** im Stil des Commodore 1702 für Pi + 2,8″-Display zum 3D-Drucken (`case/`)
- **SID-Adressen**: braucht ein Stück einen zweiten SID an einer anderen Adresse, stellt die Jukebox einen freien
  Sockel des Ultimate um und danach zurück (wie „Auto-adjust SID addresses“ der PC-Jukebox; nie UltiSIDs); Stücke,
  deren Adressen das Ultimate nicht bietet, sind in der Liste lila mit ⚠ markiert
- **Mehrere Ultimates** mit Auswahl; Netzwerksuche (ein Eintrag je Gerät, Ethernet-Adresse)
- **Titel auf den Pico-Visualizern** (`POST /jb/np` mit Digest-Login oder ohne Passwort per UDP `C64NP1`, alle 30 s
  Abgleich der Spielzeit, `stop=1` am Ende)
- **Stream-Verteiler:** der Pi holt den Audio-Stream per Unicast über das Netzwerkkabel und reicht jedes Paket
  unverändert an alle eingetragenen Picos weiter – kein Multicast
- **Geräte im Netz:** meldet sich wie die Picos (UDP 11064, `t:"pi"`) und zeigt die Picos und den Weg des Tons
- **Passwortschutz** (Startpasswort `commodore64`, wie bei den Picos), **Sicherung** aller Einstellungen als eine Datei
- Installation mit **einem Skript** auf Raspberry Pi OS Lite (64 bit, Trixie oder Bookworm) als systemd-Dienst

## Bilder

<p><img src="docs/bedienung/bilder/web_pc.png" width="100%" alt="Weboberfläche am PC: Wiedergabe und Liste"></p>
<p>
<img src="docs/bedienung/bilder/tv_titlecard.png" width="49%" alt="Fernseher: Effekt mit Jetzt-läuft-Karte">
<img src="docs/bedienung/bilder/tv_menu.png" width="49%" alt="Fernseher: Menü für die TV-Fernbedienung">
</p>
<p>
<img src="docs/bedienung/bilder/tv_sidvoices.png" width="49%" alt="Fernseher: SID-Stimmen als Notenrolle">
<img src="docs/bedienung/bilder/tft_play.png" width="36.7%" alt="2,8-Zoll-Touch-Display am Pi">
</p>

*Die Weboberfläche am PC; am Fernseher ein Effekt mit „Jetzt läuft“-Karte, das Menü für die TV-Fernbedienung und die
SID-Stimmen als Notenrolle; das optionale Touch-Display am Pi. Alles zur Bedienung:
[docs/Bedienung_Pi-Jukebox.pdf](docs/Bedienung_Pi-Jukebox.pdf).*

> **Anleitung für alle drei Geräte zusammen** (Visualizer, Audio-Empfänger, Raspberry-Pi-Jukebox – Einrichtung,
> Verkettung, Bedienung, Besonderheiten, mit Bildern): [docs/Anleitung_C64-Oekosystem.pdf](docs/Anleitung_C64-Oekosystem.pdf) –
> englisch: [docs/Guide_C64-Ecosystem.pdf](docs/Guide_C64-Ecosystem.pdf)

## Was geprüft wurde – und was nicht

**Am echten Gerät geprüft** (Raspberry Pi 3B mit Raspberry Pi OS „Trixie“, Ultimate 64 Elite II und C64 Ultimate,
19.–24.10.2026):

- Installation per `install/deploy.sh` (ruft `install.sh` auf); Dienst läuft (~45–70 MB, ~10 % eines Kerns), Webseite
  antwortet in 9–28 ms
- Netzwerksuche: Elite II und C64 Ultimate je einmal mit ihrer Ethernet-Adresse, dazu die SMB-Rechner (4,2 s)
- Abspielen vom USB-Stick des Elite II (direkt) und des C64 Ultimate (Upload), Unterlied, Pause/Fortsetzen, Wechsel am
  Titelende, fehlende Datei übersprungen, Stopp; HVSC-Songlängen (56 665 Einträge) und STIL vom Stick
- Netzwerkfreigabe eines NAS (SMB 3): SIDs von dort abspielen (Upload), Ordner mit 96 SIDs in 0,19 s; Bilder für die
  Diashow am Fernseher vom NAS
- SID-Sockel des Ultimate automatisch umstellen und wieder zurückstellen
- Stream-Verteiler: Elite II → Pi → Audio-Empfänger und zwei Visualizer, je ~251 Pakete/s, stabil; Titel per UDP an
  die Picos
- Fernseher (4K-TV mit 1080p): Effekte mit ~30 Bildern/s, Ton und Bild des C64, Ton über HDMI mit Aus-/Einblenden,
  Diashow, die SID-Stimmen als Notenrolle, „Jetzt läuft“-Karte, Bedienung mit der Fernbedienung des Fernsehers (HDMI-CEC),
  Lautstärkeregler für den Fernsehton
- 2,8″-Touch-Display: Bild, Touch, Kalibrierung, Tasten
- Wiederholungserkennung für Titel ohne Länge läuft am Pi; Verlauf „Zuletzt gespielt“ im Tab „Listen“

**Noch nicht am Gerät geprüft:** Freigaben mit SMB 2 (ältere NAS) sowie von einem Windows-PC oder Mac, USB-Stick direkt am Pi (automatisches
Einhängen), das kleine OLED-Display, das eigene WLAN des Pi und der Party-Modus.

**Automatische Tests am PC:** `pytest` mit Attrappen für Ultimate-REST, FTP-Server (verhält sich wie der des Ultimate:
kein MLSD, Unix-LIST), SMB-Server (SMB 2/3 und SMB-1-Rückfall), Freigaben-Liste per DCE/RPC, Picos (`/jb/np` mit
Digest, UDP), Display-Controller (ILI9341 + Touch) und Player mit simulierter Uhr; dazu Browsertests (Playwright) am
Handy- und Desktop-Format ohne JavaScript-Fehler und ohne waagrechte Bildlaufleiste.

## Hardware

| Teil | |
|---|---|
| Raspberry Pi 3B (oder neuer) | 1 GB RAM genügt; die Jukebox braucht rund 50 MB, mit HVSC-Songlängen rund 80 MB |
| microSD-Karte ab 8 GB, offizielles Netzteil | |
| Netzwerkkabel | empfohlen (Stream-Verteiler) |
| optional ein USB-Stick | wird nur gelesen, unter `/media/usb` |
| optional ein 0,96″-OLED, I2C, SSD1306 | z. B. AZDelivery, wenige Euro; 4 Kabel an Pin 1, 3, 5, 6 – siehe Handbuch „Display“ |
| oder ein 2,8″-Display mit Touch, SPI, ILI9341 + XPT2046 | rote Platine 86 × 50 mm (ARCELI, AZDelivery), rund 13 €; 13 Steckkabel (Buchse–Buchse) – siehe Handbuch „Display“ |
| optional das Gehäuse | `case/` – Brotkasten mit Mini-Monitor, OpenSCAD, STL, STEP, Anleitung |

## Installation

Raspberry Pi OS Lite (64-bit) mit dem Raspberry Pi Imager schreiben (Rechnername `c64pi`, SSH an). Dann vom Mac/PC aus:

```
./install/deploy.sh pi@c64pi.local
```

oder auf dem Pi im Projektordner `sudo ./install/install.sh`. Danach **http://c64pi.local/** öffnen, Passwort
`commodore64`. Aktualisieren = dasselbe noch einmal; Einstellungen bleiben. Details: [Handbuch](docs/HANDBUCH.md).

## Projektstruktur

```
c64jukebox/            das Programm (Python 3.11+, aiohttp, smbprotocol, pysmb)
  __main__.py          Start: python3 -m c64jukebox --data <ordner> --port 80
  core.py              alles zusammen: Quellen, Cache, Player, Stream, Geräte, Aufträge, Sicherung
  web.py               Weboberfläche + JSON-API, Login (Cookie), Schutz gegen fremde Formulare
  player.py            Wiedergabeliste, Titelende (Songlänge/Zeitlimit/Stille), Unterlieder
  sources.py           SMB, FTP (ftplib), lokal; Ultimate-USB = FTP zum Ultimate
  smb2.py              SMB 2/3 (smbprotocol) + Freigaben-Liste per DCE/RPC; SMB 1 nur als Rückfall (pysmb)
  ultimate.py          REST-Client (X-Password)
  nowplaying.py        Titel an die Picos (Digest bzw. UDP C64NP1)
  stream.py            Stream-Verteiler (UDP 11001)          devices.py   Geräte im Netz (UDP 11064)
  netscan.py           Suche nach SMB/FTP-Rechnern und Ultimates          catalog.py   Cache (SQLite)
  sidfile.py           SID-Kopf, MD5          songlengths.py   HVSC-Songlängen          markdown.py   Handbuch -> HTML
  imports.py           Playlists der PC-Jukebox (geteilte .json, .u64pl), Export          stats.py   Zähler, Favoriten
  netwatch.py          Netzwerk-Wächter (eigener Dienst c64pi-net, root): eigenes WLAN, WLAN wechseln
  display.py           OLED über I2C (SSD1306/SH1106) und die Display-Steuerung
  tft.py               2,8″-Display mit Touch (ILI9341 + XPT2046) über spidev und gpiochip
  news.py              Retro-News: RSS/Atom-Feeds holen, Bilder verkleinern (für den Fernseher)
  hdmi/                HDMI-Ausgabe (eigener Dienst c64pi-hdmi, System-Python mit pygame/numpy): Empfang von Ton
                       und Video, Spektrum, die 17 Effekte, Diashow, Bildaufbau über den Grafikchip
  web/                 index.html, app.js, style.css (kein Build-Schritt)
install/               install.sh, deploy.sh, systemd-Dienste (c64jukebox, c64pi-net, c64pi-hdmi), udev-Regel für USB-Sticks
case/                  Gehäuse „Brotkasten“ mit Mini-Monitor (OpenSCAD, STL, STEP, Vorschaubilder, Probestück)
docs/HANDBUCH.md       Handbuch (= Tab „Hilfe“)
tests/                 PC-Tests (pytest) mit Attrappen; tests/web: Browsertests (Playwright) + Demo-Server
```

## Tests am PC

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest
```

Zum Ansehen ohne Pi und ohne Ultimate: `.venv/bin/python tests/web/demo_server.py 8099` startet die Jukebox mit
Attrappen (Ultimate, FTP, SMB-Server `nas.local` mit Benutzer `nutzer`/`geheim`, Beispiel-SIDs) unter
http://127.0.0.1:8099/.

## Zusammenspiel mit den Pico-Projekten

- [c64-visualizer](https://github.com/sedorrr/c64-visualizer) – LED-Matrix; nimmt Titel per `/jb/np` oder `C64NP1` und den
  weitergeleiteten Stream (Modus „weitergeleitet“).
- [c64-audio-receiver](https://github.com/sedorrr/c64-audio-receiver) – Audio-Empfänger an der Stereoanlage; ebenso.
- Ideen und REST-Wissen aus der PC-Jukebox „Ultimate64 SID Jukebox“ (keine Abhängigkeit).

## Hinweise für die Nutzung

- **Nur fürs Heimnetz.** Die Weboberfläche läuft über HTTP ohne Verschlüsselung. Stream-Verteiler, Titelmeldungen
  (`C64NP1`) und Retro-News (`C64NEWS1`) an die Picos (UDP-Port 11001) sowie Gerätemeldungen (UDP 11064) arbeiten
  **ohne Anmeldung** – jedes Gerät im selben Netz kann sie senden. Den Pi nicht aus dem Internet erreichbar machen
  (keine Portweiterleitung im Router). Das Startpasswort `commodore64` (Weboberfläche und eigenes WLAN) gleich nach der
  Einrichtung ändern. Zugangsdaten für SMB/FTP-Quellen und die Ultimates speichert die Jukebox auf dem Pi.
- **Auf eigene Gefahr.** Eingriffe an C64, Ultimate und Pi (Displays anschließen, Gehäuse, Ein-/Ausschalten der
  Ultimates über das Netz) geschehen auf eigenes Risiko. Für Schäden an Geräten, Hardware oder Daten wird keine Haftung
  übernommen (siehe auch GPL-3.0, Abschnitte 15 und 16).
- **Retro-News:** Die Jukebox holt alle 30 Minuten die RSS-Feeds öffentlicher Retro-News-Seiten (Indie Retro News, amiga-news.de, Commodore News, Cascade64, The Oasis BBS, auf Wunsch
  weitere eigene) aus dem Internet. Gezeigt werden nur Schlagzeile, Datum, ein kurzer Anriss und ein kleines Bild mit
  Quellenangabe; die Inhalte gehören den jeweiligen Seiten. Jeder Feed lässt sich einzeln abschalten, ebenso die
  Weitergabe an die Picos.
- Getestet ist nur mit der Hardware und dem Netz des Autors – siehe [Was geprüft wurde](#was-geprüft-wurde--und-was-nicht).

## Lizenz

Copyright (C) 2026 Sedor (der-sedor.de)

Dieses Programm ist freie Software: Es darf unter den Bedingungen der **GNU General Public License, Version 3**, wie
von der Free Software Foundation veröffentlicht, weitergegeben und verändert werden. Es wird in der Hoffnung
verbreitet, dass es nützlich ist, aber **ohne jede Gewährleistung** – sogar ohne die Gewährleistung der
Marktreife oder der Eignung für einen bestimmten Zweck. Der vollständige Lizenztext (englisch, maßgeblich) steht in
[`LICENSE`](LICENSE).

Fremdkomponenten (per pip und apt installierte Python-Pakete) und ihre Lizenzen: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
