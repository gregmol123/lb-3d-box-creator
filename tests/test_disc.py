"""Discs: the kinds and their holes, hubs and labels, the picture's crop and zoom, the logo, the text along the edge,
discs for games without a cover, saving them as LaunchBox's "Disc" pictures, and the window's Disc view.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
"""
import math
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

ART = (40, 90, 200)
SIZE = 400


def at(img, radius, angle=0.0):
    """The pixel at a part of the disc's radius, `angle` degrees clockwise from the right."""
    c = img.width / 2
    t = math.radians(angle)
    return img.getpixel((min(img.width - 1, round(c + radius * c * math.cos(t))),
                         min(img.height - 1, round(c + radius * c * math.sin(t)))))


def near(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


def count(img, test, box=None):
    """How many solid pixels pass `test`."""
    data = (img.crop(box) if box else img).convert("RGBA").tobytes()
    return sum(1 for i in range(0, len(data), 4) if data[i + 3] > 200 and test(data[i:i + 4]))


def disc(kind, art=None, **settings):
    prof = dict(m.default_profile(), disc_kind=kind, **settings)
    return m.make_disc(art or Image.new("RGB", (300, 420), ART), prof, {"title": "Combat", "year": "1977", "publisher": ""}, None, "",
                       SIZE)


class Kinds(unittest.TestCase):
    def test_text_with_empty_fields(self):
        for text, line in (("Combat · © 1977 Atari", "Combat · © 1977 Atari"), ("Combat · © ", "Combat"),
                           ("Combat ·  · Atari", "Combat · Atari"), ("Combat · © · Atari", "Combat · Atari"),
                           (" · Atari", "Atari"), ("© ", ""), ("Pac-Man - ", "Pac-Man"), ("A | | B", "A | B"),
                           ("© 1977", "© 1977"), ("Half-Life 2 — Valve", "Half-Life 2 — Valve"), ("", "")):
            self.assertEqual(m.tidy_line(text), line, text)

    def test_kind_from_the_platform(self):
        for platform, kind in (("Sony Playstation", "psx"), ("Sony Playstation 2", "dvd"),
                               ("Sony Playstation 3", "bluray"), ("Nintendo GameCube", "gamecube"),
                               ("Nintendo Wii", "dvd"), ("Nintendo Wii U", "bluray"), ("Microsoft Xbox", "dvd"),
                               ("Microsoft Xbox 360", "dvd"), ("Microsoft Xbox One", "bluray"), ("Sega Saturn", "cd"),
                               ("Sega Dreamcast", "cd"), ("", "cd")):
            self.assertEqual(m.disc_kind({"disc_kind": "auto"}, platform), kind, platform)
        self.assertEqual(m.disc_kind({"disc_kind": "picture"}, "Sony Playstation 2"), "picture")
        self.assertEqual(m.disc_kind({"disc_kind": "junk"}, "Sony Playstation 2"), "dvd")
        self.assertEqual(m.disc_kind({}, "Sony Playstation 2"), "dvd")

    def test_every_kind(self):
        for kind, (hole, inner, _tint) in m.DISC_KINDS.items():
            img = disc(kind)
            self.assertEqual((img.size, img.mode), ((SIZE, SIZE), "RGBA"), kind)
            for corner in ((0, 0), (SIZE - 1, 0), (0, SIZE - 1), (SIZE - 1, SIZE - 1)):
                self.assertEqual(img.getpixel(corner)[3], 0, kind)               # round
            self.assertEqual(at(img, 0)[3], 0, kind)                             # the hole
            self.assertEqual(at(img, hole - 0.02)[3], 0, kind)
            self.assertGreater(at(img, hole + 0.02)[3], 40, kind)
            for angle in (0, 90, 180):
                self.assertTrue(near(at(img, 0.7, angle), ART), (kind, angle, at(img, 0.7, angle)))   # the label
                self.assertEqual(at(img, 0.7, angle)[3], 255, kind)
            self.assertTrue(near(at(img, inner + 0.03), ART), (kind, at(img, inner + 0.03)))
            hub = min(0.19, inner)
            if hub > hole + 0.01:                                                # clear plastic round the hole
                self.assertLess(at(img, (hole + hub) / 2 + 0.015)[3], 200, kind)
            if inner > 0.22:                                                     # silver between hub and label
                px = at(img, (0.19 + inner) / 2, 45)
                self.assertFalse(near(px, ART, 30), (kind, px))
                self.assertEqual(px[3], 255, kind)
        self.assertGreater(at(disc("bluray"), 0.25)[2], at(disc("bluray"), 0.25)[0])      # blue silver
        self.assertLess(sum(at(disc("cd"), 0.99, 45)[:3]), 3 * 245)

    def test_part_of_the_cover(self):
        art = Image.new("RGB", (300, 600), (220, 20, 20))
        art.paste((20, 20, 220), (0, 300, 300, 600))                          # top red, bottom blue
        red, blue = (220, 20, 20), (20, 20, 220)
        self.assertTrue(near(at(disc("cd", art, disc_crop="top"), 0.7, 90), red))
        self.assertTrue(near(at(disc("cd", art, disc_crop="bottom"), 0.7, 270), blue))
        middle = disc("cd", art, disc_crop="center")
        self.assertTrue(near(at(middle, 0.7, 270), red) and near(at(middle, 0.7, 90), blue))
        spot = Image.new("RGB", (300, 300), (0, 0, 0))
        spot.paste((255, 255, 255), (100, 100, 200, 200))
        self.assertTrue(near(at(disc("picture", spot), 0.5), (0, 0, 0)))
        self.assertTrue(near(at(disc("picture", spot, disc_zoom=2.0), 0.5), (255, 255, 255)))   # zoomed in

    def test_logo_and_text(self):
        prof = dict(m.default_profile(), disc_kind="cd")
        logo = Image.new("RGBA", (400, 120), (0, 200, 0, 255))
        img = m.make_disc(Image.new("RGB", (300, 420), ART), prof, {}, logo, "", SIZE)
        green = lambda px: px[1] > 150 and px[0] < 80 and px[2] < 80  # noqa: E731
        self.assertGreater(count(img, green, (0, 0, SIZE, SIZE // 2)), 500)
        self.assertEqual(count(img, green, (0, SIZE // 2, SIZE, SIZE)), 0)     # high up, as on real discs
        red = lambda px: px[0] > 200 and px[1] < 80 and px[2] < 80  # noqa: E731
        for pos, rows in (("bottom", (SIZE * 3 // 4, SIZE)), ("top", (0, SIZE // 4))):
            img = disc("cd", disc_text="{title} · © {year}", disc_text_color="#ff0000", disc_text_pos=pos)
            self.assertGreater(count(img, red, (0, rows[0], SIZE, rows[1])), 40, pos)
            other = (0, SIZE // 4, SIZE, SIZE) if pos == "top" else (0, 0, SIZE, SIZE * 3 // 4)
            self.assertEqual(count(img, red, other), 0, pos)
        img = disc("cd", disc_text="© {publisher}", disc_text_color="#ff0000")    # nothing to write
        self.assertEqual(count(img, red), 0)
        long = disc("cd", disc_text="A very long line of text " * 8, disc_text_color="#ff0000")
        self.assertGreater(count(long, red), 40)                                 # smaller letters, still there


class GamesDiscs(unittest.TestCase):
    def pics(self, front=None, logo=None, marquee=None):
        ctx = {"title": "Mighty Term v1.0", "platform": "Commodore VIC-20", "lb_platform": "Commodore VIC-20"}
        return m.Pictures(front, None, None, logo, ctx, marquee)

    def test_render(self):
        prof = m.default_profile()
        img = m.render_disc(prof, self.pics(Image.new("RGBA", (300, 420), ART + (255,))), "", 300)
        self.assertEqual(img.size, (300, 300))
        self.assertTrue(near(at(img, 0.7), ART))
        generic = m.render_disc(prof, self.pics(), "", 300)                         # no cover: a generic label
        self.assertEqual(generic.size, (300, 300))
        self.assertFalse(near(at(generic, 0.7), ART))
        self.assertIsNone(m.render_disc(dict(prof, generic_cover=False), self.pics(), "", 300))
        own = m.default_profile()
        own["faces"]["front"]["source"] = "picture"
        self.assertIsNone(m.render_disc(own, self.pics(), "", 300))
        green = lambda px: px[1] > 150 and px[0] < 80 and px[2] < 80  # noqa: E731
        marquee = Image.new("RGBA", (400, 100), (0, 200, 0, 255))
        with_marquee = m.render_disc(prof, self.pics(Image.new("RGBA", (300, 420), ART + (255,)), None, marquee), "", 300)
        self.assertGreater(count(with_marquee, green), 300)                         # no Clear Logo: the marquee
        no_logo = m.render_disc(dict(prof, disc_logo=False),
                                self.pics(Image.new("RGBA", (300, 420), ART + (255,)), marquee), "", 300)
        self.assertEqual(count(no_logo, green), 0)

    def test_saved_into_launchbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            red = cover((200, 30, 30))
            lb = make_lb(tmp, [("With Disc", "Europe"), ("No Disc", "Europe"), ("No Cover", "")], {
                "Box - Front": [("Europe", "With Disc-01.png", cover((20, 80, 200))), ("Europe", "No Disc-01.png", red)],
                "Disc": [("Europe", "With Disc-01.png", Image.new("RGBA", (64, 64), (9, 9, 9, 255)))]})
            games = lb.games(PLATFORM)
            prof = m.default_profile()
            found = lb.find(PLATFORM, games[0], prof)
            self.assertEqual(len(found["disc"]), 1)
            self.assertIsNone(m.output_target(lb, PLATFORM, games[0], found, {"existing": "skip"}, m.DISC_TYPE))
            path, region, replaced = m.output_target(lb, PLATFORM, games[0], found, {"existing": "replace"},
                                                     m.DISC_TYPE)
            self.assertEqual((path.name, region, len(replaced)), ("With Disc-01.png", "Europe", 1))
            export = {"region": "same", "existing": "skip", "format": "png", "jpg_bg": "#ffffff", "max_height": 300,
                      "trim": True, "threads": 2, "make_box": False, "make_disc": True}
            counts = m.batch_make(lb, PLATFORM, games, dict(prof, disc_size=500), None, None, export,
                                  threading.Event(), lb.root / "Backups", 300)
            self.assertEqual((counts["discs"], counts["saved"], counts["skipped"], counts["generic"], counts["errors"]),
                             (2, 0, 1, 1, 0))
            discs = lb.media_folder(PLATFORM, m.DISC_TYPE)
            made = discs / "Europe" / "No Disc-01.png"
            with Image.open(made) as im:
                self.assertEqual((im.size, im.mode), ((500, 500), "RGBA"))       # no trim, no height limit
                self.assertEqual(im.getpixel((0, 0))[3], 0)
                self.assertTrue(near(at(im, 0.7, 90), (200, 30, 30), 60))
            self.assertTrue((discs / "No Cover-01.png").is_file())               # generic, main folder
            self.assertFalse(lb.media_folder(PLATFORM, m.OUT_TYPE).exists())    # no boxes asked for
            both = dict(export, make_box=True, existing="next", format="jpg", jpg_bg="#00ff00")
            counts = m.batch_make(lb, PLATFORM, games[1:2], prof, None, None, both, threading.Event(),
                                  lb.root / "Backups", 300)
            self.assertEqual((counts["discs"], counts["saved"], counts["errors"]), (1, 1, 0))
            with Image.open(discs / "Europe" / "No Disc-02.jpg") as im:
                self.assertEqual(im.mode, "RGB")
                self.assertTrue(near(im.getpixel((0, 0)), (0, 255, 0), 30))      # corners in the JPEG colour
            self.assertTrue((lb.media_folder(PLATFORM, m.OUT_TYPE) / "Europe" / "No Disc-01.jpg").is_file())

    def test_plan(self):
        found = [{"front": "a.png", "box3d": ["a3d.png"]}, {"front": "b.png", "box3d": ["b.png"], "disc": ["d.png"]},
                 {"front": "c.png"}]
        self.assertEqual(m.batch_plan(found, "skip", True, False, (m.OUT_TYPE,)), (1, 2, 0, 0))
        self.assertEqual(m.batch_plan(found, "skip", True, False, (m.DISC_TYPE,)), (2, 1, 0, 0))
        self.assertEqual(m.batch_plan(found, "skip", True, False, (m.OUT_TYPE, m.DISC_TYPE)), (2, 1, 0, 0))
        self.assertEqual(m.batch_plan(found, "replace", True, False, (m.OUT_TYPE, m.DISC_TYPE)), (3, 0, 0, 0))


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("First Game", "Europe"), ("Mighty Term v1.0", "")],
                          {"Box - Front": [("Europe", "First Game-01.png", cover((20, 80, 200)))]})
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
        self.tmp.cleanup()

    def wait(self, cond, seconds=20.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_disc_view_and_saving(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 2 and app.pics is not None), "game not shown")
        app.set_view("disc")
        app.draw()
        self.assertIsNotNone(app.photo)
        self.assertEqual(app.shown_quads, {})
        self.assertIn("now: CD", app.disc_auto_radio["text"])
        app.cfg["export"]["make_disc"] = True
        app.save_one(False)                                                   # box and disc
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Saved")), app.status_text)
        self.assertTrue((self.lb.media_folder(PLATFORM, m.DISC_TYPE) / "Europe" / "First Game-01.png").is_file())
        self.assertTrue((self.lb.media_folder(PLATFORM, m.OUT_TYPE) / "Europe" / "First Game-01.png").is_file())
        self.assertTrue(self.wait(lambda: app.found[0].get("disc")), "disc not noted")
        app.cfg["export"]["make_box"] = False
        app.make_boxes("all")                                                 # the generic game's disc only
        self.assertTrue(self.wait(lambda: not app.batch_running), "batch did not finish")
        self.assertIn("discs 1", app.status_text)
        self.assertTrue((self.lb.media_folder(PLATFORM, m.DISC_TYPE) / "Mighty Term v1.0-01.png").is_file())
        self.assertFalse((self.lb.media_folder(PLATFORM, m.OUT_TYPE) / "Mighty Term v1.0-01.png").exists())
        app.cfg["export"]["make_disc"] = False
        app.make_boxes("all")                                                 # nothing chosen: a message, no run
        self.assertFalse(app.batch_running)
        self.assertEqual(app.status_text, m.TEXTS["nothing_chosen"])


if __name__ == "__main__":
    unittest.main()
