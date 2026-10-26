"""Party mode, the jukebox's side: while netwatch reports it running with the Ultimate on the cable, the chosen Ultimate
is 10.64.64.2; the settings are checked; the QR code gets the access point's address when there is no router."""
import asyncio
import json

import pytest

from c64jukebox import core as core_mod
from c64jukebox.core import Jukebox


def test_party_settings_and_address(tmp_path, monkeypatch):
    async def t():
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "Elite II", "addr": "192.168.1.168", "pw": "x"}]
        await jb.start()
        try:
            with pytest.raises(ValueError):
                jb.party_set({"on": True, "ssid": ""})
            with pytest.raises(ValueError):
                jb.party_set({"on": True, "ssid": "MeinWLAN", "pw": "kurz"})
            st = jb.party_set({"on": True, "ssid": "MeinWLAN"})
            assert st["on"] and st["ssid"] == "MeinWLAN" and not st["pw_set"]
            assert jb.config.public()["party"]["pw"] == ""
            jb.party_set({"pw": "heimgeheim"})
            assert jb.party_state()["pw_set"] and jb.config.public()["party"]["pw"] != "heimgeheim"
            # netwatch: waiting at home -> the entered address stays
            net = tmp_path / "net.json"
            net.write_text(json.dumps({"mode": "lan", "party": {"state": "wartet", "why": "Heim-WLAN in Reichweite"}, "t": 0}))
            jb._party_check()
            assert jb.ultimate().addr == "192.168.1.168"
            # running with the Ultimate on the cable -> that one, with its password
            net.write_text(json.dumps({"mode": "party", "ap": {"ssid": "MeinWLAN", "ip": "192.168.4.1"},
                                       "party": {"state": "aktiv", "eth": True, "u64": "10.64.64.2"}, "t": 0}))
            jb._party_check()
            assert jb.ultimate().addr == "10.64.64.2" and jb.ultimate().pw == "x"
            monkeypatch.setattr(core_mod, "local_ip", lambda towards="192.0.2.1": "127.0.0.1")   # no router
            assert jb.my_ip() == "192.168.4.1"
            jb.party_set({"on": False})
            jb._party_check()
            assert jb.ultimate().addr == "192.168.1.168"
        finally:
            await jb.close()
    asyncio.run(t())
