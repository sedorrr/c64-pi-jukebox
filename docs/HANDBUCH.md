# C64-Jukebox für den Raspberry Pi – Handbuch

Die C64-Jukebox macht aus einem **Raspberry Pi 3B** eine SID-Jukebox für das **Ultimate 64**, das **C64 Ultimate**
und das **Ultimate II+**. Sie läuft rund um die Uhr, wird komplett über eine Webseite bedient – am Handy genauso wie
am PC – und holt die SID-Dateien von dort, wo sie liegen: von einer **Netzwerkfreigabe** (NAS, Windows-PC, Mac), von
einem **FTP-Server**, vom **USB-Stick am Ultimate** oder von einem **USB-Stick am Pi**.

Nebenbei ist der Pi der **Stream-Verteiler** für die Pico-Geräte: Er bekommt den Audio-Stream des Ultimate über das
Netzwerkkabel und reicht ihn an beliebig viele Visualizer und Audio-Empfänger weiter. Die Picos zeigen dazu Titel,
Komponist und Spielzeit. Am **HDMI-Ausgang** zeigt der Pi auf dem Fernseher die Effekte der PC-Jukebox – über einer
Diashow eigener Bilder oder über dem Live-Bild des C64.

## Was die Jukebox kann

- SID-Dateien per Fingertipp auswählen: Ordner durchklicken wie in einem Dateimanager, filtern, in allen
  Unterordnern suchen. Zu jeder Datei stehen Titel, Komponist, Jahr, Zahl der Unterlieder und der SIDs da.
- Abspielen per Klick, **„Ordner abspielen“** samt Unterordnern, Zufall, Liste wiederholen.
- Wechsel genau am Ende eines Titels mit der Songlängen-Datei der HVSC, sonst nach einem Zeitlimit oder nach einigen
  Sekunden Stille.
- Wiedergabelisten speichern und laden.
- Mehrere Ultimates mit Auswahl, welches spielt.
- Titelanzeige auf den Pico-Visualizern und Weiterreichen des Audio-Streams an alle Picos.
- Meldet sich in der Liste „Geräte im Netz“ der Picos und zeigt sie selbst an.
- Am Fernseher (HDMI, 1920 × 1080): die 17 Effekte der PC-Jukebox, die echten SID-Stimmen als Notenrolle, Diashow eigener Bilder, das Bild des C64, Titel
  und Spielzeit eingeblendet, „Jetzt läuft“-Karte, Ton mit Aus-/Einblenden, Retro-News, Bedienung mit der
  Fernbedienung des Fernsehers (HDMI-CEC).
- Stellt bei Bedarf einen SID-Sockel des Ultimate auf die Adresse um, die ein Stück braucht, und markiert Stücke,
  die nicht passen – wie die PC-Jukebox.
- Hintergründe zum Stück aus der STIL der HVSC, Verlauf „Zuletzt gespielt“, Sperrliste für Titel, die nicht mehr
  von selbst kommen sollen.
- Passwortschutz, Sicherung aller Einstellungen in einer Datei.

## Was man braucht

| Teil | Hinweis |
|---|---|
| Raspberry Pi 3B (oder neuer) | 1 GB RAM genügt, die Jukebox braucht rund 50 MB, mit der HVSC-Songlängen-Datei rund 80 MB |
| microSD-Karte | ab 8 GB |
| Netzteil | das offizielle 5-V-Netzteil (2,5 A) |
| Netzwerkkabel | empfohlen; WLAN geht auch, der Stream-Verteiler arbeitet über Kabel am zuverlässigsten |
| optional ein Display | 0,96″-OLED (I2C, ein paar Euro) oder 2,8″-Farbdisplay mit Touch (SPI, ILI9341, rund 13 €) – siehe [Display](#display) |
| optional ein Fernseher oder Monitor | über HDMI (Micro-HDMI-Kabel beim Pi 4/5, normales beim Pi 3B) – siehe [Fernseher (HDMI)](#fernseher-hdmi) |
| Ultimate | mit eingeschalteter Web-Fernsteuerung (*Network → Web Remote Control*) und FTP-Dienst für den USB-Stick |

Am Pi wird nichts gelötet und nichts angeschlossen außer Strom, Netzwerk und auf Wunsch einem USB-Stick und einem
Display (Steckkabel). Ein Gehäuse zum 3D-Drucken – ein kleiner „Brotkasten“ mit Mini-Monitor für das 2,8″-Display –
liegt im Ordner `case/` des Projekts.

## Installation

### Raspberry Pi OS auf die Karte

1. Den **Raspberry Pi Imager** auf dem PC oder Mac starten.
2. Gerät *Raspberry Pi 3*, Betriebssystem **Raspberry Pi OS Lite (64-bit)** wählen (ohne Desktop; aktuell „Trixie“,
   das ältere „Bookworm“ geht auch).
3. In den Einstellungen des Imagers: Rechnername `c64pi`, Benutzer und Passwort festlegen, **SSH einschalten**,
   bei Bedarf das WLAN eintragen.
4. Karte schreiben, in den Pi stecken, Netzwerkkabel und Strom anschließen. Nach ein bis zwei Minuten ist der Pi als
   `c64pi.local` im Netz.

### Jukebox installieren

**Direkt auf dem Pi (am einfachsten):** per SSH am Pi anmelden (`ssh <benutzer>@c64pi.local`, Benutzername wie im
Imager festgelegt), das Projekt von GitHub holen und das Installationsskript starten:

```
sudo apt install -y git
git clone https://github.com/sedorrr/c64-pi-jukebox
cd c64-pi-jukebox
sudo ./install/install.sh
```

Ohne git geht es auch: auf GitHub **Code → Download ZIP**, die Datei auf den Pi kopieren
(`scp c64-pi-jukebox-main.zip <benutzer>@c64pi.local:`), dort `unzip c64-pi-jukebox-main.zip` (ggf. vorher `sudo apt install -y unzip`),
`cd c64-pi-jukebox-main` und `sudo ./install/install.sh`.

**Vom Mac oder Linux-PC aus:** Liegt das Projekt schon auf dem PC (geklont oder entpackt), kopiert dieser Befehl im
Projektordner alles auf den Pi und startet dort die Installation (fragt nach dem sudo-Passwort des Pi):

```
./install/deploy.sh <benutzer>@c64pi.local
```

Das Skript

- installiert Python, den Namensdienst (mDNS) und die Python-Bibliotheken (`aiohttp`, `smbprotocol`, `pysmb`) in einen
  eigenen Ordner `/opt/c64jukebox`,
- legt den Benutzer `c64jukebox` an, unter dem die Jukebox läuft (nicht als root),
- richtet den Dienst `c64jukebox` ein, der beim Einschalten startet und sich nach einem Fehler selbst neu startet,
- richtet den Dienst `c64pi-net` ein, der ohne Kabel und bekanntes WLAN ein eigenes WLAN öffnet (siehe
  [Netzwerk des Pi](#netzwerk-des-pi)), und schaltet I2C und SPI für das [Display](#display) ein,
- richtet den Dienst `c64pi-hdmi` für den [Fernseher](#fernseher-hdmi) ein (mit `python3-pygame` und `python3-numpy`
  aus den Paketquellen) und stellt den HDMI-Ausgang fest auf 1920 × 1080 bei 60 Hz (gilt nach dem nächsten Neustart),
- hängt eingesteckte USB-Sticks automatisch (nur lesend) unter `/media/usb` ein,
- setzt den Rechnernamen auf `c64pi` – die Seite ist dann unter **http://c64pi.local/** erreichbar. Wer den Namen
  behalten will: `sudo ./install/install.sh --keep-hostname`.

### Aktualisieren

Ob es eine neue Version gibt, sieht die Jukebox selbst nach: einmal am Tag liest sie die Versionsnummer des
veröffentlichten Programms auf GitHub (`github.com/sedorrr/c64-pi-jukebox`, nur diese eine kleine Datei, ohne
Angaben über den Pi). Ist sie höher als die installierte, steht oben auf der Seite ein blauer Hinweis (✕ blendet ihn
für diese Version aus), und im Menü am Fernseher heißt die Zeile **Nach Update sehen** dann **Update auf … installieren**.
Abschalten oder sofort prüfen: *Einstellungen → System → Updates* bzw. im Menü am Fernseher **Nach Update sehen**.

**Installieren auf Befehl.** Von selbst installiert die Jukebox nichts. Erst **Installieren** im blauen Hinweis bzw.
unter *Updates* oder **Update auf … installieren** im Menü am Fernseher (beides fragt nach) startet das Update:

1. Der Pi lädt das veröffentlichte Programm von GitHub (das ZIP des Zweigs `main`).
2. Danach läuft dessen Installationsskript wie bei einem Update von Hand (mit `--keep-hostname`, der Rechnername
   bleibt). Es holt fehlende Pakete und startet die Jukebox neu. Das dauert einige Minuten, die Musik vom Fernseher
   setzt so lange aus.
3. Danach meldet sich die Seite mit der neuen Version, und am Fernseher zeigt das Menü „Update auf … installiert“.

Klappt die Installation nicht, kommt das alte Programm zurück, und Seite und Fernseher nennen den Grund. Das Protokoll
steht in `/var/lib/c64jukebox/update.log`. Einstellungen, Listen und Songlängen bleiben in jedem Fall erhalten.

Dafür darf die Jukebox, die sonst ohne Rechte läuft, genau einen Dienst starten (`c64jukebox-update`, polkit-Regel aus
dem Installationsskript). Den richtet erst ein Installationsskript ab dieser Version ein. Wer von einer älteren
Version kommt, aktualisiert deshalb **einmal von Hand**: Auf dem Pi im Projektordner `git pull` und danach
`sudo ./install/install.sh`, oder vom PC aus `./install/deploy.sh` erneut aufrufen.

### Erster Aufruf

1. Im Browser **http://c64pi.local/** öffnen (geht der Name nicht, die IP-Adresse des Pi aus dem Router).
2. Mit dem Passwort `commodore64` anmelden – dasselbe Startpasswort wie bei den Picos. Ein gelber Balken erinnert
   daran, es unter *Einstellungen → Web-Passwort* zu ändern.
3. Im Tab **Geräte** das Ultimate eintragen („Im Netz suchen“ findet es) und „Speichern“.
4. Im Tab **Dateien** eine Quelle wählen oder einrichten, einen Titel antippen – er läuft.

Tipp fürs Handy: die Seite im Browser „Zum Home-Bildschirm“ hinzufügen, dann öffnet sie sich wie eine App.

## Die Weboberfläche

Oben steht immer der laufende Titel, rechts daneben der Knopf **⏻ (Ein / Aus)**: von jedem Tab aus **Fernseher
einschalten** / **ausschalten** (über [HDMI-CEC](#fernbedienung-des-fernsehers-hdmi-cec)), das gewählte **Ultimate**
ein- / ausschalten und **Jukebox ausschalten** (siehe [Ausschalten und Steckdose](#ausschalten-und-steckdose)).
Darunter die Tabs:

| Tab | Inhalt |
|---|---|
| Wiedergabe | laufender Titel mit Fortschritt, Knöpfe, Unterlied, Zufall, Wiedergabeliste |
| Dateien | Quellen, Ordner, Filter, Suche, Abspielen |
| Listen | gespeicherte Wiedergabelisten, Statistik |
| Geräte | Ultimates, Picos und Stream-Verteiler, Geräte im Netz (mit dem Namen des Pi) |
| Anzeige | *Bild am Fernseher* (HDMI, Hintergrund, Retro-News) · *Ton* (Ton am Fernseher, Bluetooth-Kopfhörer) · *Bedienung* (TV-Fernbedienung, Display am Pi) |
| Einstellungen | *Abspielen* (Wiedergabe, Songlängen, Daten der PC-Jukebox) · *Netzwerk des Pi* (WLAN, eigenes WLAN) · *System* (Passwort, Sicherung, Updates) |
| Hilfe | dieses Handbuch |

Am Handy stehen „Wiedergabe“, „Anzeige“, „Einstellungen“ und „Hilfe“ als **▶**, **📺**, **⚙** und **?** in der
Tab-Leiste. Die runden **?**-Knöpfe in
den Tabs springen an die passende Stelle des Handbuchs.

**Als App auf dem Startbildschirm:** Am iPhone/iPad in Safari **Teilen → Zum Home-Bildschirm**, am Android-Handy in
Chrome **⋮ → Zum Startbildschirm hinzufügen**. Die Jukebox bekommt ein eigenes Symbol (die Note) und öffnet sich ohne
Adressleiste wie eine App – ein App Store ist dafür nicht nötig. Sie bleibt eine Webseite: Das Handy muss im selben
Netz wie der Pi sein, und die Anmeldung bleibt wie im Browser.

## Wiedergabe

| Knopf | Wirkung |
|---|---|
| ⏮ | zum Anfang des Titels; innerhalb der ersten 5 s zum vorigen Titel |
| ▶ / ❚❚ | abspielen bzw. anhalten (das Ultimate wird pausiert) und fortsetzen |
| ⏹ | Stopp: das Ultimate wird zurückgesetzt |
| ⏭ | nächster Titel |
| ‹ Lied 1 von 3 › | anderes Unterlied des laufenden Titels |
| Zufall | mischt die Reihenfolge (der laufende Titel bleibt) |
| Liste wiederholen | am Ende der Liste von vorn beginnen, sonst hält die Jukebox an |
| Ultimate | erscheint bei mehreren Ultimates: welches spielt |
| ⚑ Ende hier merken | erscheint, solange ein Titel ohne bekannte Länge läuft (siehe unten) |

Die Jukebox spielt selbstständig weiter, auch wenn keine Seite offen ist. Nach einem Stromausfall ist die
Wiedergabeliste noch da; mit ▶ geht es beim letzten Titel weiter.

### Die Wiedergabeliste

Die Liste ist ein Fenster mit Spalten wie in der PC-Jukebox (Ultimate64 SID Player):

| Spalte | Inhalt |
|---|---|
| # | Platz in der Liste |
| Dateiname, Titel, Komponist | aus dem SID-Kopf (am Handy: Titel, darunter Komponist, Stück und SIDs) |
| Stück | gewähltes Unterlied / Zahl der Unterlieder, nur bei mehreren |
| SIDs | Zahl der SID-Chips und ihre Adressen, z. B. `2 ($D400/$D420)` |
| Länge | `3:05` aus der HVSC, `3:05*` blau = eigene Länge, `(5:00)` grau = keine bekannt, es gilt das Zeitlimit |
| Gespielt | wie oft der Titel gestartet wurde |
| ★ | Favorit – antippen schaltet um |

- **Der laufende Titel** ist gelb hinterlegt und steht immer im Blick: bei jedem Titelwechsel rückt das Fenster ihn in
  die Mitte, und hat man 15 s nicht geblättert, holt es ihn zurück. ⌖ springt sofort hin. Ein grünes ▸ zeigt, welcher
  Titel als Nächstes kommt.
- **Abspielen:** doppelt antippen oder doppelklicken (am PC auch Enter); ▶ spielt den ausgewählten Titel.
- **Auswählen:** antippen; mit Strg/⌘ mehrere einzeln, mit Shift einen Bereich. Pfeiltasten wandern durch die Liste.
- **⋯** bei einem Titel (oder Rechtsklick) öffnet: Abspielen, Als Nächstes spielen, Stück wählen, Eigene Länge,
  Favorit, Im Tab Dateien zeigen, Aus der Liste nehmen.
- **Als Nächstes** setzt die ausgewählten Titel direkt hinter den laufenden (eine Warteschlange, auch bei Zufall).
- **Entfernen** (oder Entf) nimmt die ausgewählten Titel aus der Liste.
- **Sortieren:** ein Tipp auf einen Spaltenkopf sortiert die Liste danach (▲), ein zweiter umgekehrt (▼). Der laufende
  Titel spielt weiter.
- **Umsortieren:** am PC eine Zeile mit der Maus an eine andere Stelle ziehen (nicht während einer Suche).
- **Suchen:** das Feld über der Liste durchsucht die ganze Liste nach Dateiname, Titel und Komponist; ★ zeigt nur
  Favoriten.
- **Doppelklick auf „Stück“** wählt ein anderes Unterlied, **Doppelklick auf „Länge“** legt eine eigene Länge fest
  (m:ss, leer = wieder die HVSC-Länge). Eigene Längen gelten für die Datei (über ihre MD5), auch in anderen Listen.
  Eine Länge für den gerade laufenden Titel gilt sofort: Er endet dann dort (bzw. sofort, wenn er schon länger läuft).
- **⚑ Ende hier merken:** Kennt keine Songlängen-Datei einen Titel, spielt er bis zum Zeitlimit. Ist er vorher zu
  Ende oder fängt er von vorn an, drückst du „Ende hier merken“: die bisherige Spielzeit wird seine eigene Länge (wie
  von Hand eingetragen, mit `*`), und es geht mit dem nächsten Titel weiter. Künftig spielt er genau so lange – auch
  in der PC-Jukebox, wenn du die eigenen Längen dorthin mitnimmst. Dasselbe gibt es im [Menü am Fernseher](#fernbedienung-des-fernsehers-hdmi-cec).
- **Längen prüfen** liest die Kopfdaten aller Titel, deren Angaben noch fehlen (das passiert nach „Ordner abspielen“
  und dem Laden einer Liste auch von selbst im Hintergrund), und sucht danach für alle Titel ohne Länge dasselbe Stück
  [über den Namen](#laenge-ueber-den-namen) in der HVSC. Ein Balken über der Liste zeigt den Fortschritt, am Ende steht
  z. B. „35 Titel ohne Länge, davon 22 in der HVSC gefunden“ mit dem Knopf **22 Längen übernehmen** (bei der
  Einstellung *automatisch* werden sie gleich übernommen). Auch im [Menü am Fernseher](#fernbedienung-des-fernsehers-hdmi-cec).
- Die Kopfzeile zeigt die Zahl der Titel, die Gesamtdauer (Titel ohne Länge zählen mit dem Zeitlimit, „geschätzt“)
  und woher die Liste kommt.
- **Mehr ▾:** Playlist der PC-Jukebox importieren, für die PC-Jukebox exportieren, **Entdecken** (ein Titel, der noch
  nie lief, sonst einer der am seltensten gespielten), **Entdecken: ein neuer Komponist**, **Stopp nach …** (nach einer
  Zahl von Titeln oder nach Minuten, immer am Ende eines Titels), Alles auswählen, Liste leeren.
- Tasten am PC (außerhalb von Eingabefeldern): Leertaste = Abspielen/Pause, ← / → = voriger/nächster Titel.
- **Zufall** bevorzugt wie in der PC-Jukebox Titel, die seltener gespielt wurden.
- Die Liste darf sehr lang sein (bis 50 000 Titel, eine ganze HVSC): Die Seite zeichnet nur die sichtbaren Zeilen.

### Länge über den Namen

Songlängen werden über die MD5 der ganzen Datei gefunden. Viele Stücke liegen aber in Party- oder CSDB-Ordnern in einer
**anderen Fassung** als in der HVSC: Die HVSC berichtigt beim Aufnehmen oft den Kopf der Datei (aus „Laszlo Vincze“
wird „László Vincze“) – dieselbe Musik, aber eine andere MD5, also „Länge unbekannt“.

Startet ein Titel ohne Länge, sucht die Jukebox deshalb in der geladenen HVSC-Datei nach demselben **Dateinamen oder
Titel** (ohne Umlaute, Akzente, Leer- und Satzzeichen: „Verkürzte Ausfahrt“ = `Verkuerzte_Ausfahrt.sid`). Zählen tut ein
Treffer nur, wenn sein Komponisten-Ordner zum Komponisten im SID-Kopf passt (`MUSICIANS/V/Vincenzo` zu „Laszlo Vincze
(vincenzo)“); bei Spielen und Demos ohne Komponisten-Ordner nur, wenn es genau einen gibt. Allerweltsnamen wie
„Intro“ oder „Tune“ werden nicht gesucht.

Dann steht im Tab Wiedergabe „In der HVSC als Verkuerzte_Ausfahrt.sid (musicians/v/vincenzo) mit 2:46 – als Länge
übernehmen?“ – **Übernehmen** speichert die Längen aller Unterlieder als eigene Längen dieser Datei (mit `*`), der
laufende Titel endet dann dort; **Nein** lässt alles, wie es ist. Am Fernseher steht dezent über der Spielzeit
„Länge 2:30 in der HVSC gefunden · OK: übernehmen“ – OK öffnet das Menü gleich auf **HVSC-Länge übernehmen**, ein
zweites OK übernimmt.
Einstellung in **Einstellungen → Wiedergabe:** *vorschlagen* (Standard), *automatisch als Länge übernehmen* oder *aus*.

**Wie gut das klappt:** 600 zufällige Dateien aus einer CSDB-Sammlung, verglichen mit der HVSC 85: 69 kannte die HVSC
über die MD5, **331 fanden sich über den Namen**, 143 gar nicht. Bei 259 der 331 sind die Musikdaten hinter dem Kopf
sogar byte-gleich mit der HVSC-Datei – dann stimmt die Länge sicher. Die übrigen sind andere Fassungen (z. B.
`speedy_no_loop.sid` gegen `speedy.sid`), die anders lang sein können – darum fragt die Jukebox lieber nach.

### Wiederholung erkennen

Die meisten SID-Stücke laufen endlos im Kreis; die Länge in der HVSC ist die Stelle, an der sie von vorn anfangen.
Für Titel **ohne** bekannte Länge sucht die Jukebox diese Stelle selbst im Audio-Stream (er muss also laufen): Sie
merkt sich laufend einen „Fingerabdruck“ des Klangs (Töne und Klangfarbe) und vergleicht ihn mit allem, was das Stück
bisher gespielt hat. Klingt es eine Weile genau wie am Anfang, hat das Stück von vorn angefangen.

Dann steht im Tab Wiedergabe „Fängt nach 1:35 von vorn an – als Länge übernehmen?“:

- **Übernehmen** macht 1:35 zur eigenen Länge des Titels (wie [Ende hier merken](#die-wiedergabeliste), mit `*`), und es
  geht gleich mit dem nächsten weiter – das Stück hat ja schon von vorn angefangen.
- **Nein** lässt es bis zum Zeitlimit weiterspielen (beim nächsten Mal sucht die Jukebox wieder).
- Am Fernseher steht dezent über der Spielzeit „Fängt nach 1:35 von vorn an · OK: als Länge übernehmen“ – OK öffnet
  das Menü gleich auf **Erkannte Länge übernehmen**, ein zweites OK übernimmt.

Einstellung in **Einstellungen → Wiedergabe → Wiederholung erkennen:** *vorschlagen* (Standard), *automatisch als Länge
übernehmen* (ohne Nachfrage – nur, wenn du den Vorschlägen traust) oder *aus*.

**Wie gut das klappt:** Gemessen an 40 zufälligen Stücken aus der HVSC, deren Länge bekannt ist: 22-mal die richtige
Länge (auf 3 s genau), 5-mal eine falsche, 13-mal kein Vorschlag. Wenn ein Vorschlag kommt, stimmt er also etwa 4 von 5
Mal – darum fragt die Jukebox lieber nach. Falsch liegt sie vor allem bei Stücken, deren erster Teil sich genau
wiederholt, bevor das ganze Stück von vorn anfängt. Keinen Vorschlag gibt es bei Stücken, die nach einem Vorspiel in
die Mitte zurückspringen (das ist vom zweimal gespielten Refrain nicht zu unterscheiden), und wenn das Zeitlimit
vorher kommt.

**Wann:** Gesucht wird ab dem Start des Titels. Gemeldet wird etwa 45 s nach der Stelle, an der das Stück von vorn
anfängt – so lange muss die Wiederholung halten, bis sie sicher ist. Beim Zeitlimit von 5 Minuten werden also Stücke
bis gut 4 Minuten Länge erkannt; wer längere erkennen lassen will, stellt das Zeitlimit höher. Nach einer Pause
sucht die Jukebox für diesen Titel nicht mehr.

Die Suche läuft als eigener Prozess auf einem anderen Kern des Pi (mit dem numpy des HDMI-Teils) und nur, solange
ein Titel ohne Länge spielt; die Wiedergabe bremst sie nicht. Jeder Fund steht im Ereignisprotokoll
(„Wiederholung erkannt: …“).

### SID-Adressen am Ultimate

Stücke für zwei oder drei SIDs erwarten den zweiten (dritten) Chip an einer bestimmten Adresse, meist `$D420` oder
`$D500` – das steht im Kopf der SID-Datei (Spalte „SIDs“). Ist das Ultimate anders eingestellt, fehlt eine Stimme.
Wie die PC-Jukebox („Auto-adjust SID addresses“) stellt die Jukebox dann **vor dem Stück** einen Sockel um:

- nur im **eindeutigen Fall**: genau **eine** Adresse fehlt, und genau **ein** SID-Sockel ist frei (seine Adresse braucht
  das Stück nicht) – sonst ändert sie nichts und meldet „nicht eindeutig“;
- nur **echte SID-Sockel**, **nie die UltiSIDs**; liefert ein UltiSID die Adresse schon, bleibt alles, wie es ist;
- nur im Arbeitsspeicher des Ultimate (nicht dauerhaft gespeichert);
- **zurück** stellt sie, sobald ein Stück die Adresse nicht mehr braucht, bei **Stopp**, beim Wechsel auf ein anderes
  Ultimate und – falls der Strom mitten im Stück weg war – beim nächsten Start des Pi (die alte Adresse merkt sie sich
  vor dem Umstellen in `/var/lib/c64jukebox/sid-socket.json`).

Unter dem laufenden Titel steht, was passiert ist („Sockel 2 für dieses Stück auf $D420 (sonst $D500)“).
Ein- und ausschalten: **Einstellungen → Wiedergabe → SID-Adressen am Ultimate bei Bedarf umstellen** (an).
**SID-Adressen am Ultimate anzeigen** liest die Belegung aus (Sockel und UltiSIDs) – wie „Check SID Addresses…“ der
PC-Jukebox.

**Markierung in der Wiedergabeliste:** Stücke, deren SID-Adressen das gewählte Ultimate gerade nicht bietet, stehen in
der Spalte „SIDs“ **lila mit ⚠** – wie in der PC-Jukebox, für jedes Stück (auch Ein-SID-Stücke für eine ungewöhnliche
Adresse). Der Hinweis beim Darüberfahren sagt, ob vor dem Stück ein Sockel umgestellt wird oder ob es keine eindeutige
Umstellung gibt (dann klingt das Stück unvollständig). Die Jukebox liest die Belegung jede Minute und beim Wechsel
des Ultimate neu; eine eigene Umstellung zählt dabei nicht – markiert wird gegen die normale Einstellung.

### Zeitplan

Unter **Einstellungen → Zeitplan** startet oder stoppt die Jukebox die Musik zu festen Zeiten, zum Beispiel werktags um
18:00 die Liste „Feierabend“ und jeden Abend um 23:00 Stopp. Jeder Eintrag hat:

- **an** – zum vorübergehenden Abschalten, ohne den Eintrag zu löschen;
- **Wochentage** und **Uhrzeit** (die Uhr des Pi, mitteleuropäische Zeit mit Sommerzeit);
- **abspielen** (die aktuelle Liste oder eine gespeicherte – die ersetzt dann die aktuelle) oder **stoppen**;
- **Fernseher mit** – mit der [TV-Fernbedienung (HDMI-CEC)](#fernbedienung-des-fernsehers-hdmi-cec): beim Abspielen
  den Fernseher einschalten und auf den Pi umschalten, beim Stoppen ausschalten.

**Speichern** übernimmt die Einträge; darunter steht, was als Nächstes passiert und was zuletzt passiert ist. War der
Pi zur geplanten Zeit aus, wird nichts nachgeholt.

## Dateien auswählen

Oben im Tab **Dateien** stehen die **Quellen** als Kacheln. Eine Kachel antippen öffnet sie, ✎ bearbeitet sie,
**+ Quelle** richtet eine neue ein. Die Jukebox merkt sich je Quelle den zuletzt geöffneten Ordner.

- **Ordner** antippen öffnet ihn. Die Pfadzeile darüber führt mit einem Tipp zurück.
- **SID-Datei antippen** (oder ▶) spielt sie – und danach die übrigen Dateien des Ordners, so wie sie gerade
  angezeigt werden (mit Filter nur die passenden). Die bisherige Wiedergabeliste wird dabei ersetzt.
- **+** hängt eine Datei hinten an die Liste an, ohne die laufende Wiedergabe zu unterbrechen.
- **▶ Ordner abspielen** nimmt alle SIDs des Ordners, mit dem Haken **mit Unterordnern** auch aus allen
  Unterordnern, mit **Zufall** gemischt; beim Sammeln steht darunter, welcher Ordner gerade gelesen wird.
  **+ Liste** hängt sie stattdessen an.
- Zu jeder SID zeigt die Liste **Titel, Komponist, Jahr, Unterlieder, Spielzeit** und gelb **2 SIDs** bzw.
  **3 SIDs** bei Stereo-Stücken. Die Angaben werden beim ersten Öffnen eines Ordners aus den Dateien gelesen (in
  großen Ordnern füllt sich die Liste nach und nach) und dann auf dem Pi gemerkt.

### Filtern und Suchen

- Das **Filterfeld** wirkt sofort auf den offenen Ordner: es sucht in Dateiname, Titel, Komponist und Jahr. Mehrere
  Wörter müssen alle vorkommen, z. B. `hubbard 1986`.
- **🔍 Unterordner** sucht das Wort aus dem Filterfeld in **allen Unterordnern** des offenen Ordners – im Pfad
  (`MUSICIANS/H/Hubbard_Rob/…`) und in Titel und Komponist der schon einmal angezeigten Dateien. Bis zu 500 Treffer.
  Während der Suche steht darunter, wie viele Ordner schon durchsucht sind und welcher gerade dran ist.
  Eine wiederholte Suche ist schnell, weil der Pi die Ordnerlisten einen Tag lang behält. Mit ✕ in der Pfadzeile geht
  es zurück zum Ordner. „Ordner abspielen“ spielt dann die Treffer.
- **🔍 HVSC** (sobald die [Songlängen](#songlaengen) der HVSC aus einer Quelle geladen sind) sucht in der **ganzen
  HVSC** – sofort, ohne einen Ordner zu lesen: Die Jukebox kennt alle Pfade aus `Songlengths.md5`. Dasselbe gilt für
  🔍 Unterordner in einem Ordner der HVSC. Dateiname und Komponisten-Ordner (`Hubbard_Rob`) findet sie damit gleich;
  **Titel, Komponist und Veröffentlichung** aus den Dateien selbst kommen dazu, sobald einmal *Einstellungen →
  Songlängen → Titel für die Suche einlesen* gelaufen ist. Das liest im Hintergrund von jeder HVSC-Datei nur die
  ersten 124 Byte (über SMB einige Minuten, der Fortschritt steht dort; die Musik läuft weiter) und muss nur nach
  einer neuen HVSC-Version wiederholt werden – dann nur für die neuen Dateien.

### Quellen einrichten

**+ Quelle** öffnet den Dialog. Zuerst die **Art** wählen, dann:

1. **Im Netz suchen** – der Pi sucht im Heimnetz nach Rechnern mit Freigaben (SMB) bzw. FTP-Servern. Während der
   Suche (einige Sekunden) zeigt ein Balken den Fortschritt in Prozent, darunter die Adressen, die gerade geprüft
   werden (z. B. „prüft gerade 192.168.1.65 … .128“, 64 gleichzeitig), und was schon gefunden wurde. Danach einen
   Treffer antippen – das trägt ihn als Server ein.
2. Bei Netzwerkfreigaben **Benutzer und Passwort** eintragen (leer = Gast) und **Freigaben anzeigen**: alle
   Freigaben des Rechners erscheinen, eine antippen.
3. Optional einen **Ordner** innerhalb der Freigabe, z. B. `/C64Music` – dann beginnt die Quelle dort.
4. **Verbindung testen** und **Speichern**.

| Art | Server | Freigabe / Ordner | Benutzer |
|---|---|---|---|
| Netzwerkfreigabe (SMB) | `nas.local`, `diskstation` oder IP | Name der Freigabe, darin optional ein Ordner | Benutzer des NAS/PCs |
| FTP-Server | Name oder IP, Port meist 21 | Startordner | leer = anonym |
| USB-Stick am Ultimate | – (das Ultimate aus „Geräte“) | `/` oder z. B. `/USB2/SID-Tunes` | – (Netzwerk-Passwort des Ultimate) |
| Ordner oder USB-Stick am Pi | – | `/media/usb` | – |

### Netzwerkfreigabe (SMB)

So heißen die freigegebenen Ordner von Windows, macOS, Linux (Samba) und jedem NAS (Synology, QNAP, Fritz!Box-NAS …).
Die Jukebox hängt nichts ein, sie liest die Dateien direkt – mit SMB 2 oder 3 (auch verschlüsselt), bei sehr alten
Geräten mit SMB 1. Hinweise:

- **Windows:** Ordner freigeben (Eigenschaften → Freigabe), Benutzer = Windows-Benutzer (bei einem Microsoft-Konto die
  E-Mail-Adresse), Passwort = dessen Passwort.
- **macOS:** Systemeinstellungen → Allgemein → Teilen → Dateifreigabe; unter „Optionen“ für den Benutzer „Windows-
  Dateifreigabe“ einschalten.
- **Synology/QNAP:** einen eigenen Benutzer nur mit Leserecht auf den Musikordner anlegen – das ist am sichersten.
- Die Freigabe wird beim Öffnen eines Ordners gefragt; nach einer Minute ohne Zugriff trennt der Pi die Verbindung.
- Das Passwort steht auf dem Pi in der Einstellungsdatei (nur für die Jukebox lesbar) und in der Sicherung. Die
  Webseite zeigt es nie, sondern •••• – so lassen, dann bleibt es beim Speichern erhalten.

### FTP-Server

Für Rechner oder NAS mit FTP-Dienst. Die Jukebox nutzt passives FTP und kann Server mit und ohne UTF-8-Dateinamen.

### USB-Stick am Ultimate

Die Dateien auf dem USB-Stick oder der SD-Karte des Ultimate. Im Ultimate muss der **FTP-Dienst** eingeschaltet sein
(*Network → FTP Server*). Liegt die Datei auf dem Ultimate, das gerade spielt, startet die Jukebox sie direkt dort
(ohne Übertragung). Bei mehreren Ultimates kann eine Quelle an „das gerade gewählte“ oder an ein bestimmtes Ultimate
gebunden sein – dann spielt auch ein anderes Ultimate die Dateien (sie werden übertragen).

### Ordner oder USB-Stick am Pi

Einen USB-Stick in den Pi stecken: er erscheint nach wenigen Sekunden unter `/media/usb/sda1` (FAT, exFAT, NTFS
und Linux-Dateisysteme, nur lesend). Die vorbereitete Quelle **USB-Stick am Pi** zeigt `/media/usb`. Abziehen ist
jederzeit erlaubt, die Jukebox schreibt nie auf den Stick.

## Songlängen

Mit der Songlängen-Datei der **HVSC** (High Voltage SID Collection) wechselt die Jukebox genau am Ende eines Titels,
und Fortschrittsbalken und Liste zeigen die Spielzeit.

1. Die Datei heißt `Songlengths.md5` und liegt in der HVSC im Ordner `C64Music/DOCUMENTS`.
2. Im Tab **Dateien** zu diesem Ordner gehen und bei der Datei **als HVSC-Längen laden** tippen. Oder im Tab
   **Einstellungen → Songlängen** die Datei vom Handy/PC hochladen.
3. Der Pi liest sie ein (ein paar Sekunden) und behält sie, auch über einen Neustart.
4. Geladen aus einer Quelle (nicht hochgeladen), kennt die Jukebox damit auch alle Pfade der HVSC für die
   [Suche über die ganze HVSC](#filtern-und-suchen); **Titel für die Suche einlesen** ergänzt Titel und Komponisten.

**Eigene Längen** haben Vorrang vor der HVSC: eine Textdatei mit Zeilen `<md5>=<Sekunden>` (das Format des
Ultimate64 SID Player) oder im HVSC-Format `<md5>=m:ss m:ss …`. Die MD5 wird über die ganze Datei gebildet.

Ohne bekannte Länge gilt:

- **Zeitlimit** (*Einstellungen → Wiedergabe*, Standard 5 Minuten, 0 = nie),
- **oder nach N s Stille** (Standard 5 s): die Jukebox hört den Audio-Stream mit und springt weiter, wenn ein Titel
  endet und still wird. Das geht nur, wenn der [Stream-Verteiler](#stream-verteiler) an ist.

**Unterlieder:** „nur das Startlied“ spielt je Datei das im SID-Kopf genannte Lied, „alle nacheinander“ spielt alle
Unterlieder einer Datei, bevor die nächste Datei kommt.

### Längen am Mac ermitteln (ganze Ordner)

Für Sammlungen außerhalb der HVSC (Party-Ordner, CSDB) gibt es ein Werkzeug für den Mac, das die Längen **vorab für
ganze Ordner** ermittelt – statt Titel für Titel beim Abspielen. Für jede SID-Datei, die die HVSC nicht über ihre MD5
kennt:

1. **über den Namen** (wie [Länge über den Namen](#laenge-ueber-den-namen)); mit dem HVSC-Ordner vergleicht es auch
   die Musikdaten: byte-gleich = „hvsc-same“ (sicher), sonst „hvsc-other“ (andere Fassung, nur auf Wunsch);
2. **durch Zuhören:** jedes Unterlied wird mit libsidplayfp abgespielt, rund 80-mal schneller als in Echtzeit –
   „end“: das Stück hört auf (4 s Stille), „loop“: es fängt von vorn an ([Wiederholung erkennen](#wiederholung-erkennen)).

Heraus kommen eine `user_songlengths.txt` (Format der PC-Jukebox, alle Unterlieder) und ein Bericht als CSV, woher
jede Länge stammt. Die Datei lädst du in **Einstellungen → Songlängen** als eigene Längen hoch („hinzufügen“) – oder
legst sie in den Ordner der PC-Jukebox.

```
cd tools/sidlen && c++ -O2 -std=c++17 -isysroot "$(xcrun --show-sdk-path)" sidrender.cpp \
    -I"$(brew --prefix libsidplayfp)/include" -L"$(brew --prefix libsidplayfp)/lib" -lsidplayfp -o sidrender
python3 tools/find_lengths.py "<Ordner>" --hvsc ".../C64Music/DOCUMENTS/Songlengths.md5" --hvsc-dir ".../C64Music"
```

Gebraucht werden `brew install libsidplayfp` und Python mit numpy (die `.venv` des Projekts). **Gemessen** an 40
HVSC-Stücken mit bekannter Länge: 27 richtig (alle 6 „end“ richtig), 4 falsch, 9 ohne Ergebnis, 36 s für alle 40.
Falsch liegt „loop“ bei Stücken, deren erster Teil sich genau wiederholt. Ordner `X24` (18 Dateien): 2 schon bekannt,
13 über den Namen mit gleichen Musikdaten (z. B. Brutopian Schlager 3:07), 1 durch Zuhören, 2 ohne Ergebnis – in 44 s.
Mit `--kinds hvsc-same,end` kommen nur die sicheren Längen in die Datei.

### STIL – Hintergründe zu den Stücken

Die HVSC hat neben den Songlängen die Datei `STIL.txt` (*SID Tune Information List*, ebenfalls in
`C64Music/DOCUMENTS`): Anmerkungen zu rund 17 000 Stücken – woher eine Melodie stammt („Original von“), die Namen der
Unterlieder, Geschichten der Musiker. Im Tab **Dateien** bei der Datei **als STIL laden** tippen; der Pi liest sie in
wenigen Sekunden ein und behält sie.

Danach steht unter dem laufenden Titel (Tab **Wiedergabe**) und – mit dem Haken „dazu die STIL-Hintergründe zum Stück“
in der Karte **Fernseher (HDMI)** – unten links am Fernseher, was die STIL zum Stück und zum gerade laufenden Unterlied
weiß (höchstens 6 Zeilen). Gefunden wird ein Stück über seinen Pfad in der HVSC; liegt es woanders (z. B. in einem
eigenen Ordner), über seine MD5 und die Pfade in der Songlängen-Datei – dafür müssen die HVSC-Songlängen geladen sein.
Entfernen: **Einstellungen → Songlängen**, Zeile „STIL“.

## Wiedergabelisten

- **Speichern:** im Tab „Wiedergabe“ bei der Liste auf **Speichern …** und einen Namen eingeben. Ein vorhandener Name
  wird überschrieben.
- **Laden:** im Tab „Listen“ **▶ Laden** ersetzt die aktuelle Liste und spielt sie, **+** hängt sie hinten an,
  **↗** exportiert sie für die PC-Jukebox, **✎** benennt sie um, 🗑 löscht sie. Spielt der Zeitplan die Liste, zieht
  er beim Umbenennen mit; beim Löschen wird sein Eintrag ausgeschaltet (sonst spielte er eine andere Liste).
  Am Fernseher geht beides auch: Menü → Musik wählen → Liste wählen (siehe [Menü am Fernseher](#fernbedienung-des-fernsehers-hdmi-cec)).
- Eine Liste merkt sich zu jedem Titel die Quelle und den Pfad. Wird eine Quelle gelöscht oder eine Datei verschoben,
  überspringt die Jukebox den Titel mit einer Meldung.

### Listen zusammenstellen

Im Tab „Listen“ stellt die Jukebox Listen selbst zusammen – aus der ganzen **HVSC**, ohne jede Datei einzeln zu lesen:
Die geladene Songlängen-Datei kennt alle Stücke mit Pfad und Länge. Dafür müssen die HVSC-Songlängen **aus einer
Quelle** geladen sein (Tab **Dateien**, nicht hochgeladen); der HVSC-Ordner ist der, aus dem die Datei stammt.

**Ein Tipp spielt sofort:**

| Knopf | |
|---|---|
| ★ Favoriten | alle Favoriten, auch außerhalb der HVSC |
| Meistgespielt | die 50 am häufigsten gespielten Titel |
| Nie gespielt | 50 zufällige Stücke der HVSC, die noch nie liefen |
| Zufällige aus der HVSC | 50 zufällige Stücke |
| Kurze Stücke | 50 zufällige unter 2 Minuten |
| Stücke für 2 oder 3 SIDs | 100 zufällige Mehr-SID-Stücke (dafür lohnt die [SID-Umstellung](#sid-adressen-am-ultimate)) |

**Eigene Auswahl aus der HVSC:** Bereich (Musiker, Spiele, Demos), Komponist oder Pfad enthält (zum Beispiel
„Hubbard“ oder „Galway“ – der Ordnername in der HVSC), Länge von–bis, nur 2/3 SIDs, nur mit
[STIL-Hintergrund](#stil-hintergruende-zu-den-stuecken), nur nie gespielte, Anzahl und Reihenfolge. Dann
**Abspielen** (ersetzt die Liste), **Anhängen** oder **Als Liste speichern**. Nach dem Erscheinungsjahr lässt sich so
nicht auswählen – das steht nur in den Dateien selbst.

### Zuletzt gespielt

Im Tab „Listen“ stehen die zuletzt gespielten Titel mit Uhrzeit (neueste oben; gemerkt werden 100, auch über einen
Neustart). **▶** spielt einen davon als nächsten, **+** hängt ihn hinten an die Liste. **Als Wiedergabeliste
übernehmen** macht aus dem Verlauf eine neue Liste (in der gespielten Reihenfolge, jeder Titel einmal) – die lässt sich
dann wie jede Liste speichern. **Verlauf löschen** leert ihn.

### Gesperrte Titel

Ein Stück, das man nicht mehr hören möchte, muss nicht aus jeder Liste gelöscht werden: **⊘ Nicht mehr spielen**
(unter dem laufenden Titel, im Menü **⋯** einer Zeile oder am Fernseher im Menü) springt sofort zum nächsten und setzt
das Stück auf die Sperrliste. Danach überspringt die Jukebox es überall, wo sie selbst wählt: beim Weiterschalten am
Titelende und mit **⏭**, bei Zufall, bei „Entdecken“ und in den [zusammengestellten Listen](#listen-zusammenstellen).
In der Wiedergabeliste ist es durchgestrichen. **Von Hand gewählt** (Zeile antippen, ▶) spielt es trotzdem.

Gesperrt wird die Datei (über ihre MD5-Summe, wie die Favoriten): eine Kopie unter anderem Namen oder in einem anderen
Ordner ist ebenfalls gesperrt. Ein Favorit verliert beim Sperren seinen Stern; wer ein gesperrtes Stück wieder zum
Favoriten macht, hebt die Sperre auf. Im Tab „Listen“ stehen unter **Gesperrte Titel** alle gesperrten Stücke
(neueste oben) mit **Wieder spielen**; die Sperrliste ist Teil der [Sicherung](#sicherung). Sind alle Titel einer
Liste gesperrt, hält die Wiedergabe an.

### Playlists der PC-Jukebox importieren

Im Tab „Wiedergabe“ unter **Mehr ▾ → Playlist der PC-Jukebox importieren …**: Datei wählen, dann die **Quelle und den
Ordner, in dem gesucht wird** (samt Unterordnern; vorbelegt mit dem zuletzt im Tab „Dateien“ geöffneten Ordner), z. B.
die HVSC auf der Netzwerkfreigabe. Danach ist sie die aktuelle Wiedergabeliste und auf Wunsch unter ihrem Namen
gespeichert. Was nicht gefunden wurde, steht in einer Liste.

- **Geteilte Playlist** (`…_u64playlist.json`, in der PC-Jukebox „Export Playlist for Sharing“): genau wie dort – erst
  wird der ganze Ordner erfasst, dann für jeden Titel zuerst die Datei mit **derselben MD5** genommen, sonst die mit
  **demselben Dateinamen** (Groß-/Kleinschreibung egal); gibt es mehrere, gilt die erste. Titel und Komponist zählen
  nicht. Die MD5 der HVSC-Dateien kennt die Jukebox aus der geladenen `Songlengths.md5` (dort steht zu jeder MD5 der
  HVSC-Pfad), andere Dateien liest sie einmal und merkt sich die MD5 – der erste Import aus einem großen Ordner ohne
  HVSC dauert deshalb etwas.
- **.u64pl** (die Playlist-Dateien der PC-Jukebox): Darin stehen die Pfade des PCs, z. B.
  `/Volumes/Musik/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid`. Die PC-Jukebox überspringt Pfade, die es nicht gibt;
  auf dem Pi gibt es keinen davon. Deshalb sucht die Jukebox im gewählten Ordner die Datei, deren Pfad **am Ende am
  längsten übereinstimmt** (`H/Hubbard_Rob/Commando.sid` vor `Commando.sid`), sonst nach dem Dateinamen.
  Einträge `u64://<Adresse>/<Pfad>` (Dateien auf einem Ultimate) gehen an die Quelle „USB-Stick am Ultimate“ dieses
  Ultimate.
- **Export:** „Für die PC-Jukebox exportieren“ (Mehr ▾ oder ↗ im Tab „Listen“) schreibt eine geteilte Playlist
  (`<Name>_u64playlist.json`) – in der PC-Jukebox mit „Import Shared Playlist…“ zu laden.

### Daten der PC-Jukebox

Im Tab **Einstellungen → Daten der PC-Jukebox übernehmen** lassen sich die Dateien aus dem Einstellungsordner des
Ultimate64 SID Player einlesen (Mac: `~/Library/Application Support/Ultimate64SIDPlayer`, Windows: `%APPDATA%`):

| Datei | Wirkung |
|---|---|
| `play_counts.json` | die Zähler „Gespielt“ werden zu den eigenen addiert |
| `favorites.json` | die Favoriten (★) kommen dazu |
| `user_songlengths.txt` | eigene Längen: neue kommen dazu; weichen welche ab, bleiben die eigenen – außer der Haken „bei abweichenden Längen die aus der Datei nehmen“ ist gesetzt |

Zähler, Favoriten und eigene Längen gehören wie in der PC-Jukebox zur **MD5 der Datei** – sie gelten also auch, wenn die
Datei woanders liegt. „Eigene Längen herunterladen“ liefert die `user_songlengths.txt` für die PC-Jukebox.

**Automatisch abgleichen** (PC-Jukebox ab Version 1.83): dort *Settings → Preferences… → Pi-Jukebox* einschalten,
Adresse (`c64pi.local`) und das Passwort dieser Seite eintragen. Vor jedem „Check Lengths“ holt sich die PC-Jukebox die
eigenen Längen, die nur der Pi kennt, und schickt ihm die, die nur sie kennt; beim Speichern ihrer Längen am
Programmende gehen neue gleich mit. Haben beide für dasselbe Stück eine andere Länge, fragt die PC-Jukebox einmal, welche
gilt. Längen je Unterlied (nur hier möglich) bleiben unberührt. Auf der Seite ist dafür nichts einzustellen.

## Ultimates

Im Tab **Geräte → Ultimates** stehen die Geräte, die spielen können:

- **Im Netz suchen** findet Ultimates im Heimnetz (auch mit Netzwerk-Passwort, wenn das Passwort schon bei einem
  eingetragenen Ultimate steht); Fortschritt und gerade geprüfte Adressen stehen dabei unter den Knöpfen. Jedes
  Ultimate erscheint einmal, mit seiner **Ethernet-Adresse** – nur darüber
  streamt es. Antippen übernimmt es, dann **Speichern**.
- **Netzwerk-Passwort:** das unter *Network → Network Password* im Ultimate eingestellte; leer, wenn keins gesetzt ist.
- **aktiv:** dieses Ultimate spielt. Bei mehreren Ultimates gibt es dieselbe Auswahl im Tab „Wiedergabe“. Ein Wechsel
  stoppt die laufende Wiedergabe und holt – bei eingeschaltetem Verteiler – den Stream vom neuen Gerät.
- **⏻ Ein / Aus:** **Aus** stellt umgestellte SID-Sockel zurück, stoppt die Wiedergabe und schaltet das Ultimate aus
  (`machine:poweroff`). **Ein** weckt es über sein **WLAN** („Wake-Up on WiFi“ des Ultimate 64-II, wie „Wake via WiFi“
  in der PC-Jukebox): ein Wake-on-LAN-Paket an seine **WLAN-MAC**. Die Zeile darunter meldet, wann es wieder antwortet
  (am Elite II nach etwa 12 s). Die WLAN-MAC merkt sich die Jukebox selbst, sobald das Ultimate einmal eingeschaltet
  war (sie steht dann im Feld darunter); sonst dort eintragen – sie steht im Router oder auf dem Gerät. Den Ton holt der
  Pi trotzdem nur über das Kabel. Am Fernseher: Menü → „Ultimate einschalten“ / „Ultimate ausschalten“ (fragt nach).

## Stream-Verteiler

Das Ultimate schickt seinen Audio-Stream nur an **eine** Adresse. Ist der Verteiler an, ist diese Adresse der Pi: Er
bekommt den Stream über das Netzwerkkabel und reicht jedes Paket unverändert an alle Picos in der Liste weiter – an
Visualizer genauso wie an den Audio-Empfänger. Multicast wird nicht gebraucht (der macht viele WLANs langsam).

1. Tab **Geräte → Picos und Stream-Verteiler**: die Picos eintragen (`c64viz.local`, `c64audio.local` …) oder unten
   bei „Geräte im Netz“ **als Pico eintragen** tippen, dann **Speichern**.
2. Den Haken **Audio-Stream vom Ultimate zum Pi holen …** setzen. Der Pi bittet das Ultimate um den Stream und tut
   das erneut, sobald 5 s nichts kommt (z. B. nach einem Neustart des Ultimate).
3. Auf **jedem Pico** im Tab „WLAN & Ultimate“ als Empfänger-Modus **„weitergeleitet“** wählen. Sonst holt sich der
   Pico den Stream selbst vom Ultimate und nimmt ihn damit dem Pi weg.
4. Die **Weiterleitung auf den Picos** ausschalten, wenn der Pi alle direkt beliefert – oder bewusst eine Kette
   bauen: der Pi beliefert nur den Audio-Empfänger, der reicht an den Visualizer weiter usw. Beides geht; nur ein Pico,
   der den Stream zweimal bekäme, nimmt den ersten und verwirft den zweiten.

Der Kasten unter dem Haken zeigt, ob der Stream kommt (Pakete pro Sekunde, normal etwa 250) und wie viel an jeden
Pico geht. Steht bei einem Pico „Name nicht gefunden“, ist er aus oder heißt anders.

Stream-Daten (Ton, Bild des C64, SID-Stimmen) nimmt der Pi **nur von den eingetragenen Adressen der Ultimates** an –
also über das Netzwerkkabel. Schickt ein Ultimate über seine WLAN-Adresse (das Elite II tat das, als es hing), verwirft
der Pi die Pakete und zeigt im Kasten „… Pakete von <Adresse> verworfen“. Das WLAN des Ultimate braucht die Jukebox
nicht. Darum die Ultimates im Tab „Geräte“ mit ihrer **Kabeladresse** eintragen.

Für jeden Pico lässt sich einzeln einstellen, ob er den **Stream** bekommt.

### Titelanzeige auf den Picos

Zu jedem Titel schickt die Jukebox Titel, Komponist, Länge, Unterlied und SID-Adressen an die Picos; die Matrix zeigt
den Titel, der Fortschritt läuft mit, und ein Stück mit 2 SIDs schaltet den Visualizer auf Stereo. Alle 30 s geht die
Spielzeit erneut hinaus, am Ende „Stopp“.

### Retro-News auf den Picos

Der Haken **Retro-News an die Picos schicken** (Karte „Picos und Stream-Verteiler“) schickt die neuesten 6
Schlagzeilen der [Retro-News](#retro-news) an alle Picos, die Titel bekommen – auf demselben Weg wie die Titel (UDP bzw.
Webseite mit Passwort), wenn sie sich ändern und sonst alle 15 Minuten. Die Picos (Firmware ab 2026-10-22) zeigen im
Leerlauf nach jedem Lauftext eine Schlagzeile in Gelb, z. B. `+++ CSDb: Neue Demo +++`. Umlaute werden ausgeschrieben
(ä → ae), die Matrix hat keine anderen Sonderzeichen. Es gelten die Quellen aus „Retro-News am Fernseher“ – der
Fernseher selbst muss dafür nicht an sein. Haken aus: Die Picos vergessen die Schlagzeilen sofort; einzelne Picos
blenden sie mit „Retro-News“ in ihren Einstellungen (`@news off`) aus.

- **Titel per UDP** erreicht einen Pico nur, wenn er seinen Stream vom Pi bekommt (wie die Titel). Sonst
  **Titel per Webseite** mit dem Web-Passwort des Pico wählen.

| Einstellung | Weg | Wann |
|---|---|---|
| Titel per UDP | ohne Passwort an den Stream-Port des Pico (`C64NP1 …`) | der Pico bekommt seinen Stream vom Pi (oder gerade gar keinen) |
| Titel per Webseite | `POST /jb/np` mit dem Web-Passwort des Pico | immer; Passwort des Pico eintragen |
| keine Titel | – | – |

Ein Pico nimmt die UDP-Meldung nur an, wenn bei ihm „Audio-Stream verwenden“ an ist und kein anderes Gerät gerade
einen Stream an ihn schickt. Picos reichen die Titel an ihr eigenes Weiterleitungsziel weiter.

## Netzwerk des Pi

Am zuverlässigsten hängt der Pi am **Netzwerkkabel**. Der Dienst `c64pi-net` passt auf und hilft, wenn kein Netz da
ist; die Karte **Einstellungen → Netzwerk des Pi → WLAN und Netzwerk** zeigt, was er gerade macht.

| Lage | Was der Pi tut |
|---|---|
| Kabel steckt | nichts weiter – Adresse vom Router, Seite unter `c64pi.local` |
| kein Kabel, ein bekanntes WLAN in Reichweite | verbindet sich damit |
| weder Kabel noch bekanntes WLAN (60 s lang; nach dem Einschalten frühestens nach 90 s) | öffnet sein **eigenes WLAN** |

**Das eigene WLAN** heißt `C64-Jukebox` (bei einem anderen Namen in der Geräteliste `C64-Jukebox-<Name>`), das Passwort
ist `commodore64`; beides lässt sich in der Karte ändern (Passwort mindestens 8 Zeichen). Handy oder PC damit verbinden,
dann die Adresse öffnen, die das Display und diese Seite zeigen, meist `http://192.168.5.1/`.

**Ausweichen:** Bevor der Pi sein WLAN öffnet, schaut er, welche C64-Geräte schon eigene WLANs aufgespannt haben. Die
Picos (Visualizer, Audio-Empfänger) benutzen dort immer `192.168.4.1`; sieht der Pi eins davon, nimmt er
`192.168.5.1`, sonst `192.168.4.1`. Sieht er einen anderen Pi mit eigenem WLAN, weicht er auf den nächsten Bereich
(`192.168.6.1` …) und einen Namen mit `-2` aus. So landet ein Handy nie in zwei Netzen mit denselben Adressen.

Im eigenen WLAN schaut der Pi alle 5 Minuten, ob ein bekanntes WLAN wieder da ist – nicht, solange jemand in den
letzten 5 Minuten die Seite benutzt hat. Der Pi kann nicht gleichzeitig sein WLAN aufspannen und suchen; für die Suche
geht sein WLAN deshalb etwa 15 Sekunden aus und, wenn nichts Bekanntes in Reichweite ist, wieder an. Dasselbe passiert
bei **WLANs suchen** auf der Seite, solange man über das eigene WLAN verbunden ist – danach die Seite neu laden.
Klappt das Verbinden mit einem neuen WLAN nicht (falsches Passwort), ist das eigene WLAN sofort wieder da. Wird das Kabel eingesteckt, geht das eigene WLAN sofort aus (und war das WLAN
des Pi vorher ganz ausgeschaltet, auch wieder ganz aus).

**Ein WLAN einrichten:** **WLANs suchen**, das gewünschte antippen, Passwort eingeben. Der Pi merkt es sich (gespeichert
von NetworkManager) und nimmt es künftig, wenn das Kabel fehlt. **Dieses WLAN vergessen** löscht das gerade benutzte.

### Party-Modus

Für unterwegs, wo es kein WLAN gibt (oder man das fremde nicht nutzen will): Der Pi spannt selbst ein WLAN auf – **unter
dem Namen und Passwort deines Heim-WLANs**. Die Picos, der Audio-Empfänger und die Handys kennen dieses WLAN schon und
verbinden sich von selbst; an ihnen muss man nichts umstellen. Das **Ultimate kommt per Netzwerkkabel direkt an den
Pi** (die Ultimates streamen den Ton nur über das Kabel).

**Einschalten:** **Einstellungen → Party-Modus**, Haken setzen, beim Heim-WLAN den Namen wählen (die im Pi gespeicherten
WLANs stehen zur Auswahl) – das Passwort kann leer bleiben, wenn der Pi dieses WLAN schon kennt; sonst eintippen.
**Speichern.** Danach darf der Schalter an bleiben:

- **Zu Hause bleibt der Party-Modus still:** Hat der Pi am Kabel eine Adresse vom Router oder ist das Heim-WLAN in
  Reichweite, verhält er sich ganz normal. So kann er nie zu Hause Adressen verteilen.
- **Auf der Party:** etwa 15 s nach dem Start steht das WLAN. Am Kabel gibt der Pi **genau eine Adresse** aus, für das
  Ultimate (**10.64.64.2**) – aber erst, wenn sich nach dem Einstecken 40 s lang kein Router gemeldet hat. Die Jukebox
  spricht das gewählte Ultimate dann unter dieser Adresse an und holt sich den Ton.
- Die Weboberfläche erreicht man unter `http://c64pi.local/` oder über den **QR-Code** am Fernseher; die Karte zeigt die
  Adresse. Das Display des Pi zeigt „Party-WLAN“. Das Passwort des Heim-WLANs erscheint nirgends.
- Zieht man das Netzwerkkabel, hört der Pi dort sofort auf, Adressen zu verteilen.

Nur **ein** Ultimate am Kabel (für mehrere bräuchte es einen Switch – das unterstützt der Party-Modus nicht). Die
Picos dürfen nicht im 5-GHz-WLAN hängen (sie kennen nur 2,4 GHz) – das WLAN des Pi ist immer 2,4 GHz.

## Display

Ein Display am Pi zeigt, was läuft, und vor allem, wie man ihn erreicht – im eigenen WLAN mit Name, Passwort und
Adresse. Zwei Arten gehen; welche angeschlossen ist, stellt man im Tab **Anzeige**, Karte „Display am Pi“, unter
**Art** ein und speichert.

| Art | Bauteil | Kabel |
|---|---|---|
| 0,96″ OLED (Standard) | 128 × 64 Punkte, I2C, SSD1306 (z. B. AZDelivery), ein paar Euro; 1,3″ mit SH1106 geht auch | 4 |
| 2,8″ mit Touch | 320 × 240 Punkte, Farbe, SPI, ILI9341 mit Touch-Controller XPT2046 (rote Platine 86 × 50 mm, z. B. ARCELI oder AZDelivery, „2,8 Zoll SPI TFT mit Touch“), rund 13 € | 13 |

### Das kleine OLED

| Display | Pi (Stiftleiste) |
|---|---|
| VCC | Pin 1 (3,3 V) |
| GND | Pin 6 (GND) |
| SDA | Pin 3 (GPIO 2) |
| SCL | Pin 5 (GPIO 3) |

Vier Buchse-Buchse-Kabel genügen, nichts wird gelötet. **Nicht an 5 V** anschließen, auch wenn das Display es aushält –
dann lägen die Datenleitungen auf 5 V. Das Installationsskript schaltet I2C ein; nach dem ersten Mal einmal neu starten
(`sudo reboot`).

**Was es zeigt:** solange ein Titel läuft, alle 8 s abwechselnd

- **Wiedergabe:** Spielzeit und Länge, Stück, Titel, Komponist, Fortschritt, Stream (Pakete/s und Zahl der Picos);
- **Netz:** `c64pi.local`, Kabel bzw. WLAN-Name und Adresse, Stream-Verteiler.

Ohne Wiedergabe, ohne Netz und im eigenen WLAN steht nur die Netz-Seite da. Gegen Einbrennen verschiebt sich das Bild
jede Minute um einen Punkt, und nach 10 Minuten ohne Titel wird das Display dunkel (einstellbar, 0 = nie); ein neuer
Titel oder ein Wechsel des Netzes weckt es. Die Karte zeigt, ob und wo das Display gefunden wurde.

### Das 2,8″-Display mit Touch

Jeder Anschluss bekommt ein eigenes Steckkabel (Dupont, Buchse auf Buchse) – **13 Kabel**, gelötet wird nichts. Das
Display hängt am ersten SPI-Bus des Pi, der Touch an einem zweiten; den schaltet das Installationsskript ein (gilt nach
dem nächsten Neustart des Pi).

| Display (Beschriftung) | Pi (Stiftleiste) |
|---|---|
| VCC | Pin 1 (3,3 V) |
| GND | Pin 6 (GND) |
| CS | Pin 24 (CE0) |
| RESET | Pin 22 (GPIO 25) |
| DC | Pin 18 (GPIO 24) |
| SDI (MOSI) | Pin 19 (MOSI) |
| SCK | Pin 23 (SCLK) |
| LED | Pin 12 (GPIO 18) – Hintergrundlicht, wird zum Dunkelschalten ausgeschaltet |
| SDO (MISO) | **frei lassen** |
| T_CLK | Pin 40 (GPIO 21) |
| T_CS | Pin 36 (GPIO 16) |
| T_DIN | Pin 38 (GPIO 20) |
| T_DO | Pin 35 (GPIO 19) |
| T_IRQ | Pin 11 (GPIO 17) |

Pin 1 ist der Stift an der Ecke der Stiftleiste, die zum SD-Kartenschlitz zeigt; die Pins 35–40 sind die letzten drei
Paare am anderen Ende.

**Mit Y-Kabeln** (Dupont 1 Buchse auf 2 Buchsen) geht es auch über einen einzigen SPI-Bus: T_DIN zusätzlich an Pin 19,
T_CLK zusätzlich an Pin 23, T_DO an Pin 21 (MISO), T_CS an Pin 26 (CE1), T_IRQ wie oben. Dann in der Karte **Touch
angeschlossen: „mit Y-Kabeln“** wählen.

**Bleibt das Bild weiß** (Hintergrundlicht an, aber nie ein Bild): Meist kommt die D/C-Leitung nicht an – sie sagt
dem Display, ob ein Befehl oder Bilddaten kommen. Kabel tauschen; hilft das nicht, kann Pin 18 am Pi selbst defekt
sein (schon vorgekommen: der Pin ließ sich nicht mehr auf „high“ schalten). Dann D/C auf **Pin 31** stecken und in der
Karte **D/C an: „Pin 31“** wählen (Pin 31 hat nur andere GPIOs als Nachbarn; Pin 16 geht auch, liegt aber neben GND).

**Nur bei ausgeschaltetem Pi stecken, und GND zuerst und fest.** Fehlt dem Display die Masse, fließt sein Strom über
die Signalleitungen zum Pi zurück – das hat bei einem Aufbau zwei GPIOs des Pi und das Hintergrundlicht des Displays
zerstört. Eine Buchse, die beim Stecken auf den Nachbarstift rutscht, kann einen Pin ebenso gegen GND kurzschließen.

**SDO bleibt frei:** auf vielen dieser Platinen gibt das Display die Leitung nicht frei und stört dann den Touch. Die
4 Stifte für die SD-Karte am anderen Ende der Platine werden nicht gebraucht.

**Einschalten:** in der Karte **Art: „2,8″ mit Touch“** wählen, **Speichern**. Das Installationsskript schaltet SPI
ein; nach dem ersten Mal einmal neu starten (`sudo reboot`). Beim ersten Start zeigt das Display drei Kreuze
nacheinander: jeweils **genau auf das Kreuz tippen** (mit einem Stift oder dem Fingernagel – der Touch ist „resistiv“
und reagiert auf Druck). Danach kennt die Jukebox den Touch; **Touch einrichten** in der Karte wiederholt das. Steht das
Bild auf dem Kopf (Stiftleiste rechts statt links), **Bild um 180° drehen** anhaken – die Touch-Einrichtung bleibt
gültig.

**Was es zeigt** – in den Farben des C64:

- **Wiedergabe:** Spielzeit und Länge, Stück, Titel (zwei Zeilen), Komponist, Jahr, „2 SIDs“, Fortschritt, Stream; unten
  vier Tasten **⏮ ■ ⏭ ⏻** (vorheriger Titel, Stopp – bzw. ▶ Abspielen, wenn nichts läuft –, nächster Titel, Ein / Aus).
  Eine gedrückte Taste blinkt kurz auf.
- **Ein / Aus** (Taste ⏻): **Fernseher an**, **Fernseher aus** (über [HDMI-CEC](#fernbedienung-des-fernsehers-hdmi-cec);
  ist die TV-Fernbedienung ausgeschaltet, sind die beiden Tasten dunkel), **Jukebox ausschalten** (rot – erst ein
  zweiter Tipp innerhalb von 5 s schaltet aus, die Taste sagt dann „Nochmal tippen“) und **Zurück**. Oben rechts steht,
  ob der Fernseher an ist, darunter, was der letzte Tipp bewirkt hat. Nach 30 s ohne Tipp geht es zurück zur Wiedergabe.
- **Pegel:** zwei Balken für links und rechts mit Spitzenhalter (grün, gelb, orange, rot wie die Farben des C64), darunter
  die letzten 15 Sekunden als Säulen, oben der Titel, unten die Spielzeit. Gemessen wird der Audio-Stream des Ultimate,
  viermal pro Sekunde – nur solange die Seite zu sehen ist. Ohne Stream bleiben die Balken leer.
- **Netz:** `c64pi.local`, Kabel bzw. WLAN-Name und Adresse, Stream-Verteiler, Ultimate.
- **Eigenes WLAN:** Name, Passwort und Adresse groß.

Ein Tipp **außerhalb der Tasten** wechselt für 30 s zur nächsten Seite: Wiedergabe → Pegel → Netz → Wiedergabe. Ohne Titel in der Liste und im eigenen WLAN steht
die Netz-Seite da. Nach 10 Minuten ohne Wiedergabe geht das Hintergrundlicht aus (einstellbar, 0 = nie); **der erste
Tipp weckt** das Display nur, erst der zweite bedient. Es werden nur die geänderten Teile des Bildes übertragen – die
Jukebox braucht dafür kaum Rechenzeit.

## Fernseher (HDMI)

Am HDMI-Ausgang zeigt der Pi in **1920 × 1080** die Effekte der PC-Jukebox (deren „Spectrum Analyzer“), passend zur
Musik, die gerade läuft – über schwarzem Grund, über einer **Diashow eigener Bilder** oder über dem **Live-Bild des
C64**. Oben rechts stehen Titel und Komponist, die benötigten SID-Chips mit Adressen, das Jahr und das Unterlied,
unten rechts die Spielzeit.

**Einschalten:** Tab **Anzeige**, Karte **Fernseher (HDMI)**, Haken bei „Bild am HDMI-Ausgang des Pi zeigen“. Darunter
die Karten **Hintergrund am Fernseher** und **Ton am Fernseher**. Jede Änderung in diesen Karten gilt sofort – am Fernseher sieht man gleich, wie ein Effekt oder ein Hintergrund wirkt. Ist der
Haken aus, gibt der Pi den Bildschirm frei (dort erscheint wieder seine Textanzeige).

**Auflösung:** immer 1920 × 1080 bei 60 Hz, auch an einem 4K-Fernseher (der vergrößert das Bild selbst) – so passt es
an jeden Fernseher und Monitor. Das Installationsskript stellt das ein; es gilt nach dem nächsten Neustart des Pi.
Den Fernseher am besten vor dem Einschalten des Pi anschließen.

**Effekte** – dieselben 17 wie in der PC-Jukebox:

| Effekt | |
|---|---|
| Balken | LED-Balken grün/gelb/rot mit Spitzenhalter |
| Netz | die letzten sechs Spektren als Drahtgitter |
| Wolke | schwebende Teilchen; bei Stücken mit 2 SIDs zwei Wolken (linker/rechter Kanal) |
| Oszilloskop | die Schwingung selbst; bei 2 SIDs zwei Kurven |
| Strahlen | Speichen von der Mitte aus |
| Regen / Matrix | fallende Nullen und Einsen, schneller bei lauten Frequenzen |
| C64 Retro | dicke Balken in C64-Farben auf blauem BASIC-Bildschirm (verdeckt den Hintergrund) |
| Kaleidoskop | gespiegelte, gedrehte Fächer |
| Stereo-VU-Meter | zwei Zeigerinstrumente links/rechts |
| Wellenverlauf | Lautstärke als Laufschrift von rechts nach links |
| Schallplatte | drehende Platte, Titel und Komponist auf dem Etikett |
| 3-Stimmen-SID | drei große Balken, je SID eine Zeile mit Adresse (aus dem Klang geschätzt) |
| SID-Stimmen (Noten, vom Ultimate) | die **echten** drei Stimmen jedes SID als Notenrolle – siehe unten |
| Neon-Gitter | 80er-Synthwave: Sonne, Gitter, Neonbalken |
| Night City Glitch | gelbe Balken mit Bildstörungen bei Einsätzen |
| Cyberdeck-Matrix | grüne Balken mit Leuchten, Zielkreuze, Statuszeilen |
| Milkdrop | fließende Form in wechselnden Regenbogenfarben |
| Nur Hintergrund | keine Effekte – z. B. nur das Bild des C64 |

**SID-Stimmen (Noten, vom Ultimate):** Der Ultimate kann jeden Buszyklus des C64 übers Netz schicken
(„Debug-Stream“). Die Jukebox liest daraus mit, was das Stück in die Register der SIDs schreibt, und zeigt für jeden SID
die drei Stimmen als **Notenrolle** der letzten 5 Sekunden: Tonhöhe nach oben, Zeit nach rechts, Stimme 1 rot, 2 grün,
3 blau, je heller, desto lauter (die Hüllkurve wird nachgerechnet). Rechts stehen je Stimme die Note (C64-Schreibweise,
z. B. `A-4`, `H-3`), die Wellenform (Dreieck, Säge, Puls mit Pulsbreite, Rauschen; `F` = läuft durchs Filter) und der
Pegel, über der Rolle Lautstärke und Filter. Der Ausschnitt passt sich in ganzen Oktaven den gespielten Noten an.

- Die Jukebox fordert den Debug-Stream beim gewählten Ultimate an, solange der Effekt zu sehen ist, und meldet ihn
  danach wieder ab. Am Ultimate muss **„Debug Stream Mode“** (Einstellungen des Ultimate, *Data Streams*) einen 6510-Teil enthalten –
  Standard ist „6510 Only“; sonst steht ein Hinweis in der Karte.
- Der Stream braucht ~32 Mbit/s und geht nur über **Kabel**; **nicht zusammen mit dem Hintergrund „Bild des C64“**
  (beides zusammen schafft der Netzanschluss des Ultimate nicht) – dann erscheint ein Hinweis statt der Noten.
- Gezeigt werden die SIDs, die das Stück laut Kopf braucht; ohne diese Angabe jeder SID, in den geschrieben wird.
- Am Elite II gemessen: ~2600 Pakete/s, keines verloren; der Pi braucht dafür nur wenig Rechenzeit.

**Hintergrund:** keiner (schwarz), **Bilder** oder **Bild des C64**. „Helligkeit des Hintergrunds“ dunkelt ihn ab, damit
die Effekte besser hervortreten. Mit Hintergrund werden Balken, Netz und Wolke halb durchsichtig, wie in der
PC-Jukebox.

**Nur das C64-Bild:** Effekt „Nur Hintergrund“, Hintergrund „Bild des C64“. Es erscheint im Seitenverhältnis 4:3 mit
schwarzen Rändern links und rechts – so, wie der C64 auf einem Röhrenfernseher aussah.

**Bilder für die Diashow:** in der Karte „Hintergrund am Fernseher“ **Bilder hochladen …** (JPEG oder PNG, mehrere auf einmal; vom Handy aus auch
direkt aus der Fotosammlung). Der Pi macht aus jedem Bild ein Bild in 1920 × 1080 (füllend, Überstehendes mittig
abgeschnitten) – dann muss er beim Zeigen nichts mehr umrechnen. Höchstens 300 Bilder. Sie wechseln alle 20 s
(einstellbar) mit sanftem Überblenden, auf Wunsch in zufälliger Reihenfolge (ohne dasselbe Bild zweimal hintereinander).
Das ✕ an einem Bild löscht es. Die Bilder liegen auf dem Pi unter `/var/lib/c64jukebox/hdmi-bilder` und sind nicht
Teil der [Sicherung](#sicherung).

**Bilder von einer Quelle** – wie die SIDs von einer Netzwerkfreigabe, einem FTP-Server, dem USB-Stick am Pi oder am
Ultimate: unter „Bilder von“ **einem Ordner** wählen (oder **Ordner wählen …**). Es öffnet sich ein Fenster wie der
Tab **Dateien**: oben die Quellen als Kacheln, darunter die Ordner zum Durchklicken (der Pfad oben springt zurück),
ein Filter und kleine Vorschaubilder der Bilder im Ordner. **Diesen Ordner nehmen** übernimmt den gerade offenen
Ordner, auf Wunsch **mit Unterordnern**. Die
Jukebox holt die Bilder (JPEG/PNG, höchstens 300, je höchstens 40 MB) im Hintergrund, macht sie 1920 × 1080 groß und legt
sie unter `/var/lib/c64jukebox/hdmi-quelle` ab; die Karte zeigt den Fortschritt. Alle 10 Minuten gleicht sie den Ordner
erneut ab (neue Bilder kommen dazu, gelöschte fallen weg) – oder sofort mit **Jetzt abgleichen**. Unveränderte Bilder
werden nicht noch einmal geholt. Die Diashow zeigt die ersten Bilder schon, während der Rest noch kommt.

**„Jetzt läuft“-Karte:** Bei jedem neuen Titel (und jedem neuen Unterlied) erscheint für 6 s (einstellbar 2–30 s)
mitten im Bild eine große Karte mit Titel, Komponist, Jahr, SID-Chips und – falls geladen – den
[STIL-Hintergründen](#stil-hintergruende-zu-den-stuecken); dann blendet sie aus, die kleine Schrift oben rechts bleibt.
Läuft ein Titel schon länger (z. B. weil der Fernseher gerade erst eingeschaltet wurde), kommt keine Karte.
Abschalten: Haken „bei jedem neuen Titel eine große Karte“ in der Karte **Fernseher (HDMI)**.

**QR-Code im Leerlauf:** Läuft nichts, steht oben rechts „Es läuft gerade nichts“ mit der Adresse der Weboberfläche
und daneben ein QR-Code – mit der Kamera des Handys scannen, und die Seite geht auf. Der Code enthält die
IP-Adresse des Pi (viele Android-Handys finden `c64pi.local` nicht). Abschalten: Haken „wenn nichts läuft:
QR-Code“ in der Karte **Fernseher (HDMI)**.

**Effekte im Leerlauf ausblenden:** Läuft kein Titel oder kommt nur Stille, blenden die Effekte nach 20 s (einstellbar)
sanft aus – es bleibt der Hintergrund (Diashow, Bild des C64) mit dem Hinweis „Es läuft gerade nichts“. Mit der Musik
kommen sie zurück. Ausgeblendete Effekte werden nicht berechnet, der Pi hat dann weniger zu tun.

**Effekt automatisch wechseln:** mindestens zwei Effekte ankreuzen und „während der Wiedergabe wechseln“ einschalten;
dann wechselt der Effekt alle 180 s (einstellbar) zufällig – nur während ein Titel läuft. Der oben gewählte Effekt
bleibt die Grundeinstellung.

**Ton über HDMI:** Mit dem Haken „Ton über HDMI zum Fernseher“ spielt der Pi den Ton des Ultimate über HDMI ab.
Der Regler **Lautstärke** (0–100 %, gilt sofort) macht ihn leiser, ohne die Fernbedienung zu suchen – z. B. damit
der Fernseher nicht lauter ist als die anderen Quellen; lauter als das Original wird er nicht. Der Ton kommt etwa 0,2 s später als am Audio-Ausgang des Ultimate; hängt dort
auch eine Anlage, also nur eines von beiden laut stellen, sonst klingt es nach Echo. Läuft der Ultimate-Ton gar nicht
(kein Stream), bleibt der Fernseher still.

**Aus- und Einblenden:** Mit „am Titelende aus-, beim nächsten einblenden“ wird der Ton über HDMI in den letzten
Sekunden eines Titels leiser bis zur Stille (Standard 2 s, einstellbar 0,2–15 s) und der nächste Titel sanft
eingeblendet – wie „Fade between songs“ in der PC-Jukebox. Das geht bei Titeln mit bekannter Länge und bei Titeln
ohne Länge vor dem Zeitlimit (der grauen „Default“-Länge); ein Wechsel wegen Stille kommt unangekündigt. Es wirkt nur auf den Ton über HDMI: Der Audio-Ausgang des Ultimate spielt auf dem echten SID-Chip und
bleibt unverändert. Es ist kein Überblenden – auf dem Ultimate klingt immer nur ein Titel.

### Bluetooth-Kopfhörer

Statt über den Fernseher kann der Ton auch über **Bluetooth-Kopfhörer** (oder einen Bluetooth-Lautsprecher) laufen –
z. B. abends, wenn sonst niemand mithören soll. Der Pi 4 hat Bluetooth eingebaut; nötig sind die Pakete `bluez` und
`bluez-alsa-utils` (das Installationsskript holt sie und hebt die Bluetooth-Sperre auf, mit der Raspberry Pi OS
startet – sonst meldet die Suche nichts).

1. Kopfhörer in den **Kopplungsmodus** bringen (meist die Ein-Taste einige Sekunden halten, bis eine Lampe blinkt).
2. *Anzeige → Bluetooth-Kopfhörer → Kopfhörer suchen* (12 s). Gefundene Kopfhörer stehen darunter: **Koppeln**
   (der Kopfhörer muss dabei noch im Kopplungsmodus sein; die Jukebox sucht ihn vorher kurz noch einmal).
   Beats/AirPods: Ohrhörer ins Case, Deckel offen, Taste am Case etwa 15 s halten, bis die Lampe weiß blinkt.
3. Danach ist **Ton über die Kopfhörer, solange sie verbunden sind** eingeschaltet: Der Ton des Fernsehers geht an die
   Kopfhörer, sobald sie verbunden sind, und zurück an den Fernseher, wenn man sie ausschaltet (die Jukebox sieht alle
   5 s nach). Eingeschaltete Kopfhörer verbinden sich von selbst wieder; sonst hilft **Verbinden**.

Lautstärke und Aus-/Einblenden wirken wie beim Ton am Fernseher. Der Ton kommt über Bluetooth etwa 0,2 s später;
die Effekte am Fernseher laufen ihm dann ein wenig voraus. Der Fernseher-Ausgang (HDMI) muss eingeschaltet sein –
der Ton läuft über denselben Weg. Am Fernseher schaltet **Ton über Kopfhörer** im Menü zwischen Kopfhörern und
Fernseher um. **✕** löscht eine Kopplung. Das Installationsskript stellt Bluetooth auf „klassisch“ (`ControllerMode =
bredr`): Apple- und Beats-Kopfhörer lassen sich über Bluetooth LE nicht koppeln. Suche und Koppeln stehen mit ihrem
Ergebnis im Ereignisprotokoll.

### Fernbedienung des Fernsehers (HDMI-CEC)

Über das HDMI-Kabel kann der Fernseher die Tasten seiner Fernbedienung an den Pi schicken (HDMI-CEC, bei den
Herstellern z. B. *Anynet+*, *SimpLink*, *Bravia Sync*, *VIERA Link*). Einschalten: Tab **Anzeige**, Karte
**TV-Fernbedienung (HDMI-CEC)**, Haken bei „Jukebox mit der Fernbedienung des Fernsehers bedienen“. Der Pi meldet sich
am Fernseher als Abspielgerät „C64-Jukebox“; beim Fernseher muss CEC eingeschaltet sein (oft im Menü „Allgemein“ oder
„Externe Geräte“).

| Taste | |
|---|---|
| ▶ Wiedergabe, ❚❚ Pause | Stopp, wenn Musik läuft – Wiedergabe, wenn gestoppt (auch die gemeinsame ▶❚❚-Taste) |
| ■ Stopp | Stopp |
| ⏭ / ⏮, ⏩ / ⏪, → / ← | nächster / voriger Titel |
| ↑ / ↓ | nächster / voriger Effekt am Fernseher |
| Programm + / − | nächstes / voriges Unterlied |
| **OK** oder eine **Menü-Taste** (Menü, Setup, Inhalt …) | öffnet das **Menü am Fernseher** (ohne HDMI-Bild: OK = Wiedergabe/Stopp wie ▶) |

**Menü am Fernseher:** ↑ ↓ wählen, **OK** oder → ausführen bzw. öffnen, **Zurück** oder ← eine Ebene zurück (in der
obersten: schließen). Nach 30 s ohne Taste schließt es von selbst. Darin:

- **Musik wählen** – ganz oben **In der HVSC suchen** (wenn die HVSC-Songlängen geladen sind): Wörter mit der
  Bildschirmtastatur eingeben, **Fertig** zeigt die Treffer (bis 200; Titel und Komponist wie bei
  [🔍 HVSC](#filtern-und-suchen)). **Alle … abspielen** oder ein Treffer macht aus den Treffern die Wiedergabeliste,
  **Zurück** führt wieder zur Tastatur, um die Wörter zu ändern. Darunter die **Quellen** („Ordner: USB-Stick am Ultimate“ …), dann die Zusammenstellungen
  (★ Favoriten, Meistgespielt, Nie gespielt, Zufällige aus der HVSC, Kurze Stücke, Stücke für 2 oder 3 SIDs) und alle
  gespeicherten Listen; die gewählte spielt sofort. In einer Quelle blättert man durch die Ordner wie im Tab
  **Dateien**: **Diesen Ordner abspielen**, **… mit allen Unterordnern**, **Ordner hinten anhängen**, darunter die
  Unterordner (`Name/ ›`) und die SID-Dateien – eine Datei spielt den Ordner ab ihr. **Zurück** geht einen Ordner
  nach oben. Während der Ordner gelesen wird, steht der Fortschritt in der Hinweiszeile.
- **Ende hier merken** – nur solange ein Titel ohne bekannte Länge läuft: die bisherige Spielzeit wird seine Länge,
  dann kommt der nächste (siehe [Die Wiedergabeliste](#die-wiedergabeliste)). Nach dem Übernehmen einer Länge zeigt das Menü 2 s die Bestätigung
  und schließt sich dann von selbst. Hat die Jukebox die Wiederholung selbst
  gefunden, steht hier stattdessen **Erkannte Länge übernehmen** (siehe [Wiederholung erkennen](#wiederholung-erkennen)),
  hat sie dasselbe Stück in der HVSC gefunden, **HVSC-Länge übernehmen** (siehe [Länge über den Namen](#laenge-ueber-den-namen)).
- **Titel nicht mehr spielen** – fragt nach und setzt den laufenden Titel auf die Sperrliste (siehe
  [Gesperrte Titel](#gesperrte-titel)), dann kommt der nächste.
- **Zufall**, **Wiederholen** – an/aus.
- **Effekt** – alle Effekte zur Auswahl (der laufende ist markiert); eine Wahl schaltet den automatischen Wechsel aus.
- **Bild und Ton** (rechts die Lautstärke) – **Effekte automatisch wechseln**, **Titel einblenden**, **Ton am
  Fernseher** (an/aus), **Ton über Kopfhörer** (nur mit gekoppelten [Bluetooth-Kopfhörern](#bluetooth-kopfhoerer)) und
  **Lautstärke am Fernseher** (jedes OK eine Stufe leiser: 100 → 90 … 10, dann wieder 100).
- **Ultimate** – welches Ultimate spielt: alle eingetragenen (das aktive mit ●), ein anderes wählen (läuft gerade
  Musik, fragt das Menü vorher: sie wird dabei gestoppt). Darunter **Einschalten** / **Ausschalten** für das gewählte
  (über sein WLAN wecken bzw. ausschalten, Ausschalten fragt nach, siehe [Ultimates](#ultimates)). **Im Netzwerk
  suchen** sucht wie im Tab **Geräte** (Fortschritt in der Hinweiszeile); neue Ultimates erscheinen darunter als
  „+ Name“ – OK trägt eins ein und wählt es. Ein Netzwerk-Passwort trägt man auf der Webseite nach.
- **Längen prüfen** – wie auf der Webseite (Fortschritt in der Hinweiszeile des Menüs); danach erscheint
  **22 HVSC-Längen übernehmen**.
- **Nach Update sehen** – fragt GitHub nach einer neuen Version (rechts steht die installierte). Gibt es eine, heißt
  die Zeile **Update auf … installieren**: OK fragt nach und installiert sie, die Jukebox startet dabei neu (siehe
  [Aktualisieren](#aktualisieren)).
- **Ausschalten** – steht unten, direkt nach dem Öffnen also mit zweimal ↑ erreichbar: **Fernseher ausschalten**
  (sofort), **Jukebox ausschalten** (fragt nach; mit eingerichteter Steckdose geht danach auch der Strom aus, siehe
  [Ausschalten und Steckdose](#ausschalten-und-steckdose)) und **Ultimate ausschalten** (fragt nach).
- Eine **gespeicherte Liste** in „Musik wählen“ öffnet ein kleines Menü: **Abspielen**, **Hinten anhängen**,
  **Umbenennen** (eine Tastatur am Bildschirm: Pfeile wählen, OK tippt, Zurück löscht das letzte Zeichen, „Fertig“
  übernimmt) und **Löschen** (fragt nach, „Nein“ ist vorgewählt).

▶, ■, ⏭ und ⏮ wirken auch bei offenem Menü. Welche Tasten ein Fernseher (oder ein Fire TV Cube dazwischen) über HDMI-CEC
weitergibt, ist verschieden: jede ankommende Taste steht mit ihrem Code im Ereignisprotokoll (`/api/events`,
„Fernbedienung: Taste 0x… (…)“).

Die meisten Fernseher schicken die Tasten nur an das Gerät, das sie gerade zeigen – also erst auf den Eingang des Pi
umschalten (oder **Fernseher jetzt auf den Pi umschalten**). Das geht auch, wenn der Pi am HDMI-Eingang eines anderen
Geräts hängt (am Gerät geprüft mit einem Fire TV Cube): dann **Fernseher jetzt auf den Pi umschalten** tippen, danach
kommen die Tasten der Fernseher-Fernbedienung an. Die Fernbedienung des Fire TV steuert weiter den Fire TV.

- **Beim Abspielen als aktives Gerät melden** (an): Bei jedem Start der Wiedergabe meldet sich der Pi beim Fernseher als
  das Gerät, das er zeigt – dann kommen die Tasten an, ohne dass man vorher etwas antippen muss, auch nach einem
  Neustart des Pi. Manche Fernseher schalten dabei auf den Eingang des Pi um; wen das stört, nimmt den Haken heraus.

- **Fernseher einschalten …, wenn die Wiedergabe beginnt:** startet man die Musik am Handy, geht der Fernseher an und
  schaltet auf den Pi. Achtung: auch, wenn gerade jemand fernsieht.
- **Fernseher ausschalten, wenn nichts mehr läuft – nach N min:** nur, wenn der Fernseher gerade den Pi zeigt.
- **Fernseher einschalten …, wenn der Pi startet:** sobald der Pi nach dem Einschalten (z. B. „Alexa, schalte Jukebox
  ein“ über die [Steckdose](#ausschalten-und-steckdose)) am HDMI-Kabel bereit ist, geht der Fernseher an und zeigt den
  Pi – nur in den ersten 90 s nach dem Start, damit ein später eingeschalteter Fernseher nicht auf den Pi springt.
  Später schaltet **Fernseher jetzt auf den Pi umschalten** den Fernseher jederzeit ein.
- **Jukebox ausschalten, wenn der Fernseher ausgeht:** eine Minute nach dem Standby des Fernsehers fährt der Pi herunter
  (mit Steckdose auch der Strom), siehe [Ausschalten und Steckdose](#ausschalten-und-steckdose).

Die Zeile darunter zeigt den Zustand: „Warte auf den Fernseher …“ heißt, der Pi hat noch keine Adresse am HDMI-Kabel
(Fernseher aus oder CEC am Fernseher abgeschaltet). Der Pi braucht dafür kein zusätzliches Programm.

### Retro-News

Auf Wunsch zeigt der Fernseher aktuelle Meldungen aus der Retro-Szene – Karte **Retro-News am Fernseher** im Tab
**Anzeige**:

- **im Leerlauf zeigen:** sind die Effekte ausgeblendet, erscheint eine große Karte mit Quelle, Datum, Schlagzeile,
  Kurztext und (wenn die Meldung eins hat) Bild; alle 15 s (einstellbar) die nächste.
- **als Laufband:** während der Musik laufen die Schlagzeilen unten durchs Bild; die Spielzeit rückt darüber.

Unter *Nachrichtenquellen* stehen die bekannten Seiten zur Auswahl – ein Haken schaltet eine Quelle sofort ein oder aus:

| Quelle | Sprache | | voreingestellt |
|---|---|---|---|
| Indie Retro News (`indieretronews.com`) | englisch | Retro-Spiele aller Systeme, mit Bildern | an |
| amiga-news.de | deutsch | Amiga-Meldungen, nur Schlagzeilen | an |
| Commodore News (`commodore-news.com`) | deutsch | Commodore/Amiga, mit Kurztext | an |
| Cascade64 (`cascade64.de`) | englisch | Commodore-Neuheiten, mit Bildern | an |
| The Oasis BBS (`theoasisbbs.com`) | englisch | C64/Amiga, mit Bildern | an |
| BrewOtaku (`brewotaku.com`) | englisch | Homebrew-Magazin, alle Systeme | aus |
| PDRoms (`pdroms.de`) | englisch | Homebrew-Neuheiten aller Systeme | aus |

Weitere RSS- oder Atom-Feeds kommen mit **+ Quelle** dazu (Name und Adresse, dann **Speichern**); Namen und Adressen
lassen sich in der Liste ändern, das ✕ entfernt eine Quelle, **Standard-Quellen** stellt die Liste oben wieder her.
Höchstens 20 Quellen. Die Jukebox holt die Feeds alle 30 Minuten (sofort mit **Jetzt
laden**), bei jeder Quelle steht, wie viele Meldungen kamen oder welcher Fehler. Gezeigt werden 40 Meldungen, die
Quellen **abwechselnd**: erst die neueste jeder Quelle, dann die zweitneueste jeder Quelle und so weiter (innerhalb
einer Runde die neueste zuerst) – so steht Aktuelles vorn, und eine Quelle mit vielen Meldungen an einem Tag füllt
nicht den Bildschirm am Stück; je Quelle höchstens 15; Bilder macht die Jukebox klein (640 × 400), bevor der Fernseher sie
bekommt. Dafür braucht der Pi Internet.

**Woher Ton und Bild kommen:**

- Der **Ton** für die Effekte kommt vom [Stream-Verteiler](#stream-verteiler): Ist die HDMI-Ausgabe an, holt der Pi den
  Audio-Stream des Ultimate auch dann, wenn der Haken beim Stream-Verteiler aus ist – die eingetragenen Picos
  bekommen ihn dann ebenfalls weitergereicht.
- Das **Bild des C64** schickt das ausgewählte Ultimate auf Anfrage des Pi direkt zu ihm (rund 22 Mbit/s, nur über das
  Netzwerkkabel des Ultimate). Wie für den Ton müssen im Ultimate die *Data Streams* erlaubt sein.
- **Das Ultimate schickt sein Bild nur an ein Ziel.** Nutzt die PC-Jukebox gleichzeitig das „Ultimate64 Video Stream“ als
  Hintergrund ihres Spectrum Analyzers, nehmen sich PC und Pi das Bild gegenseitig weg – dort dann Bilder als
  Hintergrund wählen. Wird „Bild des C64“ hier abgewählt, meldet der Pi das Bild beim Ultimate wieder ab.

**Last:** Die HDMI-Ausgabe läuft als eigener Dienst (`c64pi-hdmi`) mit niedrigerer Priorität als Jukebox und
Stream-Verteiler. Der Grafikchip vergrößert und überblendet; der Prozessor zeichnet nur die Effekte in halber Auflösung
(960 × 540). Am Pi 3B laufen alle Effekte mit 30 Bildern/s; der Dienst braucht dafür etwa die Hälfte eines der vier
Prozessorkerne, mit dem Bild des C64 knapp einen. Die Karte zeigt, wie viele Bilder es gerade sind und ob Ton und Bild
ankommen.

## Geräte im Netz

Wie die Picos meldet sich der Pi alle 10 s im Heimnetz (als Art „Raspberry Pi“, mit dem gerade laufenden Titel).
Die Karte **Geräte im Netz** im Tab „Geräte“ zeigt alle Picos und Pis mit Adresse, Firmware-Stand und Stream sowie den
**Weg des Tons**, z. B. „Elite II (192.168.1.168) → c64pi 250/s → [c64audio 250/s, c64viz 250/s]“.
**Neu suchen** fragt alle Geräte sofort. Den Namen, unter dem der Pi dort erscheint, legt man in derselben Karte unter
*Name des Pi in dieser Liste* fest.

## Ausschalten und Steckdose

*Einstellungen → Ausschalten und Steckdose → **Jukebox ausschalten***, oben rechts auf jeder Seite der Knopf ⏻ →
**Jukebox ausschalten**, im Menü am Fernseher **Ausschalten → Jukebox ausschalten** oder am
[Touch-Display](#das-2-8-display-mit-touch) ⏻ → **Jukebox ausschalten**
stoppt die Musik und fährt den Pi sauber herunter. Einfach den Strom wegnehmen sollte man nicht: Das kann die
SD-Karte beschädigen.

Hängt der Pi an einer **smarten Steckdose mit Tuya-Technik** (z. B. Antela, App „Smart Life“ oder „Tuya Smart“),
stellt er vor dem Herunterfahren ihren eingebauten **Ausschalt-Timer**: Nach *Strom aus nach* Sekunden (Standard 30,
mindestens 20 – der Pi braucht etwa 10 s) schaltet die Steckdose ab. Eingeschaltet wird über die App oder per Sprache,
z. B. „Alexa, schalte Jukebox ein“ – der Pi startet, sobald Strom da ist. „Alexa, schalte Jukebox **aus**“ besser nicht
benutzen: Das nimmt dem laufenden Pi den Strom.

Antwortet die Steckdose nicht, bleibt der Pi an (die Seite fragt, ob er trotzdem herunterfahren soll – der Strom bleibt
dann an). Scheitert das Herunterfahren selbst, nimmt die Jukebox den Timer sofort zurück.

**Einrichten.** Die Jukebox schaltet die Steckdose direkt im Heimnetz (ohne Cloud). Dafür braucht sie
die **Geräte-ID** und den **lokalen Schlüssel** der Steckdose. Beides zeigt die Tuya-Entwicklerplattform (kostenloses
Konto, einmalig etwa 15 Minuten):

1. Auf [platform.tuya.com](https://platform.tuya.com) ein Konto anlegen, *Cloud → Development → Create Cloud Project*
   (Rechenzentrum *Central Europe*, die vorgeschlagenen Dienste übernehmen).
2. Im Projekt *Devices → Link App Account → Add App Account*: den QR-Code mit der App „Smart Life“ scannen
   (*Ich → Scan-Symbol oben rechts*). Danach stehen alle Geräte der App mit ihrer **Device ID** in der Liste.
3. Den lokalen Schlüssel zeigt *Cloud → API Explorer → Device Management → Query device details* für die Device ID
   (Feld `local_key`). Wer Python hat, bekommt beides auch mit `python3 -m tinytuya wizard`.
4. In der Karte **Geräte-ID** und **Lokaler Schlüssel** eintragen, **Prüfen** tippen: Die Jukebox sucht die Steckdose im
   Netz (die Adresse darf leer bleiben), zeigt ob sie an ist, ihre Leistung und ob sie einen Ausschalt-Timer hat.

**Mit dem Fernseher aus.** *Anzeige → TV-Fernbedienung → Jukebox ausschalten, wenn der Fernseher ausgeht*: Geht der
Fernseher in Standby – mit seiner Fernbedienung, durch die Jukebox (*Fernseher ausschalten, wenn nichts mehr läuft*) oder
über die Seite –, fährt der Pi eine Minute später herunter, mit eingerichteter Steckdose geht danach der Strom aus.
Kommt der Fernseher in dieser Minute wieder, bleibt der Pi an. Die Jukebox hört dafür auf die Standby-Meldung des
Fernsehers und fragt ihn alle 30 s, ob er an ist (HDMI-CEC muss eingeschaltet sein). Sie reagiert nur auf ein Ausgehen,
das sie selbst gesehen hat: Startet der Pi bei ausgeschaltetem Fernseher (z. B. für Musik nur über die Picos), bleibt
er an. Solange Bluetooth-Kopfhörer verbunden sind, bleibt er ebenfalls an. Die Karte zeigt, ob der Fernseher an ist
und wann der Pi ausgeht; das Ereignisprotokoll nennt jeden Schritt.

Der Schlüssel ändert sich, wenn man die Steckdose in der App neu einrichtet – dann wieder holen. Die Steckdose sollte im
Router eine feste Adresse bekommen; sonst sucht die Jukebox sie bei jedem Prüfen neu. Damit der Pi sich selbst
ausschalten darf, legt das Installationsskript eine polkit-Regel an; fehlt sie, sagt die Karte das.

## Sicherung

*Einstellungen → Sicherung → Sicherung herunterladen* speichert eine Datei `c64pi-sicherung-<Datum>.json` mit allen
Einstellungen, Quellen samt Passwörtern, Ultimates, Picos, Wiedergabelisten, der aktuellen Liste, den eigenen
Songlängen, den Zählern, Favoriten und gesperrten Titeln. Die Datei deshalb gut aufheben. Das Web-Passwort ist nur als Prüfsumme enthalten.

**Sicherung einspielen** ersetzt alles durch den Stand der Datei – auch auf einem neu installierten Pi. Die
HVSC-Songlängen sind nicht in der Sicherung (die Datei ist groß und kommt aus der HVSC); einfach neu laden.

Wer lieber Dateien sichert: alles liegt im Ordner `/var/lib/c64jukebox` auf dem Pi, z. B.

```
sudo tar czf c64jukebox-daten.tgz -C /var/lib c64jukebox
```

### Passwort vergessen

Per SSH am Pi anmelden und das Passwort auf `commodore64` zurücksetzen:

```
sudo systemctl stop c64jukebox
sudo sed -i 's/"pw_hash": "[^"]*"/"pw_hash": ""/' /var/lib/c64jukebox/config.json
sudo systemctl start c64jukebox
```

## Fehlersuche

| Meldung / Beobachtung | Ursache und Abhilfe |
|---|---|
| Seite `c64pi.local` geht nicht | Pi noch nicht hochgefahren, oder das Gerät kennt keine `.local`-Namen (manche Android-Handys): die IP-Adresse aus dem Router nehmen |
| „Kein Ultimate eingetragen“ | Tab „Geräte“: Ultimate eintragen und speichern |
| „Ultimate … nicht erreichbar“ | Ultimate aus, falsche Adresse, oder *Web Remote Control* im Ultimate aus |
| „Ultimate lehnt ab: Netzwerk-Passwort falsch?“ | Netzwerk-Passwort beim Ultimate eintragen |
| „Ultimate hängt („Network Host Resolve Error“)“ | Das Ultimate findet den Pi nicht mehr und nimmt keinen Stream an ihn an (beim Ultimate 64 Elite II mit Firmware 3.15a mehrfach beobachtet, oft mit ein paar Paketen über sein WLAN). Der Pi meldet sich dann von selbst neu beim Ultimate an (höchstens alle 30 s, „… Pi hat sich beim Ultimate neu gemeldet“). Hilft das nicht: **den Pi neu starten** – das brachte den Ton bisher jedes Mal sofort zurück. In der Zwischenzeit holt sich der Audio-Empfänger den Stream selbst |
| „SMB-Anmeldung abgelehnt“ | Benutzer/Passwort; bei Windows mit Microsoft-Konto die E-Mail-Adresse als Benutzer |
| „SMB-Server … nicht erreichbar“ | Rechner aus, Name falsch (IP probieren), Freigabe im Betriebssystem nicht eingeschaltet |
| Freigaben werden nicht angezeigt | manche NAS zeigen sie nur angemeldeten Benutzern: Benutzer/Passwort eintragen; sonst den Namen der Freigabe von Hand eintragen |
| „FTP-Server … nicht erreichbar“ beim Ultimate | FTP-Dienst im Ultimate einschalten (*Network → FTP Server*) |
| Ordner mit SIDs zeigt „…“ statt Titel | die Kopfdaten werden gerade gelesen; bei sehr großen Ordnern über SMB dauert das beim ersten Mal |
| „Ultimate antwortet mit Fehler 404“ beim Stream | das Ultimate meldet manchmal „Network Host Resolve Error“; der Pi fragt nach 10 s erneut, meist klappt es dann |
| „Wartet auf den Stream …“ | im Ultimate *Data Streams* erlaubt? Ultimate über Kabel angeschlossen? Ein Pico im Modus Unicast holt sich den Stream zurück: dort „weitergeleitet“ wählen |
| Titel springt zu früh weiter | „nach N s Stille“: Stück mit langer Pause – Sekunden erhöhen oder abschalten |
| Titel läuft endlos | keine Songlänge bekannt und Zeitlimit 0: Songlängen laden oder ein Zeitlimit setzen |
| Display: „nicht gefunden (… spidev0.0)“ | SPI ist aus: `sudo raspi-config nonint do_spi 0` und neu starten (das Installationsskript macht das) |
| 2,8″-Display bleibt weiß | Verdrahtung prüfen (DC, RESET, CS, MOSI, SCK); ein weißes Bild heißt: Strom ist da, aber keine Befehle kommen an |
| Karte „Fernseher“: „Der HDMI-Dienst meldet sich nicht“ | `systemctl status c64pi-hdmi` und `journalctl -u c64pi-hdmi -e` auf dem Pi; nach der ersten Installation einmal neu starten |
| Fernseher bleibt schwarz, die Karte meldet aber Bilder/s | läuft gerade ein Titel? Ohne Musik sind die Balken fast schwarz – oben rechts steht dann „Es läuft gerade nichts“; sonst einen helleren Effekt (C64 Retro) wählen |
| Kein Ton am Fernseher | Haken „Ton über HDMI zum Fernseher“ gesetzt? Fernseher nicht stumm? Die Karte zeigt „Ton über HDMI“, wenn er läuft |
| Fernseher zeigt „kein Signal“ | Fernseher auf den richtigen HDMI-Eingang stellen; den Pi bei angeschlossenem Fernseher neu starten |
| „kein Bild vom C64“ | im Ultimate *Data Streams* erlauben; Ultimate über Netzwerkkabel; nutzt die PC-Jukebox das Bild gerade? (siehe [Fernseher (HDMI)](#fernseher-hdmi)) |
| „keine SID-Daten vom Ultimate“ | „Debug Stream Mode“ des Ultimate auf „6510 Only“; Ultimate über Netzwerkkabel; Hintergrund nicht „Bild des C64“ (siehe [Fernseher (HDMI)](#fernseher-hdmi)) |
| „kein Ton“ in der Karte „Fernseher (HDMI)“ | das Ultimate liefert keinen Audio-Stream: Karte „Picos und Stream-Verteiler“ ansehen |
| Effekte ruckeln | einfachere Effekte wählen (Balken, Netz, Strahlen); die Diashow braucht beim Bildwechsel kurz Rechenzeit |
| Touch reagiert nicht oder an falscher Stelle | **Touch einrichten** in der Karte; T_IRQ, T_CS, T_DO, T_DIN, T_CLK prüfen; SDO des Displays muss frei sein |

Das Protokoll des Dienstes zeigt `journalctl -u c64jukebox -e` auf dem Pi.

## Anhang

### Dateien auf dem Pi

| Ort | Inhalt |
|---|---|
| `/opt/c64jukebox` | das Programm mit eigener Python-Umgebung (`venv`) |
| `/var/lib/c64jukebox/config.json` | alle Einstellungen |
| `/var/lib/c64jukebox/playlists/` | gespeicherte Wiedergabelisten (JSON) |
| `/var/lib/c64jukebox/current.json` | die aktuelle Wiedergabeliste |
| `/var/lib/c64jukebox/songlengths-*.txt` | geladene Songlängen |
| `/var/lib/c64jukebox/stil.txt` | geladene STIL (Hintergründe zu den Stücken) |
| `/var/lib/c64jukebox/history.json` | zuletzt gespielte Titel |
| `/var/lib/c64jukebox/cache.db` | gemerkte SID-Kopfdaten und Ordnerlisten (darf gelöscht werden) |
| `/etc/systemd/system/c64jukebox.service` | der Dienst |
| `/etc/systemd/system/c64pi-net.service` | der Netzwerk-Wächter (läuft als root, steuert NetworkManager) |
| `/run/c64pi/net.json` | was der Netzwerk-Wächter gerade tut |
| `/var/lib/c64jukebox/stats.json` | Zähler „Gespielt“ und Favoriten |
| `/etc/udev/rules.d/99-c64jukebox-usb.rules` | automatisches Einhängen von USB-Sticks |
| `/var/lib/c64jukebox/hdmi-bilder/` | die Bilder für die Diashow am Fernseher (1920 × 1080, JPEG) |
| `/etc/systemd/system/c64pi-hdmi.service` | die HDMI-Ausgabe (System-Python mit `python3-pygame`, `python3-numpy`) |
| `/run/c64pi/hdmi-in.json`, `/run/c64pi/hdmi.json` | Einstellungen und laufender Titel für die HDMI-Ausgabe, deren Zustand |

Deinstallieren: `sudo systemctl disable --now c64jukebox`, dann die Dateien oben löschen.

### HTTP-Schnittstelle

Alle Anfragen unter `/api/` brauchen die Anmeldung (Cookie aus `POST /api/login` mit `{"pw": "…"}`); jedes `POST`
braucht zusätzlich den Kopf `X-C64: 1`. Antworten sind JSON. **Auf dem Pi selbst** (Adresse 127.0.0.1, z. B. nach
`ssh nutzer@c64pi.local`) entfällt die Anmeldung, der Kopf `X-C64: 1` bleibt Pflicht – so lässt sich die Jukebox über
SSH steuern:

```
curl -s -H 'X-C64: 1' -H 'Content-Type: application/json' -d '{"c":"next"}' http://127.0.0.1/api/ctl
```

Wer das nicht möchte, trägt in `/etc/systemd/system/c64jukebox.service` hinter `--port 80` noch `--no-local-admin` ein.

| Anfrage | Bedeutung |
|---|---|
| `GET /api/state` | Zustand: laufender Titel, Spielzeit, Stream, Ultimates |
| `POST /api/ctl` `{"c":"next"}` | `play`, `pause` (wechselt), `stop`, `next`, `prev`, `goto` + `i`, `song` + `n`, `remove` + `i`, `clear`, `shuffle` + `on`, `block` (laufender Titel, oder + `i`), `unblock` + `key` oder `i` |
| `POST /api/search` `{"src","path","q"}` | Suche (Auftrag; in der HVSC sofort aus dem Verzeichnis) |
| `GET /api/hvsc/titles`, `POST /api/hvsc/titles` | Wie viele HVSC-Dateien die Suche mit Titel kennt (`n` von `of`) / Titel einlesen (Auftrag) |
| `POST /api/update/check` | Jetzt auf GitHub nach einer neuen Version sehen (`ver`, `newer`, `installed`) |
| `POST /api/update/install` | Die neuere Version installieren (Dienst `c64jukebox-update`, die Jukebox startet dabei neu); Fortschritt und Ergebnis in `/api/state` unter `upd` (`running`, `last`) |
| `GET /api/power`, `POST /api/power/off` `{"force"}` | Darf der Pi sich ausschalten, ist eine Steckdose eingerichtet / Steckdosen-Timer stellen und herunterfahren (`timer`, `secs`) |
| `POST /api/plug/check` | Steckdose fragen (Auftrag: `ip`, `ver`, `on`, `timer`, `secs`, `watt`) |
| `GET /api/bt?devices=1`, `POST /api/bt` `{"act","mac"}` | Bluetooth-Kopfhörer: Zustand und gekoppelte Geräte / `scan`, `pair` (Aufträge), `connect`, `disconnect`, `forget`, `on` + `on` |
| `GET /api/blocked` | Sperrliste: `items` mit `key`, `title`, `author`, `path`, `at` |
| `POST /api/queue` | Titel in die Liste: `{"mode":"replace","items":[{"src":…,"path":…}],"start":0}`; `mode` auch `add` oder `next` |
| `POST /api/folder` | Ordner abspielen: `{"src","path","recursive","shuffle","mode"}` |
| `GET /api/ls?src=…&path=…` | Ordnerliste |
| `GET /api/list` | Wiedergabeliste |
| `GET /api/devices` | Geräte im Netz (wie `GET /devices` der Picos) |
| `GET /api/sidcfg` | SID-Adressen des gewählten Ultimate (und ein gerade umgestellter Sockel) |
| `POST /api/display/calibrate` | Touch einrichten: das 2,8″-Display zeigt die drei Kreuze |
| `GET /api/hdmi`, `POST /api/hdmi` `{"on":true,"mode":"milkdrop","bg":"video"}` | HDMI-Ausgabe: Einstellungen (auch `auto`, `auto_s`, `auto_modes`, `img_s`, `shuffle`, `opacity`, `osd`), Zustand, Bilder |
| `POST /api/hdmi/upload?name=…` (die Datei), `POST /api/hdmi/delete` `{"name":…}` | Bilder der Diashow |
| `GET /api/backup`, `POST /api/restore` | Sicherung |

### Netzwerk-Protokolle

Wie bei den Picos (siehe deren Handbuch, Anhang „Netzwerk-Protokolle“):

| Port | Richtung | Inhalt |
|---|---|---|
| UDP 11001 | Ultimate → Pi → Picos | Audio-Stream (770 Byte je Paket), unverändert weitergereicht; dazu `C64NP1 <Abfrage>` mit den Parametern von `/jb/np` |
| UDP 11000 | Ultimate → Pi | Video-Stream (780 Byte je Paket: 4 Zeilen à 384 Punkte, 16 Farben), nur bei „Bild des C64“ |
| UDP 11002 | Pi intern | Kopie jedes Audio-Pakets für die HDMI-Ausgabe (127.0.0.1) |
| UDP 11064 | alle | Gerätemeldungen `C64DEV1 {JSON}` alle 10 s per Broadcast, `C64DEV1?` fragt alle |
| TCP 80 | Browser → Pi | Weboberfläche |
| TCP 80 | Pi → Ultimate | REST: `PUT /v1/runners:sidplay?file=…&songnr=…`, `POST /v1/runners:sidplay` (Datei), `PUT /v1/machine:reset` (ebenso `pause`, `resume`), `PUT /v1/streams/audio:start?ip=<pi>:11001`, `PUT /v1/streams/video:start?ip=<pi>:11000` (und `:stop`), `GET /v1/configs/SID%20Addressing`, `PUT /v1/configs/SID%20Addressing/SID%20Socket%20<n>%20Address?value=%24D420`, `GET /v1/info` |
| TCP 21 | Pi → Ultimate/FTP-Server | Ordner und Dateien |
| TCP 445 | Pi → NAS/PC | SMB-Freigaben |

Die Gerätemeldung des Pi: `t` = `"pi"`, `n` Name, `ip`, `b` Version, `up` Sekunden seit dem Start, `st` Verteiler an,
`rx` Pakete/s vom Ultimate, `from` dessen Adresse, `fw` die Picos (durch Kommas getrennt), `fwip` Adresse des ersten,
`fp` Pakete/s an die Picos, `src`/`srcl` gewähltes Ultimate, `title` laufender Titel.
