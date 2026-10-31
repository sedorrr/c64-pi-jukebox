"""Browser tests (Playwright, Chromium) against the demo server: phone and desktop size, the whole way from the
login to playing, sources, lists, devices, settings and the manual. Screenshots land in tests/web/*.png."""
import json
import os
import re

import pytest

pw = pytest.importorskip("playwright.sync_api")

from demo_server import Demo  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PHONE = {"width": 390, "height": 844}
DESK = {"width": 1200, "height": 900}


@pytest.fixture(scope="module")
def demo():
    d = Demo().start()
    yield d
    d.stop()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def new_page(browser, demo, size, login=True):
    demo.jb.config.data["web"]["pw_hash"] = ""            # an earlier test may have changed the password
    ctx = browser.new_context(viewport=size, accept_downloads=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.errors = errors
    page.goto(demo.url)
    if login:
        page.fill("#lpw", "commodore64")
        page.press("#lpw", "Enter")
        page.wait_for_selector("#app:not([hidden])")
    return page


def no_overflow(page):
    w = page.evaluate("document.documentElement.scrollWidth")
    assert w <= page.viewport_size["width"], "page wider than the screen: %d" % w


def plays(demo):
    return [c for c in demo.u64.calls if c[1] == "/v1/runners:sidplay"]


def until(cond, secs=5):
    import time
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def open_path(page, *names):
    for n in names:
        page.click("#flist li.dir:has-text('%s')" % n)
        page.wait_for_function("document.getElementById('fstatus').textContent.indexOf('Lese') < 0")


def test_login(browser, demo):
    page = new_page(browser, demo, PHONE, login=False)
    page.wait_for_selector("#login:not([hidden])")
    page.fill("#lpw", "falsch")
    page.press("#lpw", "Enter")
    page.wait_for_selector("#lmsg:has-text('Passwort falsch')")
    page.fill("#lpw", "commodore64")
    page.click("#lform button")
    page.wait_for_selector("#app:not([hidden])")
    assert page.is_visible("#pwwarn")                          # still the first password
    demo.jb.update = {"ver": "9.9", "newer": True, "at": 0}       # a newer version on GitHub: the blue hint
    page.wait_for_selector("#updbar:not([hidden]):has-text('Version 9.9')")
    page.click("#updx")                                        # closed: stays away for this version
    page.reload()
    page.wait_for_selector("#app:not([hidden])")
    page.wait_for_timeout(1500)
    assert page.is_hidden("#updbar")
    demo.jb.update = None
    right = page.evaluate("Math.max(...[...document.querySelectorAll('#tabs button')].map(b => b.getBoundingClientRect().right))")
    assert right <= PHONE["width"], "tabs do not fit on the phone: %d" % right
    assert not page.errors


def test_phone_browse_and_play(browser, demo):
    page = new_page(browser, demo, PHONE)
    page.click("#tabs button[data-t=files]")
    page.wait_for_selector(".src.on")
    assert page.locator(".src").count() == 3                    # two sources + "+ Quelle"
    no_overflow(page)
    open_path(page, "USB2", "SID-Tunes", "MUSICIANS", "H", "Hubbard_Rob")
    page.wait_for_selector("#flist li.sid:has-text('Rob Hubbard')")
    assert page.inner_text("#flist li.sid >> nth=0").count("3 Lieder") == 1
    page.fill("#ffilter", "delta")
    assert page.locator("#flist li.sid").count() == 1
    page.fill("#ffilter", "")
    n0 = len(plays(demo))
    page.click("#flist li.sid:has-text('Commando')")
    page.wait_for_function("document.getElementById('toast').textContent.includes('Commando')")
    m, path, q, _ = plays(demo)[n0]
    assert (m, q["file"]) == ("PUT", "/USB2/SID-Tunes/MUSICIANS/H/Hubbard_Rob/Commando.sid")   # on the Ultimate: by path
    page.screenshot(path=os.path.join(HERE, "phone_files.png"), full_page=True)
    page.click("#tabs button[data-t=play]")
    page.wait_for_selector("#nt:has-text('Commando')")
    assert page.is_visible("#songsel") and "Lied 1 von 3" in page.inner_text("#sinfo")
    page.click("#sup")
    page.wait_for_selector("#sinfo:has-text('Lied 2 von 3')")
    assert plays(demo)[-1][2]["songnr"] == "2"
    page.click("#bplay")                                       # pause
    page.wait_for_selector("#nb:has-text('Pause')")
    assert demo.u64.calls[-1][1] == "/v1/machine:pause"
    page.click("#bplay")
    page.wait_for_function("!document.getElementById('nb').textContent.includes('Pause')")
    page.wait_for_selector("#lrows .lrow.cur:has-text('Commando')")              # the running tune is marked
    assert page.locator("#lrows .lrow[data-i]").count() == 2
    page.click("#lrows .lrow[data-i='1']")
    page.click("#lrows .lrow[data-i='1']")                                     # double tap plays
    page.wait_for_selector("#nt:has-text('Delta')")
    page.wait_for_selector("#lrows .lrow.cur[data-i='1']")
    page.click("#lcheck")                                                    # "Längen prüfen": its answer is seen
    page.wait_for_selector("#plmsg:has-text('Dateien gelesen')")
    assert page.is_enabled("#lcheck")
    cur, pl = demo.jb.player.cur, demo.jb.player                             # "Ende hier merken": only without a length
    was = cur["secs"]
    cur["secs"], pl.version = None, pl.version + 1
    page.wait_for_selector("#endrow:not([hidden])")
    cur["secs"], pl.version = 120, pl.version + 1
    page.wait_for_selector("#endrow[hidden]", state="attached")
    cur["secs"], pl.version = None, pl.version + 1                          # a repeat found: the suggestion instead
    demo.jb.loop_hint, pl.version = {"len": 95, "lag": 95, "cur": cur}, pl.version + 1
    page.wait_for_selector("#looprow:not([hidden])")
    assert "1:35" in page.inner_text("#looptxt") and not page.is_visible("#endrow")
    page.locator("#looprow >> xpath=..").screenshot(path=os.path.join(HERE, "phone_loop.png"))
    page.click("#bloopno")
    page.wait_for_selector("#looprow[hidden]", state="attached")
    assert demo.jb.loop_hint is None
    cur["secs"], pl.version = was, pl.version + 1
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_play.png"), full_page=True)
    # save the list, see it in "Listen", load it again
    page.click("#lsave")
    page.fill("#askin", "Hubbard")
    page.click("#askok")
    page.wait_for_selector("#toast:has-text('Gespeichert')")
    page.click("#tabs button[data-t=lists]")
    page.wait_for_selector("#pls li:has-text('Hubbard')")
    assert "2 Titel" in page.inner_text("#pls li")
    page.wait_for_selector("#hist li:has-text('Delta')")                    # "Zuletzt gespielt", newest first
    assert page.locator("#hist li").count() == 3                          # Commando song 1 and 2, Delta
    assert "Delta" in page.inner_text("#hist li >> nth=0") and "Lied 2/3" in page.inner_text("#hist li >> nth=1")
    no_overflow(page)
    page.wait_for_selector("#smpre button[data-pre=fav]")                 # "Listen zusammenstellen"
    assert page.locator("#smpre button").count() == 6 and "Favoriten" in page.inner_text("#smstate")
    page.click("#smown summary")
    assert page.is_visible("#smplay")
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_lists.png"), full_page=True)
    page.click("#smown summary")
    page.click("#pls li button[data-a=ren]")                              # rename the list
    page.fill("#askin", "Hubbard Best")
    page.click("#askok")
    page.wait_for_selector("#pls li:has-text('Hubbard Best')")
    assert [p["name"] for p in demo.jb.playlists()] == ["Hubbard Best"]
    page.click("#pls li button[data-a=add]")
    page.wait_for_selector("#toast:has-text('angehängt')")
    page.click("#tabs button[data-t=play]")
    page.wait_for_selector("#lhead:has-text('4 Titel')")
    # row menu: remove the last one
    page.click("#lrows .lrow[data-i='3'] [data-more]")
    page.click("#menubtns button:has-text('Aus der Liste nehmen')")
    page.wait_for_selector("#lhead:has-text('3 Titel')")
    page.on("dialog", lambda d: d.accept())
    page.click("#lmenu")
    page.click("#menubtns button:has-text('Liste leeren')")
    page.wait_for_selector("#lempty:not([hidden])")
    assert demo.u64.calls[-1][1] == "/v1/machine:reset"
    assert not page.errors


def test_desktop_folder_search_and_new_source(browser, demo):
    page = new_page(browser, demo, DESK)
    page.click("#tabs button[data-t=files]")
    page.click(".src:has-text('Ordner am Pi')")
    page.wait_for_selector("#flist li.dir:has-text('MUSICIANS')")
    page.fill("#ffilter", "hubbard")
    page.click("#fsearch")
    page.wait_for_selector("#crumbs:has-text('Suche')")
    assert page.locator("#flist li.sid").count() == 2
    assert "MUSICIANS/H/Hubbard_Rob" in page.inner_text("#flist")
    page.click("#crumbs a:has-text('✕')")
    page.wait_for_selector("#flist li.dir:has-text('MUSICIANS')")
    # the whole HVSC from Songlengths.md5 (loaded from this source); titles read once in the settings
    import os as _os
    sl = open(_os.path.join(demo.jb.config.source("pi")["path"], "DOCUMENTS", "Songlengths.md5"), "rb").read()
    demo.call(demo.jb.set_songlengths("hvsc", sl, {"src": "pi", "path": "/DOCUMENTS/Songlengths.md5", "label": "Ordner am Pi"}))
    try:
        page.wait_for_selector("#fhvsc:not([hidden])")
        page.click(".src:has-text('USB-Stick am Ultimate')")                     # from another source
        page.fill("#ffilter", "huelsbeck")
        page.click("#fhvsc")
        page.wait_for_selector("#fstatus:has-text('1 Treffer')")                # Turrican: only its header says so
        assert "Huelsbeck_Chris/Shades.sid" in page.inner_text("#flist")
        page.click("#tabs button[data-t=set]")
        page.wait_for_selector("#hvtrow:not([hidden]) #hvtgo")
        page.click("#hvtgo")
        page.wait_for_selector("#hvtstate:has-text('7 von 7')")
        page.click("#tabs button[data-t=files]")
        page.fill("#ffilter", "rainbow arts")                                   # only in the headers
        page.click("#fhvsc")
        page.wait_for_selector("#fstatus:has-text('2 Treffer')")
        assert "Turrican" in page.inner_text("#flist")
        page.click("#crumbs a:has-text('✕')")
    finally:
        demo.jb.clear_songlengths("hvsc")
    page.wait_for_selector("#flist li.dir:has-text('MUSICIANS')")
    # the whole folder with sub-folders, shuffled
    page.check("#fshuf")
    page.click("#fplay")
    page.wait_for_selector("#toast:has-text('7 Titel')")
    page.click("#tabs button[data-t=play]")
    page.wait_for_selector("#lhead:has-text('7 Titel')")
    assert page.is_checked("#oshuf")
    page.uncheck("#oshuf")
    # a new SMB source found by the network search
    page.click("#tabs button[data-t=files]")
    page.click("#srcnew")
    page.wait_for_selector("#srcdlg[open]")
    page.click("#sscan")
    page.wait_for_selector("#sscanprog .jprog")                # progress while it searches
    txt = page.inner_text("#sscanprog")
    assert re.search(r"\d+ %", txt) and ("prüft gerade" in txt or "Namen" in txt), txt
    page.wait_for_selector("#sscanres button")
    page.fill("#su", "nutzer")
    page.fill("#sw", "geheim")
    page.click("#sscanres button >> nth=0")
    page.wait_for_selector("#sshareres button:has-text('Musik')")
    page.click("#sshareres button:has-text('Musik')")
    assert page.input_value("#ss") == "Musik"
    page.click("#stest")
    page.wait_for_selector("#smsg:has-text('Verbindung klappt')")
    page.screenshot(path=os.path.join(HERE, "desk_source.png"))
    page.click("#ssave")
    page.wait_for_selector(".src.on:has-text('Musik')")
    open_path(page, "C64Music", "GAMES", "S-Z")
    page.wait_for_selector("#flist li.sid:has-text('Turrican')")
    page.click("#flist li.sid:has-text('Turrican') button.add")
    page.wait_for_selector("#toast:has-text('angehängt')")
    up = plays(demo)[-1]
    assert up[0] == "PUT" or up[0] == "POST"
    # edit: the password stays masked and is kept on saving
    page.click(".src.on button.ed")
    assert page.input_value("#sw") == "\u2022\u2022\u2022\u2022"
    page.click("#ssave")
    cfg = json.load(open(demo.jb.config.path))
    assert [s for s in cfg["sources"] if s["kind"] == "smb"][0]["pw"] == "geheim"
    # song lengths from the folder, shown with the tunes
    page.click("#crumbs a >> nth=0")
    open_path(page, "C64Music", "DOCUMENTS")
    page.click("#flist li.other button[data-sl=hvsc]")
    page.wait_for_selector("#toast:has-text('Songlängen geladen')")
    page.click("#crumbs a >> nth=1")
    open_path(page, "MUSICIANS", "G", "Galway_Martin")
    page.wait_for_selector("#flist li.sid:has-text('Wizball')")
    assert re.search(r"\d:\d\d", page.inner_text("#flist li.sid"))
    page.screenshot(path=os.path.join(HERE, "desk_files.png"), full_page=True)
    assert not page.errors


def test_devices_settings_help(browser, demo):
    page = new_page(browser, demo, PHONE)
    page.click("#tabs button[data-t=dev]")
    page.wait_for_selector("#u64rows .erow")
    assert page.input_value("#u64rows .ul") == "Elite II"
    page.click("#picoadd")
    page.fill("#picorows .erow >> nth=1 >> .pa", "c64viz2.local")
    page.select_option("#picorows .erow >> nth=1 >> .pn", "http")
    page.click("#picosave")
    until(lambda: len(demo.jb.config["picos"]) == 2)
    assert [p["addr"] for p in demo.jb.config["picos"]] == ["c64viz.local", "c64viz2.local"]
    assert demo.jb.config["picos"][1]["np"] == "http"
    page.check("#ston")
    until(lambda: any(c[1] == "/v1/streams/audio:start" for c in demo.u64.calls))
    page.uncheck("#ston")
    page.fill("#u64rows .erow >> nth=0 >> .uw", "02-00-00-00-00-01")      # WLAN MAC for waking (not a real device)
    page.click("#u64save")
    until(lambda: demo.jb.config["ultimates"][0].get("wmac") == "02:00:00:00:00:01")
    page.once("dialog", lambda d: d.accept())                  # "ausschalten?"
    page.click("#u64rows .erow >> nth=0 >> .uoff")
    page.wait_for_selector("#u64power:has-text('ausgeschaltet')")
    assert any(c[1] == "/v1/machine:poweroff" for c in demo.u64.calls)
    page.check("#pnews")                                       # retro news to the Picos
    until(lambda: demo.jb.config["pico_news"] is True)
    page.wait_for_selector("#pnstate:has-text('Schlagzeilen')")
    page.uncheck("#pnews")
    until(lambda: demo.jb.config["pico_news"] is False)
    page.click("#u64scan")
    page.wait_for_selector("#u64found button")
    assert "Ultimate 64 Elite II" in page.inner_text("#u64found")
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_devices.png"), full_page=True)
    # settings
    assert page.input_value("#pname") == demo.jb.config["name"]            # the Pi's name: with the device list
    page.click("#tabs button[data-t=set]")
    page.wait_for_function("document.getElementById('plim').value !== ''")       # settings loaded
    page.fill("#plim", "3")
    page.select_option("#psub", "all")
    page.click("#psave")
    until(lambda: demo.jb.config["player"]["limit_min"] == 3)
    assert demo.jb.config["player"]["subsongs"] == "all"
    # the timer: a new entry (weekdays 18:00, play) with Saturday added, another one that stops
    page.click("#schadd")
    page.click("#schrows .srow:last-child .days label:has-text('Sa')")
    page.click("#schadd")
    page.select_option("#schrows .srow:last-child .sdo", "stop")
    assert page.is_hidden("#schrows .srow:last-child .slist")
    page.fill("#schrows .srow:last-child .stime", "23:30")
    page.click("#schsave")
    page.wait_for_selector("#toast:has-text('Zeitplan gespeichert')")
    sch = demo.jb.config["schedule"]
    assert [(e["time"], e["do"], e["days"]) for e in sch] == [("18:00", "play", [0, 1, 2, 3, 4, 5]), ("23:30", "stop", [0, 1, 2, 3, 4])]
    assert "Als Nächstes:" in page.inner_text("#schstate")
    page.locator("#schrows").evaluate("e => e.closest('.card').scrollIntoView()")
    page.screenshot(path=os.path.join(HERE, "phone_schedule.png"))
    page.click("#schrows .srow:first-child .sx")
    page.click("#schsave")
    until(lambda: [e["do"] for e in demo.jb.config["schedule"]] == ["stop"])
    no_overflow(page)
    page.set_input_files("#slupc", files=[{"name": "mine.txt", "mimeType": "text/plain",
                                           "buffer": b"0123456789abcdef0123456789abcdef=99\n"}])
    page.wait_for_selector("#slstate:has-text('1 Einträge')")
    with page.expect_download() as dl:
        page.click("#bkdl")
    path = dl.value.path()
    bk = json.load(open(path))
    assert bk["fmt"] == "c64pi-backup"
    page.on("dialog", lambda d: d.accept())
    page.set_input_files("#bkup", files=[{"name": "s.json", "mimeType": "application/json", "buffer": json.dumps(bk).encode()}])
    page.wait_for_selector("#toast:has-text('Sicherung eingespielt')")
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_settings.png"), full_page=True)
    # the manual, also from a "?" in another tab
    page.click("#tabs button[data-t=files]")
    page.click("a.hl >> visible=true")
    page.wait_for_selector("#helpbody h2")
    assert page.is_visible("section[data-tab=help]")
    page.wait_for_function("Math.abs(document.getElementById('h-dateien-auswaehlen').getBoundingClientRect().top) < 150")
    no_overflow(page)
    # the password: change, log out, log in with the new one
    page.click("#tabs button[data-t=set]")
    page.fill("#pwold", "commodore64")
    page.fill("#pwnew", "sid6581")
    page.click("#pwsave")
    page.wait_for_selector("#toast:has-text('Passwort geändert')")
    page.wait_for_selector("#pwwarn", state="hidden")
    page.click("#logout")
    page.wait_for_selector("#login:not([hidden])")
    page.fill("#lpw", "sid6581")
    page.press("#lpw", "Enter")
    page.wait_for_selector("#app:not([hidden])")
    assert not page.errors


def test_help_links_have_targets():
    """every help('…') of the page names a section of the manual"""
    from c64jukebox.markdown import to_html
    root = os.path.dirname(os.path.dirname(HERE))
    html = open(os.path.join(root, "c64jukebox", "web", "index.html"), encoding="utf-8").read()
    _, ids = to_html(open(os.path.join(root, "docs", "HANDBUCH.md"), encoding="utf-8").read())
    links = re.findall(r"help\('([^']+)'\)", html)
    assert links and all(h in ids for h in links), [h for h in links if h not in ids]


def test_list_window(browser, demo):
    """the table: sort, select several, play next, favorite, own length, search, focus on the running tune"""
    page = new_page(browser, demo, DESK)
    demo.call(demo.jb.player.set_items([{"src": "pi", "path": "/" + p, "name": p.rsplit("/", 1)[-1]} for p, _ in
                                        __import__("demo_server").TUNES], 0, play=True, source="Test"))
    page.click("#tabs button[data-t=play]")
    page.wait_for_selector("#lrows .lrow.cur[data-i='0']")

    async def check():                    # what the page's routes do after a new list (alone, no cache helps)
        demo.jb.auto_check()
    demo.call(check())
    until(lambda: all(i.get("md5") for i in demo.jb.player.items), 15)     # headers read in the background
    demo.call(demo.jb.sid_refresh())                                        # like every minute
    page.wait_for_selector("#lrows .lrow .c-sids.sidw:has-text('$D420')")   # Dual Core: socket 2 is $D500
    assert "umgestellt" in page.get_attribute("#lrows .c-sids.sidw", "title")
    assert page.locator("#lrows .c-sids.sidw").count() == 1
    page.locator("#lwin").screenshot(path=os.path.join(HERE, "desk_sidwarn.png"))
    page.click("#lhd [data-col=title]")                                     # sort by title
    page.wait_for_selector("#lhd [data-col=title]:has-text('▲')")
    titles = [r["title"] for r in demo.call(_rows(demo.jb))]
    assert titles == sorted(titles, key=str.lower)
    assert demo.jb.player.items[demo.jb.player.current_index()]["name"] == "Commando.sid"   # still the running one
    page.click("#lhd [data-col=title]")
    page.wait_for_selector("#lhd [data-col=title]:has-text('▼')")
    # select two with ctrl, queue them next
    page.click("#lrows .lrow[data-i='1']")
    page.click("#lrows .lrow[data-i='2']", modifiers=["ControlOrMeta"])
    assert page.locator("#lrows .lrow.sel").count() == 2
    page.click("#lnext")
    page.wait_for_selector("#toast:has-text('2 Titel kommen als Nächstes')")
    p = demo.jb.player
    assert p.order[p.pos + 1:p.pos + 3] == [1, 2]
    # favorite + only favorites
    page.click("#lrows .lrow[data-i='4'] [data-fav]")
    page.wait_for_selector("#lrows .lrow[data-i='4'] .c-fav:has-text('★')")
    page.check("#lfav")
    page.wait_for_function("document.querySelectorAll('#lrows .lrow[data-i]').length === 1")
    page.uncheck("#lfav")
    # own length via the row menu
    page.click("#lrows .lrow[data-i='5'] [data-more]")
    page.click("#menubtns button:has-text('Eigene Länge')")
    page.fill("#askin", "3:05")
    page.click("#askok")
    page.wait_for_selector("#lrows .lrow[data-i='5'] .c-len:has-text('3:05*')")
    # never play again via the row menu: struck through, in the "Listen" tab with "Wieder spielen"
    page.click("#lrows .lrow[data-i='6'] [data-more]")
    page.click("#menubtns button:has-text('Nicht mehr spielen')")
    page.wait_for_selector("#lrows .lrow.blk[data-i='6']")
    assert len(demo.jb.stats.block) == 1
    page.click("#tabs button[data-t=lists]")
    page.wait_for_selector("#blocked li button:has-text('Wieder spielen')")
    page.click("#blocked li button")
    page.wait_for_function("document.querySelectorAll('#blocked li').length === 0")
    assert not demo.jb.stats.block
    page.click("#tabs button[data-t=play]")
    page.wait_for_selector("#lrows .lrow[data-i='6']:not(.blk)")
    # search (server side, whole list)
    page.fill("#lfilter", "hülsbeck")
    page.wait_for_function("document.querySelectorAll('#lrows .lrow[data-i]').length === 2")
    page.fill("#lfilter", "")
    page.wait_for_function("document.querySelectorAll('#lrows .lrow[data-i]').length === 7")
    # a long list: the running tune is brought into view
    many = [{"src": "pi", "path": "/x%d.sid" % k, "name": "x%04d.sid" % k} for k in range(3000)]
    demo.call(demo.jb.player.set_items(many, 2500, play=False, source="lang"))
    demo.jb.player.state = "stop"
    page.wait_for_selector("#lhead:has-text('3.000 Titel')")
    page.click("#lfocus")
    # measured in one go in the page: the rows are drawn anew now and then, a row found a moment ago may be gone
    page.wait_for_function("""() => {
        const r = document.querySelector("#lrows .lrow.cur[data-i='2500']"), w = document.querySelector("#lwin");
        if (!r || !w) return false;
        const a = r.getBoundingClientRect(), b = w.getBoundingClientRect();
        return b.top < a.top && a.top < b.bottom;
    }""")
    assert page.locator("#lrows .lrow").count() < 120                      # only the visible rows exist
    page.screenshot(path=os.path.join(HERE, "desk_list.png"))
    assert not page.errors


async def _rows_async(jb):
    return jb.list_rows(0, 50)["rows"]


def _rows(jb):
    return _rows_async(jb)


def test_import_shared_playlist(browser, demo, tmp_path):
    import hashlib
    import demo_server
    songs = [{"md5": hashlib.md5(d).hexdigest(), "filename": "renamed.sid", "title": "x", "author": "y"}
             for p, d in demo_server.TUNES[:3]]
    songs.append({"md5": "0" * 32, "filename": "Turrican.sid", "title": "T", "author": "C"})      # by file name
    songs.append({"md5": "1" * 32, "filename": "gibtsnicht.sid", "title": "Fehlt", "author": "Niemand"})
    f = tmp_path / "Party_u64playlist.json"
    f.write_text(json.dumps({"format": "ultimate64_sid_player_shared_playlist", "version": 1, "name": "Party", "songs": songs}))
    page = new_page(browser, demo, PHONE)
    page.click("#tabs button[data-t=play]")
    page.click("#lmenu")
    page.click("#menubtns button:has-text('importieren')")
    page.wait_for_selector("#impsrc option[value=pi]", state="attached")
    page.set_input_files("#impfile", str(f))
    page.wait_for_selector("#impname:has-text('5 Titel')")
    page.select_option("#impsrc", "pi")
    page.fill("#imppath", "/")
    page.click("#impgo")
    page.wait_for_selector("#impres:has-text('4 von 5')")
    assert "Fehlt - Niemand" in page.inner_text("#impres") and "Party" in page.inner_text("#impres")
    names = [i["name"] for i in demo.jb.player.items]
    assert names[:3] == [p.rsplit("/", 1)[-1] for p, _ in demo_server.TUNES[:3]] and names[3] == "Turrican.sid"
    page.click("#impclose")
    assert not page.errors


def test_network_and_display_card(browser, demo):
    page = new_page(browser, demo, PHONE)
    page.on("dialog", lambda d: d.accept())
    page.click("#tabs button[data-t=set]")                      # settings, group "Netzwerk des Pi"
    page.wait_for_selector("#netstate:has-text('Netzwerkkabel')")
    assert "192.168.1.78" in page.inner_text("#netstate")
    page.click("#wscan")
    page.wait_for_selector("#wlist button:has-text('MeinWLAN')")
    assert "3 WLANs gefunden" in page.inner_text("#wmsg")
    page.click("#wlist button:has-text('MeinWLAN')")
    page.fill("#askin", "geheim123")
    page.click("#askok")
    page.wait_for_selector("#wmsg:has-text('verbunden mit MeinWLAN')")
    assert demo.net.requests[-1] == {"id": demo.net.requests[-1]["id"], "action": "connect", "ssid": "MeinWLAN", "pw": "geheim123"}
    page.fill("#apssid", "C64-Wohnzimmer")
    page.fill("#appw", "kurz")
    page.click("#netsave")
    page.wait_for_selector("#toast:has-text('mindestens 8 Zeichen')")
    page.fill("#appw", "retro12345")
    page.click("#netsave")
    until(lambda: demo.jb.config["wlan"]["ap_pw"] == "retro12345")
    assert demo.jb.config["wlan"]["ap_ssid"] == "C64-Wohnzimmer"
    # party mode: the home WLAN's name; a short password is refused, an empty one means "the saved one"
    page.check("#pon")
    page.fill("#pssid", "")
    page.click("#psave2")
    page.wait_for_selector("#toast:has-text('Heim-WLANs')")
    page.fill("#pssid", "MeinWLAN")
    page.fill("#ppw", "kurz")
    page.click("#psave2")
    page.wait_for_selector("#toast:has-text('mindestens 8 Zeichen')")
    page.fill("#ppw", "")
    page.click("#psave2")
    until(lambda: demo.jb.config["party"] == {"on": True, "ssid": "MeinWLAN", "pw": ""})
    page.wait_for_selector("#pstate:has-text('wartet')")
    page.uncheck("#pon")
    page.click("#psave2")
    until(lambda: demo.jb.config["party"]["on"] is False)
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_settings.png"), full_page=True)
    page.click("#tabs button[data-t=show]")                     # tab "Anzeige": the small display
    page.wait_for_selector("#hmode option", state="attached")   # the tab has loaded its settings
    page.select_option("#dtype", "sh1106")
    page.fill("#doff", "30")
    page.click("#dsave")
    until(lambda: demo.jb.config["display"] == {"type": "sh1106", "off_min": 30, "flip": False, "cal": None, "touch": "own", "dc": 24})
    page.wait_for_selector("#dstate:has-text('Display')")
    assert not page.is_visible("#dcal")
    page.select_option("#dtype", "tft")                          # 2.8" touch: flip + calibration appear
    page.wait_for_selector("#dcal", state="visible")
    assert page.input_value("#dtouch") == "own"                   # without Y cables: the touch on its own bus
    page.select_option("#ddc", "23")                              # a Pi with a damaged pin 18: D/C on pin 16
    page.click("#dsave")
    until(lambda: demo.jb.config["display"]["dc"] == 23)
    page.click("#dcal")
    page.wait_for_selector("#toast:has-text('Kein Touch-Display')")       # not in use yet (and no SPI here)
    page.check("#dflip")
    page.click("#dsave")
    until(lambda: demo.jb.config["display"]["type"] == "tft")
    assert demo.jb.config["display"]["flip"] is True
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_show.png"), full_page=True)
    assert not page.errors


def test_hdmi_card(browser, demo):
    import io
    import time
    from PIL import Image
    page = new_page(browser, demo, PHONE)
    page.on("dialog", lambda d: d.accept())
    page.click("#tabs button[data-t=show]")
    page.wait_for_selector("#hstate:has-text('aus')")
    assert page.locator("#hmode option").count() == 18
    page.check("#hon")
    until(lambda: demo.jb.config["hdmi"]["on"])
    page.wait_for_selector("#hstate:has-text('meldet sich nicht')")
    with open(os.path.join(demo.run_dir, "hdmi.json"), "w") as f:     # what the service would report
        json.dump({"t": time.time(), "on": True, "fps": 29.8, "screen": "Grafikchip (KMSDRM)", "audio_age": 0.1}, f)
    page.wait_for_selector("#hstate:has-text('29.8 Bilder/s')", timeout=8000)
    assert "Ton kommt an" in page.inner_text("#hstate")
    page.select_option("#hmode", "milkdrop")
    until(lambda: demo.jb.config["hdmi"]["mode"] == "milkdrop")
    page.select_option("#hbg", "images")
    page.wait_for_selector("#himgbox:not([hidden])")
    buf = io.BytesIO()
    Image.new("RGB", (1200, 800), (30, 90, 160)).save(buf, "JPEG")
    page.set_input_files("#hfiles", files=[{"name": "Strand.jpg", "mimeType": "image/jpeg", "buffer": buf.getvalue()}])
    page.wait_for_selector("#hlist figure:has-text('Strand.jpg') img")
    page.wait_for_function("document.querySelector('#hlist img').naturalWidth === 1920")
    page.uncheck("#hidle")
    until(lambda: demo.jb.config["hdmi"]["idle_hide"] is False)
    page.check("#hidle")
    # retro news: switch on, own feed (a wrong address is refused), back to the standard ones
    page.check("#nidle")
    until(lambda: demo.jb.config["hdmi"]["news_idle"] is True)
    assert page.locator("#nfeeds .nrow").count() == 7                 # the known pages
    assert page.locator("#nfeeds .non:checked").count() == 5
    page.check("#nfeeds .nrow:has(.nu[value*='brewotaku']) .non")     # a tick takes effect at once
    until(lambda: any(f["on"] and "brewotaku" in f["url"] for f in demo.jb.config["hdmi"]["news_feeds"]))
    page.click("#nadd")
    page.fill("#nfeeds .nrow:last-child .nl", "Kaputt")
    page.fill("#nfeeds .nrow:last-child .nu", "ftp://nein")
    page.click("#nsave")
    page.wait_for_selector("#toast:has-text('Keine gültige Adresse')")
    page.fill("#nfeeds .nrow:last-child .nu", "https://example.org/feed.xml")
    page.click("#nfeeds .nrow:first-child .nx")
    page.click("#nsave")
    until(lambda: [f["url"] for f in demo.jb.config["hdmi"]["news_feeds"]][-1] == "https://example.org/feed.xml"
          and len(demo.jb.config["hdmi"]["news_feeds"]) == 7)
    page.click("#ndefault")
    until(lambda: demo.jb.config["hdmi"]["news_feeds"] == [])
    page.wait_for_function("document.querySelectorAll('#nfeeds .nrow').length === 7")
    page.uncheck("#nidle")
    page.check("#hsound")
    until(lambda: demo.jb.config["hdmi"]["sound"] is True)
    page.wait_for_selector("#hfade:not([disabled])")
    page.check("#hfade")
    page.fill("#hfades", "3.5")
    page.press("#hfades", "Enter")
    page.locator("#hmode").focus()
    until(lambda: demo.jb.config["hdmi"]["fade"] is True and demo.jb.config["hdmi"]["fade_s"] == 3.5)
    page.locator("#hvol").fill("60")                                  # a range input takes fill()
    until(lambda: demo.jb.config["hdmi"]["volume"] == 60)
    assert page.inner_text("#hvolv") == "60 %"
    page.uncheck("#hstil")
    until(lambda: demo.jb.config["hdmi"]["osd_stil"] is False)
    page.check("#hstil")
    # the TV's remote (HDMI-CEC): off by default; here (no /dev/cec0) it says why it does not work
    assert page.is_hidden("#cecbox")
    page.check("#con")
    until(lambda: demo.jb.config["cec"]["on"] is True)
    page.wait_for_selector("#cecstate:has-text('kein CEC-Anschluss')")
    assert page.is_disabled("#ctvnow")
    page.fill("#ctvoff", "15")
    page.press("#ctvoff", "Enter")
    until(lambda: demo.jb.config["cec"]["tv_off_min"] == 15)
    page.uncheck("#con")
    until(lambda: demo.jb.config["cec"]["on"] is False and demo.jb.cec is None)
    page.check("#hautomodes input[value=bars]")
    until(lambda: demo.jb.config["hdmi"]["auto_modes"] == ["bars"])
    page.check("#hautomodes input[value=vinyl]")
    page.check("#hauto")
    until(lambda: demo.jb.config["hdmi"]["auto"] and demo.jb.config["hdmi"]["auto_modes"] == ["bars", "vinyl"])
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_hdmi.png"), full_page=True)
    # pictures from a source: the folder picker works like the "Dateien" tab
    src = next(x for x in demo.jb.config["sources"] if x["kind"] == "local")
    os.makedirs(os.path.join(src["path"], "Bilder"), exist_ok=True)
    Image.new("RGB", (800, 600), (200, 80, 40)).save(os.path.join(src["path"], "Bilder", "Sonne.jpg"))
    page.select_option("#hsrc", "*")
    page.wait_for_selector("#picdlg[open] #picsrc .src")
    page.click("#picsrc .src[data-id='%s']" % src["id"])
    page.click("#piccrumbs a[data-p='/']")
    page.click("#piclist li.dir:has-text('Bilder')")
    page.wait_for_selector("#piclist li.img:has-text('Sonne.jpg')")
    page.wait_for_function("document.querySelector('#piclist img').naturalWidth === 240")       # the preview
    assert "1 Bild" in page.inner_text("#picstatus")
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "phone_picker.png"))
    page.fill("#picfilter", "mond")
    page.wait_for_selector("#piclist li.img", state="detached")
    page.fill("#picfilter", "")
    page.click("#picok")
    until(lambda: demo.jb.config["hdmi"]["img_src"] == src["id"] and demo.jb.config["hdmi"]["img_path"] == "/Bilder")
    page.wait_for_selector("#hsrcbox:not([hidden])")
    assert not page.is_visible("#hupbox") and "Bilder" in page.inner_text("#hfolder")
    page.wait_for_selector("#hsyncmsg:has-text('1 Bild')")
    page.select_option("#hsrc", "")
    page.wait_for_selector("#hupbox:not([hidden])")
    page.click("#hlist button[data-n='Strand.jpg']")
    page.wait_for_selector("#hlist:has-text('Noch keine Bilder')")
    page.uncheck("#hon")
    until(lambda: not demo.jb.config["hdmi"]["on"])
    assert not page.errors


def test_switch_off_with_the_plug(browser, demo):
    from test_plug import ID
    page = new_page(browser, demo, PHONE)
    page.on("dialog", lambda d: d.accept())
    page.click("#tabs button[data-t=set]")
    page.wait_for_selector("#pwrstate:has-text('ohne Steckdose')")
    page.fill("#plid", ID)
    page.fill("#plkey", demo.plug.key)
    page.click("#plchk")                                          # saved, then found in the network by its id
    page.wait_for_selector("#plstate:has-text('Steckdose an (192.168.1.60, Version 3.5), 12.3 W')")
    assert page.input_value("#plip") == "192.168.1.60" and demo.jb.config["plug"]["key"] == demo.plug.key
    page.reload()
    page.wait_for_selector("#app:not([hidden])")
    page.click("#tabs button[data-t=set]")
    page.wait_for_selector("#pwrstate:has-text('30 s später')")
    page.wait_for_timeout(1000)                                   # the tab came back by itself and was loaded twice
    assert page.input_value("#plkey") == "••••"                   # the key leaves the Pi only masked
    page.fill("#ploff", "45")
    page.click("#plsave")
    until(lambda: demo.jb.config["plug"]["off_s"] == 45)
    assert demo.jb.config["plug"]["key"] == demo.plug.key
    page.click("#pwroff")
    page.wait_for_selector("#pwrstate:has-text('schaltet in 45 s ab')")
    assert demo.plug.dps["9"] == 45 and page.is_disabled("#pwroff")
    no_overflow(page)
    demo.jb.powering_off = False
    demo.jb.config.data["plug"].update(ip="", id="", key="")
    assert not page.errors


def test_update_on_request(browser, demo):
    import json
    import os
    import time
    from c64jukebox import VERSION
    demo.jb.update = {"ver": "9.9", "newer": True, "at": 0}
    page = new_page(browser, demo, PHONE)
    page.on("dialog", lambda d: d.accept())
    page.wait_for_selector("#updbar:not([hidden]):has-text('Version 9.9')")
    no_overflow(page)
    page.click("#updgo")                                          # asks, then the root unit (harmless in the demo)
    page.wait_for_selector("#updtxt:has-text('Das Update läuft')")
    assert page.is_hidden("#updgo") and page.is_hidden("#updx") and demo.jb.updating
    path = os.path.join(demo.jb.data_dir, "update.json")
    with open(path, "w") as f:                                    # update.sh is done, the service runs again
        json.dump({"state": "ok", "ver": VERSION, "from": "1.0", "msg": "", "at": int(time.time())}, f)
    demo.jb.update = None
    page.wait_for_selector("#updtxt:has-text('Version %s ist installiert')" % VERSION)
    assert not demo.jb.updating
    page.click("#updx")
    page.reload()
    page.wait_for_selector("#app:not([hidden])")
    page.wait_for_timeout(1500)
    assert page.is_hidden("#updbar")
    os.remove(path)
    demo.jb.menu.close()
    assert not page.errors


def test_power_from_every_tab(browser, demo):
    """the button at the top: TV on / off, the Ultimate, "Jukebox ausschalten" - from every tab, also on the phone"""
    page = new_page(browser, demo, PHONE)
    page.on("dialog", lambda d: d.accept())
    page.click("#tabs button[data-t=lists]")
    page.click("#topoff")
    page.wait_for_selector("#menudlg[open]")
    labels = page.eval_on_selector_all("#menubtns button", "bs => bs.map(b => b.textContent)")
    assert labels[0] == "Fernseher einschalten" and labels[1] == "Fernseher ausschalten" and labels[-1] == "Jukebox ausschalten"
    assert "einschalten" in labels[2] and "ausschalten" in labels[3]
    no_overflow(page)
    page.screenshot(path=os.path.join(HERE, "power_menu.png"))
    page.click("#menubtns button >> nth=4")
    until(lambda: demo.jb.powering_off)
    demo.jb.powering_off = False
    assert not page.errors
