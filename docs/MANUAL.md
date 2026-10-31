# C64 Jukebox for the Raspberry Pi – Manual

The C64 Jukebox turns a **Raspberry Pi 3B** into a SID jukebox for the **Ultimate 64**, the **C64 Ultimate**
and the **Ultimate II+**. It runs around the clock, is operated entirely through a web page – on a phone just as well
as on a PC – and fetches the SID files from wherever they are: from a **network share** (NAS, Windows PC, Mac), from
an **FTP server**, from the **USB stick on the Ultimate** or from a **USB stick on the Pi**.

On the side, the Pi is the **stream distributor** for the Pico devices: it receives the Ultimate's audio stream over
the network cable and passes it on to any number of visualizers and audio receivers. The Picos also show the tune,
composer and playing time. On its **HDMI output** the Pi shows the effects of the PC jukebox on the TV – over a
slide show of your own pictures or over the live picture of the C64.

## What the jukebox can do {#was-die-jukebox-kann}

- Choose SID files with a tap: click through folders as in a file manager, filter, search in all
  subfolders. Every file shows its title, composer, year, number of sub-tunes and SIDs.
- Play with a click, **“Play folder”** including subfolders, Shuffle, Repeat list.
- Changes exactly at the end of a tune using the HVSC song lengths file, otherwise after a time limit or after a few
  seconds of silence.
- Save and load play lists.
- Several Ultimates, with a choice of which one plays.
- Tune display on the Pico visualizers and passing the audio stream on to all Picos.
- Announces itself in the Picos' “Devices on the network” list and shows them itself.
- On the TV (HDMI, 1920 × 1080): the 17 effects of the PC jukebox, the real SID voices as a piano roll, a slide show of your own pictures, the picture of the C64, tune
  and playing time overlaid, a “Now playing” card, sound with fade-out/fade-in, Retro news, control with the
  TV's remote (HDMI-CEC).
- If needed, switches a SID socket of the Ultimate to the address a tune requires, and marks tunes
  that do not fit – like the PC jukebox.
- Background information on the tune from the HVSC's STIL, a “Recently played” history, a block list for tunes that
  should no longer come up by themselves.
- Password protection, backup of all settings in one file.

## What you need {#was-man-braucht}

| Part | Note |
|---|---|
| Raspberry Pi 3B (or newer) | 1 GB RAM is enough, the jukebox needs about 50 MB, with the HVSC song lengths file about 80 MB |
| microSD card | 8 GB or more |
| Power supply | the official 5 V power supply (2.5 A) |
| Network cable | recommended; Wi-Fi works too, the stream distributor is most reliable over a cable |
| optionally a display | 0.96″ OLED (I2C, a few euros) or 2.8″ colour display with touch (SPI, ILI9341, about €13) – see [Display](#display) |
| optionally a TV or monitor | via HDMI (micro HDMI cable for the Pi 4/5, a normal one for the Pi 3B) – see [TV (HDMI)](#fernseher-hdmi) |
| Ultimate | with web remote control switched on (*Network → Web Remote Control*) and the FTP service for the USB stick |

Nothing is soldered to the Pi and nothing is connected except power, network and, if you like, a USB stick and a
display (jumper wires). A case for 3D printing – a small “breadbin” with a mini monitor for the 2.8″ display –
is in the project's `case/` folder.

## Installation {#installation}

### Raspberry Pi OS on the card {#raspberry-pi-os-auf-die-karte}

1. Start the **Raspberry Pi Imager** on your PC or Mac.
2. Choose the device *Raspberry Pi 3* and the operating system **Raspberry Pi OS Lite (64-bit)** (without desktop; currently “Trixie”,
   the older “Bookworm” works too).
3. In the Imager's settings: host name `c64pi`, set a user name and password, **switch on SSH**,
   enter the Wi-Fi if needed.
4. Write the card, put it in the Pi, connect the network cable and power. After one or two minutes the Pi is on the
   network as `c64pi.local`.

### Installing the jukebox {#jukebox-installieren}

**Directly on the Pi (easiest):** log in to the Pi via SSH (`ssh <benutzer>@c64pi.local`, user name as set in the
Imager), fetch the project from GitHub and start the installation script:

```
sudo apt install -y git
git clone https://github.com/sedorrr/c64-pi-jukebox
cd c64-pi-jukebox
sudo ./install/install.sh
```

It also works without git: on GitHub **Code → Download ZIP**, copy the file to the Pi
(`scp c64-pi-jukebox-main.zip <benutzer>@c64pi.local:`), there `unzip c64-pi-jukebox-main.zip` (if necessary `sudo apt install -y unzip` first),
`cd c64-pi-jukebox-main` and `sudo ./install/install.sh`.

**From a Mac or Linux PC:** if the project is already on the PC (cloned or unpacked), this command in the
project folder copies everything to the Pi and starts the installation there (it asks for the Pi's sudo password):

```
./install/deploy.sh <benutzer>@c64pi.local
```

The script

- installs Python, the name service (mDNS) and the Python libraries (`aiohttp`, `smbprotocol`, `pysmb`) into a
  folder of its own, `/opt/c64jukebox`,
- creates the user `c64jukebox` that the jukebox runs as (not as root),
- sets up the service `c64jukebox`, which starts at power-on and restarts itself after an error,
- sets up the service `c64pi-net`, which opens a Wi-Fi of its own when there is no cable and no known Wi-Fi (see
  [The Pi's network](#netzwerk-des-pi)), and switches on I2C and SPI for the [Display](#display),
- sets up the service `c64pi-hdmi` for the [TV](#fernseher-hdmi) (with `python3-pygame` and `python3-numpy`
  from the package sources) and fixes the HDMI output to 1920 × 1080 at 60 Hz (applies after the next restart),
- mounts plugged-in USB sticks automatically (read-only) under `/media/usb`,
- sets the host name to `c64pi` – the page can then be reached at **http://c64pi.local/**. If you want to keep your
  host name: `sudo ./install/install.sh --keep-hostname`.

### Updating {#aktualisieren}

The jukebox checks for a new version itself: once a day it reads the version number of the
published program on GitHub (`github.com/sedorrr/c64-pi-jukebox`, only this one small file, without
any information about the Pi). If it is higher than the installed one, a blue notice appears at the top of the page (✕ hides it
for this version), and in the TV menu the line **Check for update** then reads **Install update …**.
To switch this off or check right away: *Settings → System → Updates*, or **Check for update** in the TV menu.

**Installing on command.** The jukebox never installs anything by itself. Only **Install** in the blue notice or
under *Updates*, or **Install update …** in the TV menu (both ask for confirmation), starts the update:

1. The Pi downloads the published program from GitHub (the ZIP of the `main` branch).
2. Then its installation script runs as for a manual update (with `--keep-hostname`, the host name
   stays). It fetches missing packages and restarts the jukebox. This takes a few minutes; the music from the TV
   pauses during that time.
3. Afterwards the page comes back with the new version, and on the TV the menu shows “Update to … installed”.

If the installation fails, the old program comes back, and the page and the TV give the reason. The log
is in `/var/lib/c64jukebox/update.log`. Settings, lists and song lengths are kept in any case.

For this, the jukebox, which otherwise runs without privileges, may start exactly one service (`c64jukebox-update`, a polkit rule from
the installation script). Only an installation script from this version on sets it up. If you are coming from an older
version, you therefore update **once by hand**: on the Pi, in the project folder, `git pull` followed by
`sudo ./install/install.sh`, or run `./install/deploy.sh` again from the PC.

### First start {#erster-aufruf}

1. Open **http://c64pi.local/** in the browser (if the name does not work, use the Pi's IP address from the router).
2. Log in with the password `commodore64` – the same default password as on the Picos. A yellow bar reminds
   you to change it under *Settings → Web password*.
3. In the **Devices** tab, enter the Ultimate (**Search the network** finds it) and **Save**.
4. In the **Files** tab, choose or set up a source, tap a tune – it plays.

Tip for phones: add the page to the home screen in the browser (“Add to Home Screen”), then it opens like an app.

## The web interface {#die-weboberflaeche}

The playing tune is always shown at the top, with the **⏻ (On / Off)** button to the right of it: from any tab,
**Switch TV on** / **off** (via [HDMI-CEC](#fernbedienung-des-fernsehers-hdmi-cec)), switch the selected **Ultimate**
on / off and **Switch off jukebox** (see [Switching off and smart plug](#ausschalten-und-steckdose)).
Below that are the tabs:

| Tab | Contents |
|---|---|
| Player | playing tune with progress, buttons, sub-tune, Shuffle, play list |
| Files | sources, folders, filter, search, play |
| Lists | saved play lists, statistics |
| Devices | Ultimates, Picos and stream distributor, devices on the network (with the Pi's name) |
| Display | *Picture on the TV* (HDMI, background, Retro news) · *Sound* (Sound on the TV, Bluetooth headphones) · *Controls* (TV remote, display on the Pi) |
| Settings | *Playback* (playback, song lengths, PC jukebox data) · *The Pi's network* (Wi-Fi, own Wi-Fi) · *System* (password, backup, updates) |
| Help | this manual |

On a phone, “Player”, “Display”, “Settings” and “Help” appear as **▶**, **📺**, **⚙** and **?** in the
tab bar. The round **?** buttons in
the tabs jump to the matching place in the manual.

The language (German / English) is chosen under **Settings → System → Language / Sprache**; it applies to the page,
the TV menu, the displays and this manual.

**As an app on the home screen:** on an iPhone/iPad in Safari **Share → Add to Home Screen**, on an Android phone in
Chrome **⋮ → Add to Home screen**. The jukebox gets an icon of its own (the note) and opens without an
address bar like an app – no app store is needed for this. It remains a web page: the phone must be on the same
network as the Pi, and logging in stays as in the browser.

## Player {#wiedergabe}

| Button | Effect |
|---|---|
| ⏮ | to the start of the tune; within the first 5 s to the previous tune |
| ▶ / ❚❚ | play or pause (the Ultimate is paused) and resume |
| ⏹ | Stop: the Ultimate is reset |
| ⏭ | next tune |
| ‹ Song 1 of 3 › | another sub-tune of the playing tune |
| Shuffle | shuffles the order (the playing tune stays) |
| Repeat list | start again at the end of the list, otherwise the jukebox stops |
| Ultimate | appears with several Ultimates: which one plays |
| ⚑ Mark end here | appears while a tune without a known length is playing (see below) |

The jukebox keeps playing on its own, even if no page is open. After a power cut the
play list is still there; ▶ continues with the last tune.

### The play list {#die-wiedergabeliste}

The list is a window with columns as in the PC jukebox (Ultimate64 SID Player):

| Column | Contents |
|---|---|
| # | position in the list |
| File name, title, composer | from the SID header (on a phone: title, below it composer, song and SIDs) |
| Song | selected sub-tune / number of sub-tunes, only if there are several |
| SIDs | number of SID chips and their addresses, e.g. `2 ($D400/$D420)` |
| Length | `3:05` from the HVSC, `3:05*` blue = own length, `(5:00)` grey = none known, the time limit applies |
| Played | how often the tune was started |
| ★ | favourite – tapping toggles it |

- **The playing tune** has a yellow background and always stays in view: at every change of tune the window moves it to
  the middle, and if you have not scrolled for 15 s, it brings it back. ⌖ jumps there at once. A green ▸ shows which
  tune comes next.
- **Play:** double-tap or double-click (on a PC also Enter); ▶ plays the selected tune.
- **Select:** tap; with Ctrl/⌘ several individually, with Shift a range. The arrow keys move through the list.
- **⋯** next to a tune (or right-click) opens: Play, Play next, Choose song, Own length,
  Favourite, Show in the Files tab, Remove from the list.
- **Play next** puts the selected tunes directly after the playing one (a queue, also with Shuffle).
- **Remove** (or Del) takes the selected tunes out of the list.
- **Sort:** a tap on a column header sorts the list by it (▲), a second tap in reverse (▼). The playing
  tune keeps playing.
- **Reorder:** on a PC, drag a row with the mouse to another place (not during a search).
- **Search:** the field above the list searches the whole list by file name, title and composer; ★ shows only
  favourites.
- **Double-click on “Song”** chooses another sub-tune, **double-click on “Length”** sets an own length
  (m:ss, empty = the HVSC length again). Own lengths apply to the file (via its MD5), also in other lists.
  A length for the tune that is playing right now applies at once: it then ends there (or immediately, if it has already played longer).
- **⚑ Mark end here:** if no song lengths file knows a tune, it plays until the time limit. If it ends before that
  or starts over, press **Mark end here**: the playing time so far becomes its own length (as if
  entered by hand, with `*`), and playback continues with the next tune. From then on it plays exactly that long – also
  in the PC jukebox, if you take your own lengths there. The same exists in the [TV menu](#fernbedienung-des-fernsehers-hdmi-cec).
- **Check lengths** reads the header data of all tunes whose details are still missing (this also happens by itself in the
  background after “Play folder” and after loading a list), and then, for all tunes without a length, looks for the same tune
  [by its name](#laenge-ueber-den-namen) in the HVSC. A bar above the list shows the progress; at the end it says
  e.g. “35 tunes without length, 22 of them found in the HVSC” with the button **Use 22 lengths** (with the
  setting *automatically* they are used right away). Also in the [TV menu](#fernbedienung-des-fernsehers-hdmi-cec).
- The header line shows the number of tunes, the total duration (tunes without a length count with the time limit, “estimated”)
  and where the list comes from.
- **More ▾:** import a PC jukebox playlist, export for the PC jukebox, **Discover** (a tune that has never
  played, otherwise one of the least played), **Discover: a new composer**, **Stop after …** (after a
  number of tunes or after minutes, always at the end of a tune), Select all, Clear list.
- Keys on a PC (outside input fields): Space = play/pause, ← / → = previous/next tune.
- **Shuffle**, as in the PC jukebox, prefers tunes that have been played less often.
- The list may be very long (up to 50,000 tunes, a whole HVSC): the page draws only the visible rows.

### Length by name {#laenge-ueber-den-namen}

Song lengths are found via the MD5 of the whole file. Many tunes in party or CSDB folders, however, are in a
**different version** from the one in the HVSC: when adding them, the HVSC often corrects the file header (“Laszlo Vincze”
becomes “László Vincze”) – the same music, but a different MD5, so “length unknown”.

So when a tune without a length starts, the jukebox searches the loaded HVSC file for the same **file name or
title** (ignoring umlauts, accents, spaces and punctuation: “Verkürzte Ausfahrt” = `Verkuerzte_Ausfahrt.sid`). A hit
only counts if its composer folder matches the composer in the SID header (`MUSICIANS/V/Vincenzo` for “Laszlo Vincze
(vincenzo)”); for games and demos without a composer folder only if there is exactly one. Common names such as
“Intro” or “Tune” are not searched for.

The **Player** tab then says “In the HVSC as Verkuerzte_Ausfahrt.sid (musicians/v/vincenzo) with 2:46 – use as
length?” – **Use** saves the lengths of all sub-tunes as own lengths of this file (with `*`), and the
playing tune then ends there; **No** leaves everything as it is. On the TV, a discreet line above the playing time says
“Length 2:30 found in the HVSC · OK: use” – OK opens the menu directly on **Use HVSC length**, a
second OK applies it.
Setting in **Settings → Playback:** *suggest* (default), *use as length automatically* or *off*.

**How well it works:** 600 random files from a CSDB collection, compared with HVSC 85: the HVSC knew 69
by their MD5, **331 were found by name**, 143 not at all. For 259 of the 331 the music data after the header is
even byte-identical to the HVSC file – then the length is certainly right. The rest are other versions (e.g.
`speedy_no_loop.sid` versus `speedy.sid`), which may have a different length – that is why the jukebox prefers to ask.

### Detecting repetition {#wiederholung-erkennen}

Most SID tunes loop endlessly; the length in the HVSC is the point at which they start over.
For tunes **without** a known length, the jukebox looks for this point itself in the audio stream (so it has to be running): it
keeps a “fingerprint” of the sound (notes and timbre) and compares it with everything the tune
has played so far. If it sounds exactly like the beginning for a while, the tune has started over.

The **Player** tab then says “Starts over after 1:35 – use as length?”:

- **Use** makes 1:35 the tune's own length (like [Mark end here](#die-wiedergabeliste), with `*`), and playback
  moves straight on to the next one – the tune has already started over, after all.
- **No** lets it play on until the time limit (next time the jukebox searches again).
- On the TV, a discreet line above the playing time says “Starts over after 1:35 · OK: use as length” – OK opens
  the menu directly on **Use detected length**, a second OK applies it.

Setting in **Settings → Playback → Detect repetition:** *suggest* (default), *use as length
automatically* (without asking – only if you trust the suggestions) or *off*.

**How well it works:** measured on 40 random tunes from the HVSC whose length is known: 22 times the right
length (to within 3 s), 5 times a wrong one, 13 times no suggestion. So when a suggestion comes, it is right about 4 times out of 5
– that is why the jukebox prefers to ask. It is wrong mainly with tunes whose first part repeats exactly
before the whole tune starts over. There is no suggestion for tunes that jump back to the middle after an intro
(this cannot be told apart from a chorus played twice), or when the time limit
comes first.

**When:** the search starts when the tune starts. It reports about 45 s after the point at which the tune starts
over – the repetition has to hold that long before it is certain. With a time limit of 5 minutes, tunes
up to a good 4 minutes long are detected; if you want longer ones detected, set the time limit higher. After a pause
the jukebox no longer searches for this tune.

The search runs as a separate process on another core of the Pi (with the numpy of the HDMI part) and only while
a tune without a length is playing; it does not slow down playback. Every find is recorded in the event log
(“Repetition detected: …”).

### SID addresses on the Ultimate {#sid-adressen-am-ultimate}

Tunes for two or three SIDs expect the second (third) chip at a particular address, usually `$D420` or
`$D500` – this is in the header of the SID file (column “SIDs”). If the Ultimate is set up differently, a voice is missing.
Like the PC jukebox (“Auto-adjust SID addresses”), the jukebox then switches a socket **before the tune**:

- only in the **unambiguous case**: exactly **one** address is missing, and exactly **one** SID socket is free (the tune does not need
  its address) – otherwise it changes nothing and reports “not unambiguous”;
- only **real SID sockets**, **never the UltiSIDs**; if an UltiSID already provides the address, everything stays as it is;
- only in the Ultimate's working memory (not saved permanently);
- it switches **back** as soon as a tune no longer needs the address, on **Stop**, when changing to another
  Ultimate and – if the power went off in the middle of a tune – at the next start of the Pi (it remembers the old address
  before switching, in `/var/lib/c64jukebox/sid-socket.json`).

Below the playing tune it says what happened (“Socket 2 set to $D420 for this tune (otherwise $D500)”).
To switch on and off: **Settings → Playback → Switch SID addresses on the Ultimate when needed** (on).
**Show SID addresses on the Ultimate** reads out the assignment (sockets and UltiSIDs) – like “Check SID Addresses…” in the
PC jukebox.

**Marking in the play list:** tunes whose SID addresses the selected Ultimate does not currently offer appear in
the “SIDs” column **in purple with ⚠** – as in the PC jukebox, for every tune (also single-SID tunes for an unusual
address). The tooltip says whether a socket will be switched before the tune or whether there is no unambiguous
switch (then the tune sounds incomplete). The jukebox reads the assignment every minute and when the
Ultimate changes; its own switching does not count – tunes are marked against the normal setting.

### Schedule {#zeitplan}

Under **Settings → Schedule** the jukebox starts or stops the music at fixed times, for example on weekdays at
18:00 the list “Feierabend” and every evening at 23:00 Stop. Each entry has:

- **on** – to switch it off temporarily without deleting the entry;
- **days of the week** and **time** (the Pi's clock, Central European Time with daylight saving time);
- **play** (the current list or a saved one – which then replaces the current one) or **stop**;
- **TV too** – with the [TV remote (HDMI-CEC)](#fernbedienung-des-fernsehers-hdmi-cec): when playing,
  switch the TV on and switch it to the Pi; when stopping, switch it off.

**Save** applies the entries; below them it shows what happens next and what happened last. If the
Pi was off at the scheduled time, nothing is made up for later.

## Choosing files {#dateien-auswaehlen}

At the top of the **Files** tab the **sources** appear as tiles. Tapping a tile opens it, ✎ edits it,
**+ Source** sets up a new one. The jukebox remembers the last opened folder for each source.

- Tapping a **folder** opens it. The path line above it takes you back with one tap.
- **Tapping a SID file** (or ▶) plays it – and after it the other files of the folder, in the order they are currently
  shown (with a filter, only the matching ones). The previous play list is replaced.
- **+** appends a file to the end of the list without interrupting the current playback.
- **▶ Play folder** takes all SIDs of the folder, with the tick **with subfolders** also from all
  subfolders, shuffled with **Shuffle**; while collecting, the line below shows which folder is being read.
  **+ List** appends them instead.
- For every SID the list shows **title, composer, year, sub-tunes, playing time** and, in yellow, **2 SIDs** or
  **3 SIDs** for stereo tunes. The details are read from the files the first time a folder is opened (in
  large folders the list fills up bit by bit) and are then remembered on the Pi.

### Filtering and searching {#filtern-und-suchen}

- The **filter field** acts on the open folder at once: it searches file name, title, composer and year. Several
  words must all occur, e.g. `hubbard 1986`.
- **🔍 Subfolders** searches for the word from the filter field in **all subfolders** of the open folder – in the path
  (`MUSICIANS/H/Hubbard_Rob/…`) and in the title and composer of files that have been shown before. Up to 500 hits.
  During the search, the line below shows how many folders have been searched and which one is being searched now.
  A repeated search is quick, because the Pi keeps the folder lists for a day. ✕ in the path line goes
  back to the folder. “Play folder” then plays the hits.
- **🔍 HVSC** (as soon as the HVSC's [song lengths](#songlaengen) have been loaded from a source) searches the **whole
  HVSC** – instantly, without reading a folder: the jukebox knows all paths from `Songlengths.md5`. The same applies to
  🔍 Subfolders in a folder of the HVSC. This finds file names and composer folders (`Hubbard_Rob`) straight away;
  **title, composer and release** from the files themselves are added once *Settings →
  Song lengths → Read titles for searching* has run. In the background this reads only the
  first 124 bytes of each HVSC file (a few minutes over SMB, the progress is shown there; the music keeps playing) and only needs to be repeated after
  a new HVSC version – and then only for the new files.

### Setting up sources {#quellen-einrichten}

**+ Source** opens the dialogue. First choose the **type**, then:

1. **Search the network** – the Pi searches the home network for computers with shares (SMB) or FTP servers. During the
   search (a few seconds) a bar shows the progress in per cent, below it the addresses currently being checked
   (e.g. “checking 192.168.1.65 … .128”, 64 at a time), and what has been found so far. Then tap a
   hit – this enters it as the server.
2. For network shares, enter the **user and password** (empty = guest) and **Show shares**: all
   shares of the computer appear; tap one.
3. Optionally a **folder** within the share, e.g. `/C64Music` – the source then starts there.
4. **Test connection** and **Save**.

| Type | Server | Share / folder | User |
|---|---|---|---|
| Network share (SMB) | `nas.local`, `diskstation` or IP | name of the share, optionally a folder inside it | user of the NAS/PC |
| FTP server | name or IP, port usually 21 | start folder | empty = anonymous |
| USB stick on the Ultimate | – (the Ultimate from “Devices”) | `/` or e.g. `/USB2/SID-Tunes` | – (the Ultimate's network password) |
| Folder or USB stick on the Pi | – | `/media/usb` | – |

### Network share (SMB) {#netzwerkfreigabe-smb}

This is what the shared folders of Windows, macOS, Linux (Samba) and every NAS (Synology, QNAP, Fritz!Box NAS …) are called.
The jukebox mounts nothing; it reads the files directly – with SMB 2 or 3 (also encrypted), with very old
devices with SMB 1. Notes:

- **Windows:** share the folder (Properties → Sharing), user = Windows user (with a Microsoft account the
  e-mail address), password = its password.
- **macOS:** System Settings → General → Sharing → File Sharing; under “Options” switch on “Windows
  File Sharing” for the user.
- **Synology/QNAP:** create a user of its own with read access to the music folder only – that is the safest.
- The share is contacted when a folder is opened; after a minute without access the Pi closes the connection.
- The password is stored on the Pi in the settings file (readable only by the jukebox) and in the backup. The
  web page never shows it, only •••• – leave it like that and it is kept when saving.

### FTP server {#ftp-server}

For computers or NAS devices with an FTP service. The jukebox uses passive FTP and handles servers with and without UTF-8 file names.

### USB stick on the Ultimate {#usb-stick-am-ultimate}

The files on the USB stick or the SD card of the Ultimate. The **FTP service** must be switched on in the Ultimate
(*Network → FTP Server*). If the file is on the Ultimate that is currently playing, the jukebox starts it directly there
(without transfer). With several Ultimates a source can be tied to “the one currently selected” or to a particular Ultimate
– then another Ultimate can play the files too (they are transferred).

### Folder or USB stick on the Pi {#ordner-oder-usb-stick-am-pi}

Plug a USB stick into the Pi: after a few seconds it appears under `/media/usb/sda1` (FAT, exFAT, NTFS
and Linux file systems, read-only). The prepared source **USB stick on the Pi** shows `/media/usb`. You may unplug it
at any time; the jukebox never writes to the stick.

## Song lengths {#songlaengen}

With the song lengths file of the **HVSC** (High Voltage SID Collection) the jukebox changes exactly at the end of a tune,
and the progress bar and the list show the playing time.

1. The file is called `Songlengths.md5` and is in the HVSC in the folder `C64Music/DOCUMENTS`.
2. In the **Files** tab go to this folder and tap **load as HVSC lengths** next to the file. Or upload the file
   from your phone/PC in **Settings → Song lengths**.
3. The Pi reads it in (a few seconds) and keeps it, even across a restart.
4. When it is loaded from a source (not uploaded), the jukebox also knows all paths of the HVSC for the
   [search across the whole HVSC](#filtern-und-suchen); **Read titles for searching** adds titles and composers.

**Own lengths** take precedence over the HVSC: a text file with lines `<md5>=<Sekunden>` (seconds; the format of the
Ultimate64 SID Player) or in the HVSC format `<md5>=m:ss m:ss …`. The MD5 is calculated over the whole file.

Without a known length:

- **time limit** (*Settings → Playback*, default 5 minutes, 0 = never),
- **or after N s of silence** (default 5 s): the jukebox listens to the audio stream and moves on when a tune
  ends and goes quiet. This only works if the [stream distributor](#stream-verteiler) is on.

**Sub-tunes:** “start song only” plays the song named in the SID header for each file, “all one after another” plays all
sub-tunes of a file before the next file comes.

### Finding lengths on a Mac (whole folders) {#laengen-am-mac-ermitteln-ganze-ordner}

For collections outside the HVSC (party folders, CSDB) there is a tool for the Mac that finds the lengths **in advance for
whole folders** – instead of tune by tune during playback. For every SID file that the HVSC does not know by its MD5:

1. **by name** (like [Length by name](#laenge-ueber-den-namen)); with the HVSC folder it also compares
   the music data: byte-identical = “hvsc-same” (certain), otherwise “hvsc-other” (different version, only on request);
2. **by listening:** every sub-tune is played with libsidplayfp, about 80 times faster than real time –
   “end”: the tune stops (4 s of silence), “loop”: it starts over ([Detecting repetition](#wiederholung-erkennen)).

The result is a `user_songlengths.txt` (format of the PC jukebox, all sub-tunes) and a CSV report on where
each length comes from. You upload the file in **Settings → Song lengths** as own lengths (“add”) – or
put it in the PC jukebox's folder.

```
cd tools/sidlen && c++ -O2 -std=c++17 -isysroot "$(xcrun --show-sdk-path)" sidrender.cpp \
    -I"$(brew --prefix libsidplayfp)/include" -L"$(brew --prefix libsidplayfp)/lib" -lsidplayfp -o sidrender
python3 tools/find_lengths.py "<Ordner>" --hvsc ".../C64Music/DOCUMENTS/Songlengths.md5" --hvsc-dir ".../C64Music"
```

You need `brew install libsidplayfp` and Python with numpy (the project's `.venv`). **Measured** on 40
HVSC tunes with a known length: 27 right (all 6 “end” right), 4 wrong, 9 without a result, 36 s for all 40.
“loop” goes wrong with tunes whose first part repeats exactly. Folder `X24` (18 files): 2 already known,
13 by name with identical music data (e.g. Brutopian Schlager 3:07), 1 by listening, 2 without a result – in 44 s.
With `--kinds hvsc-same,end` only the certain lengths go into the file.

### STIL – background on the tunes {#stil-hintergruende-zu-den-stuecken}

Besides the song lengths, the HVSC has the file `STIL.txt` (*SID Tune Information List*, also in
`C64Music/DOCUMENTS`): notes on about 17,000 tunes – where a melody comes from (“Original by”), the names of the
sub-tunes, stories of the musicians. In the **Files** tab tap **load as STIL** next to the file; the Pi reads it in
a few seconds and keeps it.

After that, below the playing tune (**Player** tab) and – with the tick “plus the STIL background on the tune”
in the **TV (HDMI)** card – at the bottom left of the TV, it shows what the STIL knows about the tune and the sub-tune currently playing
(at most 6 lines). A tune is found by its path in the HVSC; if it is somewhere else (e.g. in a
folder of your own), by its MD5 and the paths in the song lengths file – for this the HVSC song lengths must be loaded.
To remove it: **Settings → Song lengths**, line “STIL”.

## Play lists {#wiedergabelisten}

- **Save:** in the **Player** tab, tap **Save …** at the list and enter a name. An existing name
  is overwritten.
- **Load:** in the **Lists** tab, **▶ Load** replaces the current list and plays it, **+** appends it at the end,
  **↗** exports it for the PC jukebox, **✎** renames it, 🗑 deletes it. If the schedule plays the list, it
  follows the renaming; when the list is deleted, its schedule entry is switched off (otherwise it would play a different list).
  Both also work on the TV: menu → Choose music → choose a list (see [TV menu](#fernbedienung-des-fernsehers-hdmi-cec)).
- A list remembers the source and the path of each tune. If a source is deleted or a file is moved,
  the jukebox skips the tune with a message.

### Build lists {#listen-zusammenstellen}

In the **Lists** tab the jukebox builds lists itself – from the whole **HVSC**, without reading each file individually:
the loaded song lengths file knows all tunes with path and length. For this the HVSC song lengths must have been loaded **from a
source** (**Files** tab, not uploaded); the HVSC folder is the one the file comes from.

**One tap plays at once:**

| Button | |
|---|---|
| ★ Favourites | all favourites, also outside the HVSC |
| Most played | the 50 most frequently played tunes |
| Never played | 50 random HVSC tunes that have never played |
| Random from the HVSC | 50 random tunes |
| Short tunes | 50 random ones under 2 minutes |
| Tunes for 2 or 3 SIDs | 100 random multi-SID tunes (this is where the [SID switching](#sid-adressen-am-ultimate) pays off) |

**Your own selection from the HVSC:** area (musicians, games, demos), composer or path contains (for example
“Hubbard” or “Galway” – the folder name in the HVSC), length from–to, only 2/3 SIDs, only with
[STIL background](#stil-hintergruende-zu-den-stuecken), only never played, number and order. Then
**Play** (replaces the list), **Append** or **Save as list**. The year of release cannot be used
for selection this way – it is only in the files themselves.

### Recently played {#zuletzt-gespielt}

The **Lists** tab shows the recently played tunes with the time (newest at the top; 100 are remembered, even across a
restart). **▶** plays one of them next, **+** appends it to the end of the list. **Use as play
list** turns the history into a new list (in the order played, each tune once) – which can
then be saved like any list. **Clear history** empties it.

### Blocked tunes {#gesperrte-titel}

A tune you no longer want to hear does not have to be deleted from every list: **⊘ Never play again**
(below the playing tune, in the **⋯** menu of a row or in the menu on the TV) skips to the next one at once and puts
the tune on the block list. After that the jukebox skips it wherever it chooses by itself: when moving on at the
end of a tune and with **⏭**, with Shuffle, with “Discover” and in the [built lists](#listen-zusammenstellen).
In the play list it is crossed out. **Chosen by hand** (tap the row, ▶) it plays anyway.

What is blocked is the file (by its MD5 sum, like the favourites): a copy under another name or in another
folder is blocked too. A favourite loses its star when blocked; making a blocked tune a
favourite again lifts the block. In the **Lists** tab, **Blocked tunes** shows all blocked tunes
(newest at the top) with **Play again**; the block list is part of the [Backup](#sicherung). If all tunes of a
list are blocked, playback stops.

### Importing PC jukebox playlists {#playlists-der-pc-jukebox-importieren}

In the **Player** tab under **More ▾ → Import PC jukebox playlist …**: choose the file, then the **source and the
folder to search in** (including subfolders; preset to the folder last opened in the **Files** tab), e.g.
the HVSC on the network share. After that it is the current play list and, if you like, saved under its name.
Anything that was not found is shown in a list.

- **Shared playlist** (`…_u64playlist.json`, in the PC jukebox “Export Playlist for Sharing”): exactly as there – first
  the whole folder is scanned, then for each tune the file with **the same MD5** is taken first, otherwise the one with
  **the same file name** (case does not matter); if there are several, the first one counts. Title and composer do not
  count. The jukebox knows the MD5 of the HVSC files from the loaded `Songlengths.md5` (which lists the
  HVSC path for every MD5); other files it reads once and remembers the MD5 – so the first import from a large folder without
  HVSC takes a while.
- **.u64pl** (the playlist files of the PC jukebox): these contain the PC's paths, e.g.
  `/Volumes/Musik/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid`. The PC jukebox skips paths that do not exist;
  on the Pi none of them exists. So the jukebox searches the chosen folder for the file whose path **matches longest
  at the end** (`H/Hubbard_Rob/Commando.sid` before `Commando.sid`), otherwise by file name.
  Entries `u64://<Adresse>/<Pfad>` (files on an Ultimate) go to the source “USB stick on the Ultimate” of that
  Ultimate.
- **Export:** “Export for the PC jukebox” (More ▾ or ↗ in the **Lists** tab) writes a shared playlist
  (`<Name>_u64playlist.json`) – to be loaded in the PC jukebox with “Import Shared Playlist…”.

### PC jukebox data {#daten-der-pc-jukebox}

In the tab **Settings → Import PC jukebox data** you can read in the files from the settings folder of the
Ultimate64 SID Player (Mac: `~/Library/Application Support/Ultimate64SIDPlayer`, Windows: `%APPDATA%`):

| File | Effect |
|---|---|
| `play_counts.json` | the “Played” counters are added to your own |
| `favorites.json` | the favourites (★) are added |
| `user_songlengths.txt` | own lengths: new ones are added; if some differ, your own are kept – unless the tick “for differing lengths take the ones from the file” is set |

Counters, favourites and own lengths belong, as in the PC jukebox, to the **MD5 of the file** – so they also apply if the
file is somewhere else. “Download own lengths” provides the `user_songlengths.txt` for the PC jukebox.

**Synchronise automatically** (PC jukebox version 1.83 or later): switch on *Settings → Preferences… → Pi-Jukebox* there,
enter the address (`c64pi.local`) and the password of this page. Before every “Check Lengths” the PC jukebox fetches the
own lengths that only the Pi knows and sends it the ones only it knows; when it saves its lengths at
program exit, new ones go along too. If both have a different length for the same tune, the PC jukebox asks once which one
applies. Lengths per sub-tune (only possible there) are left untouched. Nothing needs to be set on the page for this.

## Ultimates {#ultimates}

The **Devices → Ultimates** tab lists the devices that can play:

- **Search the network** finds Ultimates on the home network (also with a network password, if the password is already entered for a
  listed Ultimate); progress and the addresses being checked are shown below the buttons. Each
  Ultimate appears once, with its **Ethernet address** – it only
  streams over that. Tapping it adopts it, then **Save**.
- **Network password:** the one set in the Ultimate under *Network → Network Password*; empty if none is set.
- **active:** this Ultimate plays. With several Ultimates the same choice is in the **Player** tab. A change
  stops the current playback and – with the distributor on – fetches the stream from the new device.
- **⏻ On / Off:** **Off** resets switched SID sockets, stops playback and switches the Ultimate off
  (`machine:poweroff`). **On** wakes it via its **Wi-Fi** (“Wake-Up on WiFi” of the Ultimate 64-II, like “Wake via WiFi”
  in the PC jukebox): a Wake-on-LAN packet to its **Wi-Fi MAC**. The line below reports when it answers again
  (on the Elite II after about 12 s). The jukebox remembers the Wi-Fi MAC itself once the Ultimate has been switched on
  (it is then shown in the field below); otherwise enter it there – it is shown in the router or on the device. The Pi still
  fetches the sound only over the cable. On the TV: menu → “Switch Ultimate on” / “Switch Ultimate off” (asks for confirmation).

## Stream distributor {#stream-verteiler}

The Ultimate sends its audio stream to **one** address only. If the distributor is on, that address is the Pi: it
receives the stream over the network cable and passes every packet on unchanged to all Picos in the list –
to visualizers just as to the audio receiver. Multicast is not needed (it makes many Wi-Fi networks slow).

1. Tab **Devices → Picos and stream distributor**: enter the Picos (`c64viz.local`, `c64audio.local` …) or, further down
   under “Devices on the network”, tap **add as Pico**, then **Save**.
2. Set the tick **Fetch audio stream from the Ultimate to the Pi …**. The Pi asks the Ultimate for the stream and does
   so again whenever nothing arrives for 5 s (e.g. after a restart of the Ultimate).
3. On **every Pico**, in the tab “WLAN & Ultimate”, choose **“weitergeleitet”** (forwarded) as the receiver mode. Otherwise the
   Pico fetches the stream itself from the Ultimate and so takes it away from the Pi.
4. Switch off **forwarding on the Picos** if the Pi supplies them all directly – or deliberately build a chain:
   the Pi supplies only the audio receiver, which passes it on to the visualizer, and so on. Both work; only a Pico
   that would receive the stream twice takes the first and discards the second.

The box below the tick shows whether the stream is arriving (packets per second, normally about 250) and how much goes to each
Pico. If a Pico shows “Name not found”, it is off or has a different name.

The Pi accepts stream data (sound, picture of the C64, SID voices) **only from the entered addresses of the Ultimates** –
that is, over the network cable. If an Ultimate sends from its Wi-Fi address (the Elite II did this when it hung), the
Pi discards the packets and shows “… packets from <address> discarded” in the box. The jukebox does not need the Ultimate's
Wi-Fi. So enter the Ultimates in the **Devices** tab with their **cable address**.

For each Pico you can set individually whether it receives the **stream**.

### Tune display on the Picos {#titelanzeige-auf-den-picos}

For every tune the jukebox sends title, composer, length, sub-tune and SID addresses to the Picos; the matrix shows
the title, the progress runs along, and a tune with 2 SIDs switches the visualizer to stereo. Every 30 s the
playing time is sent again, at the end “Stop”.

### Retro news on the Picos {#retro-news-auf-den-picos}

The tick **Send Retro news to the Picos** (card “Picos and stream distributor”) sends the latest 6
headlines of the [Retro news](#retro-news) to all Picos that receive tunes – the same way as the tunes (UDP or
web page with password), whenever they change and otherwise every 15 minutes. The Picos (firmware from 2026-10-22 on) show in
idle mode one headline in yellow after each scrolling text, e.g. `+++ CSDb: Neue Demo +++`. Umlauts are written out
(ä → ae); the matrix has no other special characters. The sources from “Retro news on the TV” apply – the
TV itself does not have to be on for this. Tick off: the Picos forget the headlines at once; individual Picos
hide them with “Retro-News” in their settings (`@news off`).

- **Tunes via UDP** only reaches a Pico if it gets its stream from the Pi (like the tunes). Otherwise
  choose **Tunes via web page** with the Pico's web password.

| Setting | Route | When |
|---|---|---|
| Tunes via UDP | without password to the Pico's stream port (`C64NP1 …`) | the Pico gets its stream from the Pi (or none at the moment) |
| Tunes via web page | `POST /jb/np` with the Pico's web password | always; enter the Pico's password |
| no tunes | – | – |

A Pico only accepts the UDP message if “Audio-Stream verwenden” (use audio stream) is on and no other device is currently
sending it a stream. Picos pass the tunes on to their own forwarding target.

## The Pi's network {#netzwerk-des-pi}

The Pi is most reliable on a **network cable**. The service `c64pi-net` keeps watch and helps when there is no
network; the card **Settings → The Pi's network → Wi-Fi and network** shows what it is doing right now.

| Situation | What the Pi does |
|---|---|
| cable plugged in | nothing more – address from the router, page at `c64pi.local` |
| no cable, a known Wi-Fi in range | connects to it |
| neither cable nor known Wi-Fi (for 60 s; after power-on at the earliest after 90 s) | opens its **own Wi-Fi** |

**The own Wi-Fi** is called `C64-Jukebox` (with a different name in the device list `C64-Jukebox-<Name>`), the password
is `commodore64`; both can be changed in the card (password at least 8 characters). Connect your phone or PC to it,
then open the address shown by the display and this page, usually `http://192.168.5.1/`.

**Avoiding clashes:** before the Pi opens its Wi-Fi, it looks at which C64 devices have already opened Wi-Fi networks of their own. The
Picos (visualizer, audio receiver) always use `192.168.4.1` there; if the Pi sees one of them, it takes
`192.168.5.1`, otherwise `192.168.4.1`. If it sees another Pi with its own Wi-Fi, it moves to the next range
(`192.168.6.1` …) and a name with `-2`. This way a phone never ends up in two networks with the same addresses.

In its own Wi-Fi the Pi checks every 5 minutes whether a known Wi-Fi is back – not while someone has used the page in the
last 5 minutes. The Pi cannot run its Wi-Fi and search at the same time; for the search its Wi-Fi therefore
goes off for about 15 seconds and, if nothing known is in range, comes back on. The same happens
with **Search Wi-Fi networks** on the page while you are connected via the own Wi-Fi – reload the page afterwards.
If connecting to a new Wi-Fi fails (wrong password), the own Wi-Fi is back at once. When the cable is plugged in, the own Wi-Fi goes off at once (and if the Pi's
Wi-Fi was completely switched off before, it is completely off again).

**Setting up a Wi-Fi:** **Search Wi-Fi networks**, tap the one you want, enter the password. The Pi remembers it (stored
by NetworkManager) and uses it from then on when the cable is missing. **Forget this Wi-Fi** deletes the one currently in use.

### Party mode {#party-modus}

For when you are out and there is no Wi-Fi (or you do not want to use someone else's): the Pi opens a Wi-Fi itself – **under
the name and password of your home Wi-Fi**. The Picos, the audio receiver and the phones already know this Wi-Fi and
connect by themselves; nothing needs to be changed on them. The **Ultimate is connected directly to the Pi with a network
cable** (the Ultimates stream the sound only over the cable).

**Switching on:** **Settings → Party mode**, set the tick, choose the name of the home Wi-Fi (the Wi-Fi networks stored in the Pi
are offered) – the password can stay empty if the Pi already knows this Wi-Fi; otherwise type it in.
**Save.** After that the switch may stay on:

- **At home, Party mode stays quiet:** if the Pi gets an address from the router on the cable, or the home Wi-Fi is in
  range, it behaves quite normally. So it can never hand out addresses at home.
- **At the party:** the Wi-Fi is up about 15 s after the start. On the cable the Pi hands out **exactly one address**, for the
  Ultimate (**10.64.64.2**) – but only once no router has answered for 40 s after plugging in. The jukebox
  then addresses the selected Ultimate at this address and fetches the sound.
- The web interface is reached at `http://c64pi.local/` or via the **QR code** on the TV; the card shows the
  address. The Pi's display shows “Party-WLAN”. The password of the home Wi-Fi appears nowhere.
- If you pull out the network cable, the Pi stops handing out addresses there at once.

Only **one** Ultimate on the cable (several would need a switch – Party mode does not support that). The
Picos must not be on the 5 GHz Wi-Fi (they only know 2.4 GHz) – the Pi's Wi-Fi is always 2.4 GHz.

## Display {#display}

A display on the Pi shows what is playing and, above all, how to reach the Pi – in its own Wi-Fi with name, password and
address. Two kinds work; which one is connected is set in the **Display** tab, card “Display on the Pi”, under
**Type**, then saved.

| Type | Part | Wires |
|---|---|---|
| 0.96″ OLED (default) | 128 × 64 pixels, I2C, SSD1306 (e.g. AZDelivery), a few euros; 1.3″ with SH1106 works too | 4 |
| 2.8″ with touch | 320 × 240 pixels, colour, SPI, ILI9341 with touch controller XPT2046 (red board 86 × 50 mm, e.g. ARCELI or AZDelivery, “2.8 inch SPI TFT with touch”), about €13 | 13 |

### The small OLED {#das-kleine-oled}

| Display | Pi (pin header) |
|---|---|
| VCC | Pin 1 (3.3 V) |
| GND | Pin 6 (GND) |
| SDA | Pin 3 (GPIO 2) |
| SCL | Pin 5 (GPIO 3) |

Four female-to-female wires are enough; nothing is soldered. **Do not connect to 5 V**, even if the display can take it –
then the data lines would be at 5 V. The installation script switches on I2C; after the first time, restart once
(`sudo reboot`).

**What it shows:** while a tune is playing, alternating every 8 s

- **Player:** playing time and length, song, title, composer, progress, stream (packets/s and number of Picos);
- **Network:** `c64pi.local`, cable or Wi-Fi name and address, stream distributor.

Without playback, without a network and in its own Wi-Fi only the network page is shown. To prevent burn-in the picture shifts
by one pixel every minute, and after 10 minutes without a tune the display goes dark (adjustable, 0 = never); a new
tune or a change of network wakes it. The card shows whether and where the display was found.

### The 2.8″ display with touch {#das-2-8-display-mit-touch}

Each connection gets its own jumper wire (Dupont, female to female) – **13 wires**; nothing is soldered. The
display is on the Pi's first SPI bus, the touch on a second one; the installation script switches that on (applies after
the Pi's next restart).

| Display (label) | Pi (pin header) |
|---|---|
| VCC | Pin 1 (3.3 V) |
| GND | Pin 6 (GND) |
| CS | Pin 24 (CE0) |
| RESET | Pin 22 (GPIO 25) |
| DC | Pin 18 (GPIO 24) |
| SDI (MOSI) | Pin 19 (MOSI) |
| SCK | Pin 23 (SCLK) |
| LED | Pin 12 (GPIO 18) – backlight, switched off to darken the display |
| SDO (MISO) | **leave unconnected** |
| T_CLK | Pin 40 (GPIO 21) |
| T_CS | Pin 36 (GPIO 16) |
| T_DIN | Pin 38 (GPIO 20) |
| T_DO | Pin 35 (GPIO 19) |
| T_IRQ | Pin 11 (GPIO 17) |

Pin 1 is the pin at the corner of the pin header that faces the SD card slot; pins 35–40 are the last three
pairs at the other end.

**With Y cables** (Dupont 1 female to 2 female) it also works over a single SPI bus: T_DIN additionally to pin 19,
T_CLK additionally to pin 23, T_DO to pin 21 (MISO), T_CS to pin 26 (CE1), T_IRQ as above. Then choose **Touch
connected: “with Y cables”** in the card.

**If the picture stays white** (backlight on, but never a picture): usually the D/C line is not getting through – it tells
the display whether a command or picture data is coming. Swap the wire; if that does not help, pin 18 on the Pi itself may be
faulty (it has happened: the pin could no longer be switched “high”). Then plug D/C into **pin 31** and choose
**D/C on: “Pin 31”** in the card (pin 31 has only other GPIOs as neighbours; pin 16 works too, but is next to GND).

**Only connect with the Pi switched off, and GND first and firmly.** If the display has no ground, its current flows
back to the Pi through the signal lines – in one setup this destroyed two of the Pi's GPIOs and the display's backlight.
A socket that slips onto the neighbouring pin while plugging in can just as well short a pin to GND.

**SDO stays unconnected:** on many of these boards the display does not release the line and then disturbs the touch. The
4 pins for the SD card at the other end of the board are not needed.

**Switching on:** in the card choose **Type: “2.8″ with touch”**, **Save**. The installation script switches on SPI;
after the first time, restart once (`sudo reboot`). At the first start the display shows three crosses
one after another: **tap exactly on each cross** (with a stylus or your fingernail – the touch is “resistive”
and reacts to pressure). After that the jukebox knows the touch; **Set up touch** in the card repeats this. If the
picture is upside down (pin header on the right instead of the left), tick **Rotate picture by 180°** – the touch setup stays
valid.

**What it shows** – in the colours of the C64:

- **Player:** playing time and length, song, title (two lines), composer, year, “2 SIDs”, progress, stream; at the bottom
  four buttons **⏮ ■ ⏭ ⏻** (previous tune, Stop – or ▶ Play when nothing is playing –, next tune, On / Off).
  A pressed button flashes briefly.
- **On / Off** (button ⏻): **TV on**, **TV off** (via [HDMI-CEC](#fernbedienung-des-fernsehers-hdmi-cec);
  if the TV remote is switched off, these two buttons are dark), **Switch off jukebox** (red – only a
  second tap within 5 s switches off; the button then says “Tap again”) and **Back**. At the top right it shows
  whether the TV is on, below that what the last tap did. After 30 s without a tap it returns to the Player page.
- **Levels:** two bars for left and right with peak hold (green, yellow, orange, red like the colours of the C64), below them
  the last 15 seconds as columns, the title at the top, the playing time at the bottom. The Ultimate's audio stream is measured
  four times a second – only while the page is shown. Without a stream the bars stay empty.
- **Network:** `c64pi.local`, cable or Wi-Fi name and address, stream distributor, Ultimate.
- **Own Wi-Fi:** name, password and address in large print.

A tap **outside the buttons** switches to the next page for 30 s: Player → Levels → Network → Player. Without tunes in the list and in its own Wi-Fi
the network page is shown. After 10 minutes without playback the backlight goes off (adjustable, 0 = never); **the first
tap only wakes** the display, only the second one operates it. Only the changed parts of the picture are transferred – the
jukebox needs hardly any processing time for this.

## TV (HDMI) {#fernseher-hdmi}

On its HDMI output the Pi shows the effects of the PC jukebox (its “Spectrum Analyzer”) in **1920 × 1080**, matching the
music that is playing – over a black background, over a **slide show of your own pictures** or over the **live picture of the
C64**. At the top right are the title and composer, the required SID chips with addresses, the year and the sub-tune,
at the bottom right the playing time.

**Switching on:** **Display** tab, card **TV (HDMI)**, tick “Show picture on the Pi's HDMI output”. Below it
are the cards **Background on the TV** and **Sound on the TV**. Every change in these cards applies at once – you can see straight away on the TV how an effect or a background looks. If the
tick is off, the Pi releases the screen (its text console appears there again).

**Resolution:** always 1920 × 1080 at 60 Hz, even on a 4K TV (which enlarges the picture itself) – so it fits
every TV and monitor. The installation script sets this; it applies after the Pi's next restart.
It is best to connect the TV before switching on the Pi.

**Effects** – the same 17 as in the PC jukebox:

| Effect | |
|---|---|
| Bars | LED bars green/yellow/red with peak hold |
| Net | the last six spectra as a wire mesh |
| Cloud | floating particles; for tunes with 2 SIDs two clouds (left/right channel) |
| Oscilloscope | the waveform itself; with 2 SIDs two curves |
| Radial | spokes from the centre |
| Rain / Matrix | falling zeros and ones, faster at loud frequencies |
| C64 Retro | thick bars in C64 colours on a blue BASIC screen (covers the background) |
| Kaleidoscope | mirrored, rotated fans |
| Stereo VU Meter | two needle meters left/right |
| Waveform History | volume as a ticker from right to left |
| Vinyl | a spinning record, title and composer on the label |
| 3-Voice SID | three large bars, one line per SID with its address (estimated from the sound) |
| SID voices (notes, from the Ultimate) | the **real** three voices of each SID as a piano roll – see below |
| Neon Grid | 80s synthwave: sun, grid, neon bars |
| Night City Glitch | yellow bars with glitches on beats |
| Cyberdeck Matrix | green bars with glow, crosshairs, status lines |
| Milkdrop | flowing shape in changing rainbow colours |
| Background only | no effects – e.g. only the picture of the C64 |

**SID voices (notes, from the Ultimate):** the Ultimate can send every bus cycle of the C64 over the network
(“debug stream”). From it, the jukebox reads what the tune writes into the SID registers and shows, for each SID,
the three voices as a **piano roll** of the last 5 seconds: pitch upwards, time to the right, voice 1 red, 2 green,
3 blue, the brighter, the louder (the envelope is recalculated). On the right, for each voice, are the note (C64 notation,
e.g. `A-4`, `H-3`), the waveform (triangle, sawtooth, pulse with pulse width, noise; `F` = goes through the filter) and the
level; above the roll the volume and filter. The visible range adapts to the notes played in whole octaves.

- The jukebox requests the debug stream from the selected Ultimate while the effect is shown, and unsubscribes it
  afterwards. On the Ultimate, **“Debug Stream Mode”** (the Ultimate's settings, *Data Streams*) must include a 6510 part –
  the default is “6510 Only”; otherwise a notice appears in the card.
- The stream needs ~32 Mbit/s and only works over a **cable**; **not together with the background “Picture of the C64”**
  (the Ultimate's network port cannot manage both together) – then a notice appears instead of the notes.
- The SIDs shown are the ones the tune needs according to its header; without that information every SID that is written to.
- Measured on the Elite II: ~2600 packets/s, none lost; the Pi needs only little processing time for it.

**Background:** none (black), **Pictures** or **Picture of the C64**. “Background brightness” dims it so that
the effects stand out better. With a background, Bars, Net and Cloud become semi-transparent, as in the
PC jukebox.

**Only the C64 picture:** effect “Background only”, background “Picture of the C64”. It appears in a 4:3 aspect ratio with
black borders on the left and right – just as the C64 looked on a CRT TV.

**Pictures for the slide show:** in the card “Background on the TV”, **Upload pictures …** (JPEG or PNG, several at once; from a phone also
straight from the photo library). The Pi turns each picture into one in 1920 × 1080 (filling the screen, the overhang cut off
in the middle) – then it does not have to convert anything when showing it. At most 300 pictures. They change every 20 s
(adjustable) with a soft cross-fade, in random order if you like (never the same picture twice in a row).
The ✕ on a picture deletes it. The pictures are stored on the Pi under `/var/lib/c64jukebox/hdmi-bilder` and are not
part of the [Backup](#sicherung).

**Pictures from a source** – like the SIDs from a network share, an FTP server, the USB stick on the Pi or on the
Ultimate: under “Pictures from”, choose **a folder** (or **Choose folder …**). A window like the
**Files** tab opens: the sources as tiles at the top, below them the folders to click through (the path at the top jumps back),
a filter and small thumbnails of the pictures in the folder. **Use this folder** takes the folder currently open,
**with subfolders** if you like. The
jukebox fetches the pictures (JPEG/PNG, at most 300, each at most 40 MB) in the background, scales them to 1920 × 1080 and stores
them under `/var/lib/c64jukebox/hdmi-quelle`; the card shows the progress. Every 10 minutes it synchronises the folder
again (new pictures are added, deleted ones drop out) – or at once with **Synchronise now**. Unchanged pictures
are not fetched again. The slide show already shows the first pictures while the rest are still coming.

**“Now playing” card:** at every new tune (and every new sub-tune) a large card with title, composer, year, SID chips and – if loaded – the
[STIL background](#stil-hintergruende-zu-den-stuecken) appears in the middle of the picture for 6 s (adjustable 2–30 s);
then it fades out, and the small text at the top right stays.
If a tune has already been playing for a while (e.g. because the TV has only just been switched on), no card appears.
To switch it off: tick “a large card at every new tune” in the card **TV (HDMI)**.

**QR code when idle:** when nothing is playing, the top right says “Nothing is playing right now” with the address of the web interface
and a QR code next to it – scan it with your phone's camera, and the page opens. The code contains the
Pi's IP address (many Android phones cannot find `c64pi.local`). To switch it off: tick “when nothing is playing:
QR code” in the card **TV (HDMI)**.

**Hiding the effects when idle:** if no tune is playing or there is only silence, the effects fade out gently after 20 s (adjustable)
– the background remains (slide show, picture of the C64) with the note “Nothing is playing right now”. With the music
they come back. Hidden effects are not calculated, so the Pi has less to do.

**Changing the effect automatically:** tick at least two effects and switch on “change during playback”;
then the effect changes randomly every 180 s (adjustable) – only while a tune is playing. The effect chosen above
remains the basic setting.

**Sound via HDMI:** with the tick “Sound via HDMI to the TV” the Pi plays the Ultimate's sound over HDMI.
The **Volume** slider (0–100 %, applies at once) makes it quieter without looking for the remote – e.g. so that
the TV is not louder than the other sources; it never gets louder than the original. The sound comes about 0.2 s later than at the Ultimate's audio output; if an amplifier is
also connected there, turn up only one of the two, otherwise it sounds like an echo. If the Ultimate's sound is not running at all
(no stream), the TV stays silent.

**Fade-out and fade-in:** with “fade out at the end of a tune, fade in the next one” the sound via HDMI gets quieter in the last
seconds of a tune until silence (default 2 s, adjustable 0.2–15 s) and the next tune is faded in
gently – like “Fade between songs” in the PC jukebox. This works for tunes with a known length and for tunes
without a length before the time limit (the grey “default” length); a change because of silence comes unannounced. It only affects the sound via HDMI: the Ultimate's audio output plays on the real SID chip and
stays unchanged. It is not a cross-fade – on the Ultimate only one tune ever plays at a time.

### Bluetooth headphones {#bluetooth-kopfhoerer}

Instead of the TV, the sound can also play through **Bluetooth headphones** (or a Bluetooth speaker) –
e.g. in the evening, when nobody else should hear it. The Pi 4 has Bluetooth built in; the packages `bluez` and
`bluez-alsa-utils` are needed (the installation script fetches them and lifts the Bluetooth block that Raspberry Pi OS
starts with – otherwise the search finds nothing).

1. Put the headphones into **pairing mode** (usually hold the power button for a few seconds until a light flashes).
2. *Display → Bluetooth headphones → Search for headphones* (12 s). Headphones found are listed below: **Pair**
   (the headphones must still be in pairing mode; the jukebox briefly searches for them again first).
   Beats/AirPods: earbuds in the case, lid open, hold the button on the case for about 15 s until the light flashes white.
3. After that, **Sound via the headphones while they are connected** is switched on: the TV sound goes to the
   headphones as soon as they are connected, and back to the TV when you switch them off (the jukebox checks every
   5 s). Headphones that are switched on reconnect by themselves; otherwise **Connect** helps.

Volume and fade-out/fade-in work as for the sound on the TV. Over Bluetooth the sound comes about 0.2 s later;
the effects on the TV then run slightly ahead of it. The TV output (HDMI) must be switched on –
the sound goes the same way. On the TV, **Sound via headphones** in the menu switches between headphones and
TV. **✕** deletes a pairing. The installation script sets Bluetooth to “classic” (`ControllerMode =
bredr`): Apple and Beats headphones cannot be paired over Bluetooth LE. Search and pairing are recorded with their
result in the event log.

### TV remote control (HDMI-CEC) {#fernbedienung-des-fernsehers-hdmi-cec}

Over the HDMI cable the TV can send the buttons of its remote to the Pi (HDMI-CEC, called e.g. *Anynet+*, *SimpLink*,
*Bravia Sync*, *VIERA Link* by the manufacturers). To switch it on: **Display** tab, card
**TV remote (HDMI-CEC)**, tick “Control the jukebox with the TV's remote”. The Pi announces itself
to the TV as the playback device “C64-Jukebox”; CEC must be switched on in the TV (often in the menu “General” or
“External devices”).

| Button | |
|---|---|
| ▶ Play, ❚❚ Pause | Stop when music is playing – Play when stopped (also the combined ▶❚❚ button) |
| ■ Stop | Stop |
| ⏭ / ⏮, ⏩ / ⏪, → / ← | next / previous tune |
| ↑ / ↓ | next / previous effect on the TV |
| Channel + / − | next / previous sub-tune |
| **OK** or a **menu button** (Menu, Setup, Contents …) | opens the **TV menu** (without the HDMI picture: OK = Play/Stop like ▶) |

**TV menu:** ↑ ↓ select, **OK** or → runs or opens, **Back** or ← goes back one level (at the
top level: closes). After 30 s without a button press it closes by itself. In it:

- **Choose music** – at the very top **Search the HVSC** (if the HVSC song lengths are loaded): enter words with the
  on-screen keyboard, **Done** shows the hits (up to 200; title and composer as with
  [🔍 HVSC](#filtern-und-suchen)). **Play all …** or a single hit turns the hits into the play list,
  **Back** returns to the keyboard to change the words. Below that the **sources** (“Folder: USB stick on the Ultimate” …), then the built lists
  (★ Favourites, Most played, Never played, Random from the HVSC, Short tunes, Tunes for 2 or 3 SIDs) and all
  saved lists; the chosen one plays at once. In a source you browse through the folders as in the
  **Files** tab: **Play this folder**, **… with all subfolders**, **Append folder**, below them the
  subfolders (`Name/ ›`) and the SID files – a file plays the folder from that file on. **Back** goes up one
  folder. While the folder is being read, the progress is shown in the hint line.
- **Mark end here** – only while a tune without a known length is playing: the playing time so far becomes its length,
  then the next one comes (see [The play list](#die-wiedergabeliste)). After a length has been applied, the menu shows the confirmation for 2 s
  and then closes by itself. If the jukebox has found the repetition itself, this line reads
  **Use detected length** instead (see [Detecting repetition](#wiederholung-erkennen));
  if it has found the same tune in the HVSC, **Use HVSC length** (see [Length by name](#laenge-ueber-den-namen)).
- **Never play again** – asks for confirmation and puts the playing tune on the block list (see
  [Blocked tunes](#gesperrte-titel)), then the next one comes.
- **Shuffle**, **Repeat** – on/off.
- **Effect** – all effects to choose from (the current one is marked); a choice switches off the automatic change.
- **Picture and sound** (the volume on the right) – **Change effects automatically**, **Show title**, **Sound on the
  TV** (on/off), **Sound via headphones** (only with paired [Bluetooth headphones](#bluetooth-kopfhoerer)) and
  **Volume on the TV** (each OK one step quieter: 100 → 90 … 10, then 100 again).
- **Ultimate** – which Ultimate plays: all entered ones (the active one with ●); choose another (if music is
  playing, the menu asks first: it will be stopped). Below that **Switch on** / **Switch off** for the selected one
  (wake it via its Wi-Fi or switch it off; switching off asks for confirmation, see [Ultimates](#ultimates)). **Search the
  network** searches as in the **Devices** tab (progress in the hint line); new Ultimates appear below as
  “+ Name” – OK enters one and selects it. A network password is added on the web page.
- **Check lengths** – as on the web page (progress in the menu's hint line); afterwards
  **Use 22 HVSC lengths** appears.
- **Check for update** – asks GitHub for a new version (the installed one is shown on the right). If there is one, the line
  reads **Install update …**: OK asks for confirmation and installs it; the jukebox restarts in the process (see
  [Updating](#aktualisieren)).
- **Switch off** – at the bottom, so right after opening it can be reached with ↑ twice: **Switch TV off**
  (at once), **Switch off jukebox** (asks for confirmation; with a smart plug set up, the power then goes off too, see
  [Switching off and smart plug](#ausschalten-und-steckdose)) and **Switch Ultimate off** (asks for confirmation).
- A **saved list** in “Choose music” opens a small menu: **Play**, **Append**,
  **Rename** (an on-screen keyboard: arrows select, OK types, Back deletes the last character, “Done”
  applies) and **Delete** (asks for confirmation, “No” is preselected).

▶, ■, ⏭ and ⏮ also work while the menu is open. Which buttons a TV (or a Fire TV Cube in between) passes on over HDMI-CEC
varies: every incoming button is recorded with its code in the event log (`/api/events`,
“Remote: button 0x… (…)”).

Most TVs send the buttons only to the device they are currently showing – so first switch to the Pi's input
(or **Switch TV to the Pi now**). This also works if the Pi is connected to the HDMI input of another
device (tested with a Fire TV Cube): then tap **Switch TV to the Pi now**, after which
the buttons of the TV remote arrive. The Fire TV's remote keeps controlling the Fire TV.

- **Announce as active device when playing** (on): at every start of playback the Pi announces itself to the TV as
  the device it is showing – then the buttons arrive without having to tap anything first, even after a
  restart of the Pi. Some TVs switch to the Pi's input when this happens; if that bothers you, untick it.

- **Switch TV on … when playback starts:** if you start the music on your phone, the TV comes on and
  switches to the Pi. Caution: even if someone is watching TV at the time.
- **Switch TV off when nothing is playing any more – after N min:** only if the TV is currently showing the Pi.
- **Switch TV on … when the Pi starts:** as soon as the Pi is ready on the HDMI cable after power-on (e.g. “Alexa, turn on
  Jukebox” via the [smart plug](#ausschalten-und-steckdose)), the TV comes on and shows the
  Pi – only in the first 90 s after the start, so that a TV switched on later does not jump to the Pi.
  Later, **Switch TV to the Pi now** switches the TV on at any time.
- **Switch off jukebox when the TV goes off:** one minute after the TV goes into standby, the Pi shuts down
  (with a smart plug, the power too), see [Switching off and smart plug](#ausschalten-und-steckdose).

The line below shows the state: “Waiting for the TV …” means the Pi has no address on the HDMI cable yet
(TV off or CEC switched off in the TV). The Pi needs no additional program for this.

### Retro news {#retro-news}

If you like, the TV shows current news from the retro scene – card **Retro news on the TV** in the
**Display** tab:

- **show when idle:** when the effects are hidden, a large card appears with source, date, headline,
  short text and (if the item has one) a picture; every 15 s (adjustable) the next one.
- **as a ticker:** during the music the headlines scroll along the bottom of the picture; the playing time moves up above them.

Under *News sources* the known sites are offered – a tick switches a source on or off at once:

| Source | Language | | preset |
|---|---|---|---|
| Indie Retro News (`indieretronews.com`) | English | retro games for all systems, with pictures | on |
| amiga-news.de | German | Amiga news, headlines only | on |
| Commodore News (`commodore-news.com`) | German | Commodore/Amiga, with short text | on |
| Cascade64 (`cascade64.de`) | English | Commodore news, with pictures | on |
| The Oasis BBS (`theoasisbbs.com`) | English | C64/Amiga, with pictures | on |
| BrewOtaku (`brewotaku.com`) | English | homebrew magazine, all systems | off |
| PDRoms (`pdroms.de`) | English | homebrew news for all systems | off |

Further RSS or Atom feeds are added with **+ Source** (name and address, then **Save**); names and addresses
can be changed in the list, the ✕ removes a source, **Default sources** restores the list above.
At most 20 sources. The jukebox fetches the feeds every 30 minutes (at once with **Load
now**); each source shows how many items came or which error occurred. 40 items are shown, the
sources **taking turns**: first the newest of each source, then the second newest of each source and so on (within
a round the newest first) – so current items come first, and a source with many items on one day does not fill
the screen in one go; at most 15 per source; the jukebox scales pictures down (640 × 400) before the TV
gets them. For this the Pi needs internet access.

**Where sound and picture come from:**

- The **sound** for the effects comes from the [stream distributor](#stream-verteiler): if the HDMI output is on, the Pi fetches the
  Ultimate's audio stream even if the stream distributor's tick is off – the entered Picos
  then get it passed on as well.
- The **picture of the C64** is sent by the selected Ultimate directly to the Pi when the Pi asks for it (about 22 Mbit/s, only over the
  Ultimate's network cable). As for the sound, *Data Streams* must be allowed in the Ultimate.
- **The Ultimate sends its picture to only one target.** If the PC jukebox uses the “Ultimate64 Video Stream” as the
  background of its Spectrum Analyzer at the same time, the PC and the Pi take the picture away from each other – then choose pictures as the
  background there. If “Picture of the C64” is deselected here, the Pi unsubscribes the picture from the Ultimate.

**Load:** the HDMI output runs as a service of its own (`c64pi-hdmi`) with a lower priority than the jukebox and the
stream distributor. The graphics chip scales and cross-fades; the processor only draws the effects at half resolution
(960 × 540). On the Pi 3B all effects run at 30 frames/s; the service needs about half of one of the four
processor cores for this, with the picture of the C64 just under one. The card shows how many frames it is currently managing and whether sound and picture
are arriving.

## Devices on the network {#geraete-im-netz}

Like the Picos, the Pi announces itself on the home network every 10 s (as the type “Raspberry Pi”, with the tune currently playing).
The card **Devices on the network** in the **Devices** tab shows all Picos and Pis with address, firmware version and stream, as well as the
**path of the sound**, e.g. “Elite II (192.168.1.168) → c64pi 250/s → [c64audio 250/s, c64viz 250/s]”.
**Search again** asks all devices at once. The name under which the Pi appears there is set in the same card under
*Name of the Pi in this list*.

## Switching off and smart plug {#ausschalten-und-steckdose}

*Settings → Switch off and smart plug → **Switch off jukebox***, the ⏻ button at the top right of every page →
**Switch off jukebox**, **Switch off → Switch off jukebox** in the TV menu, or on the
[touch display](#das-2-8-display-mit-touch) ⏻ → **Switch off jukebox**
stops the music and shuts the Pi down cleanly. You should not simply cut the power: that can damage the
SD card.

If the Pi is plugged into a **smart plug with Tuya technology** (e.g. Antela, app “Smart Life” or “Tuya Smart”),
it sets the plug's built-in **switch-off timer** before shutting down: after *Power off after* seconds (default 30,
at least 20 – the Pi needs about 10 s) the plug switches off. It is switched on via the app or by voice,
e.g. “Alexa, turn on Jukebox” – the Pi starts as soon as there is power. Better not to use “Alexa, turn **off** Jukebox”:
that cuts the power to the running Pi.

If the plug does not answer, the Pi stays on (the page asks whether it should shut down anyway – the power then
stays on). If the shutdown itself fails, the jukebox cancels the timer at once.

**Setting up.** The jukebox switches the plug directly on the home network (without the cloud). For this it needs
the plug's **device ID** and **local key**. Both are shown by the Tuya developer platform (free
account, about 15 minutes, once):

1. Create an account on [platform.tuya.com](https://platform.tuya.com), *Cloud → Development → Create Cloud Project*
   (data centre *Central Europe*, accept the suggested services).
2. In the project, *Devices → Link App Account → Add App Account*: scan the QR code with the “Smart Life” app
   (*Me → scan icon at the top right*). After that all devices of the app are listed with their **Device ID**.
3. The local key is shown by *Cloud → API Explorer → Device Management → Query device details* for the Device ID
   (field `local_key`). If you have Python, you can also get both with `python3 -m tinytuya wizard`.
4. Enter the **Device ID** and **Local key** in the card and tap **Check**: the jukebox searches for the plug on the
   network (the address may stay empty) and shows whether it is on, its power and whether it has a switch-off timer.

**Off together with the TV.** *Display → TV remote → Switch off jukebox when the TV goes off*: if the
TV goes into standby – with its remote, through the jukebox (*Switch TV off when nothing is playing any more*) or
via the page –, the Pi shuts down one minute later, and with a smart plug set up the power then goes off.
If the TV comes back within that minute, the Pi stays on. For this the jukebox listens for the TV's standby message
and asks it every 30 s whether it is on (HDMI-CEC must be switched on). It only reacts to a switch-off
it has seen itself: if the Pi starts while the TV is off (e.g. for music only via the Picos), it stays
on. It also stays on while Bluetooth headphones are connected. The card shows whether the TV is on
and when the Pi will go off; the event log names every step.

The key changes when you set up the plug again in the app – then fetch it again. The plug should get a fixed
address in the router; otherwise the jukebox searches for it again at every check. So that the Pi may switch itself
off, the installation script creates a polkit rule; if it is missing, the card says so.

## Backup {#sicherung}

*Settings → Backup → Download backup* saves a file `c64pi-sicherung-<Datum>.json` with all
settings, sources including passwords, Ultimates, Picos, play lists, the current list, your own
song lengths, the counters, favourites and blocked tunes. So keep the file in a safe place. The web password is only included as a checksum.

**Restore backup** replaces everything with the state in the file – also on a freshly installed Pi. The
HVSC song lengths are not in the backup (the file is large and comes from the HVSC); simply load them again.

If you prefer to back up files: everything is in the folder `/var/lib/c64jukebox` on the Pi, e.g.

```
sudo tar czf c64jukebox-daten.tgz -C /var/lib c64jukebox
```

### Forgotten password {#passwort-vergessen}

Log in to the Pi via SSH and reset the password to `commodore64`:

```
sudo systemctl stop c64jukebox
sudo sed -i 's/"pw_hash": "[^"]*"/"pw_hash": ""/' /var/lib/c64jukebox/config.json
sudo systemctl start c64jukebox
```

## Troubleshooting {#fehlersuche}

| Message / observation | Cause and remedy |
|---|---|
| Page `c64pi.local` does not open | Pi not booted yet, or the device does not know `.local` names (some Android phones): use the IP address from the router |
| “No Ultimate entered” | **Devices** tab: enter the Ultimate and save |
| “Ultimate … not reachable” | Ultimate off, wrong address, or *Web Remote Control* off in the Ultimate |
| “Ultimate refuses: wrong network password?” | enter the network password for the Ultimate |
| “Ultimate hangs (“Network Host Resolve Error”)” | The Ultimate no longer finds the Pi and does not accept a stream to it (observed several times on the Ultimate 64 Elite II with firmware 3.15a, often with a few packets over its Wi-Fi). The Pi then re-registers with the Ultimate by itself (at most every 30 s, “… Pi has re-registered with the Ultimate”). If that does not help: **restart the Pi** – so far this has brought the sound back immediately every time. In the meantime the audio receiver fetches the stream itself |
| “SMB login refused” | user/password; for Windows with a Microsoft account, the e-mail address as the user |
| “SMB server … not reachable” | computer off, wrong name (try the IP), sharing not switched on in the operating system |
| Shares are not shown | some NAS devices only show them to logged-in users: enter user/password; otherwise enter the share name by hand |
| “FTP server … not reachable” with the Ultimate | switch on the FTP service in the Ultimate (*Network → FTP Server*) |
| Folder with SIDs shows “…” instead of titles | the header data is being read; with very large folders over SMB this takes a while the first time |
| “Ultimate answers with error 404” for the stream | the Ultimate sometimes reports “Network Host Resolve Error”; the Pi asks again after 10 s, and it usually works then |
| “Waiting for the stream …” | *Data Streams* allowed in the Ultimate? Ultimate connected by cable? A Pico in Unicast mode takes the stream back: choose “weitergeleitet” (forwarded) there |
| Tune skips ahead too early | “after N s of silence”: tune with a long pause – increase the seconds or switch it off |
| Tune plays endlessly | no song length known and time limit 0: load song lengths or set a time limit |
| Display: “not found (… spidev0.0)” | SPI is off: `sudo raspi-config nonint do_spi 0` and restart (the installation script does this) |
| 2.8″ display stays white | check the wiring (DC, RESET, CS, MOSI, SCK); a white picture means: there is power, but no commands are arriving |
| Card “TV”: “The HDMI service does not respond” | `systemctl status c64pi-hdmi` and `journalctl -u c64pi-hdmi -e` on the Pi; restart once after the first installation |
| TV stays black, but the card reports frames/s | is a tune playing? Without music the bars are almost black – the top right then says “Nothing is playing right now”; otherwise choose a brighter effect (C64 Retro) |
| No sound on the TV | tick “Sound via HDMI to the TV” set? TV not muted? The card shows “Sound via HDMI” when it is playing |
| TV shows “no signal” | set the TV to the right HDMI input; restart the Pi with the TV connected |
| “no picture from the C64” | allow *Data Streams* in the Ultimate; Ultimate on a network cable; is the PC jukebox using the picture right now? (see [TV (HDMI)](#fernseher-hdmi)) |
| “no SID data from the Ultimate” | the Ultimate's “Debug Stream Mode” set to “6510 Only”; Ultimate on a network cable; background not “Picture of the C64” (see [TV (HDMI)](#fernseher-hdmi)) |
| “no sound” in the card “TV (HDMI)” | the Ultimate is not delivering an audio stream: look at the card “Picos and stream distributor” |
| Effects stutter | choose simpler effects (Bars, Net, Radial); the slide show briefly needs processing time when the picture changes |
| Touch does not react or reacts in the wrong place | **Set up touch** in the card; check T_IRQ, T_CS, T_DO, T_DIN, T_CLK; the display's SDO must be unconnected |

The service log is shown by `journalctl -u c64jukebox -e` on the Pi.

## Appendix {#anhang}

### Files on the Pi {#dateien-auf-dem-pi}

| Location | Contents |
|---|---|
| `/opt/c64jukebox` | the program with its own Python environment (`venv`) |
| `/var/lib/c64jukebox/config.json` | all settings |
| `/var/lib/c64jukebox/playlists/` | saved play lists (JSON) |
| `/var/lib/c64jukebox/current.json` | the current play list |
| `/var/lib/c64jukebox/songlengths-*.txt` | loaded song lengths |
| `/var/lib/c64jukebox/stil.txt` | loaded STIL (background on the tunes) |
| `/var/lib/c64jukebox/history.json` | recently played tunes |
| `/var/lib/c64jukebox/cache.db` | remembered SID header data and folder lists (may be deleted) |
| `/etc/systemd/system/c64jukebox.service` | the service |
| `/etc/systemd/system/c64pi-net.service` | the network watchdog (runs as root, controls NetworkManager) |
| `/run/c64pi/net.json` | what the network watchdog is doing right now |
| `/var/lib/c64jukebox/stats.json` | “Played” counters and favourites |
| `/etc/udev/rules.d/99-c64jukebox-usb.rules` | automatic mounting of USB sticks |
| `/var/lib/c64jukebox/hdmi-bilder/` | the pictures for the slide show on the TV (1920 × 1080, JPEG) |
| `/etc/systemd/system/c64pi-hdmi.service` | the HDMI output (system Python with `python3-pygame`, `python3-numpy`) |
| `/run/c64pi/hdmi-in.json`, `/run/c64pi/hdmi.json` | settings and playing tune for the HDMI output, its state |

To uninstall: `sudo systemctl disable --now c64jukebox`, then delete the files above.

### HTTP interface {#http-schnittstelle}

All requests under `/api/` need the login (cookie from `POST /api/login` with `{"pw": "…"}`); every `POST`
additionally needs the header `X-C64: 1`. Answers are JSON. **On the Pi itself** (address 127.0.0.1, e.g. after
`ssh nutzer@c64pi.local`) no login is needed, but the header `X-C64: 1` is still required – this way the jukebox can be controlled over
SSH:

```
curl -s -H 'X-C64: 1' -H 'Content-Type: application/json' -d '{"c":"next"}' http://127.0.0.1/api/ctl
```

If you do not want this, add `--no-local-admin` after `--port 80` in `/etc/systemd/system/c64jukebox.service`.

| Request | Meaning |
|---|---|
| `GET /api/state` | state: playing tune, playing time, stream, Ultimates |
| `POST /api/ctl` `{"c":"next"}` | `play`, `pause` (toggles), `stop`, `next`, `prev`, `goto` + `i`, `song` + `n`, `remove` + `i`, `clear`, `shuffle` + `on`, `block` (playing tune, or + `i`), `unblock` + `key` or `i` |
| `POST /api/search` `{"src","path","q"}` | search (job; in the HVSC instantly from the index) |
| `GET /api/hvsc/titles`, `POST /api/hvsc/titles` | how many HVSC files the search knows with a title (`n` of `of`) / read in titles (job) |
| `POST /api/update/check` | check GitHub for a new version now (`ver`, `newer`, `installed`) |
| `POST /api/update/install` | install the newer version (service `c64jukebox-update`, the jukebox restarts in the process); progress and result in `/api/state` under `upd` (`running`, `last`) |
| `GET /api/power`, `POST /api/power/off` `{"force"}` | may the Pi switch itself off, is a smart plug set up / set the plug timer and shut down (`timer`, `secs`) |
| `POST /api/plug/check` | ask the smart plug (job: `ip`, `ver`, `on`, `timer`, `secs`, `watt`) |
| `GET /api/bt?devices=1`, `POST /api/bt` `{"act","mac"}` | Bluetooth headphones: state and paired devices / `scan`, `pair` (jobs), `connect`, `disconnect`, `forget`, `on` + `on` |
| `GET /api/blocked` | block list: `items` with `key`, `title`, `author`, `path`, `at` |
| `POST /api/queue` | tunes into the list: `{"mode":"replace","items":[{"src":…,"path":…}],"start":0}`; `mode` also `add` or `next` |
| `POST /api/folder` | play folder: `{"src","path","recursive","shuffle","mode"}` |
| `GET /api/ls?src=…&path=…` | folder listing |
| `GET /api/list` | play list |
| `GET /api/devices` | devices on the network (like `GET /devices` of the Picos) |
| `GET /api/sidcfg` | SID addresses of the selected Ultimate (and a currently switched socket) |
| `POST /api/display/calibrate` | set up touch: the 2.8″ display shows the three crosses |
| `GET /api/hdmi`, `POST /api/hdmi` `{"on":true,"mode":"milkdrop","bg":"video"}` | HDMI output: settings (also `auto`, `auto_s`, `auto_modes`, `img_s`, `shuffle`, `opacity`, `osd`), state, pictures |
| `POST /api/hdmi/upload?name=…` (the file), `POST /api/hdmi/delete` `{"name":…}` | pictures of the slide show |
| `GET /api/backup`, `POST /api/restore` | backup |

### Network protocols {#netzwerk-protokolle}

As with the Picos (see their manual, appendix “Netzwerk-Protokolle” / network protocols):

| Port | Direction | Contents |
|---|---|---|
| UDP 11001 | Ultimate → Pi → Picos | audio stream (770 bytes per packet), passed on unchanged; plus `C64NP1 <query>` with the parameters of `/jb/np` |
| UDP 11000 | Ultimate → Pi | video stream (780 bytes per packet: 4 lines of 384 pixels, 16 colours), only with “Picture of the C64” |
| UDP 11002 | Pi internal | copy of every audio packet for the HDMI output (127.0.0.1) |
| UDP 11064 | all | device announcements `C64DEV1 {JSON}` every 10 s by broadcast, `C64DEV1?` asks all |
| TCP 80 | browser → Pi | web interface |
| TCP 80 | Pi → Ultimate | REST: `PUT /v1/runners:sidplay?file=…&songnr=…`, `POST /v1/runners:sidplay` (file), `PUT /v1/machine:reset` (likewise `pause`, `resume`), `PUT /v1/streams/audio:start?ip=<pi>:11001`, `PUT /v1/streams/video:start?ip=<pi>:11000` (and `:stop`), `GET /v1/configs/SID%20Addressing`, `PUT /v1/configs/SID%20Addressing/SID%20Socket%20<n>%20Address?value=%24D420`, `GET /v1/info` |
| TCP 21 | Pi → Ultimate/FTP server | folders and files |
| TCP 445 | Pi → NAS/PC | SMB shares |

The Pi's device announcement: `t` = `"pi"`, `n` name, `ip`, `b` version, `up` seconds since the start, `st` distributor on,
`rx` packets/s from the Ultimate, `from` its address, `fw` the Picos (separated by commas), `fwip` address of the first one,
`fp` packets/s to the Picos, `src`/`srcl` selected Ultimate, `title` playing tune.
