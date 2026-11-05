"""Back covers: a Box - Back made for a game without one from its LaunchBox data (description, publisher, year…),
its Clear Logo and its screenshots; scans are never replaced; saving, the plan, and the window's Back view.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
"""
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lb_box3d_creator as m  # noqa: E402
from PIL import Image  # noqa: E402
from test_engine import PLATFORM, cover, make_lb  # noqa: E402

NOTES = ("Okay, let's go! " * 6 + "\n\n" + "A long second paragraph about the game and its many levels. " * 5).strip()
CTX = {"title": "Toad Brothers", "publisher": "Tradewest", "developer": "Rare", "year": "1991",
       "genre": "Beat 'em Up; Platform", "players": "2", "rating": "E - Everyone", "notes": NOTES,
       "lb_platform": "Nintendo Entertainment System"}
GREEN, MAGENTA, ORANGE = (30, 200, 60), (230, 20, 230), (250, 140, 0)


def pictures(front=None, shots=(), logo=None, ctx=None):
    pics = m.Pictures(front, None, None, logo, dict(CTX, **(ctx or {})))
    pics.shots = list(shots)
    return pics


def count(img, test, box=None):
    data = (img.crop(box) if box else img).convert("RGBA").tobytes()
    return sum(1 for i in range(0, len(data), 4) if data[i + 3] > 200 and test(data[i:i + 4]))


def is_(colour, tol=40):
    return lambda px: all(abs(a - b) <= tol for a, b in zip(px[:3], colour))


class Layout(unittest.TestCase):
    def test_portrait_back(self):
        logo = Image.new("RGBA", (400, 120), MAGENTA + (255,))
        shots = [Image.new("RGB", (320, 240), GREEN), Image.new("RGB", (320, 240), ORANGE)]
        img = m.render_back(m.default_profile(), pictures(cover((20, 80, 200), (300, 420)), shots, logo), 1000)
        self.assertEqual(img.size, (714, 1000))                          # shaped like the game's front
        self.assertEqual(img.getpixel((5, 5))[3], 255)                   # a full picture, no transparency
        self.assertGreater(count(img, is_(MAGENTA), (0, 0, 714, 150)), 3000)          # the Clear Logo on top
        for colour in (GREEN, ORANGE):
            self.assertGreater(count(img, is_(colour), (0, 150, 714, 450)), 3000)     # two screenshots in a row
        dark_text = lambda px: max(px[:3]) < 90  # noqa: E731
        self.assertGreater(count(img, dark_text, (40, 450, 674, 850)), 2000)          # the description
        self.assertGreater(count(img, dark_text, (250, 880, 714, 1000)), 300)         # the details line

    def test_choices_and_shapes(self):
        prof = dict(m.default_profile(), back_notes=False, back_details=False, back_platform=False, back_shots=0,
                    back_logo=False)
        plain = m.render_back(prof, pictures(), 700)
        self.assertEqual(plain.size, (round(700 * 995 / m.GC_HEIGHT), 700))           # no front: a generic shape
        dark_text = lambda px: max(px[:3]) < 90  # noqa: E731
        self.assertLess(count(plain, dark_text, (0, 200, plain.width, 700)), 50)      # only the title, at the top
        wide = m.render_back(m.default_profile(), pictures(Image.new("RGB", (600, 420), (9, 9, 9)),
                                                           [Image.new("RGB", (320, 240), GREEN)]), 700)
        self.assertGreater(wide.width, wide.height)
        half = wide.width // 2
        self.assertGreater(count(wide, is_(GREEN), (0, 0, half, 700)), 3000)          # screenshots on the left
        self.assertEqual(count(wide, is_(GREEN), (half, 0, wide.width, 700)), 0)
        self.assertGreater(count(wide, dark_text, (half, 100, wide.width, 560)), 1500)  # the text on the right
        dark = m.render_back(dict(m.default_profile(), gc_style="dark"), pictures(), 700)
        self.assertLess(sum(dark.getpixel((10, 350))[:3]), 3 * 90)

    def test_text_fits(self):
        font = m.load_font("Arial", 20)
        self.assertEqual(m._wrap("one two\n\nthree", font, 1000), ["one two", "", "three"])
        self.assertEqual(m._wrap("a\nb", font, 1000, single=True), ["a", "b"])
        long = m._wrap("word " * 200, font, 200)
        self.assertGreater(len(long), 10)
        self.assertTrue(all(font.getlength(line) <= 200 for line in long))
        block = m.text_block("word " * 400, (300, 100), (0, 0, 0), largest=40, smallest=20)
        self.assertEqual(block.size, (300, 100))                         # cut short, never larger than its box


class Saving(unittest.TestCase):
    def test_marks_and_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            lb = make_lb(tmp, [("Scanned", ""), ("Made", ""), ("Bare", "")], {
                "Box - Front": [("", "Scanned-01.png", cover((200, 30, 30))), ("", "Bare-01.png", cover((20, 60, 220)))],
                "Box - Back": [("", "Scanned-01.png", cover((90, 90, 90)))]})
            backs = lb.media_folder(PLATFORM, m.BACK_TYPE)
            made = backs / "Made-01.png"
            m.save_picture(Image.new("RGB", (100, 140), (1, 2, 3)), made, None, None, lb.root, "png")
            jpg = Path(tmp) / "marked.jpg"
            m.save_picture(Image.new("RGB", (100, 140), (1, 2, 3)), jpg, None, None, lb.root, "jpg")
            self.assertTrue(m.made_here(made) and m.made_here(jpg))
            self.assertFalse(m.made_here(backs / "Scanned-01.png"))          # a scan
            self.assertFalse(m.made_here(Path(tmp) / "missing.png"))
            lb.index(PLATFORM, m.BACK_TYPE, refresh=True)
            games = {g.title: g for g in lb.games(PLATFORM)}
            prof = m.default_profile()
            found = {t: lb.find(PLATFORM, g, prof) for t, g in games.items()}
            for policy in ("skip", "replace", "next"):                         # a scan is never touched
                self.assertIsNone(m.output_target(lb, PLATFORM, games["Scanned"], found["Scanned"],
                                                  {"existing": policy}, m.BACK_TYPE), policy)
            self.assertIsNone(m.output_target(lb, PLATFORM, games["Made"], found["Made"], {"existing": "skip"},
                                              m.BACK_TYPE))
            again = m.output_target(lb, PLATFORM, games["Made"], found["Made"], {"existing": "replace"}, m.BACK_TYPE)
            self.assertEqual(again[0].name, "Made-01.png")                   # its own back: made again on Replace
            self.assertEqual(m.batch_plan(list(found.values()), "skip", True, False, (m.BACK_TYPE,)), (1, 2, 0, 0))
            export = {"region": "same", "existing": "replace", "format": "png", "jpg_bg": "#ffffff",
                      "max_height": 400, "trim": True, "threads": 2, "make_box": False, "make_back": True}
            counts = m.batch_make(lb, PLATFORM, list(games.values()), prof, None, None, export, threading.Event(),
                                  lb.root / "Backups", 400)
            self.assertEqual((counts["backs"], counts["skipped"], counts["errors"]), (2, 1, 0))
            with Image.open(backs / "Bare-01.png") as im:
                self.assertEqual(im.size, (round(m.BACK_HEIGHT * 480 / 680), m.BACK_HEIGHT))
                self.assertTrue(m.made_here(backs / "Bare-01.png"))
            with Image.open(backs / "Scanned-01.png") as im:
                self.assertEqual(im.getpixel((5, 5))[:3], (90, 90, 90))     # the scan untouched

    def test_game_data_and_screenshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            lb = make_lb(tmp, [("Shots", "")], {
                "Screenshot - Gameplay": [("", "Shots-01.png", Image.new("RGB", (64, 48), GREEN)),
                                          ("", "Shots-02.png", Image.new("RGB", (64, 48), GREEN)),     # the same
                                          ("", "Shots-03.png", Image.new("RGB", (64, 48), ORANGE))]})
            xml = lb.root / "Data" / "Platforms" / f"{PLATFORM}.xml"
            xml.write_text(xml.read_text(encoding="utf-8").replace(
                "<Region></Region>", "<Region></Region><Notes>A game.\r\n\r\nSecond part.</Notes><MaxPlayers>2"
                "</MaxPlayers><Rating>E - Everyone</Rating>"), encoding="utf-8")
            lb = m.LaunchBox(lb.root)
            lb.load()
            game = lb.games(PLATFORM)[0]
            self.assertEqual((game.notes.split(), game.players, game.rating),
                             (["A", "game.", "Second", "part."], "2", "E - Everyone"))
            self.assertIn("\n\n", game.notes)                                 # its paragraphs kept
            self.assertEqual(game.context()["players"], "2")
            pics, _ = m.load_pictures(lb, PLATFORM, game, m.default_profile(), back=True)
            self.assertEqual(len(pics.shots), 2)                              # the same picture twice counts once
            pics, _ = m.load_pictures(lb, PLATFORM, game, dict(m.default_profile(), back_shots=1), back=True)
            self.assertEqual(len(pics.shots), 1)


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("Front Game", ""), ("Scanned Game", "")], {
            "Box - Front": [("", "Front Game-01.png", cover((20, 80, 200)))],
            "Box - Back": [("", "Scanned Game-01.png", cover((90, 90, 90)))]})
        self.old = (m.CONFIG_PATH, m.CACHE_DIR)
        m.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        m.CACHE_DIR = Path(self.tmp.name) / "cache"
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root), "yes": True})

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        m.CONFIG_PATH, m.CACHE_DIR = self.old
        self.tmp.cleanup()

    def wait(self, cond, seconds=20.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_back_view_and_saving(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 2 and app.pics is not None), "games not loaded")
        front, scanned = (next(i for i, g in enumerate(app.games) if g.title == t) for t in ("Front Game",
                                                                                           "Scanned Game"))
        app.show_game(front)
        self.assertTrue(self.wait(lambda: app.current_index == front and app.pics is not None))
        app.set_view("back")
        app.draw()
        self.assertIsNotNone(app.photo)
        self.assertIn("Box - Back: none yet", app.info_label["text"])
        app.cfg["export"].update(make_box=False, make_back=True)
        app.save_one(False)
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Saved")), app.status_text)
        self.assertTrue((self.lb.media_folder(PLATFORM, m.BACK_TYPE) / "Front Game-01.png").is_file())
        self.assertTrue(self.wait(lambda: app.found[front].get("back")), "back not noted")
        app.update_info()
        self.assertIn("Box - Back: made by this program", app.info_label["text"])
        for mode, rows in (("noback", ()), ("hasback", (str(front), str(scanned)))):
            app.filter_var.set(m.TEXTS["filter_" + mode])
            app.on_filter_mode()
            self.assertEqual(tuple(sorted(app.tree.get_children())), tuple(sorted(rows)), mode)
        app.filter_var.set(m.TEXTS["filter_all"])
        app.on_filter_mode()
        app.show_game(scanned)
        self.assertTrue(self.wait(lambda: app.current_index == scanned and app.pics is not None))
        self.assertIn("Box - Back: yes (a scan", app.info_label["text"])
        app.make_boxes("all")                                         # both have one now: nothing to make
        self.assertFalse(app.batch_running)
        app.open_gallery()
        app.gallery.kind_var.set("back")
        app.gallery.on_kind()
        self.assertEqual(sorted(i for i, _p, _n in app.gallery.items), sorted([front, scanned]))
        app.gallery.close()


if __name__ == "__main__":
    unittest.main()
