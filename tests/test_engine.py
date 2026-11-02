"""Tests of the parts without a window: names, corners, pictures, saving into a made-up LaunchBox folder.

Run: python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lb_box3d_creator as m  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

PLATFORM = "Test Platform"


def cover(color, size=(480, 680), mark=(255, 230, 40)):
    img = Image.new("RGB", size, color)
    ImageDraw.Draw(img).rectangle((size[0] // 6, size[1] // 8, size[0] * 5 // 6, size[1] // 2), fill=mark)
    return img


def make_lb(tmp, games, files):
    """A LaunchBox folder with one platform. games: [(title, region)]; files: {media type: [(region, name, img)]}."""
    root = Path(tmp) / "LaunchBox"
    (root / "Data" / "Platforms").mkdir(parents=True)
    (root / "Data" / "Platforms.xml").write_text(
        f'<?xml version="1.0" standalone="yes"?>\n<LaunchBox><Platform><Name>{PLATFORM}</Name></Platform></LaunchBox>',
        encoding="utf-8")
    body = "".join(
        f"<Game><Title>{t.replace('&', '&amp;').replace(chr(39), '&apos;')}</Title><ID>{i:08d}-0000-0000-0000-000000000000"
        f"</ID><Platform>{PLATFORM}</Platform><Region>{r}</Region></Game>" for i, (t, r) in enumerate(games))
    (root / "Data" / "Platforms" / f"{PLATFORM}.xml").write_text(
        f'<?xml version="1.0" standalone="yes"?>\n<LaunchBox>{body}</LaunchBox>', encoding="utf-8")
    for media_type, items in files.items():
        for region, name, img in items:
            folder = root / "Images" / PLATFORM / media_type / region
            folder.mkdir(parents=True, exist_ok=True)
            img.save(folder / name)
    lb = m.LaunchBox(root)
    lb.load()
    return lb


class NamesAndGeometry(unittest.TestCase):
    def test_clean_name_like_launchbox(self):
        self.assertEqual(m.clean_name("Tom Clancy's Splinter Cell: Blacklist"), "Tom Clancy_s Splinter Cell_ Blacklist")
        self.assertEqual(m.clean_name("AC/DC Live: Rock Band"), "AC_DC Live_ Rock Band")
        self.assertEqual(m.clean_name('Scene It? "Box" <1>|2*'), "Scene It_ _Box_ _1__2_")
        self.assertEqual(m.clean_name("Nike+ Kinect & Co. (Black Edition)! Steins;Gate"),
                         "Nike+ Kinect & Co. (Black Edition)! Steins;Gate")

    def test_homography_round_trip(self):
        quad = [(10, 20), (210, 40), (205, 330), (12, 300)]
        h = m.homography([(0, 0), (1, 0), (1, 1), (0, 1)], quad)
        for (u, v), (x, y) in zip([(0, 0), (1, 0), (1, 1), (0, 1)], quad):
            px, py = m.apply_h(h, u, v)
            self.assertAlmostEqual(px, x, places=6)
            self.assertAlmostEqual(py, y, places=6)

    def test_valid_quad(self):
        self.assertTrue(m.valid_quad([(0, 0), (10, 0), (10, 10), (0, 10)]))
        self.assertFalse(m.valid_quad([(0, 0), (0, 0), (0, 0), (0, 0)]))
        self.assertFalse(m.valid_quad([(0, 0), (10, 0), (10, float("nan")), (0, 10)]))
        self.assertFalse(m.valid_quad("junk"))


class Corners(unittest.TestCase):
    def test_synthetic_template(self):
        img = Image.new("RGBA", (800, 1000), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.polygon([(40, 60), (760, 110), (760, 900), (40, 950)], fill=(30, 60, 160, 255))      # the case
        front = [(150, 140), (720, 170), (720, 860), (150, 890)]
        spine = [(60, 150), (130, 140), (130, 890), (60, 880)]
        d.polygon(front, fill=(250, 250, 250, 255))
        d.polygon(spine, fill=(240, 240, 240, 255))
        quads = m.detect_quads(img)
        for found, wanted in ((quads["front"], front), (quads["spine"], spine)):
            self.assertIsNotNone(found)
            for (x, y), (wx, wy) in zip(found, wanted):
                self.assertLess(abs(x - wx), 3.0, (found, wanted))
                self.assertLess(abs(y - wy), 3.0, (found, wanted))

    def test_corner_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Image.new("RGBA", (400, 500), (0, 0, 0, 0))
            box3d = {"template_size": {"width": 200, "height": 250},
                     "cover_quad": {"tl": [50, 20], "tr": [190, 30], "br": [190, 230], "bl": [50, 240]},
                     "spine_quad": {"tl": [5, 25], "tr": [50, 20], "br": [50, 240], "bl": [5, 235]}}
            (Path(tmp) / "case.json").write_text(json.dumps(box3d), encoding="utf-8")
            quads = m.profile_quads(Path(tmp) / "case.png", img.size)          # scaled from 200x250 to 400x500
            self.assertEqual(quads["front"], [(100, 40), (380, 60), (380, 460), (100, 480)])
            self.assertEqual(quads["spine"][0], (10, 50))
            folder = Path(tmp) / "dvd"
            folder.mkdir()
            ours = {"quads": {"front": [[1, 2], [300, 2], [300, 400], [1, 400]], "spine": None}}
            (folder / "profile.json").write_text(json.dumps(ours), encoding="utf-8")
            quads = m.profile_quads(folder / "template.png", img.size)         # box3d's own folder layout
            self.assertEqual(quads["front"][2], (300, 400))
            self.assertIsNone(quads["spine"])
            (Path(tmp) / "bad.json").write_text('{"cover_quad": {"tl": [0, 0]}}', encoding="utf-8")
            self.assertIsNone(m.profile_quads(Path(tmp) / "bad.png", img.size))
            self.assertIsNone(m.profile_quads(Path(tmp) / "none.png", img.size))

    def test_see_through_window(self):
        img = Image.new("RGBA", (800, 1000), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.polygon([(40, 60), (760, 110), (760, 900), (40, 950)], fill=(20, 20, 20, 255))      # case frame
        window = [(150, 140), (720, 170), (720, 860), (150, 890)]
        d.polygon(window, fill=(255, 255, 255, 10))                                           # glass over the art
        found = m.detect_quads(img)["front"]
        for (x, y), (wx, wy) in zip(found, window):
            self.assertLess(abs(x - wx), 3.0, found)
            self.assertLess(abs(y - wy), 3.0, found)

    def test_shipped_templates(self):
        templates = sorted(m.MODEL_DIR.glob("*.png"))
        if not templates:
            self.skipTest("no box model folder")
        for path in templates:
            img = Image.open(path).convert("RGBA")
            quads = m.template_quads(path, img)
            self.assertTrue(m.valid_quad(quads["front"]), path.name)
            self.assertGreater(m.quad_area(quads["front"]), 0.12 * img.width * img.height, path.name)
            if quads.get("spine"):
                self.assertTrue(m.valid_quad(quads["spine"]), path.name)
        for path in templates:                               # each one brings its corners (a box3d profile)
            with Image.open(path) as im:
                self.assertIsNotNone(m.profile_quads(path, im.size), path.name)

    def test_first_guess(self):
        quads = m.default_quads((800, 1200))
        for face in ("front", "spine"):
            self.assertTrue(m.valid_quad(quads[face]))
            self.assertTrue(all(0 <= x <= 800 and 0 <= y <= 1200 for x, y in quads[face]))
        self.assertLess(max(x for x, _ in quads["spine"]), min(x for x, _ in quads["front"]))


class Pictures(unittest.TestCase):
    def test_spine_cut_only_from_matching_full(self):
        front = cover((20, 80, 200))
        back = cover((200, 40, 40), mark=(10, 10, 10))
        full = Image.new("RGB", (480 * 2 + 60, 680), (0, 0, 0))
        full.paste(back, (0, 0))
        full.paste(Image.new("RGB", (60, 680), (250, 250, 0)), (480, 0))
        full.paste(front, (540, 0))
        cut = m.spine_from_full(full, front)
        self.assertIsNotNone(cut)
        self.assertEqual(cut.size, (60, 680))
        self.assertEqual(cut.getpixel((30, 300)), (250, 250, 0))
        other = cover((200, 200, 200), mark=(0, 120, 0))
        self.assertIsNone(m.spine_from_full(full, other))                          # another edition's full scan
        self.assertIsNone(m.spine_from_full(full.crop((0, 0, 970, 680)), front))   # a 10 px spine is too thin

    def test_render_perspective_and_template(self):
        pics = m.Pictures(front=cover((20, 80, 200)).convert("RGBA"), spine=Image.new("RGBA", (60, 680), "yellow"))
        prof = m.default_profile()
        img, used = m.render_box(prof, None, None, pics, height=500)
        self.assertEqual(img.height, 500)
        self.assertIsNotNone(used["spine"])
        tl, tr, br, bl = used["front"]
        self.assertGreater(m.dist(tl, bl), m.dist(tr, br))          # the left edge is nearer, so taller
        self.assertLess(used["spine"][0][0], tl[0])                  # the spine is left of the front
        template = Image.new("RGBA", (600, 800), (0, 0, 0, 0))
        ImageDraw.Draw(template).rectangle((20, 20, 580, 780), fill=(250, 250, 250, 255))
        quads = {"front": [(100, 60), (560, 80), (560, 740), (100, 760)], "spine": None}
        img, _ = m.render_box(prof, template, quads, pics)
        self.assertEqual(img.size, template.size)
        r, g, b, a = img.getpixel((330, 600))
        self.assertTrue(b > 150 and r < 80, (r, g, b))               # the cover's blue, not the white case

    def test_profile_survives_junk(self):
        prof = m.merged_profile({"faces": "x", "generic": {"angle": "y", "perspective": 5}, "layers": [1],
                                 "overlay": "z", "sheen": False, "template": 3})
        self.assertEqual(prof["generic"]["angle"], m.default_profile()["generic"]["angle"])
        self.assertEqual(prof["generic"]["perspective"], 5)
        self.assertFalse(prof["sheen"])
        self.assertEqual(prof["template"], m.GENERIC)
        self.assertEqual(prof["layers"], {"front": [], "spine": []})


class FromBox3d(unittest.TestCase):
    """The features taken over from box3d."""

    def test_light_layer(self):
        base = Image.new("RGBA", (200, 200), (40, 40, 40, 255))
        template = Image.new("RGBA", (200, 200), (255, 255, 255, 128))
        quad = [(50, 50), (150, 50), (150, 150), (50, 150)]
        m.light_layer(base, template, [quad], 1.0)
        inside, outside = base.getpixel((100, 100)), base.getpixel((10, 10))
        self.assertGreater(inside[0], 120)                     # screened lighter where the face is
        self.assertEqual(outside[:3], (40, 40, 40))           # the case around it is left alone
        self.assertEqual(inside[3], 255)

    def test_tint(self):
        img = Image.new("RGBA", (10, 10), (20, 20, 20, 200))
        self.assertEqual(m.tint_picture(img, "#ff0000", "multiply").getpixel((5, 5)), (20, 0, 0, 200))
        r, g, b, a = m.tint_picture(img, "#2050ff", "colorize").getpixel((5, 5))
        self.assertTrue(b > r and a == 200, (r, g, b, a))
        self.assertIs(m.tint_picture(img, "", "multiply"), img)

    def test_band_spine(self):
        front = Image.new("RGB", (400, 600), (230, 20, 20))
        front.paste((20, 20, 230), (200, 0, 400, 600))
        left = m.make_spine(front, None, "", (60, 600), "band", band=("left", 0.2, 0.2, 0.5), draw_logo=False)
        right = m.make_spine(front, None, "", (60, 600), "band", band=("right", 0.2, 0.2, 0.5), draw_logo=False)
        r, g, b, _ = left.getpixel((30, 300))
        self.assertTrue(r > b and r < 200, (r, g, b))         # the left band, darkened
        r, g, b, _ = right.getpixel((30, 300))
        self.assertTrue(b > r, (r, g, b))

    def test_marquee_and_made_up_spines_only(self):
        canvas = Image.new("RGBA", (100, 400), (0, 0, 0, 0))
        layer = {"kind": "marquee", "size": 100.0, "box_w": 0.8, "box_h": 0.3, "x": 0.5, "y": 0.5, "rotation": -90,
                 "opacity": 1.0, "only_made": True, "slot": "game"}
        m.draw_layers(canvas, [layer], {}, None, Image.new("RGBA", (300, 60), (250, 0, 0, 255)))
        self.assertEqual(canvas.getpixel((50, 200))[:3], (250, 0, 0))
        prof = m.default_profile()
        prof["layers"]["spine"] = [layer]
        prof["shadows"] = False
        pics = m.Pictures(front=Image.new("RGBA", (400, 600), "white"), marquee=Image.new("RGBA", (300, 60), "red"),
                          spine=Image.new("RGBA", (60, 600), (0, 200, 0, 255)))
        real = m.face_canvas("spine", pics, prof, (100, 400), (pics.spine, "spine"))
        self.assertEqual(real.getpixel((50, 200))[:3], (0, 200, 0))          # a real spine keeps no slot logo
        made = m.face_canvas("spine", pics, prof, (100, 400), (None, "generate"))
        self.assertEqual(made.getpixel((50, 200))[:3], (255, 0, 0))

    def test_slots_from_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = {"spine": {"width": 100, "height": 800}, "cover_quad": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "spine_layout": {"game": {"max_w": 80, "max_h": 240, "center_y": 400, "rotate": -90},
                                     "top": {"max_w": 60, "max_h": 80, "center_y": 100, "rotate": -90},
                                     "bottom": {"max_w": 60, "max_h": 80, "center_y": 700, "rotate": -90},
                                     "logo_alpha": 0.7}}
            (Path(tmp) / "case.json").write_text(json.dumps(prof), encoding="utf-8")
            layers = m.spine_slot_layers(Path(tmp) / "case.png")
            self.assertEqual([ly["slot"] for ly in layers], ["game"])           # no assets: only the game slot
            game = layers[0]
            self.assertEqual((game["kind"], game["box_w"], game["box_h"], game["y"], game["opacity"]),
                             ("marquee", 0.8, 0.3, 0.5, 0.7))
            (Path(tmp) / "case-assets").mkdir()
            Image.new("RGBA", (20, 20), "white").save(Path(tmp) / "case-assets" / "logo_top.png")
            layers = m.spine_slot_layers(Path(tmp) / "case.png")
            self.assertEqual([ly["slot"] for ly in layers], ["top", "game"])
            self.assertEqual(layers[0]["kind"], "logo")
        self.assertEqual([ly["slot"] for ly in m.spine_slot_layers(None)], ["game"])   # no profile: a default slot

    def test_box3d_export_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            quads = {"front": [(100.4, 95.0), (638.0, 42.2), (638.0, 922.0), (100.0, 998.0)],
                     "spine": [(0.0, 58.0), (100.0, 92.0), (100.0, 998.0), (0.0, 945.0)]}
            prof = m.default_profile()
            prof["layers"]["spine"] = m.spine_slot_layers(None)
            data = m.box3d_profile("My Case!", (703, 1000), quads, prof)
            self.assertEqual(data["name"], "My_Case")
            self.assertTrue(all(isinstance(v, int) for q in ("cover_quad", "spine_quad")
                                for p in data[q].values() for v in p))
            self.assertLessEqual(data["spine_layout"]["game"]["center_y"], data["spine"]["height"])
            (Path(tmp) / "case.json").write_text(json.dumps(data), encoding="utf-8")
            back = m.profile_quads(Path(tmp) / "case.png", (703, 1000))
            for face in ("front", "spine"):
                for (x, y), (bx, by) in zip(quads[face], back[face]):
                    self.assertLessEqual(abs(x - bx), 0.5)
                    self.assertLessEqual(abs(y - by), 0.5)

    def test_plan(self):
        found = [{"front": "a"}, {"front": "b", "box3d": ["x"]}, {}, {"front": "c"}]
        self.assertEqual(m.batch_plan(found, "skip"), (2, 1, 1, 0))
        self.assertEqual(m.batch_plan(found, "replace"), (3, 0, 1, 0))
        self.assertEqual(m.batch_plan(found, "skip", need_front=False), (3, 1, 0, 0))
        self.assertEqual(m.batch_plan(found, "skip", generic=True), (3, 1, 0, 1))       # the one without a front
        self.assertEqual(m.batch_plan(found + [{"box3d": ["y"]}], "skip", generic=True), (3, 2, 0, 1))


class LaunchBoxFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        blue, red = cover((20, 80, 200)), cover((200, 30, 30))
        self.lb = make_lb(self.tmp.name, [("Tom Clancy's Test: One?", "Europe"), ("Second Game", "Europe"),
                                          ("No Pictures", "Europe")], {
            "Box - Front": [("Europe", "Tom Clancy_s Test_ One_-01.jpg", blue), ("", "Second Game-01.png", red)],
            "Box - Spine": [("North America", "Tom Clancy_s Test_ One_-01.png", Image.new("RGB", (50, 680), "white"))],
            "Box - 3D": [("", "Second Game-01.png", red)],
        })
        self.games = self.lb.games(PLATFORM)

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, existing):
        return {"region": "same", "existing": existing, "format": "png", "jpg_bg": "#ffffff", "max_height": 600,
                "trim": True, "threads": 2}

    def test_platform_and_games(self):
        self.assertEqual(self.lb.platforms, [PLATFORM])
        self.assertEqual([g.title for g in self.games], ["Tom Clancy's Test: One?", "Second Game", "No Pictures"])

    def test_pictures_and_regions(self):
        prof = m.default_profile()
        found = self.lb.find(PLATFORM, self.games[0], prof)
        self.assertEqual(found["region"], "Europe")
        self.assertNotIn("spine", found)                         # only in another region folder
        self.assertIn("spine_other_region", found)
        prof["match_region"] = False
        self.assertIn("spine", self.lb.find(PLATFORM, self.games[0], prof))
        self.assertEqual(len(self.lb.find(PLATFORM, self.games[1], prof)["box3d"]), 1)

    def test_targets(self):
        prof = m.default_profile()
        one = self.lb.find(PLATFORM, self.games[0], prof)
        path, region, replaced = m.output_target(self.lb, PLATFORM, self.games[0], one, self.export("skip"))
        self.assertEqual((path.parent.name, path.name, region), ("Europe", "Tom Clancy_s Test_ One_-01.png", "Europe"))
        two = self.lb.find(PLATFORM, self.games[1], prof)
        self.assertIsNone(m.output_target(self.lb, PLATFORM, self.games[1], two, self.export("skip")))
        path, _, replaced = m.output_target(self.lb, PLATFORM, self.games[1], two, self.export("replace"))
        self.assertEqual(path.name, "Second Game-01.png")
        self.assertEqual(len(replaced), 1)
        path, _, replaced = m.output_target(self.lb, PLATFORM, self.games[1], two, self.export("next"))
        self.assertEqual(path.name, "Second Game-02.png")
        self.assertIsNone(replaced)

    def test_batch(self):
        prof = m.default_profile()
        prof["generic_cover"] = False                  # games without a Box - Front left out (test_generic: made)
        backup = self.lb.root / "Backups" / "test"
        counts = m.batch_make(self.lb, PLATFORM, self.games, prof, None, None, self.export("skip"), threading.Event(),
                              backup, 600)
        self.assertEqual((counts["saved"], counts["skipped"], counts["nofront"], counts["errors"]), (1, 1, 1, 0))
        out = self.lb.media_folder(PLATFORM, m.OUT_TYPE)
        made = out / "Europe" / "Tom Clancy_s Test_ One_-01.png"
        self.assertTrue(made.is_file())
        with Image.open(made) as im:
            self.assertEqual(im.mode, "RGBA")
        counts = m.batch_make(self.lb, PLATFORM, self.games, prof, None, None, self.export("replace"),
                              threading.Event(), backup, 600)
        self.assertEqual((counts["saved"], counts["errors"]), (2, 0))
        self.assertTrue((backup / "Images" / PLATFORM / m.OUT_TYPE / "Second Game-01.png").is_file())
        leftovers = [p for p in out.rglob("*") if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_circuit_breaker(self):
        with tempfile.TemporaryDirectory() as tmp:
            small = Image.new("RGB", (30, 40), "blue")
            lb = make_lb(tmp, [(f"Game {i}", "") for i in range(40)],
                         {"Box - Front": [("", f"Game {i}-01.png", small) for i in range(40)]})
            old = m.load_pictures

            def broken(*args, **kwargs):
                raise OSError("disk gone")

            m.load_pictures = broken            # every box fails the same way
            try:
                counts = m.batch_make(lb, PLATFORM, lb.games(PLATFORM), m.default_profile(), None, None,
                                      dict(self.export("skip"), threads=1), threading.Event(), lb.root / "Backups", 600)
            finally:
                m.load_pictures = old
        self.assertEqual(counts["aborted"], "in_a_row")
        self.assertGreaterEqual(counts["errors"], m.ABORT_IN_A_ROW)
        self.assertLess(counts["errors"], 20)  # the rest stopped without trying

    def test_stop(self):
        stop = threading.Event()
        stop.set()
        counts = m.batch_make(self.lb, PLATFORM, self.games, m.default_profile(), None, None, self.export("skip"), stop,
                              self.lb.root / "Backups", 600)
        self.assertEqual(counts["saved"], 0)


class Config(unittest.TestCase):
    def test_bad_config_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = m.CONFIG_PATH
            m.CONFIG_PATH = Path(tmp) / "cfg.json"
            try:
                m.CONFIG_PATH.write_text(json.dumps({"export": {"threads": "many", "max_height": 700},
                                                     "profiles": [], "lb_root": 5}), encoding="utf-8")
                cfg = m.load_config()
                self.assertIsInstance(cfg["export"]["threads"], int)
                self.assertEqual(cfg["export"]["max_height"], 700)
                self.assertEqual(cfg["profiles"], {})
                self.assertEqual(cfg["lb_root"], "")
                m.save_config(cfg)
                self.assertTrue(m.CONFIG_PATH.is_file())
                self.assertFalse(os.path.exists(str(m.CONFIG_PATH) + ".tmp"))
            finally:
                m.CONFIG_PATH = old


if __name__ == "__main__":
    unittest.main()
