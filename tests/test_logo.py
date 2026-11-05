"""A Clear Logo cut from the game's cover: the frame drawn round it in the Logo view, its even ground taken away,
saved into LaunchBox as the game's Clear Logo (never over a file) and used from then on.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
"""
import random
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lb_box3d_creator as m  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from test_engine import PLATFORM, make_lb  # noqa: E402

BAND, LETTER = (30, 60, 200), (230, 30, 30)
BOX = (20, 30, 380, 170)                 # the frame round the logo


def titled_cover(size=(400, 560)):
    """A cover: art below, and the title as red "letters" on an even blue band at the top."""
    rng = random.Random(4)
    img = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(img)
    for _ in range(600):                                          # busy art
        x, y = rng.randrange(size[0]), rng.randrange(180, size[1])
        d.rectangle((x, y, x + 12, y + 12), fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    d.rectangle((0, 0, size[0], 179), fill=BAND)
    for i in range(5):                                            # five letters
        d.rectangle((50 + i * 62, 60, 90 + i * 62, 140), fill=LETTER)
    return img


class Cutting(unittest.TestCase):
    def test_letters_without_their_ground(self):
        logo = m.cut_logo(titled_cover(), BOX)
        self.assertEqual(logo.mode, "RGBA")
        self.assertTrue(abs(logo.width - 290) <= 6 and abs(logo.height - 80) <= 6, logo.size)   # cut to the letters
        self.assertEqual(logo.getpixel((logo.width // 2 - 26, logo.height // 2))[3], 0)  # between two letters
        self.assertEqual(logo.getpixel((20, logo.height // 2))[:3], LETTER)
        self.assertEqual(logo.getpixel((20, logo.height // 2))[3], 255)

    def test_kept_as_a_rectangle(self):
        whole = m.cut_logo(titled_cover(), BOX, away=False)
        self.assertEqual((whole.size, whole.getchannel("A").getextrema()), ((360, 140), (255, 255)))
        busy = m.cut_logo(titled_cover(), (20, 200, 380, 500))       # no even ground: kept whole
        self.assertEqual((busy.size, busy.getchannel("A").getextrema()), ((360, 300), (255, 255)))
        self.assertIsNone(m.cut_logo(titled_cover(), (10, 10, 12, 12)))
        flipped = m.cut_logo(titled_cover(), (380, 170, 20, 30), away=False)  # a frame drawn the other way
        self.assertEqual(flipped.size, (360, 140))

    def test_saved_as_clear_logo(self):
        with tempfile.TemporaryDirectory() as tmp:
            lb = make_lb(tmp, [("Some Game: Two", "")], {"Box - Front": [("", "Some Game_ Two-01.png", titled_cover())]})
            game = lb.games(PLATFORM)[0]
            logo = m.cut_logo(titled_cover(), BOX)
            first = m.save_clear_logo(lb, PLATFORM, game, logo)
            second = m.save_clear_logo(lb, PLATFORM, game, logo)          # never over a file
            self.assertEqual((first.name, second.name), ("Some Game_ Two-01.png", "Some Game_ Two-02.png"))
            self.assertEqual(first.parent, lb.media_folder(PLATFORM, m.LOGO_TYPE))
            self.assertTrue(m.made_here(first))
            found = lb.find(PLATFORM, game, m.default_profile())
            self.assertEqual(Path(found["logo"]).name, "Some Game_ Two-01.png")
            pics, _ = m.load_pictures(lb, PLATFORM, game, m.default_profile(), found)
            self.assertIsNotNone(pics.logo)


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("Logo Game", "")], {"Box - Front": [("", "Logo Game-01.png", titled_cover())]})
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

    def event(self, x, y):
        """A mouse event at the cover's pixel (x, y) in the Logo view."""
        ox, oy = self.app.view_origin
        f = self.app.view_fit
        return type("Event", (), {"x": ox + x * f, "y": oy + y * f})()

    def test_pick_and_save(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 1 and app.pics is not None), "game not shown")
        self.assertIn("no Clear Logo", app.logo_state["text"])
        app.save_logo()                                              # no frame yet: a message, nothing saved
        self.assertEqual(app.status_text, m.TEXTS["logo_frame_first"])
        app.set_view("logo")
        app.draw()
        self.assertIsNotNone(app.photo)
        app.on_press(self.event(*BOX[:2]))
        app.on_motion(self.event(200, 100))
        app.on_motion(self.event(*BOX[2:]))
        app.on_release(self.event(*BOX[2:]))
        for got, want in zip(app.logo_sel, BOX):
            self.assertAlmostEqual(got, want, delta=2)
        self.assertIsNotNone(app.logo_cut)
        self.assertIsNotNone(app.logo_photo)
        self.assertEqual(app.logo_cut.getpixel((app.logo_cut.width // 2 - 26, app.logo_cut.height // 2))[3], 0)
        app.profile["logo_away"] = False                            # the whole frame instead
        app.update_logo_cut()
        self.assertEqual(app.logo_cut.getchannel("A").getextrema(), (255, 255))
        app.profile["logo_away"] = True
        app.update_logo_cut()
        app.save_logo()
        saved = self.lb.media_folder(PLATFORM, m.LOGO_TYPE) / "Logo Game-01.png"
        self.assertTrue(saved.is_file())
        self.assertIn("Clear Logo saved", app.status_text)
        self.assertTrue(self.wait(lambda: app.pics is not None and app.pics.logo is not None), "logo not used")
        self.assertIn("has a Clear Logo", app.logo_state["text"])
        self.assertIsNone(app.logo_sel)


if __name__ == "__main__":
    unittest.main()
