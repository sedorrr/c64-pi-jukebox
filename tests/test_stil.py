"""STIL.txt: the format, the lookup by HVSC path or MD5, loading through the page, and the TV."""
import asyncio
import json
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame                                                     # noqa: E402
from aiohttp.test_utils import TestClient, TestServer             # noqa: E402

from c64jukebox import sidfile                                    # noqa: E402
from c64jukebox.core import Jukebox                               # noqa: E402
from c64jukebox.hdmi.app import Osd                               # noqa: E402
from c64jukebox.stil import Stil, parse                           # noqa: E402
from c64jukebox.web import make_app                               # noqa: E402
from fakes import FakeUltimate, make_sid                          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
H = {"X-C64: 1".split(": ")[0]: "1"}
STIL = """### Rob Hubbard ######################
/MUSICIANS/H/Hubbard_Rob/
 COMMENT: All his tunes.

/MUSICIANS/H/Hubbard_Rob/Commando.sid
 COMMENT: "There is an interesting story behind Commando. I went down to
          their office and started working on it late at night." (RH)
(#1)
   TITLE: BGM1 [from the arcade game Commando] (0:00)
  ARTIST: Tamayo Kawamoto
(#2)
    NAME: High score
     BUG: not shown

/MUSICIANS/G/Galway_Martin/Comic_Bakery.sid
 COMMENT: Tune #1 was also in the game "Top Gun".
"""


def test_parse_and_lookup():
    db = parse(STIL)
    assert "/musicians/h/hubbard_rob/commando.sid" in db and "/musicians/h/hubbard_rob/" in db
    s = Stil()
    s.load(STIL)
    one = s.lookup("/MUSICIANS/H/Hubbard_Rob/Commando.sid", 1)
    assert one[0].startswith('"There is an interesting story') and one[0].endswith('late at night." (RH)')   # continued line
    assert "Titel: BGM1 [from the arcade game Commando] (0:00)" in one and "Original von: Tamayo Kawamoto" in one
    two = s.lookup("/musicians/h/hubbard_rob/commando.sid", 2)
    assert "Name: High score" in two and not any("BGM1" in x for x in two) and not any("not shown" in x for x in two)
    assert s.lookup("/nix.sid", 1) == [] and s.lookup(None, 1) == []


def test_state_page_and_tv(tmp_path):
    async def t():
        tune = make_sid("Commando", "Rob Hubbard")
        hv = tmp_path / "sids" / "C64Music" / "MUSICIANS" / "H" / "Hubbard_Rob"
        hv.mkdir(parents=True)
        (hv / "Commando.sid").write_bytes(tune)
        other = tmp_path / "sids" / "Lieblinge"
        other.mkdir()
        (other / "cmd.sid").write_bytes(tune)                             # the same file outside the HVSC
        (tmp_path / "sids" / "STIL.txt").write_text(STIL, encoding="latin-1")
        md5 = sidfile.md5(tune)
        u64 = await FakeUltimate().start()
        jb = Jukebox(str(tmp_path / "data"), stream_port=0, dev_port=0, bcast="127.0.0.1", run_dir=str(tmp_path))
        jb.config.data["ultimates"] = [{"label": "E", "addr": u64.addr, "pw": ""}]
        jb.config.data["sources"] = [{"id": "pi", "kind": "local", "label": "Pi", "path": str(tmp_path / "sids")}]
        app = make_app(jb)
        app.on_startup.append(lambda a: jb.start())
        app.on_cleanup.append(lambda a: jb.close())
        c = TestClient(TestServer(app))
        await c.start_server()
        try:
            await c.post("/api/login", json={"pw": "commodore64"}, headers=H)
            r = await (await c.post("/api/stil/load", json={"src": "pi", "path": "/STIL.txt"}, headers=H)).json()
            for _ in range(100):
                d = await (await c.get("/api/job?id=" + r["job"])).json()
                if d["done"]:
                    break
                await asyncio.sleep(0.05)
            assert d["result"]["n"] == 3
            st = await (await c.get("/api/state")).json()
            assert st["sl"]["stil"] == 3
            await jb.player.set_items([{"src": "pi", "path": "/C64Music/MUSICIANS/H/Hubbard_Rob/Commando.sid",
                                        "name": "Commando.sid"}], 0, play=True, source="t")
            st = await (await c.get("/api/state")).json()
            assert st["player"]["now"]["stil"][0].startswith('"There is')                  # by its HVSC path
            await jb.player.set_items([{"src": "pi", "path": "/Lieblinge/cmd.sid", "name": "cmd.sid"}], 0, play=True,
                                      source="t")
            st = await (await c.get("/api/state")).json()
            assert st["player"]["now"]["stil"] == []                                       # not known yet
            await jb.set_songlengths("hvsc", ("; /MUSICIANS/H/Hubbard_Rob/Commando.sid\n%s=3:05\n" % md5).encode(),
                                     {"label": "t"})
            st = await (await c.get("/api/state")).json()
            assert st["player"]["now"]["stil"][0].startswith('"There is')                  # by its MD5
            jb._hdmi_write()
            hin = json.load(open(tmp_path / "hdmi-in.json"))
            assert hin["player"]["now"]["stil"]
            # the TV: bottom left
            pygame.init()
            items = Osd().items(hin["player"], "", "c64pi")
            stil = next(i for i in items if i.key == "osd_stil")
            assert stil.rect.left == 60 and stil.rect.bottom == 1080 - 48 and stil.rect.width <= 1160
            assert "osd_stil" not in [i.key for i in Osd().items(hin["player"], "", "c64pi", stil=False)]
            await c.post("/api/stil/clear", json={}, headers=H)
            st = await (await c.get("/api/state")).json()
            assert st["sl"]["stil"] == 0 and st["player"]["now"]["stil"] == []
        finally:
            await c.close()
            await u64.stop()
    asyncio.run(t())


def test_continuation_that_looks_like_a_field():
    s = Stil()
    s.load("/X/y.sid\n COMMENT: The tune is from the game. See also\n         NOTE: this line belongs to the comment.\n")
    assert s.lookup("/X/y.sid", 1) == ["The tune is from the game. See also NOTE: this line belongs to the comment."]
