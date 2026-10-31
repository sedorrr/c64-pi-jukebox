"""Bluetooth headphones: bluetoothctl's output read, a fake bluetoothctl (a script with its state in a file) through
the page's routes - search, pair, connect - and the TV sound switched to bluez-alsa while they are connected."""
import asyncio
import json
import os
import stat
import sys

from c64jukebox import bt
from c64jukebox.hdmi.soundproc import Sound
from test_web import H, get, job, login, post, run

MAC = "12:34:56:78:9A:BC"
OTHER = "AA:BB:CC:DD:EE:01"

FAKE = r'''#!%s
"""a fake bluetoothctl: headphones %s nearby (in pairing mode), a keyboard %s"""
import json, os, sys
f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bt.json")
st = json.load(open(f)) if os.path.exists(f) else {"power": False, "seen": [], "paired": [], "conn": []}
a = [x for x in sys.argv[1:]]
while a and a[0].startswith("--"):
    a = a[2:] if a[0] in ("--timeout", "--agent") else a[1:]
cmd, arg = a[0], (a[1] if len(a) > 1 else "")
NAMES = {"%s": ("Kopfhoerer X", "audio-headphones"), "%s": ("Tastatur", "input-keyboard")}
if cmd == "power":
    if os.path.exists(os.path.join(os.path.dirname(f), "blocked")):
        print("Failed to set power on: org.bluez.Error.Failed"); sys.exit(1)
    st["power"] = True
    print("Changing power on succeeded")
elif cmd == "scan":
    st["seen"] = [] if os.path.exists(os.path.join(os.path.dirname(f), "gone")) else list(NAMES)
    print("Discovery started")
elif cmd == "devices":
    for m in (st["paired"] if arg == "Paired" else st["seen"] + [x for x in st["paired"] if x not in st["seen"]]):
        print("Device %%s %%s" %% (m, NAMES[m][0]))
elif cmd == "info":
    if arg not in st["seen"] + st["paired"]:
        print("Device %%s not available" %% arg); sys.exit(1)
    n, icon = NAMES[arg]
    print("Device %%s (public)\n\tName: %%s\n\tAlias: %%s\n\tIcon: %%s\n\tPaired: %%s\n\tBonded: %%s\n\tTrusted: %%s\n\tConnected: %%s" %% (
        arg, n, n, icon, "yes" if arg in st["paired"] else "no", "yes" if arg in st.get("bonded", []) else "no", "yes" if arg in st["paired"] else "no",
        "yes" if arg in st["conn"] else "no"))
elif cmd == "pair":
    if not st["power"] or arg not in st["seen"]:
        print("Failed to pair: org.bluez.Error.AuthenticationFailed"); sys.exit(1)
    print("Pairing successful")
    if arg in st.get("trusted", []):                # Beats Fit Pro: paired, not bonded - kept only when trusted
        st["paired"].append(arg)
        if st.get("pairable"):                      # a key is stored only while the adapter is pairable
            st.setdefault("bonded", []).append(arg)
    else:
        st["seen"].remove(arg)
elif cmd == "pairable":
    st["pairable"] = arg == "on"
elif cmd == "trust":
    if arg not in st["seen"] + st["paired"]:
        print("Device %%s not available" %% arg); sys.exit(1)
    st.setdefault("trusted", []).append(arg)
    print("Changing %%s trust succeeded" %% arg)
elif cmd == "connect":
    if arg in st["paired"] and arg not in st["conn"]:
        st["conn"].append(arg)
    print("Connection successful")
elif cmd == "disconnect":
    st["conn"] = [x for x in st["conn"] if x != arg]
elif cmd == "remove":
    st["paired"] = [x for x in st["paired"] if x != arg]; st["conn"] = [x for x in st["conn"] if x != arg]
json.dump(st, open(f, "w"))
''' % (sys.executable, MAC, OTHER, MAC, OTHER)


def fake_tool(tmp):
    p = tmp / "fakebt" / "bluetoothctl"
    p.parent.mkdir()
    p.write_text(FAKE)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_parse():
    assert bt.parse_devices("Device %s Kopfhörer\n\x1b[0;94m[bluetooth]\x1b[0m# \nDevice %s\n" % (MAC, OTHER)) == \
        [(MAC, "Kopfhörer"), (OTHER, "")]
    i = bt.parse_info("Device %s (public)\n\tName: WH-1000\n\tAlias: Meine\n\tIcon: audio-headset\n\tPaired: yes\n"
                      "\tTrusted: no\n\tConnected: yes\n" % MAC)
    assert i == {"name": "Meine", "icon": "audio-headset", "paired": True, "bonded": False, "connected": True,
                 "trusted": False}
    # the pair error, not the lines a running search prints in between
    assert bt._last("Attempting to pair with %s\nFailed to pair: org.bluez.Error.AuthenticationFailed\n"
                    "[DEL] Device %s x\n" % (MAC, OTHER)) == "Failed to pair: org.bluez.Error.AuthenticationFailed"
    assert bt.alsa_device(MAC) == "plug:'bluealsa:DEV=%s,PROFILE=a2dp'" % MAC


def test_pair_and_sound_to_the_headphones(tmp_path):
    async def t(c, jb, u64):
        jb.bt = bt.Bluetooth(tool=fake_tool(tmp_path))
        jb.run_dir = str(tmp_path)
        jb.config.data["hdmi"].update(on=True, sound=False)
        jb.apply_targets()
        await login(c)
        s, r = await get(c, "/api/bt?devices=1")
        assert r["present"] and r["devices"] == [] and not r["mac"]
        s, r = await post(c, "/api/bt", {"act": "pair", "mac": "nonsense"})
        assert not r["ok"]
        s, r = await post(c, "/api/bt", {"act": "scan"})
        found = (await job(c, r["job"]))["result"]
        assert [d["mac"] for d in found] == [MAC]                        # the keyboard is no headphone
        # BlueZ forgets what a search found 30 s after it: pairing searches again
        f = tmp_path / "fakebt" / "bt.json"
        f.write_text(json.dumps(dict(json.loads(f.read_text()), seen=[])))
        s, r = await post(c, "/api/bt", {"act": "pair", "mac": MAC.lower()})
        res = await job(c, r["job"])
        assert res["result"]["connected"] and res["result"]["name"] == "Kopfhoerer X"
        assert res["result"]["bonded"]                                  # it takes the Pi again after switching off
        st = jb.bt_status()
        assert st == {"present": True, "on": True, "mac": MAC, "name": "Kopfhoerer X", "connected": True, "active": True}
        # the TV sound process gets the stream (TV sound itself is off) and plays to bluez-alsa
        assert ("127.0.0.1", jb.hdmi_sound_port) in jb.hub.local
        jb._hdmi_write()
        cfg = json.load(open(os.path.join(jb.run_dir, "hdmi-in.json")))["cfg"]
        assert cfg["sound"] is True and cfg["sound_dev"] == bt.alsa_device(MAC)
        assert ("Ton über Kopfhörer", "an") in [x[:2] for x in jb.menu.entries_of("sound")]
        # switched off on the TV: the TV again (its sound switch is off: no sound process)
        await jb.menu._do(("btout",))
        assert not jb.config["bt"]["on"] and "Fernseher" in jb.menu.note
        assert ("127.0.0.1", jb.hdmi_sound_port) not in jb.hub.local
        s, r = await post(c, "/api/bt", {"act": "on", "on": True})
        assert r["active"]
        # the headphones switched off: back to the TV, found by the check every few seconds
        await post(c, "/api/bt", {"act": "disconnect", "mac": MAC})
        assert not jb.bt_status()["active"]
        jb._hdmi_write()
        assert json.load(open(os.path.join(jb.run_dir, "hdmi-in.json")))["cfg"]["sound_dev"] == ""
        s, r = await get(c, "/api/bt?devices=1")
        assert [(d["mac"], d["connected"]) for d in r["devices"]] == [(MAC, False)]
        await post(c, "/api/bt", {"act": "connect", "mac": MAC})
        assert jb.bt_active()
        await post(c, "/api/bt", {"act": "forget", "mac": MAC})
        assert jb.bt_status()["mac"] == "" and not jb.bt_active()
        assert "Ton über Kopfhörer" not in [x[0] for x in jb.menu.entries_of("main")]
    run(tmp_path, t)


def test_no_bluetooth_on_the_pi(tmp_path):
    async def t(c, jb, u64):
        jb.bt = bt.Bluetooth(tool="bluetoothctl-nicht-da")
        await login(c)
        s, r = await post(c, "/api/bt", {"act": "scan"})
        assert not r["ok"] and "fehlt" in r["msg"]
        assert (await get(c, "/api/bt"))[1]["present"] is False
    run(tmp_path, t)


def test_sound_switches_its_output():
    s = Sound()                                         # aplay starts only with the first packet
    try:
        assert s.device == "" and "-D" in s.cmd
        s.set_device(bt.alsa_device(MAC))
        assert s.cmd[s.cmd.index("-D") + 1] == bt.alsa_device(MAC) and "Ausgabe" in s.gaps[-1]
        s.set_device("")
        assert s.cmd[s.cmd.index("-D") + 1] != bt.alsa_device(MAC)
    finally:
        s.close()


def test_sound_process_takes_the_output():
    """the HDMI service's handle sends "dev" down, the process reports what it plays to"""
    import time
    from c64jukebox.hdmi.soundproc import SoundProc
    sp = SoundProc(0, [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"])
    try:
        assert sp.port
        sp.device = bt.alsa_device(MAC)
        for _ in range(40):
            if sp.dev == bt.alsa_device(MAC):
                break
            time.sleep(0.1)
        assert sp.dev == bt.alsa_device(MAC)
        sp.device = ""
        for _ in range(40):
            if sp.dev == "":
                break
            time.sleep(0.1)
        assert sp.dev == ""
    finally:
        sp.close()


def test_blocked_radio_says_so(tmp_path):
    async def t(c, jb, u64):
        jb.bt = bt.Bluetooth(tool=fake_tool(tmp_path))
        (tmp_path / "fakebt" / "blocked").write_text("")
        await login(c)
        s, r = await post(c, "/api/bt", {"act": "scan"})
        res = await job(c, r["job"])
        assert "rfkill" in res["error"]
    run(tmp_path, t)


def test_headphones_gone_before_pairing(tmp_path):
    """out of pairing mode by the time "Koppeln" is pressed: a clear message, the log says so"""
    from c64jukebox import events
    async def t(c, jb, u64):
        jb.bt = bt.Bluetooth(tool=fake_tool(tmp_path))
        await login(c)
        s, r = await post(c, "/api/bt", {"act": "scan"})
        assert (await job(c, r["job"]))["result"]
        (tmp_path / "fakebt" / "gone").write_text("")
        f = tmp_path / "fakebt" / "bt.json"
        f.write_text(json.dumps(dict(json.loads(f.read_text()), seen=[])))
        bt.FIND_S, old = 2, bt.FIND_S
        try:
            s, r = await post(c, "/api/bt", {"act": "pair", "mac": MAC})
            res = await job(c, r["job"])
        finally:
            bt.FIND_S = old
        assert "nicht mehr gefunden" in res["error"]
        assert any("Koppeln mit %s fehlgeschlagen" % MAC in x[1] for x in events._log)
        assert not jb.bt_status()["mac"]
    run(tmp_path, t)


def test_answer_ends_the_call(tmp_path):
    """bluetoothctl --timeout 30 pair … waits out the 30 s after "Pairing successful": the answer ends it"""
    import time
    p = tmp_path / "slowbt"
    p.write_text("#!/bin/sh\necho 'Attempting to pair'\necho 'Pairing successful'\nexec sleep 30\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    t0 = time.monotonic()
    ok, out = asyncio.run(bt.Bluetooth(tool=str(p)).run("pair", MAC, timeout=40, until=r"Pairing successful"))
    assert ok and "Pairing successful" in out and time.monotonic() - t0 < 5
