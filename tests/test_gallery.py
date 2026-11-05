"""A scanner's edges cut off covers (thin white or black strips go, bands of the cover's design stay) and the gallery
of the games' Box - 3D / Disc pictures.

Run: python -m unittest discover -s tests   (the window tests need a desktop)
"""
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

ART = (40, 90, 160)


def art(size=(400, 560)):
    """A cover with something on it everywhere (no even edge of its own)."""
    img = Image.new("RGB", size, ART)
    d = ImageDraw.Draw(img)
    for x in range(0, size[0], 16):
        d.line((x, 0, x + size[1] // 3, size[1]), fill=(200, 60, 40), width=3)
    return img


def framed(img, left=0, top=0, right=0, bottom=0, color=(255, 255, 255)):
    """The cover on a scanner: margins of `color` round it."""
    out = Image.new("RGB", (img.width + left + right, img.height + top + bottom), color)
    out.paste(img, (left, top))
    return out


class ScanEdges(unittest.TestCase):
    def test_thin_white_margins_are_cut(self):
        img = framed(art(), left=8, top=10, bottom=6)
        self.assertEqual(m.scan_margins(img), (8, 10, 0, 6))
        cut, box = m.trim_scan(img)
        self.assertEqual((cut.size, box), ((400, 560), (8, 10, 0, 6)))
        noisy = framed(art(), right=9, color=(236, 238, 230))            # an off-white scanner bed
        self.assertEqual(m.scan_margins(noisy), (0, 0, 9, 0))

    def test_covers_without_margins_stay(self):
        img = art()
        self.assertEqual(m.scan_margins(img), (0, 0, 0, 0))
        self.assertIs(m.trim_scan(img)[0], img)
        self.assertIsNone(m.trim_scan(img)[1])
        white = Image.new("RGB", (400, 560), (255, 255, 255))           # all white: nothing to tell apart
        self.assertEqual(m.scan_margins(white), (0, 0, 0, 0))
        self.assertEqual(m.scan_margins(Image.new("RGB", (10, 10), (255, 255, 255))), (0, 0, 0, 0))

    def test_design_bands_stay(self):
        thick = framed(art(), top=40)                                     # a white band of 7 %: the design's
        self.assertEqual(m.scan_margins(thick)[1], 0)
        band = framed(art(), top=12, color=(0, 0, 0))                     # a black band of 2 % on one side
        self.assertEqual(m.scan_margins(band)[1], 0)
        logo = framed(art(), top=30)                                      # a white band with a small logo in it
        ImageDraw.Draw(logo).rectangle((170, 8, 230, 18), fill=(20, 20, 20))
        self.assertEqual(m.scan_margins(logo)[1], 0)

    def test_black_edges(self):
        line = framed(art(), left=3, color=(5, 5, 5))                     # a scanner's thin black line
        self.assertEqual(m.scan_margins(line), (3, 0, 0, 0))
        lid = framed(art(), 10, 10, 10, 10, (0, 0, 0))                    # scanned on a black lid: black all round
        self.assertEqual(m.scan_margins(lid), (10, 10, 10, 10))

    def test_transparent_padding_and_big_scans(self):
        padded = Image.new("RGBA", (420, 580), (255, 255, 255, 0))
        padded.paste(art().convert("RGBA"), (10, 10))
        self.assertEqual(m.scan_margins(padded), (10, 10, 10, 10))
        big = framed(art((3200, 4400)), left=40)                          # looked at smaller: never cut too much
        left = m.scan_margins(big)[0]
        self.assertTrue(36 <= left <= 40, left)

    def test_load_pictures(self):
        with tempfile.TemporaryDirectory() as tmp:
            lb = make_lb(tmp, [("Scanned", "")], {"Box - Front": [("", "Scanned-01.png", framed(art(), 8, 10, 0, 6))]})
            game = lb.games(PLATFORM)[0]
            pics, _ = m.load_pictures(lb, PLATFORM, game, m.default_profile())
            self.assertEqual((pics.front.size, pics.trimmed.get("front")), ((400, 560), (8, 10, 0, 6)))
            pics, _ = m.load_pictures(lb, PLATFORM, game, dict(m.default_profile(), trim_scans=False))
            self.assertEqual((pics.front.size, pics.trimmed), ((408, 576), {}))
            with Image.open(lb.root / "Images" / PLATFORM / "Box - Front" / "Scanned-01.png") as im:
                self.assertEqual(im.size, (408, 576))                    # LaunchBox's file stays as it was


class GalleryWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        box = Image.new("RGBA", (300, 420), (200, 40, 40, 255))
        disc = Image.new("RGBA", (300, 300), (40, 200, 40, 255))
        self.lb = make_lb(self.tmp.name, [("Alpha", ""), ("Beta", ""), ("Gamma", "")], {
            "Box - Front": [("", "Alpha-01.png", framed(art(), 8, 10, 0, 6)), ("", "Beta-01.png", art()),
                            ("", "Gamma-01.png", art())],
            "Box - 3D": [("", "Alpha-01.png", box), ("", "Gamma-01.png", box), ("", "Gamma-02.png", box)],
            "Disc": [("", "Beta-01.png", disc)]})
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

    def event_at(self, gal, k):
        x, y = gal.origin(k)
        return type("Event", (), {"x": x + 10, "y": y + 10 - gal.canvas.canvasy(0)})()

    def test_gallery(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 3 and app.pics is not None), "games not loaded")
        titles = [g.title for g in app.games]
        alpha, beta, gamma = (titles.index(t) for t in ("Alpha", "Beta", "Gamma"))
        self.assertIn("scan edge cut", app.info_label["text"])                   # Alpha's scanned cover
        app.open_gallery()
        gal = app.gallery
        self.assertIsNotNone(gal)
        self.assertTrue(self.wait(lambda: len(gal.photos) == 2), "thumbnails not made")
        self.assertEqual([(i, n) for i, _path, n in gal.items], [(alpha, 1), (gamma, 2)])
        self.assertEqual(len(list((m.CACHE_DIR / "thumbs").glob("*.jpg"))), 2)  # kept for the next time
        self.assertIn("1 games in the list have none", gal.count_label["text"])
        gal.on_click(self.event_at(gal, 1))                                       # Gamma in the main window
        self.assertTrue(self.wait(lambda: app.current is not None and app.current.title == "Gamma"))
        gal.on_mark(self.event_at(gal, 0))                                        # Alpha is bad
        self.assertEqual(gal.marked, {alpha})
        self.assertEqual(str(gal.select_button["state"]), "normal")
        gal.select_marked()
        self.assertEqual(app.tree.selection(), (str(alpha),))
        gal.on_mark(self.event_at(gal, 0))                                        # and back
        self.assertEqual(gal.marked, set())
        gal.kind_var.set("disc")
        gal.on_kind()
        self.assertEqual([i for i, _p, _n in gal.items], [beta])
        app.filter_var.set(m.TEXTS["filter_has"])                                 # only games with a Box - 3D
        app.on_filter_mode()
        self.assertTrue(self.wait(lambda: not gal.items and gal.canvas.find_withtag("empty")), "list not followed")
        gal.close()
        self.assertIsNone(app.gallery)
        self.assertEqual(app.cfg["gallery"]["kind"], "disc")                     # remembered
        app.open_gallery()
        self.assertEqual(app.gallery.kind_var.get(), "disc")
        app.gallery.close()


if __name__ == "__main__":
    unittest.main()
