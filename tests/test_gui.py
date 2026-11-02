"""The window with a made-up LaunchBox folder: platform, game list, preview, saving one box, a whole platform.

Run: python -m unittest discover -s tests   (needs a desktop; the window shows for a few seconds)
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
from test_engine import PLATFORM, cover, make_lb  # noqa: E402


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("First: Game", "Europe"), ("Second Game", "")], {
            "Box - Front": [("Europe", "First_ Game-01.png", cover((20, 80, 200))),
                            ("", "Second Game-01.png", cover((200, 30, 30)))]})
        self.old_config = m.CONFIG_PATH
        m.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root)})

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

    def test_flow(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        self.assertEqual(list(app.plat_combo["values"]), [PLATFORM])
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: len(app.games) == 2), "games not loaded")
        self.assertEqual(len(app.tree.get_children()), 2)
        self.assertTrue(self.wait(lambda: app.pics is not None), "first game not shown")
        app.draw()
        self.assertIsNotNone(app.photo)
        self.assertTrue(app.shown_quads.get("front"))
        app.save_one(False)
        self.assertTrue(self.wait(lambda: app.status_text.startswith("Saved")), app.status_text)
        out = self.lb.media_folder(PLATFORM, m.OUT_TYPE)
        self.assertEqual(len(list(out.rglob("*.png"))), 1)
        app.options["yes"] = True                      # no confirmation / summary dialogs
        app.make_boxes("all")
        self.assertTrue(app.batch_running)
        self.assertTrue(self.wait(lambda: not app.batch_running), "batch did not finish")
        self.assertIn("1", app.status_text)            # saved 1 (the other game already had its box)
        self.assertEqual(len(list(out.rglob("*.png"))), 2)
        self.assertTrue(self.wait(lambda: all(f.get("box3d") for f in app.found.values())), "statuses not refreshed")
        app.build()                                    # the window built again keeps the list
        self.assertEqual(len(app.tree.get_children()), 2)
        app.profile["template"] = "box3d-dvd.png"
        app.load_template()
        if app.template_img is not None:
            self.assertTrue(m.valid_quad(app.quads["front"]))
            app.draw()
            self.assertIsNotNone(app.photo)
        app.undo()


if __name__ == "__main__":
    unittest.main()
