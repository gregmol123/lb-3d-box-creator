"""Sharper small covers: the upscale models of a made-up Forge/A1111 and ComfyUI on 127.0.0.1, the choice of model,
the cache, what happens with no server or no model, the covers of a made-up LaunchBox folder and the window's button.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
"""
import base64
import io
import json
import socket
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
from test_ai import A1111, Comfy, png, serve  # noqa: E402
from test_engine import PLATFORM, cover, make_lb  # noqa: E402

UPSCALERS = ["None", "Lanczos", "Nearest", "R-ESRGAN 4x+ Anime6B", "R-ESRGAN 4x+", "4x-UltraSharp"]


class A1111Up(A1111):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/sdapi/v1/upscalers":
            self.server.calls.append(("GET", path))
            return self.send(200, [{"name": n, "model_name": None, "scale": 4} for n in self.server.upscalers])
        return super().do_GET()

    def do_POST(self):
        srv, path = self.server, self.path.split("?")[0]
        if path != "/sdapi/v1/extra-single-image":
            return super().do_POST()
        payload = srv.last = json.loads(self.body())
        srv.calls.append(("POST", path))
        if srv.fail:
            return self.send(500, {"error": "OutOfMemoryError", "detail": "CUDA out of memory"})
        img = Image.open(io.BytesIO(base64.b64decode(payload["image"])))
        s = float(payload["upscaling_resize"])
        big = img.resize((round(img.width * s), round(img.height * s)), Image.BICUBIC)
        return self.send(200, {"image": base64.b64encode(png(big)).decode(), "html_info": ""})


class ComfyUp(Comfy):
    def do_GET(self):
        srv, path = self.server, self.path.split("?")[0]
        if path == "/object_info/UpscaleModelLoader":
            srv.calls.append(("GET", path))
            spec = ["COMBO", {"options": srv.upscalers}] if srv.new_combo else [srv.upscalers, {}]
            return self.send(200, {"UpscaleModelLoader": {"input": {"required": {"model_name": spec}}}})
        if path == "/view":
            srv.calls.append(("GET", path))
            img = srv.uploaded
            return self.send(200, raw=png(img.resize((img.width * 4, img.height * 4))), ctype="image/png")
        return super().do_GET()

    def do_POST(self):
        srv, path = self.server, self.path.split("?")[0]
        if path != "/prompt":
            return super().do_POST()
        graph = srv.graph = json.loads(self.body())["prompt"]
        srv.calls.append(("POST", path))
        if graph.get("2", {}).get("class_type") != "UpscaleModelLoader":
            return self.send(400, {"error": {"message": "not an upscale job"}})
        srv.ready_at = time.time() + srv.delay
        return self.send(200, {"prompt_id": "job-1", "number": 1, "node_errors": {}})


def a1111_up(**attrs):
    return serve(A1111Up, **{"api": True, "current": "", "preview": None, "last": None, "drop": 0,
                             "upscalers": UPSCALERS, "fail": False, **attrs})


def comfy_up(**attrs):
    return serve(ComfyUp, **{"models": [], "new_combo": True, "ready_at": 0.0, "uploaded": None, "graph": None,
                             "upscalers": ["4x-UltraSharp.pth", "RealESRGAN_x4plus_anime_6B.pth"], **attrs})


def posts(srv, path="/sdapi/v1/extra-single-image"):
    return [c for c in srv.calls if c == ("POST", path)]


class Choice(unittest.TestCase):
    def test_pick_upscaler(self):
        names = ["R-ESRGAN 4x+ Anime6B", "R-ESRGAN 4x+", "4x-UltraSharp"]
        self.assertEqual(m.pick_upscaler(names), "4x-UltraSharp")
        self.assertEqual(m.pick_upscaler(names[:2]), "R-ESRGAN 4x+")                  # never the anime one
        self.assertEqual(m.pick_upscaler(names, "R-ESRGAN 4x+ Anime6B"), "R-ESRGAN 4x+ Anime6B")   # chosen
        self.assertEqual(m.pick_upscaler(names, "gone.pth"), "4x-UltraSharp")
        self.assertEqual(m.pick_upscaler(["SwinIR_4x"]), "SwinIR_4x")
        self.assertEqual(m.pick_upscaler(["LDSR"]), "LDSR")                            # else the first
        self.assertEqual(m.pick_upscaler([]), "")


class Servers(unittest.TestCase):
    def setUp(self):
        self.servers = []

    def tearDown(self):
        for srv in self.servers:
            srv.shutdown()
            srv.server_close()

    def start(self, maker, **attrs):
        srv, url = maker(**attrs)
        self.servers.append(srv)
        return srv, url

    def test_a1111(self):
        srv, url = self.start(a1111_up)
        server = m.AIServer.detect(url)
        self.assertEqual(server.upscalers(), ["R-ESRGAN 4x+ Anime6B", "R-ESRGAN 4x+", "4x-UltraSharp"])
        big = server.upscale(Image.new("RGBA", (60, 90), (10, 20, 30, 255)), "4x-UltraSharp", 4.0)
        self.assertEqual(big.size, (240, 360))
        self.assertEqual((srv.last["upscaler_1"], srv.last["upscaling_resize"], srv.last["resize_mode"]),
                         ("4x-UltraSharp", 4.0, 0))

    def test_comfy(self):
        for new_combo in (True, False):
            srv, url = self.start(comfy_up, new_combo=new_combo)
            server = m.AIServer.detect(url)
            self.assertEqual(server.upscalers(), srv.upscalers)
        big = server.upscale(Image.new("RGB", (50, 70), (200, 10, 10)), "4x-UltraSharp.pth")
        self.assertEqual(big.size, (200, 280))
        self.assertEqual(srv.graph["2"]["inputs"]["model_name"], "4x-UltraSharp.pth")
        self.assertEqual(srv.graph["3"]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(srv.graph["4"]["class_type"], "PreviewImage")    # nothing lands in ComfyUI's output


class Upscaling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cache = m.CACHE_DIR
        m.CACHE_DIR = Path(self.tmp.name) / "cache"
        self.servers = []
        self.prof = dict(m.default_profile(), upscale=True, upscale_below=800)

    def tearDown(self):
        m.CACHE_DIR = self.old_cache
        for srv in self.servers:
            srv.shutdown()
            srv.server_close()
        self.tmp.cleanup()

    def start(self, maker, **attrs):
        srv, url = maker(**attrs)
        self.servers.append(srv)
        up = m.Upscaler()
        up.configure(url)
        return srv, up

    def test_small_cover_made_bigger_once(self):
        srv, up = self.start(a1111_up)
        small = Image.new("RGBA", (100, 150), (20, 80, 200, 255))
        self.assertIs(up.apply(small, None, dict(self.prof, upscale=False)), small)      # off
        self.assertIs(up.apply(small, None, dict(self.prof, upscale_below=150)), small)  # big enough
        self.assertEqual(posts(srv), [])
        big = up.apply(small, None, self.prof)
        self.assertEqual((big.size, big.mode), ((400, 600), "RGBA"))
        self.assertEqual(srv.last["upscaler_1"], "4x-UltraSharp")
        kept = list(m.CACHE_DIR.glob("up-*-4x_UltraSharp.jpg"))
        self.assertEqual(len(kept), 1)
        again = up.apply(small, None, self.prof)                     # from the cache folder
        self.assertEqual(again.size, (400, 600))
        self.assertEqual(len(posts(srv)), 1)
        chosen = up.apply(small, None, dict(self.prof, upscale_model="R-ESRGAN 4x+"))   # another model: made again
        self.assertEqual((chosen.size, srv.last["upscaler_1"], len(posts(srv))), ((400, 600), "R-ESRGAN 4x+", 2))
        self.assertTrue(list(m.CACHE_DIR.glob("up-*-R_ESRGAN_4x_.jpg")))
        self.assertFalse(list(m.CACHE_DIR.glob("*.tmp")))

    def test_sizes(self):
        srv, up = self.start(a1111_up)
        path = Path(self.tmp.name) / "front.png"
        cover((20, 80, 200), (600, 900)).save(path)
        with Image.open(path) as im:
            img = im.convert("RGBA")
        out = up.apply(img, str(path), dict(self.prof, upscale_below=1000))
        self.assertEqual((srv.last["upscaling_resize"], out.size), (2.0, (1200, 1800)))   # x4 would be too big
        digest = m.file_sha(path)[7:23]
        self.assertTrue(list(m.CACHE_DIR.glob(f"up-{digest}-*.jpg")))                    # kept by the file's sha
        tall = Image.new("RGBA", (500, 700), "white")
        self.assertEqual(up.apply(tall, None, self.prof).size, (1714, 2400))              # 2800 high: made smaller

    def test_nothing_to_upscale_with(self):
        small = Image.new("RGBA", (100, 150), "red")
        srv, up = self.start(a1111_up, upscalers=["None", "Lanczos", "Nearest"])
        self.assertIs(up.apply(small, None, self.prof), small)
        self.assertEqual(up.note, m.TEXTS["up_no_model"])
        srv.fail = True
        srv.upscalers = UPSCALERS
        _srv2, up2 = self.start(a1111_up, fail=True)
        self.assertIs(up2.apply(small, None, self.prof), small)
        self.assertIn("out of memory", up2.note.lower())
        self.assertIsNone(up2.server)                                # asked again next time
        _srv3, up3 = self.start(a1111_up, api=False)
        self.assertIs(up3.apply(small, None, self.prof), small)      # a web UI started without --api
        self.assertIn("--api", up3.note)
        calls = len(_srv3.calls)
        self.assertIs(up3.apply(small, None, self.prof), small)
        self.assertEqual(len(_srv3.calls), calls)                     # not asked again for a minute

    def test_no_server(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        up = m.Upscaler()
        up.configure(f"127.0.0.1:{port}")
        small = Image.new("RGBA", (100, 150), "red")
        self.assertIs(up.apply(small, None, self.prof), small)
        self.assertIn(str(port), up.note)
        start = time.time()
        self.assertIs(up.apply(small, None, self.prof), small)
        self.assertLess(time.time() - start, 0.5)                    # not on every game of a batch

    def test_address_from_the_window(self):
        srv, url = a1111_up()
        self.servers.append(srv)
        up = m.Upscaler()
        up.resolver = lambda: url
        self.assertEqual(up.apply(Image.new("RGBA", (100, 150), "red"), None, self.prof).size, (400, 600))

    def test_comfy_and_launchbox_covers(self):
        srv, url = comfy_up()
        self.servers.append(srv)
        old = m.UPSCALER
        m.UPSCALER = m.Upscaler()
        m.UPSCALER.configure(url)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                lb = make_lb(tmp, [("Small Cover", ""), ("Big Cover", "")], {"Box - Front": [
                    ("", "Small Cover-01.png", cover((20, 80, 200), (120, 170))),
                    ("", "Big Cover-01.png", cover((200, 30, 30), (600, 850)))]})
                small, big = lb.games(PLATFORM)
                pics, _ = m.load_pictures(lb, PLATFORM, small, self.prof)
                self.assertEqual(pics.front.size, (480, 680))
                pics, _ = m.load_pictures(lb, PLATFORM, big, self.prof)
                self.assertEqual(pics.front.size, (600, 850))
                self.assertEqual(len(posts(srv, "/prompt")), 1)
                pics, _ = m.load_pictures(lb, PLATFORM, small, dict(self.prof, upscale=False))
                self.assertEqual(pics.front.size, (120, 170))
        finally:
            m.UPSCALER = old


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.srv, self.url = a1111_up()
        self.old = (m.CONFIG_PATH, m.CACHE_DIR, m.UPSCALER)
        m.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        m.CACHE_DIR = Path(self.tmp.name) / "cache"
        m.CONFIG_PATH.write_text(json.dumps({"ai": {"url": self.url}}), encoding="utf-8")
        m.UPSCALER = m.Upscaler()
        self.lb = make_lb(self.tmp.name, [("Small Cover", "")],
                          {"Box - Front": [("", "Small Cover-01.png", cover((20, 80, 200), (120, 170)))]})
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root), "yes": True})

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        m.CONFIG_PATH, m.CACHE_DIR, m.UPSCALER = self.old
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def wait(self, cond, seconds=20.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_models_and_preview(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        self.assertEqual(m.UPSCALER.url, self.url)
        app.refresh_upscalers()
        self.assertTrue(self.wait(lambda: "4x-UltraSharp" in app.up_model_combo["values"]), "models not listed")
        self.assertIn("3 upscale models", app.up_label["text"])
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: app.pics is not None), "game not shown")
        self.assertEqual(app.pics.front.size, (120, 170))
        app.profile["upscale"] = True
        app.setting_changed("profile", "upscale")
        self.assertTrue(self.wait(lambda: app.pics is not None and app.pics.front.size == (480, 680)),
                        "cover not upscaled")


if __name__ == "__main__":
    unittest.main()
