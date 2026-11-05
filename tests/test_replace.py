"""Replace keeps a picture someone else made when the new one would be made up: a game without a Box - Front keeps
its Box - 3D and Disc (only a box from a real cover, also one found on the web, takes their place), and a game
without a Cart - Front keeps its Cart - 3D (no cartridge from the cover in its place). The program's own pictures
are made again as before, and saving one game asks first.

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
from test_cart import cartridge  # noqa: E402
from test_engine import PLATFORM, cover, make_lb  # noqa: E402

EXPORT = {"region": "same", "existing": "replace", "format": "png", "jpg_bg": "#ffffff", "max_height": 300,
          "trim": True, "threads": 2}


def theirs(color=(90, 20, 20)):
    """A picture someone else made: no mark of this program."""
    return Image.new("RGBA", (300, 420), color + (255,))


class Batches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("Real Box", ""), ("Our Box", ""), ("With Cover", ""), ("Nothing", "")], {
            "Box - Front": [("", "With Cover-01.png", cover((20, 80, 200)))],
            "Box - 3D": [("", "Real Box-01.png", theirs()), ("", "With Cover-01.png", theirs((20, 90, 20)))],
            "Disc": [("", "Real Box-01.png", theirs((10, 10, 120)))]})
        self.boxes = self.lb.media_folder(PLATFORM, m.OUT_TYPE)
        m.save_picture(theirs((200, 200, 0)), self.boxes / "Our Box-01.png", None, None, self.lb.root, "png")
        self.lb.forget_indexes()
        self.games = self.lb.games(PLATFORM)
        self.prof = dict(m.default_profile(), web_covers="off")
        self.backup = self.lb.root / "Backups" / "test"

    def tearDown(self):
        self.tmp.cleanup()

    def run_batch(self, **export):
        return m.batch_make(self.lb, PLATFORM, self.games, self.prof, None, None, dict(EXPORT, **export),
                            threading.Event(), self.backup, 300)

    def backed_up(self):
        return sorted(p.name for p in self.backup.rglob("*.png")) if self.backup.exists() else []

    def test_marks(self):
        self.assertTrue(m.others_picture([self.boxes / "Real Box-01.png"]))
        self.assertFalse(m.others_picture([self.boxes / "Our Box-01.png"]))
        self.assertTrue(m.others_picture([self.boxes / "Our Box-01.png", self.boxes / "Real Box-01.png"]))
        self.assertFalse(m.others_picture([]))

    def test_box3d(self):
        real = (self.boxes / "Real Box-01.png").read_bytes()
        counts = self.run_batch()
        self.assertEqual((counts["kept"], counts["generic"], counts["saved"], counts["errors"]), (1, 2, 3, 0))
        self.assertEqual((self.boxes / "Real Box-01.png").read_bytes(), real)    # someone else's: kept as it was
        for title in ("Our Box", "With Cover", "Nothing"):                       # made (again) by the program
            self.assertTrue(m.made_here(self.boxes / f"{title}-01.png"), title)
        self.assertEqual(self.backed_up(), ["Our Box-01.png", "With Cover-01.png"])
        self.assertIn("kept (someone else's picture", m.TEXTS["batch_done"].format(platform=PLATFORM, **counts))

    def test_disc_and_box(self):
        discs = self.lb.media_folder(PLATFORM, m.DISC_TYPE)
        counts = self.run_batch(make_disc=True)
        self.assertEqual((counts["kept"], counts["generic"], counts["saved"], counts["discs"]), (1, 2, 3, 3))
        self.assertFalse(m.made_here(discs / "Real Box-01.png"))                 # its disc is kept too
        self.assertTrue(m.made_here(discs / "Our Box-01.png"))
        only_discs = self.run_batch(make_box=False, make_disc=True)
        self.assertEqual((only_discs["kept"], only_discs["discs"], only_discs["saved"]), (1, 3, 0))

    def test_next_adds(self):
        counts = self.run_batch(existing="next")
        self.assertEqual((counts["kept"], counts["generic"], counts["saved"]), (0, 3, 4))
        self.assertFalse(m.made_here(self.boxes / "Real Box-01.png"))            # still the first one shown
        self.assertTrue(m.made_here(self.boxes / "Real Box-02.png"))
        self.assertEqual(self.backed_up(), [])

    def test_without_generic_covers(self):
        counts = m.batch_make(self.lb, PLATFORM, self.games, dict(self.prof, generic_cover=False), None, None,
                              dict(EXPORT), threading.Event(), self.backup, 300)
        self.assertEqual((counts["kept"], counts["nofront"], counts["saved"]), (0, 3, 1))   # as before
        self.assertEqual(self.backed_up(), ["With Cover-01.png"])

    def test_plan(self):
        found = [self.lb.find(PLATFORM, g, self.prof) for g in self.games]
        self.assertEqual(m.batch_plan(found, "replace", True, True, (m.OUT_TYPE,)), (3, 1, 0, 2))    # Real Box kept
        self.assertEqual(m.batch_plan(found, "replace", True, True, (m.OUT_TYPE,), web=True),
                         (4, 0, 0, 3))                                   # the web may find its cover: planned
        self.assertEqual(m.batch_plan(found, "replace", True, True, (m.OUT_TYPE, m.DISC_TYPE)), (3, 1, 0, 2))
        self.assertEqual(m.batch_plan(found, "replace", True, False, (m.OUT_TYPE,)), (1, 0, 3, 0))   # as before
        self.assertEqual(m.batch_plan(found, "skip", True, True, (m.OUT_TYPE,)), (1, 3, 0, 1))
        self.assertEqual(m.batch_plan(found, "next", True, True, (m.OUT_TYPE,)), (4, 0, 0, 3))
        everything_ours = m.batch_plan(found, "replace", True, True, (m.OUT_TYPE,), ours=lambda paths: True)
        self.assertEqual(everything_ours, (4, 0, 0, 3))


class Carts(unittest.TestCase):
    def test_cart_from_the_cover_keeps_theirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            donor = Path(tmp) / "donor.png"
            cartridge().save(donor)
            prof = dict(m.default_profile(), cart_donor=str(donor), cart_label_l=0.225, cart_label_t=0.114,
                        cart_label_r=0.775, cart_label_b=0.684, web_covers="off")
            lb = make_lb(tmp, [("Their Cart", ""), ("Photo Cart", ""), ("New Cart", "")], {
                "Box - Front": [("", "Their Cart-01.png", cover((200, 30, 30))),
                                ("", "Photo Cart-01.png", cover((20, 60, 220))),
                                ("", "New Cart-01.png", cover((20, 160, 20)))],
                "Cart - Front": [("", "Photo Cart-01.png", cartridge())],
                "Cart - 3D": [("", "Their Cart-01.png", theirs()), ("", "Photo Cart-01.png", theirs((0, 0, 90)))]})
            games = lb.games(PLATFORM)
            found = [lb.find(PLATFORM, g, prof) for g in games]
            self.assertEqual(m.batch_plan(found, "replace", True, False, (m.CART_TYPE,), cart_cover=True),
                             (2, 1, 0, 0))
            self.assertEqual(m.batch_plan(found, "skip", True, False, (m.CART_TYPE,), cart_cover=True), (1, 2, 0, 0))
            backup = lb.root / "Backups" / "test"
            counts = m.batch_make(lb, PLATFORM, games, prof, None, None, dict(EXPORT, make_box=False, make_cart=True),
                                  threading.Event(), backup, 300)
            self.assertEqual((counts["carts"], counts["cartcovers"], counts["kept"], counts["errors"]), (2, 1, 1, 0))
            carts = lb.media_folder(PLATFORM, m.CART_TYPE)
            self.assertFalse(m.made_here(carts / "Their Cart-01.png"))          # kept: no cartridge photo of its own
            self.assertTrue(m.made_here(carts / "Photo Cart-01.png"))           # from its own photo: replaced
            self.assertTrue(m.made_here(carts / "New Cart-01.png"))             # from its cover: it had none
            self.assertEqual(sorted(p.name for p in backup.rglob("*.png")), ["Photo Cart-01.png"])


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("Real Box", ""), ("With Cover", "")], {
            "Box - Front": [("", "With Cover-01.png", cover((20, 80, 200)))],
            "Box - 3D": [("", "Real Box-01.png", theirs()), ("", "With Cover-01.png", theirs((20, 90, 20)))]})
        self.boxes = self.lb.media_folder(PLATFORM, m.OUT_TYPE)
        self.old = (m.CONFIG_PATH, m.CACHE_DIR, m.messagebox.askyesnocancel)
        m.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        m.CACHE_DIR = Path(self.tmp.name) / "cache"
        self.asked, self.answer = [], None

        def ask(_title, text, **_kw):
            self.asked.append(text)
            return self.answer

        m.messagebox.askyesnocancel = ask
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root), "yes": True})

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        m.CONFIG_PATH, m.CACHE_DIR, m.messagebox.askyesnocancel = self.old
        self.tmp.cleanup()

    def wait(self, cond, seconds=20.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_saving_one_game_asks(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 2 and app.pics is not None), "games not loaded")
        real, with_cover = (next(i for i, g in enumerate(app.games) if g.title == t) for t in ("Real Box", "With Cover"))
        app.profile["web_covers"] = "off"
        app.show_game(real)
        self.assertTrue(self.wait(lambda: app.pics is not None and app.current is app.games[real]), "game not shown")
        before = (self.boxes / "Real Box-01.png").read_bytes()
        for policy in ("replace", "skip"):                      # theirs, for a generic box: asked either way
            app.cfg["export"]["existing"] = policy
            app.save_one(False)
            self.assertEqual(len(self.asked), 1, policy)
            self.assertIn("made up", self.asked[0])
            self.assertIn("Real Box-01.png", self.asked[0])
            self.asked.clear()
        self.assertEqual((self.boxes / "Real Box-01.png").read_bytes(), before)    # Cancel: nothing done
        app.cfg["export"]["existing"] = "replace"
        self.answer = False                                       # No: added as the next picture
        app.save_one(False)
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Saved")), app.status_text)
        self.assertTrue(m.made_here(self.boxes / "Real Box-02.png"))
        self.assertEqual((self.boxes / "Real Box-01.png").read_bytes(), before)
        self.asked.clear()
        app.show_game(with_cover)                                 # a real cover: replaced without a question
        self.assertTrue(self.wait(lambda: app.pics is not None and app.current is app.games[with_cover]),
                        "game not shown")
        app.save_one(False)
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Saved")), app.status_text)
        self.assertEqual(self.asked, [])
        self.assertTrue(m.made_here(self.boxes / "With Cover-01.png"))


if __name__ == "__main__":
    unittest.main()
