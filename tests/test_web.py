"""Covers from the web: libretro's thumbnails and Steam (made-up servers on 127.0.0.1), title and platform matching,
saving into a made-up LaunchBox folder, whole-platform runs and the window's "find on the web" button.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
"""
import io
import json
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lb_box3d_creator as m  # noqa: E402
from PIL import Image  # noqa: E402
from test_engine import PLATFORM, make_lb  # noqa: E402

BOXARTS = {
    "Atari - 2600": ["Combat (USA)", "Combat (Europe)", "Combat (USA) (Beta)", "Combat (Japan)", "Pitfall! (USA)",
                     "Pac-Man (USA)", "International Soccer 98 (Europe)"],
    "Nintendo - Super Nintendo Entertainment System": [
        "Legend of Zelda, The - A Link to the Past (USA)", "Legend of Zelda, The - A Link to the Past (Europe)",
        "Zelda no Densetsu - Kamigami no Triforce (Japan)"],
    "Sega - Mega Drive - Genesis": [],
}
STEAM = {"portal": [{"type": "app", "name": "Portal 2", "id": 620}, {"type": "app", "name": "Portal", "id": 400}],
         "half-life": [{"type": "app", "name": "Half-Life", "id": 70}, {"type": "dlc", "name": "Half-Life OST", "id": 9}],
         "the witcher 3: wild hunt": [{"type": "app", "name": "The Witcher 3: Wild Hunt — Remastered Soundtrack", "id": 9},
                                      {"type": "app", "name": "The Witcher® 3: Wild Hunt — Remastered", "id": 70},
                                      {"type": "app", "name": "The Witcher 3: Wild Hunt - Blood and Wine", "id": 8}],
         "doom": [{"type": "app", "name": "DOOM Eternal", "id": 9}]}
COLORS = {"(USA)": (30, 60, 200), "(Europe)": (20, 160, 60), "(Japan)": (200, 40, 40)}


def jpeg(size, color):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def png_bytes(size, color):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def index_page(names):
    """A folder page as the libretro thumbnail server (Apache) shows it."""
    rows = "".join(f'<a href="{urllib.parse.quote(n)}">{n}</a>  2024-05-01 10:00  12K\n' for n in names)
    return (f'<html><head><title>Index of /</title></head><body><h1>Index of /</h1><pre><a href="?C=N;O=D">Name</a>\n'
            f'<a href="/">Parent Directory</a>\n{rows}</pre></body></html>').encode()


class Web(BaseHTTPRequestHandler):
    """thumbnails.libretro.com, Steam's store search and Steam's picture servers (the parts this program uses)."""

    def log_message(self, *args):
        pass

    def send(self, code, body=b"", ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        srv = self.server
        path = urllib.parse.unquote(self.path.split("?")[0])
        srv.calls.append(path)
        if path == "/flaky":
            srv.flaky += 1
            return self.send(503 if srv.flaky == 1 else 200, b"ok")
        if path == "/":
            return self.send(200, index_page([s + "/" for s in BOXARTS] + ["README.md"]))
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] in BOXARTS and parts[1] == "Named_Boxarts":
            if len(parts) == 2:
                return self.send(200, index_page([n + ".png" for n in BOXARTS[parts[0]]]))
            name = parts[2][:-4]
            if name in BOXARTS[parts[0]]:
                color = next((c for tag, c in COLORS.items() if tag in name), (90, 90, 90))
                return self.send(200, png_bytes((300, 420), color), "image/png")
        if path == "/api/storesearch/":
            term = urllib.parse.parse_qs(self.path.split("?", 1)[1]).get("term", [""])[0].casefold()
            items = STEAM.get(term, [])
            return self.send(200, json.dumps({"total": len(items), "items": items}).encode(), "application/json")
        if path.startswith(("/art1/", "/art2/", "/art3/")):
            which, app = path[1:5], path.split("/")[-1].split(".")[0]
            if app == "400":            # Portal: the first address is missing, the second is landscape
                if which == "art1":
                    return self.send(404, b"not found")
                if which == "art2":
                    return self.send(200, jpeg((460, 215), (120, 120, 120)), "image/jpeg")
                return self.send(200, jpeg((300, 450), (240, 140, 20)), "image/jpeg")
            if app == "70":
                return self.send(200, jpeg((300, 450), (250, 120, 0)), "image/jpeg")
        return self.send(404, b"<html>404 Not Found</html>")


class WebCase(unittest.TestCase):
    """Points the program at a made-up web server and an empty cache folder."""

    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Web)
        self.srv.daemon_threads = True
        self.srv.calls, self.srv.flaky = [], 0
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (m.LIBRETRO_URL, m.STEAM_SEARCH, m.STEAM_ART, m.CACHE_DIR, m.WEB_GAP)
        m.LIBRETRO_URL = self.url
        m.STEAM_SEARCH = self.url + "/api/storesearch/?term={term}&l=english&cc=US"
        m.STEAM_ART = tuple(self.url + f"/art{i}/{{id}}.jpg" for i in (1, 2, 3))
        m.CACHE_DIR = Path(self.tmp.name) / "cache"
        m.WEB_GAP = 0.0
        m._cache_mem.clear()
        m._web_down.clear()

    def tearDown(self):
        m.LIBRETRO_URL, m.STEAM_SEARCH, m.STEAM_ART, m.CACHE_DIR, m.WEB_GAP = self.saved
        m._cache_mem.clear()
        m._web_down.clear()
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def calls(self, prefix):
        return [c for c in self.srv.calls if c.startswith(prefix)]


class Matching(unittest.TestCase):
    def test_title_key(self):
        self.assertEqual(m.title_key("Legend of Zelda, The - A Link to the Past (USA) [b]"),
                         "the legend of zelda a link to the past")
        self.assertEqual(m.title_key("The Legend of Zelda: A Link to the Past"), "the legend of zelda a link to the past")
        self.assertEqual(m.title_key("Pokémon Snap"), "pokemon snap")
        self.assertEqual(m.title_key("Tom & Jerry"), "tom and jerry")
        self.assertEqual(m.title_key("Don't Pull"), "dont pull")
        self.assertEqual(m.title_key("Ms. Pac-Man (1982)"), "ms pac man")
        self.assertEqual(m.title_key(""), "")

    def test_libretro_match(self):
        names = BOXARTS["Atari - 2600"]
        self.assertEqual(m.libretro_match("Combat", "Europe", names), "Combat (Europe)")
        self.assertEqual(m.libretro_match("Combat", "North America", names), "Combat (USA)")
        self.assertEqual(m.libretro_match("Combat", "Japan", names), "Combat (Japan)")
        self.assertEqual(m.libretro_match("Combat (1977)", "", names), "Combat (USA)")     # the shorter of USA/Europe
        self.assertEqual(m.libretro_match("Combat", "North America", ["Combat (USA) (Beta)", "Combat (Japan)"]),
                         "Combat (Japan)")                                # a release before a beta
        self.assertEqual(m.libretro_match("Combat", "", ["Combat (USA) (Beta)"]), "Combat (USA) (Beta)")
        self.assertEqual(m.libretro_match("PacMan", "", names), "Pac-Man (USA)")             # only spaces differ
        self.assertEqual(m.libretro_match("Pitfall!", "", names), "Pitfall! (USA)")
        self.assertEqual(m.libretro_match("International Soccer 99", "", names), "")
        self.assertEqual(m.libretro_match("Monster Mash", "", ["Monster Smash! (USA)"]), "")     # near is not enough
        self.assertEqual(m.libretro_match("Exterminator, The", "", ["Terminator, The (1993)(Domain)(PL)"]), "")
        tosec = ["Gauntlet (1985)(US Gold)(GB)(Side A)", "Gauntlet (1985)(Atari)(US)", "Gauntlet (1985)(Atari)(US)[a]",
                 "Gauntlet (1985)(Atari)(DE)(Demo)"]
        self.assertEqual(m.libretro_match("Gauntlet", "North America", tosec), "Gauntlet (1985)(Atari)(US)")
        self.assertEqual(m.libretro_match("Gauntlet", "United Kingdom", tosec), "Gauntlet (1985)(US Gold)(GB)(Side A)")
        self.assertEqual(m.libretro_match("Gauntlet", "Germany", tosec), "Gauntlet (1985)(Atari)(US)")  # not a demo
        self.assertEqual(m._region_words("Game (USA, Europe) (En,Fr,De) (Rev 1)"), {"usa", "europe", "en", "fr", "de"})
        self.assertEqual(m._region_words("Game (1985)(US Gold)(Side A)"), set())
        self.assertEqual(m.libretro_match("Something Else", "", names), "")
        self.assertEqual(m.libretro_match("", "", names), "")
        zelda = BOXARTS["Nintendo - Super Nintendo Entertainment System"]
        self.assertEqual(m.libretro_match("The Legend of Zelda: A Link to the Past", "Europe", zelda),
                         "Legend of Zelda, The - A Link to the Past (Europe)")

    def test_libretro_system(self):
        self.assertEqual(m.libretro_system("Atari 2600"), "Atari - 2600")
        self.assertEqual(m.libretro_system("Atari 2600 [Homebrew]"), "Atari - 2600")
        self.assertEqual(m.libretro_system("Sony Playstation"), "Sony - PlayStation")
        self.assertEqual(m.libretro_system("My Consoles", "Sega Genesis"), "Sega - Mega Drive - Genesis")
        self.assertEqual(m.libretro_system("Sinclair ZX81 [Cass]", ""), "Sinclair - ZX 81")
        self.assertEqual(m.libretro_system("Mine", "Sinclair ZX81 [Cass]"), "Sinclair - ZX 81")   # tags of ScrapeAs too
        three = ["Atari - 2600", "Atari - 5200", "Atari - 7800"]
        self.assertEqual(m.libretro_system("2600 & VCS - Games", "", three), "Atari - 2600")
        self.assertEqual(m.libretro_system("Atari 2600/VCS", "", three), "Atari - 2600")
        self.assertEqual(m.libretro_system("Atari 7800 ProSystem"), "Atari - 7800")          # by its words
        self.assertEqual(m.libretro_system("ZX Spectrum - Games -"), "Sinclair - ZX Spectrum")
        self.assertEqual(m.libretro_system("NEC PC Engine CD"), "NEC - PC Engine CD - TurboGrafx-CD")
        self.assertEqual(m.libretro_system("WonderSwan Color"), "Bandai - WonderSwan Color")
        for name in ("Nintendo Game & Watch", "Nintendo", "Atari", "Your 64", "Zzap! 64", "BALDWIN'S OF ST. JAMES'S",
                     "Doom Patrol", "Power on - The Story of Xbox", "Atari VCS 2600"):
            self.assertEqual(m.libretro_system(name), "", name)                   # the model must lead the name
        for name in ("Nintendo - 64 - Manuals - Games", "Mega Drive & Genesis - Video", "Sega Saturn [Magazines]",
                     "Magnavox - Odyssey2 - Catalogs", "Atari ST Books"):
            self.assertEqual(m.libretro_system(name), "", name)                   # manuals, magazines, videos…
            self.assertTrue(m.not_games(name), name)
        self.assertEqual(m.libretro_system("Mine", "Sony Playstation - Manuals"), "")
        self.assertFalse(m.not_games("Atari 2600 [Applications]"))
        self.assertEqual(m.libretro_system(PLATFORM), "")
        self.assertEqual(m.libretro_system("Windows"), "")

    def test_pc_platforms(self):
        for name in ("Windows", "Microsoft Windows", "MS-DOS", "PC Games [Steam]", "PC"):
            self.assertTrue(m.is_pc_platform(name), name)
        self.assertTrue(m.is_pc_platform("My PC games", "Windows"))
        for name in ("Atari ST", "Pocket PC", "Sony Playstation"):
            self.assertFalse(m.is_pc_platform(name), name)


class Downloads(WebCase):
    def test_retry_and_not_found(self):
        self.assertEqual(m.web_get(self.url + "/flaky"), b"ok")            # 503 first, then the answer
        self.assertEqual(len(self.calls("/flaky")), 2)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            m.web_get(self.url + "/missing")
        ctx.exception.close()
        self.assertEqual(len(self.calls("/missing")), 1)                   # "not found" is not tried again

    def test_server_not_answering_is_left_alone(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with self.assertRaises(OSError):
            m.web_get(f"http://127.0.0.1:{port}/x", timeout=5, tries=1)
        start = time.time()
        with self.assertRaises(OSError) as ctx:
            m.web_get(f"http://127.0.0.1:{port}/y", timeout=5)
        self.assertLess(time.time() - start, 0.5)
        self.assertIn("did not answer", str(ctx.exception))
        self.assertEqual(m.web_get(self.url + "/flaky"), b"ok")            # other servers are still asked

    def test_lists_are_kept(self):
        systems = m.libretro_systems()
        self.assertEqual(systems, list(BOXARTS))                             # folders only, not README.md
        m.libretro_systems()
        self.assertEqual(len(self.calls("/")), 1, self.srv.calls)            # from memory
        m._cache_mem.clear()
        self.assertEqual(m.libretro_systems(), systems)
        self.assertEqual(len([c for c in self.srv.calls if c == "/"]), 1)  # from the cache folder
        kept = json.loads((m.CACHE_DIR / "libretro-systems.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["items"], systems)
        kept["time"] -= 15 * 86400                                           # two weeks old: asked again
        (m.CACHE_DIR / "libretro-systems.json").write_text(json.dumps(kept), encoding="utf-8")
        m._cache_mem.clear()
        m.libretro_systems()
        self.assertEqual(len([c for c in self.srv.calls if c == "/"]), 2)
        m.libretro_systems(refresh=True)
        self.assertEqual(len([c for c in self.srv.calls if c == "/"]), 3)
        self.assertEqual(m.libretro_names("Atari - 2600"), BOXARTS["Atari - 2600"])
        self.assertEqual(m.libretro_names("No Such System"), [])            # 404: kept as "none"
        m.libretro_names("No Such System")
        self.assertEqual(len(self.calls("/No Such System")), 1)
        self.assertFalse(list(m.CACHE_DIR.glob("*.tmp")))


class FindingCovers(WebCase):
    def game(self, title, region=""):
        return m.Game(ET.fromstring(f"<Game><Title>{escape(title)}</Title><Region>{region}</Region></Game>"), "x")

    def test_libretro(self):
        hit = m.find_cover_online("Atari 2600", "", self.game("Combat", "Europe"))
        data, ext, where = hit
        self.assertEqual((ext, where), (".png", "libretro: Atari - 2600 / Combat (Europe)"))
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.convert("RGB").getpixel((5, 5)), COLORS["(Europe)"])
        self.assertIsNone(m.find_cover_online("Atari 2600", "", self.game("Unknown Game")))
        self.assertEqual(self.calls("/api/"), [])                            # no Steam for a console
        self.assertIsNone(m.find_cover_online("Atari 2600", "", self.game("Combat"), "off"))
        hit = m.find_cover_online(PLATFORM, "", self.game("Combat", "Japan"), "auto", "Atari - 2600")
        self.assertEqual(hit[2], "libretro: Atari - 2600 / Combat (Japan)")   # the system chosen by hand
        hit = m.find_cover_online("Atari 2600 [Games][Europe]", "", self.game("Combat"))
        self.assertEqual(hit[2], "libretro: Atari - 2600 / Combat (Europe)")  # no region: the platform's
        self.assertEqual(m.platform_region("Sony Playstation EU"), "Europe")
        self.assertEqual(m.platform_region("Nintendo Famicom [Games][Japan]"), "Japan")
        self.assertEqual(m.platform_region("Atari ST User"), "")
        self.assertIsNone(m.find_cover_online("Sega Genesis", "", self.game("Sonic")))   # no box art there

    def test_steam(self):
        data, ext, where = m.find_cover_online("Windows", "", self.game("Portal"))
        self.assertEqual((ext, where), (".jpg", "Steam: Portal (400)"))     # Portal, not Portal 2
        with Image.open(io.BytesIO(data)) as im:
            self.assertGreater(im.height, im.width)                          # the landscape picture was skipped
        self.assertEqual(self.calls("/art1/400"), ["/art1/400.jpg"])
        hit = m.find_cover_online("Atari 2600", "", self.game("Half-Life"), "steam")
        self.assertEqual(hit[2], "Steam: Half-Life (70)")
        self.assertIsNone(m.find_cover_online("Windows", "", self.game("Portal"), "libretro"))
        self.assertIsNone(m.find_cover_online("Windows", "", self.game("Nothing On Steam")))
        hit = m.find_cover_online("Windows", "", self.game("The Witcher 3: Wild Hunt"))
        self.assertEqual(hit[2], "Steam: The Witcher® 3: Wild Hunt — Remastered (70)")   # an edition, not the music
        self.assertIsNone(m.find_cover_online("Windows", "", self.game("Doom")))          # never another game
        self.assertIsNone(m.find_cover_online("Windows - Manuals", "", self.game("Portal")))   # not a game platform
        self.assertEqual(m.web_source("Windows", ""), "Steam")
        self.assertEqual(m.web_source("MS-DOS", ""), "libretro: DOS, Steam")
        self.assertEqual(m.web_source("Atari 2600", "", "steam"), "Steam")
        self.assertEqual(m.web_source("Atari 2600", "", "off"), "")
        self.assertEqual(m.web_source(PLATFORM, ""), "")
        self.assertEqual(m.web_source(PLATFORM, "", "auto", "Atari - 2600"), "libretro: Atari - 2600")


class SavingCovers(WebCase):
    def setUp(self):
        super().setUp()
        self.lb = make_lb(self.tmp.name, [("Combat", "Europe"), ("Unknown Thing", ""), ("Pac-Man", "")], {})
        self.games = self.lb.games(PLATFORM)
        self.prof = dict(m.default_profile(), web_system="Atari - 2600")

    def test_saved_as_box_front(self):
        combat = self.games[0]
        found = self.lb.find(PLATFORM, combat, self.prof)
        self.assertNotIn("front", found)
        path, where = m.fetch_missing_cover(self.lb, PLATFORM, combat, self.prof, found)
        folder = self.lb.media_folder(PLATFORM, "Box - Front")
        self.assertEqual(path, folder / "Combat-01.png")                    # main folder, LaunchBox's naming
        self.assertEqual(where, "libretro: Atari - 2600 / Combat (Europe)")
        self.assertEqual((found["front"], found["front_type"], found["region"]), (str(path), "Box - Front", ""))
        self.assertEqual(self.lb.find(PLATFORM, combat, self.prof)["front"], str(path))
        calls = len(self.srv.calls)
        self.assertEqual(m.fetch_missing_cover(self.lb, PLATFORM, combat, self.prof, found), (None, ""))
        self.assertEqual(len(self.srv.calls), calls)                         # it has a front now: nothing asked
        again = m.save_web_cover(self.lb, PLATFORM, combat, png_bytes((50, 70), (1, 2, 3)), ".png")
        self.assertEqual(again.name, "Combat-02.png")                       # never over a file
        with self.assertRaises(OSError):
            m.save_web_cover(self.lb, PLATFORM, combat, b"<html>Service Unavailable</html>", ".png")
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["Combat-01.png", "Combat-02.png"])
        self.assertEqual(m.fetch_missing_cover(self.lb, PLATFORM, self.games[1], self.prof, {}), (None, "not found"))
        off = dict(self.prof, web_covers="off")
        self.assertEqual(m.fetch_missing_cover(self.lb, PLATFORM, self.games[2], off, {}), (None, ""))

    def export(self, **more):
        return dict({"region": "same", "existing": "skip", "format": "png", "jpg_bg": "#ffffff", "max_height": 400,
                     "trim": True, "threads": 2}, **more)

    def test_whole_platform(self):
        prof = dict(self.prof, generic_cover=False)
        counts = m.batch_make(self.lb, PLATFORM, self.games, prof, None, None, self.export(), threading.Event(),
                              self.lb.root / "Backups", 400)
        self.assertEqual((counts["covers"], counts["saved"], counts["nofront"], counts["generic"], counts["errors"]),
                         (2, 2, 1, 0, 0))
        fronts = self.lb.media_folder(PLATFORM, "Box - Front")
        boxes = self.lb.media_folder(PLATFORM, m.OUT_TYPE)
        self.assertEqual(sorted(p.name for p in fronts.iterdir()), ["Combat-01.png", "Pac-Man-01.png"])
        self.assertEqual(sorted(p.name for p in boxes.iterdir()), ["Combat-01.png", "Pac-Man-01.png"])
        again = m.batch_make(self.lb, PLATFORM, self.games, self.prof, None, None, self.export(), threading.Event(),
                             self.lb.root / "Backups", 400)
        self.assertEqual((again["covers"], again["generic"], again["saved"], again["skipped"]), (0, 1, 1, 2))
        self.assertTrue((boxes / "Unknown Thing-01.png").is_file())
        self.assertFalse((fronts / "Unknown Thing-01.png").exists())        # generic covers are not saved as fronts

    def test_web_out_of_reach(self):
        old = m.libretro_names

        def offline(*args, **kwargs):
            raise urllib.error.URLError("no internet")

        m.libretro_names = offline
        infos = []
        try:
            counts = m.batch_make(self.lb, PLATFORM, self.games, self.prof, None, None, self.export(threads=1),
                                  threading.Event(), self.lb.root / "Backups", 400,
                                  lambda *a: infos.append(a[-1]))
        finally:
            m.libretro_names = old
        self.assertEqual((counts["generic"], counts["saved"], counts["errors"]), (3, 3, 0))
        self.assertTrue(all(m.TEXTS["web_failed"] in info for info in infos), infos)

    def test_plan(self):
        found = [{"front": "a.png"}, {}, {"front": "b.png", "box3d": ["b3d.png"]}]
        self.assertEqual(m.batch_plan(found, "skip", True, False, (m.OUT_TYPE,), web=True), (2, 1, 0, 1))
        self.assertEqual(m.batch_plan(found, "skip", True, False, (m.OUT_TYPE,), web=False), (1, 1, 1, 0))


class Window(WebCase):
    def setUp(self):
        super().setUp()
        self.lb = make_lb(self.tmp.name, [("Combat", "Europe"), ("Unknown Thing", "")], {})
        self.old_config = m.CONFIG_PATH
        m.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root), "yes": True})

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        m.CONFIG_PATH = self.old_config
        m.UPSCALER = m.Upscaler()
        super().tearDown()

    def wait(self, cond, seconds=20.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_find_button(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 2 and len(app.found) == 2), "games not loaded")
        self.assertTrue(self.wait(lambda: app.pics is not None and app.current is app.games[0]), "game not shown")
        self.assertIn("none fits", app.web_auto_label["text"])
        app.profile["web_system"] = "Atari - 2600"
        app.find_web_cover()
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Cover found")), app.status_text)
        self.assertTrue(app.current_found.get("front"))
        self.assertTrue(app.found[0].get("front"))
        self.assertTrue((self.lb.media_folder(PLATFORM, "Box - Front") / "Combat-01.png").is_file())
        self.assertTrue(self.wait(lambda: app.pics is not None and app.pics.front is not None), "cover not shown")
        app.find_web_cover()                                                # it has one now
        self.assertEqual(app.status_text, m.TEXTS["web_has_front"])
        app.tree.selection_set("1")
        app.on_game_select()
        self.assertTrue(self.wait(lambda: app.pics is not None and app.current is app.games[1]), "game not shown")
        app.find_web_cover()
        self.assertTrue(self.wait(lambda: app.status_text.startswith("No cover")), app.status_text)
        app.load_libretro_systems()
        self.assertTrue(self.wait(lambda: "Atari - 2600" in app.web_system_combo["values"]), "systems not listed")


if __name__ == "__main__":
    unittest.main()
