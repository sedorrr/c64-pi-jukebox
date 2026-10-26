"""The event log: stream came / went / weak, dropped senders, requests at the Ultimate, devices appearing and
vanishing, tunes and automatic skips - each with a time, for finding sporadic faults afterwards."""
import asyncio
import json

from c64jukebox import events
from c64jukebox.core import Jukebox
from c64jukebox.devices import Devices
from fakes import FakeUltimate
from test_net import audio


def texts():
    return [e["text"] for e in events.recent()]


def test_log_and_recent():
    events.clear()
    events.log("eins", wall=lambda: 1761213296.25)
    r = events.recent()
    assert r[-1]["text"] == "eins" and r[-1]["t"] == 1761213296.2 and len(r[-1]["time"]) == 15


def test_devices_come_and_go():
    events.clear()
    now = [100.0]
    d = Devices(lambda: {"t": "pi"}, clock=lambda: now[0])
    d.datagram_received(b'C64DEV1 {"t":"viz","n":"c64viz2"}', ("192.168.1.224", 11064))
    d.datagram_received(b'C64DEV1 {"t":"viz","n":"c64viz2"}', ("192.168.1.224", 11064))
    now[0] += 40
    d.tick()
    assert texts() == ["Gerät da: c64viz2 (192.168.1.224)", "Gerät weg: c64viz2 (192.168.1.224), 35 s keine Meldung"]


def test_stream_events(tmp_path):
    async def t():
        events.clear()
        u = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "Elite II", "addr": u.addr, "pw": ""}]
        jb.config.data["stream"]["on"] = True
        await jb.start()
        try:
            jb.hub.my_ips = set()
            jb._stream_req_at = -1e9
            await jb._stream_keep()
            assert any(x.startswith("audio:start bei 127.0.0.1") and x.endswith("-> ok") for x in texts())
            jb.hub.datagram_received(audio(1, 3000), ("127.0.0.1", 5000))
            jb.hub.per_second()
            jb._stream_events()
            assert "Stream kommt: von 127.0.0.1" in texts()
            assert texts()[-1] == "Stream schwach: 1 Pakete/s von 127.0.0.1"
            jb.hub.datagram_received(audio(2, 3000), ("192.168.1.202", 5000))   # not an entered Ultimate
            jb.hub.last_rx -= 2
            jb._stream_events()
            assert texts()[-2].startswith("Stream weg: letztes Paket vor 2.") and texts()[-2].endswith("von 127.0.0.1")
            assert texts()[-1] == "1 Pakete von 192.168.1.202 verworfen (keine Kabeladresse eines Ultimate)"
            u.resolve_error = True
            jb._stream_req_at = jb._arp_at = -1e9
            await jb._stream_keep()
            assert any("audio:start bei" in x and "Ultimate hängt" in x for x in texts())
            assert any(x.startswith("Pi meldet sich per ARP bei 127.0.0.1 neu") for x in texts())
        finally:
            await jb.close()
            await u.stop()
    asyncio.run(t())
