"""Cartridges: a game's Cart - 3D made from its Cart - Front (a photo of the whole cartridge) - the thickness from the
platform, the photo cut out of its background, the front turned in perspective with a side wall along its outline,
saving into LaunchBox and the window's Cart view, column and filters.

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
from PIL import Image, ImageDraw  # noqa: E402
from test_engine import PLATFORM, cover, make_lb  # noqa: E402

PLASTIC, LABEL = (128, 128, 132), (210, 40, 40)


def cartridge(size=(400, 440), ground=None):
    """A grey cartridge with a red label and a notch at the bottom, on a transparent ground (or on `ground`)."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0) if ground is None else ground + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, w - 21, h - 61), fill=PLASTIC + (255,))
    d.rectangle((60, h - 62, w - 61, h - 21), fill=PLASTIC + (255,))      # the narrower bottom
    d.rectangle((90, 50, w - 91, h - 140), fill=LABEL + (255,))
    return img


def near(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


def count(img, test, box=None):
    data = (img.crop(box) if box else img).convert("RGBA").tobytes()
    return sum(1 for i in range(0, len(data), 4) if data[i + 3] > 200 and test(data[i:i + 4]))


def grey_side(px):
    """The side wall: the plastic's grey, darker."""
    return px[0] < 110 and abs(px[0] - px[1]) < 12 and abs(px[1] - px[2]) < 14


class Shapes(unittest.TestCase):
    def test_thickness_from_the_platform(self):
        for platform, depth in (("Nintendo Entertainment System [Games][USA]", 0.175), ("NES", 0.175),
                                ("Super Nintendo Entertainment System", 0.15), ("Sega Genesis", 0.18),
                                ("Sega Mega Drive [Translations]", 0.18), ("Nintendo 64 [Games][USA]", 0.155),
                                ("Nintendo Game Boy [Games][Japan]", 0.135), ("Nintendo Game Boy Color", 0.135),
                                ("Nintendo Game Boy Advance [Games][USA]", 0.14), ("Atari 2600_VCS [Games]", 0.25),
                                ("Nintendo DS [Games][Europe]", 0.11), ("NEC PC Engine", 0.04),
                                ("Something Else", m.CART_DEPTH), ("", m.CART_DEPTH)):
            self.assertEqual(m.cart_depth({}, platform), depth, platform)
        self.assertEqual(m.cart_depth({"cart_depth_auto": False, "cart_depth": 0.3}, "NES"), 0.3)

    def test_cut_out(self):
        clear = m.cart_cutout(cartridge())                                   # its own transparency: cropped to it
        self.assertEqual(clear.size, (360, 400))
        on_white = m.cart_cutout(cartridge(ground=(250, 250, 250)))          # an even background, taken away
        self.assertTrue(abs(on_white.width - 360) <= 3 and abs(on_white.height - 400) <= 3, on_white.size)
        self.assertLess(count(on_white, lambda px: min(px[:3]) > 240), 20)    # no light halo round it
        self.assertLess(on_white.getpixel((5, on_white.height - 5))[3], 30)  # beside the narrow bottom
        self.assertEqual(on_white.getpixel((180, 100))[3], 255)
        kept = m.cart_cutout(cartridge(ground=(250, 250, 250)), "keep")      # asked to keep the whole picture
        self.assertEqual(kept.size, (400, 440))
        same = cartridge(ground=PLASTIC)                                     # grey on grey: cannot be told apart
        self.assertEqual(m.cart_cutout(same).size, (400, 440))
        noisy = Image.effect_noise((300, 300), 60).convert("RGB")            # no even background at all
        self.assertEqual(m.cart_cutout(noisy).size, (300, 300))

    def test_in_perspective(self):
        prof = m.default_profile()
        img = m.make_cart(cartridge(), prof, "NES", 500)
        self.assertEqual((img.height, img.mode), (500, "RGBA"))
        for corner in ((0, 0), (img.width - 1, 0), (0, img.height - 1), (img.width - 1, img.height - 1)):
            self.assertEqual(img.getpixel(corner)[3], 0)
        red = lambda px: px[0] > 150 and px[1] < 90 and px[2] < 90  # noqa: E731
        self.assertGreater(count(img, red), 5000)                                # the label
        half = img.width // 2
        left = count(img, grey_side, (0, 0, half, img.height))
        self.assertGreater(left, 1500)                                            # the side wall, on the left
        self.assertLess(count(img, grey_side, (half, 0, img.width, img.height)), left // 4)
        right = m.make_cart(cartridge(), dict(prof, cart_side="right"), "NES", 500)
        self.assertGreater(count(right, grey_side, (right.width // 2, 0, right.width, right.height)), 1500)
        flat = m.make_cart(cartridge(), dict(prof, cart_depth_auto=False, cart_depth=0.0, cart_turn=0.0,
                                             cart_tilt=0.0), "NES", 500)
        self.assertLess(count(flat, grey_side), 200)                              # no thickness, no wall
        thick = m.make_cart(cartridge(), prof, "Atari 2600", 500)
        self.assertGreater(count(thick, grey_side), left)                         # a thicker cartridge
        fast = m.make_cart(cartridge(), prof, "NES", 300, fast=True)
        self.assertEqual(fast.height, 300)

    def test_render(self):
        prof = m.default_profile()
        self.assertIsNone(m.render_cart(prof, m.Pictures(front=cover((20, 80, 200))), "NES"))
        pics = m.Pictures()
        pics.cart_front = cartridge()
        self.assertEqual(m.render_cart(prof, pics, "NES", 400).height, 400)


class Saving(unittest.TestCase):
    def test_found_and_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            lb = make_lb(tmp, [("With Cart", "Europe"), ("Made Before", ""), ("No Cart", "")], {
                "Box - Front": [("Europe", "With Cart-01.png", cover((20, 80, 200)))],
                "Cart - Front": [("Europe", "With Cart-01.png", cartridge()), ("", "Made Before-01.png", cartridge())],
                "Cart - 3D": [("", "Made Before-01.png", cartridge())]})
            games = lb.games(PLATFORM)
            prof = m.default_profile()
            found = [lb.find(PLATFORM, g, prof) for g in games]
            self.assertTrue(found[0]["cart_front"].endswith("With Cart-01.png"))
            self.assertEqual((len(found[1]["cart3d"]), found[2].get("cart_front")), (1, None))
            self.assertEqual(m.batch_plan(found, "skip", True, False, (m.CART_TYPE,)), (1, 1, 1, 0))
            self.assertEqual(m.batch_plan(found, "replace", True, False, (m.CART_TYPE,)), (2, 0, 1, 0))
            self.assertEqual(m.batch_plan(found, "skip", True, True, (m.OUT_TYPE, m.CART_TYPE)), (3, 0, 0, 2))
            export = {"region": "same", "existing": "skip", "format": "png", "jpg_bg": "#ffffff", "max_height": 400,
                      "trim": True, "threads": 2, "make_box": False, "make_disc": False, "make_cart": True}
            prof["generic_cover"] = False
            prof["web_covers"] = "off"
            counts = m.batch_make(lb, PLATFORM, games, prof, None, None, export, threading.Event(),
                                  lb.root / "Backups", 400)
            self.assertEqual((counts["carts"], counts["skipped"], counts["nocart"], counts["nofront"],
                              counts["errors"]), (1, 1, 1, 0, 0))                # no Box - Front needed for carts
            made = lb.media_folder(PLATFORM, m.CART_TYPE) / "Europe" / "With Cart-01.png"
            with Image.open(made) as im:                                  # transparent margins cut, as for boxes
                self.assertTrue(im.mode == "RGBA" and 380 <= im.height <= 400, (im.mode, im.size))
                self.assertEqual(im.getpixel((0, 0))[3], 0)
            self.assertFalse(lb.media_folder(PLATFORM, m.OUT_TYPE).exists())
            both = dict(export, make_box=True, existing="next")
            counts = m.batch_make(lb, PLATFORM, games[2:], prof, None, None, both, threading.Event(),
                                  lb.root / "Backups", 400)
            self.assertEqual((counts["saved"], counts["carts"], counts["nofront"], counts["nocart"]), (0, 0, 1, 1))


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("Cart Game", ""), ("Bare Game", "")], {
            "Box - Front": [("", "Cart Game-01.png", cover((20, 80, 200)))],
            "Cart - Front": [("", "Cart Game-01.png", cartridge())]})
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

    def test_cart_view_and_saving(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 2 and app.pics is not None), "games not loaded")
        cart, bare = (next(i for i, g in enumerate(app.games) if g.title == t) for t in ("Cart Game", "Bare Game"))
        self.assertTrue(app.cart_platform)
        self.assertEqual(app.tree.heading("media")["text"], "Cart")
        self.assertIn("with Cart - Front 1", app.plat_info["text"])
        app.show_game(cart)
        self.assertTrue(self.wait(lambda: app.pics is not None and app.pics.cart_front is not None), "no cartridge")
        app.set_view("cart")
        app.draw()
        self.assertIsNotNone(app.photo)
        self.assertIn("Cart - Front: yes", app.info_label["text"])
        app.cfg["export"].update(make_box=False, make_cart=True)
        app.save_one(False)
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Saved")), app.status_text)
        self.assertTrue((self.lb.media_folder(PLATFORM, m.CART_TYPE) / "Cart Game-01.png").is_file())
        self.assertTrue(self.wait(lambda: app.found[cart].get("cart3d")), "cartridge not noted")
        self.assertEqual((app.tree.set(str(cart), "media"), app.tree.set(str(bare), "media")), ("1", "–"))
        for mode, rows in (("hascart", (str(cart),)), ("nocart", (str(bare),))):
            app.filter_var.set(m.TEXTS["filter_" + mode])
            app.on_filter_mode()
            self.assertEqual(app.tree.get_children(), rows, mode)
        app.filter_var.set(m.TEXTS["filter_all"])
        app.on_filter_mode()
        app.make_boxes("all")                                        # the bare game has no Cart - Front
        self.assertFalse(app.batch_running)
        self.assertIn("nothing to make", app.status_text)
        app.open_gallery()
        app.gallery.kind_var.set("cart3d")
        app.gallery.on_kind()
        self.assertEqual([i for i, _p, _n in app.gallery.items], [cart])
        app.gallery.close()
        app.show_game(bare)
        self.assertTrue(self.wait(lambda: app.current is not None and app.current.title == "Bare Game"
                                  and app.pics is not None))
        app.draw()                                                   # "no Cart - Front" instead of a picture
        self.assertIn("Cart - Front: none", app.info_label["text"])


if __name__ == "__main__":
    unittest.main()
