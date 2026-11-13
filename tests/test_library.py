"""The user's picture folders next to the program: case templates in subfolders of "box model", discs printed under
a picture of "disc model", cartridge pictures of "cart model" (a cut-out label window gets the cover under it) and
logos of "logo model", with each game's age-rating badge chosen from its LaunchBox rating.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
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
from test_engine import PLATFORM, cover, make_lb  # noqa: E402

RIM = (200, 200, 205)
FRAME = (40, 40, 44)


def disc_picture(size=400, hole=28):
    """A disc picture: see-through but for its rim and the ring round its hole."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 5, size - 5), outline=RIM + (255,), width=6)
    c = size // 2
    d.ellipse((c - hole, c - hole, c + hole, c + hole), outline=RIM + (255,), width=4)
    return img


def framed_cart(size=(300, 340), window=(50, 60, 250, 260)):
    """A cartridge picture whose label is cut out (a see-through window inside it)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((10, 10, size[0] - 11, size[1] - 11), 20, fill=FRAME + (255,))
    img.paste((0, 0, 0, 0), window)
    return img


def near(a, b, tol=30):
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


class Folders(unittest.TestCase):
    def test_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Pack" / "Deeper").mkdir(parents=True)
            for rel in ("b.png", "A.png", "Pack/z.png", "Pack/Deeper/x.jpg", "notes.txt", "Pack/case.json"):
                (root / rel).write_bytes(b"x")
            self.assertEqual(m.library(root), ["A.png", "b.png", "Pack/Deeper/x.jpg", "Pack/z.png"])
            self.assertEqual(m.library(root / "missing"), [])
            self.assertEqual(m.library_path(root, "Pack/z.png"), root / "Pack" / "z.png")
            self.assertEqual(m.library_path(root, str(root / "A.png")), root / "A.png")


class DiscPictures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = m.DISC_DIR
        m.DISC_DIR = Path(self.tmp.name) / "disc model"
        (m.DISC_DIR / "Pack").mkdir(parents=True)
        disc_picture().save(m.DISC_DIR / "Pack" / "Silver.png")

    def tearDown(self):
        m.DISC_DIR = self.old
        self.tmp.cleanup()

    def test_frame(self):
        cx, cy, r, hole = m.disc_frame(disc_picture())
        self.assertAlmostEqual(cx, 200, delta=1.5)
        self.assertAlmostEqual(r, 196, delta=2)
        self.assertAlmostEqual(hole, 26, delta=3)                 # up to the ring drawn round the hole
        bare = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        ImageDraw.Draw(bare).ellipse((0, 0, 299, 299), outline=RIM + (255,), width=3)
        self.assertAlmostEqual(m.disc_frame(bare)[3], 150 * m.DISC_KINDS["cd"][0], delta=1)   # no hole drawn
        self.assertIsNone(m.disc_frame(Image.new("RGBA", (50, 50), (0, 0, 0, 0))))

    def test_cover_under_the_picture(self):
        prof = dict(m.default_profile(), disc_kind="template", disc_template="Pack/Silver.png", disc_size=400)
        disc = m.make_disc(cover((20, 80, 200)).convert("RGBA"), prof)
        self.assertEqual(disc.size, (400, 400))
        self.assertEqual(disc.getpixel((200, 200))[3], 0)             # the hole stays see-through
        self.assertEqual(disc.getpixel((0, 0))[3], 0)                 # so does the corner, off the disc
        self.assertTrue(near(disc.getpixel((200, 330)), (20, 80, 200), 40), disc.getpixel((200, 330)))   # the cover
        self.assertTrue(near(disc.getpixel((200, 3)), RIM, 50), disc.getpixel((200, 3)))      # the rim over it
        rendered = m.render_disc(prof, m.Pictures(front=cover((20, 80, 200)).convert("RGBA"),
                                                  ctx={"title": "A Game"}), "Sony Playstation 2")
        self.assertEqual(rendered.getpixel((200, 200))[3], 0)
        generic = m.render_disc(prof, m.Pictures(ctx={"title": "No Cover", "lb_platform": PLATFORM}), PLATFORM)
        self.assertIsNotNone(generic)                                  # a generic cover goes under it too

    def test_missing_picture_falls_back(self):
        prof = dict(m.default_profile(), disc_kind="template", disc_template="Pack/Gone.png", disc_size=300)
        disc = m.make_disc(cover((20, 80, 200)).convert("RGBA"), prof, platform="Sony Playstation 2")
        self.assertEqual(disc.size, (300, 300))                        # the platform's own drawn disc (a DVD)
        self.assertEqual(m.disc_kind(prof, "Sony Playstation 2"), "template")
        full = dict(prof, disc_template=str(m.DISC_DIR / "Pack" / "Silver.png"))
        self.assertEqual(m.make_disc(cover((20, 80, 200)).convert("RGBA"), full).getpixel((150, 150))[3], 0)


class CartPictures(unittest.TestCase):
    def test_window_found(self):
        window = m.cart_window(framed_cart())
        self.assertIsNotNone(window)
        for got, want in zip(window, (50 / 300, 60 / 340, 250 / 300, 260 / 340)):
            self.assertAlmostEqual(got, want, delta=0.02)
        self.assertIsNone(m.cart_window(Image.new("RGBA", (200, 200), FRAME + (255,))))       # a solid cartridge
        label = m.find_cart_label(framed_cart())
        self.assertLess(label[0], 50 / 300)                            # a little bigger: under the frame
        self.assertGreater(label[2], 250 / 300)

    def test_cover_under_the_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "framed.png"
            framed_cart().save(path)
            left, top, right, bottom = m.find_cart_label(framed_cart())
            prof = dict(m.default_profile(), cart_donor=str(path), cart_label_l=left, cart_label_t=top,
                        cart_label_r=right, cart_label_b=bottom)
            made = m.generic_cart_front(prof, cover((200, 40, 40)))
            self.assertEqual(made.size, (300, 340))
            self.assertTrue(near(made.getpixel((150, 230)), (200, 40, 40)), made.getpixel((150, 230)))  # in it
            self.assertTrue(near(made.getpixel((30, 170)), FRAME), made.getpixel((30, 170)))            # frame
            self.assertEqual(made.getpixel((3, 3))[3], 0)                                               # outside
            self.assertEqual(made.getpixel((150, 59))[:3], FRAME)          # the frame stays over the cover's edge
            cart = m.render_cart(prof, m.Pictures(front=cover((200, 40, 40)).convert("RGBA")), "Nintendo DS", 300)
            self.assertEqual(cart.height, 300)


class Badges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = m.LOGO_DIR
        m.LOGO_DIR = Path(self.tmp.name) / "logo model"
        (m.LOGO_DIR / "Ratings").mkdir(parents=True)
        self.colours = {"Ratings/ESRB - T (Teen).png": (10, 160, 10), "Ratings/ESRB - E10+ (Everyone 10+).png":
                        (10, 10, 160), "Ratings/ESRB - E (Everyone).png": (160, 160, 10), "PEGI 16.png": (160, 10, 10)}
        for rel, colour in self.colours.items():
            Image.new("RGBA", (60, 80), colour + (255,)).save(m.LOGO_DIR / rel)

    def tearDown(self):
        m.LOGO_DIR = self.old
        self.tmp.cleanup()

    def colour(self, rating):
        pic = m.rating_badge(rating)
        return None if pic is None else pic.getpixel((30, 40))[:3]

    def test_found_by_rating(self):
        self.assertEqual(self.colour("T - Teen"), (10, 160, 10))
        self.assertEqual(self.colour("E10+ - Everyone 10+"), (10, 10, 160))
        self.assertEqual(self.colour("E - Everyone"), (160, 160, 10))           # not E10+
        self.assertEqual(self.colour("PEGI 16"), (160, 10, 10))
        for rating in ("", "RP - Rating Pending", "M - Mature", "Not Rated", None):
            self.assertIsNone(self.colour(rating), rating)

    def test_drawn_as_a_layer(self):
        layers = [{"kind": "rating", "size": 30.0, "x": 0.2, "y": 0.8, "rotation": 0.0, "opacity": 1.0}]
        canvas = Image.new("RGBA", (300, 400), (255, 255, 255, 255))
        m.draw_layers(canvas, layers, {"rating": "T - Teen"}, None)
        self.assertTrue(near(canvas.getpixel((60, 320)), (10, 160, 10)), canvas.getpixel((60, 320)))
        blank = Image.new("RGBA", (300, 400), (255, 255, 255, 255))
        m.draw_layers(blank, layers, {"rating": ""}, None)
        self.assertEqual(blank.getpixel((60, 320)), (255, 255, 255, 255))         # no rating: nothing


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.lb = make_lb(self.tmp.name, [("A Game", "")], {"Box - Front": [("", "A Game-01.png", cover((20, 80, 200)))]})
        self.old = (m.CONFIG_PATH, m.CACHE_DIR, m.MODEL_DIR, m.DISC_DIR, m.CART_DIR, m.LOGO_DIR)
        m.CONFIG_PATH, m.CACHE_DIR = tmp / "config.json", tmp / "cache"
        m.MODEL_DIR, m.DISC_DIR, m.CART_DIR, m.LOGO_DIR = (tmp / n for n in ("box model", "disc model", "cart model",
                                                                            "logo model"))
        case = Image.new("RGBA", (400, 560), (120, 120, 126, 255))
        case.paste((0, 0, 0, 0), (40, 40, 360, 520))
        for folder, rel, img in ((m.MODEL_DIR, "Pack/Case.png", case), (m.DISC_DIR, "Pack/Silver.png", disc_picture()),
                                 (m.CART_DIR, "Pack/Framed.png", framed_cart()),
                                 (m.LOGO_DIR, "Ratings/ESRB - T (Teen).png", Image.new("RGBA", (60, 80), (10, 160, 10, 255))),
                                 (m.LOGO_DIR, "Consoles/Console.png", Image.new("RGBA", (90, 30), (9, 9, 9, 255)))):
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            img.save(folder / rel)
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root), "yes": True})

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        m.CONFIG_PATH, m.CACHE_DIR, m.MODEL_DIR, m.DISC_DIR, m.CART_DIR, m.LOGO_DIR = self.old
        self.tmp.cleanup()

    def wait(self, cond, seconds=20.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_folders_in_the_window(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 1 and app.pics is not None), "game not shown")
        self.assertIn("Pack/Case.png", app.template_names())               # a template in a subfolder
        app.use_template("Pack/Case.png")
        self.assertEqual(app.cfg["custom_templates"], [])
        self.assertIsNotNone(app.template_img)
        self.assertTrue(m.valid_quad(app.quads["front"]))
        self.assertIn("Pack / Silver", app.disc_tpl_combo["values"])
        app.disc_tpl_combo.current(0)
        app.on_library_chosen("disc")
        self.assertEqual((app.profile["disc_kind"], app.profile["disc_template"]), ("template", "Pack/Silver.png"))
        app.draw()
        self.assertEqual(app.view, "disc")
        self.assertIn("Pack / Framed", app.cart_lib_combo["values"])
        app.cart_lib_combo.current(0)
        app.on_library_chosen("cart")
        self.assertTrue(app.profile["cart_donor"].endswith("Framed.png"))
        self.assertAlmostEqual(app.profile["cart_label_l"], 50 / 300 - 0.012, delta=0.02)
        self.assertEqual(app.cart_lib_var.get(), "Pack / Framed")
        values = list(app.logo_lib_combo["values"])
        self.assertEqual(values, ["Consoles / Console", "Ratings / ESRB - T (Teen)"])
        app.logo_lib_combo.current(0)
        app.add_library_logo()
        app.add_rating_badge()
        layers = app.profile["layers"][app.face]
        self.assertEqual(layers[-2]["path"], str(m.LOGO_DIR / "Consoles/Console.png"))
        self.assertEqual(layers[-1]["kind"], "rating")
        self.assertEqual(app.layer_list.get("end"), m.TEXTS["layer_rating"])
        app.draw()


if __name__ == "__main__":
    unittest.main()
