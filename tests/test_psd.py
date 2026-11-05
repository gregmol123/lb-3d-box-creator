"""Photoshop templates: a .psd case template is listed and opened through its merged picture (with its transparency),
and one without a merged picture is refused with a message instead of showing blank.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
"""
import struct
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lb_box3d_creator as m  # noqa: E402
from PIL import Image  # noqa: E402
from test_engine import make_lb  # noqa: E402


def write_psd(path, img):
    """A minimal Photoshop file: RGB with transparency, the merged picture uncompressed, no layers."""
    img = img.convert("RGBA")
    w, h = img.size
    header = b"8BPS" + struct.pack(">H6xHIIHH", 1, 4, h, w, 8, 3) + struct.pack(">I", 0) * 3
    Path(path).write_bytes(header + struct.pack(">H", 0) + b"".join(band.tobytes() for band in img.split()))


def case(size=(400, 560)):
    """An empty case: a grey rim round a see-through cover window."""
    w, h = size
    img = Image.new("RGBA", size, (120, 120, 126, 255))
    img.paste((0, 0, 0, 0), (40, 40, w - 40, h - 40))
    return img


class Opening(unittest.TestCase):
    def test_merged_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case.psd"
            write_psd(path, case())
            img = m.open_template(path)
            self.assertEqual((img.mode, img.size), ("RGBA", (400, 560)))
            self.assertEqual((img.getpixel((10, 10)), img.getpixel((200, 280))[3]), ((120, 120, 126, 255), 0))
            quads = m.detect_quads(img)                                   # its window is found like a PNG's
            self.assertTrue(m.valid_quad(quads["front"]))
            self.assertEqual(m.load_picture(path).mode, "RGBA")           # any picture can be a .psd too

    def test_no_merged_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "layers only.psd"
            write_psd(path, Image.new("RGBA", (200, 100), (255, 255, 255, 255)))     # blank: nothing merged
            with self.assertRaises(ValueError) as caught:
                m.open_template(path)
            self.assertIn("Maximize compatibility", str(caught.exception))
            png = Path(tmp) / "white.png"
            Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(png)
            self.assertEqual(m.open_template(png).size, (200, 100))       # a PNG is never refused


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("A Game", "")], {})
        self.models = Path(self.tmp.name) / "box model"
        self.models.mkdir()
        write_psd(self.models / "Case.psd", case())
        write_psd(self.models / "Blank.psd", Image.new("RGBA", (50, 50), (255, 255, 255, 255)))
        self.old = (m.CONFIG_PATH, m.MODEL_DIR)
        m.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        m.MODEL_DIR = self.models
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root), "yes": True})

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        m.CONFIG_PATH, m.MODEL_DIR = self.old
        self.tmp.cleanup()

    def test_listed_and_used(self):
        app = self.app
        self.assertIn("Case.psd", app.template_names())
        app.profile["template"] = "Case.psd"
        app.load_template()
        self.assertIsNotNone(app.template_img)
        self.assertTrue(m.valid_quad(app.quads["front"]))
        app.draw()
        app.profile["template"] = "Blank.psd"
        app.load_template()
        self.assertIsNone(app.template_img)
        self.assertIn("Maximize compatibility", app.status_text)


if __name__ == "__main__":
    unittest.main()
