"""Generic covers for entries with no Box - Front at all (applications, games without box art): names, the cover and
spine, when they are used, batches, and the window.

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

INK = (29, 42, 68)


def ink_share(img, box):
    """Share of the pixels in box that have the logo / name colour."""
    part = img.convert("RGB").crop(box)
    data = part.tobytes()
    near = sum(1 for i in range(0, len(data), 3)
               if abs(data[i] - INK[0]) + abs(data[i + 1] - INK[1]) + abs(data[i + 2] - INK[2]) < 60)
    return near / (part.width * part.height)


def has_color(img, rgb):
    data = img.convert("RGB").tobytes()
    return any(tuple(data[i:i + 3]) == rgb for i in range(0, len(data), 3))


def ctx(title="Rocket Command", platform="Commodore VIC-20 [Applications]", **more):
    return dict({"title": title, "lb_platform": platform}, **more)


class Names(unittest.TestCase):
    def test_platform_names(self):
        cases = {
            "Commodore VIC-20 [Games] [PRG]": ("COMMODORE", "VIC-20"),
            "Commodore VIC-20 [Applications]": ("COMMODORE", "VIC-20"),
            "Atari 2600/VCS [Games]": ("ATARI", "2600/VCS"),
            "Tandy Radio Shack - TRS-80 Color Computer - Manuals - Games": ("TANDY RADIO SHACK",
                                                                             "TRS-80 COLOR COMPUTER"),
            "2600 & VCS - Games": ("", "2600 & VCS"),
            "VTech Laser 500": ("VTECH", "LASER 500"),
            "MSX": ("", "MSX"),
            "": ("", ""),
        }
        for platform, want in cases.items():
            self.assertEqual(m.platform_names(platform), want, platform)

    def test_own_names(self):
        prof = m.default_profile()
        self.assertEqual(m.gc_names(prof, ctx()), ("COMMODORE", "VIC-20"))
        prof.update(gc_name="Laser 500", gc_maker="Color Computer")
        self.assertEqual(m.gc_names(prof, ctx()), ("Color Computer", "Laser 500"))
        prof["gc_maker"] = "-"
        self.assertEqual(m.gc_names(prof, ctx()), ("", "Laser 500"))

    def test_cover_title(self):
        self.assertEqual(m.cover_title("Caladuril II - Weatherstone's End (1988)(Oblique Triad)"),
                         "Caladuril II - Weatherstone's End")
        self.assertEqual(m.cover_title("Rocket Command"), "Rocket Command")
        self.assertEqual(m.cover_title("(Demo)"), "(Demo)")             # nothing left: kept as it is


class Cover(unittest.TestCase):
    def test_front_layout(self):
        img = m.generic_front(m.default_profile(), ctx(), None, (700, 1000))
        self.assertEqual((img.size, img.mode), ((700, 1000), "RGBA"))
        self.assertGreater(ink_share(img, (70, 60, 630, 340)), 0.05)     # the platform's logo at the top
        self.assertGreater(ink_share(img, (60, 720, 640, 880)), 0.05)    # the game's name at the bottom
        self.assertLess(ink_share(img, (100, 440, 600, 600)), 0.005)     # silver in between
        self.assertGreater(img.convert("L").getpixel((350, 520)), 200)

    def test_both_logo_layouts(self):
        split = m.drawn_platform_logo("COMMODORE", "VIC-20", INK)        # "VIC" big, "20" and the maker below
        whole = m.drawn_platform_logo("SINCLAIR", "ZX SPECTRUM", INK)
        long_ = m.drawn_platform_logo("TANDY", "TRS-80 COLOR COMPUTER", INK)  # two lines
        for pic in (split, whole, long_):
            self.assertTrue(pic.getchannel("A").getbbox())
        self.assertGreater(long_.height, whole.height)

    def test_dark_and_picture_grounds(self):
        prof = m.default_profile()
        prof["gc_style"] = "dark"
        dark = m.generic_front(prof, ctx(), None, (500, 700))
        self.assertLess(dark.convert("L").getpixel((250, 380)), 90)
        self.assertEqual(m.gc_ink(prof), m.GC_LIGHT)                     # navy letters turn light on dark
        with tempfile.TemporaryDirectory() as tmp:
            ground = Path(tmp) / "ground.png"
            Image.new("RGB", (300, 400), (200, 30, 30)).save(ground)
            prof.update(gc_style="picture", gc_picture=str(ground))
            own = m.generic_front(prof, ctx(), None, (500, 700))
            self.assertEqual(own.getpixel((250, 380))[:3], (200, 30, 30))
            prof["gc_picture"] = str(Path(tmp) / "missing.png")         # gone: silver instead
            self.assertGreater(m.generic_front(prof, ctx(), None, (500, 700)).convert("L").getpixel((250, 380)), 200)

    def test_logo_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            logo = Path(tmp) / "logo.png"
            Image.new("RGBA", (400, 120), (0, 200, 0, 255)).save(logo)
            prof = m.default_profile()
            img = m.generic_front(prof, ctx(platform_logo=str(logo)), None, (700, 1000))     # LaunchBox's logo
            self.assertEqual(img.getpixel((350, 120))[:3], (0, 200, 0))
            prof.update(gc_logo="drawn")
            self.assertNotEqual(m.generic_front(prof, ctx(platform_logo=str(logo)), None, (700, 1000)).getpixel(
                (350, 120))[:3], (0, 200, 0))
            prof.update(gc_logo="picture", gc_logo_file=str(logo))
            self.assertEqual(m.generic_front(prof, ctx(), None, (700, 1000)).getpixel((350, 120))[:3], (0, 200, 0))
            spine = m.generic_spine(prof, ctx(), (140, 1000))
            self.assertEqual(spine.getpixel((70, 2))[:3], m.GC_SPINE)

    def test_game_logo_instead_of_title(self):
        prof = m.default_profile()
        prof["gc_title"] = "logo"
        game_logo = Image.new("RGBA", (500, 150), (220, 120, 0, 255))
        img = m.generic_front(prof, ctx(), game_logo, (700, 1000))
        self.assertEqual(img.getpixel((350, 800))[:3], (220, 120, 0))
        img = m.generic_front(prof, ctx(), None, (700, 1000))           # no Clear Logo: the title
        self.assertGreater(ink_share(img, (60, 720, 640, 880)), 0.05)


class WhenUsed(unittest.TestCase):
    def test_only_without_a_front(self):
        prof = m.default_profile()
        bare = m.Pictures(ctx=ctx())
        made = m.generic_pictures(prof, bare)
        self.assertTrue(made.generic)
        self.assertIsNotNone(made.front)
        self.assertIsNotNone(made.spine)
        with_front = m.Pictures(front=cover((20, 80, 200)).convert("RGBA"), ctx=ctx())
        self.assertIs(m.generic_pictures(prof, with_front), with_front)   # a real Box - Front is kept
        prof["generic_cover"] = False
        self.assertIs(m.generic_pictures(prof, bare), bare)
        prof["generic_cover"] = True
        prof["faces"]["front"]["source"] = "color"
        self.assertIs(m.generic_pictures(prof, bare), bare)

    def test_real_spine_kept_and_spine_option(self):
        prof = m.default_profile()
        spine = Image.new("RGBA", (60, 700), (255, 0, 0, 255))
        self.assertIs(m.generic_pictures(prof, m.Pictures(spine=spine, ctx=ctx())).spine, spine)
        prof["gc_spine"] = False
        self.assertIsNone(m.generic_pictures(prof, m.Pictures(ctx=ctx())).spine)

    def test_cover_takes_the_templates_shape(self):
        path = m.APP_DIR / "box model" / "box3d-dvd.png"
        if not path.is_file():
            self.skipTest("box3d-dvd.png not in box model")
        tpl = m.load_picture(path)
        quads = m.template_quads(path, tpl)
        made = m.generic_pictures(m.default_profile(), m.Pictures(ctx=ctx()), tpl, quads)
        fw, fh = m.face_size(quads["front"])
        self.assertAlmostEqual(made.front.width / made.front.height, fw / fh, places=2)
        img, _ = m.render_box(m.default_profile(), tpl, quads, m.Pictures(ctx=ctx()))
        self.assertEqual(img.size, tpl.size)
        box, used = m.render_box(m.default_profile(), None, None, m.Pictures(ctx=ctx()), height=600)
        self.assertEqual(box.height, 600)
        sw, _ = m.face_size(used["spine"])
        self.assertGreater(sw, 20)                                       # a thick case, as in the video


class Batches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("With Cover", "Europe"), ("Mighty Term v1.0", ""), ("No Box (1983)", "")],
                          {"Box - Front": [("Europe", "With Cover-01.png", cover((20, 80, 200)))]})
        self.games = self.lb.games(PLATFORM)
        self.export = {"region": "same", "existing": "skip", "format": "png", "jpg_bg": "#ffffff", "max_height": 500,
                       "trim": True, "threads": 2}

    def tearDown(self):
        self.tmp.cleanup()

    def test_whole_platform(self):
        counts = m.batch_make(self.lb, PLATFORM, self.games, m.default_profile(), None, None, self.export,
                              threading.Event(), self.lb.root / "Backups", 500)
        self.assertEqual((counts["saved"], counts["generic"], counts["nofront"], counts["errors"]), (3, 2, 0, 0))
        out = self.lb.media_folder(PLATFORM, m.OUT_TYPE)
        self.assertTrue((out / "Europe" / "With Cover-01.png").is_file())       # its own cover, its region
        self.assertTrue((out / "Mighty Term v1.0-01.png").is_file())            # generic, main folder
        self.assertTrue((out / "No Box (1983)-01.png").is_file())
        prof = m.default_profile()
        prof["generic_cover"] = False
        again = m.batch_make(self.lb, PLATFORM, self.games, prof, None, None, dict(self.export, existing="replace"),
                             threading.Event(), self.lb.root / "Backups", 500)
        self.assertEqual((again["saved"], again["generic"], again["nofront"]), (1, 0, 2))

    def test_platform_logo_from_launchbox(self):
        folder = self.lb.root / "Images" / "Platforms" / m.clean_name(PLATFORM) / "Clear Logo"
        folder.mkdir(parents=True)
        Image.new("RGBA", (300, 90), (0, 160, 0, 255)).save(folder / f"{PLATFORM}.png")
        m._platform_logos.clear()
        pics, _ = m.load_pictures(self.lb, PLATFORM, self.games[1], m.default_profile())
        self.assertEqual(Path(pics.ctx["platform_logo"]).name, f"{PLATFORM}.png")
        self.assertEqual(pics.ctx["lb_platform"], PLATFORM)
        made = m.generic_pictures(m.default_profile(), pics)
        self.assertTrue(has_color(made.front.crop((0, 0, made.front.width, 400)), (0, 160, 0)))
        m._platform_logos.clear()


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("With Cover", "Europe"), ("Mighty Term v1.0", "")],
                          {"Box - Front": [("Europe", "With Cover-01.png", cover((20, 80, 200)))]})
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
        self.tmp.cleanup()

    def wait(self, cond, seconds=20.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_generic_game(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 2 and len(app.found) == 2), "games not loaded")
        app.tree.selection_set("1")
        app.on_game_select()
        self.assertTrue(self.wait(lambda: app.pics is not None and app.current is app.games[1]), "game not shown")
        self.assertIn("generic cover", app.info_label["text"])
        app.draw()
        self.assertIsNotNone(app.photo)
        self.assertTrue(app.gc_auto_label["text"])
        app.profile["generic_cover"] = False
        app.setting_changed("profile", "generic_cover")
        self.assertIn("no Box - Front", app.info_label["text"])
        app.profile["generic_cover"] = True
        app.setting_changed("profile", "generic_cover")
        app.save_one(False)                                              # one game without a front: saved
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Saved")), app.status_text)
        out = self.lb.media_folder(PLATFORM, m.OUT_TYPE)
        self.assertTrue((out / "Mighty Term v1.0-01.png").is_file())
        app.make_boxes("all")                                            # the whole platform
        self.assertTrue(self.wait(lambda: not app.batch_running), "batch did not finish")
        self.assertIn("generic covers 0", app.status_text)                # the generic one was already there
        self.assertTrue((out / "Europe" / "With Cover-01.png").is_file())


if __name__ == "__main__":
    unittest.main()
