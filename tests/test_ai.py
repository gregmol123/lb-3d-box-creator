"""AI templates: the drawing, the cut-out, the servers (made-up Forge/A1111 and ComfyUI on 127.0.0.1), Stability
Matrix's settings, and the AI window from first click to a saved template.

Run: python -m unittest discover -s tests   (the window test needs a desktop)
"""
import base64
import io
import json
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lb_box3d_creator as m  # noqa: E402
from PIL import Image, ImageChops, ImageDraw  # noqa: E402
from test_engine import PLATFORM, cover, make_lb  # noqa: E402

MODELS = ["juggernautXL_v9.safetensors [abc123]", "dreamshaperXL_lightning.safetensors [def456]"]


def painted(img):
    """What the made-up servers send back: the picture a bit lighter, with a white streak (a reflection)."""
    out = Image.eval(img.convert("RGB"), lambda v: min(255, v + 12))
    d = ImageDraw.Draw(out, "RGBA")
    w, h = out.size
    d.polygon([(0, h * 0.25), (w, h * 0.10), (w, h * 0.16), (0, h * 0.31)], fill=(255, 255, 255, 140))
    return out


def png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, obj=None, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))


class A1111(Handler):
    """Forge / SD.Next / Automatic1111 started with --api (the parts this program uses)."""

    def do_GET(self):
        srv, path = self.server, self.path.split("?")[0]
        srv.calls.append(("GET", path))
        if not srv.api:
            return self.send(404, {"detail": "Not Found"})
        if path == "/sdapi/v1/progress":
            live = "skip_current_image=false" in self.path
            return self.send(200, {"progress": 0.5, "current_image": srv.preview if live else None})
        if path == "/sdapi/v1/sd-models":
            return self.send(200, [{"title": t, "model_name": t.split(".")[0]} for t in MODELS])
        if path == "/sdapi/v1/options":
            return self.send(200, {"sd_model_checkpoint": srv.current})
        if path == "/sdapi/v1/samplers":
            return self.send(200, [{"name": n} for n in ("Euler a", "DPM++ 2M", "DPM++ SDE")])
        if path == "/sdapi/v1/schedulers":
            return self.send(200, [{"name": "automatic", "label": "Automatic"}, {"name": "karras", "label": "Karras"}])
        return self.send(404, {"detail": "Not Found"})

    def do_POST(self):
        srv, path = self.server, self.path.split("?")[0]
        data = self.body()
        srv.calls.append(("POST", path))
        if path == "/sdapi/v1/options":
            srv.current = json.loads(data)["sd_model_checkpoint"]
            return self.send(200, None)
        if path == "/sdapi/v1/interrupt":
            srv.interrupted = True
            return self.send(200, None)
        if path == "/sdapi/v1/img2img":
            payload = srv.last = json.loads(data)
            if srv.drop > 0:                    # the reply cut short, as a busy web UI on Windows sometimes does
                srv.drop -= 1
                body = json.dumps({"images": ["A" * 5000]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body[:100])
                self.close_connection = True
                return
            end = time.time() + srv.delay
            while time.time() < end and not srv.interrupted:
                time.sleep(0.05)
            guide = Image.open(io.BytesIO(base64.b64decode(payload["init_images"][0])))
            return self.send(200, {"images": [base64.b64encode(png(painted(guide))).decode()], "info": "{}"})
        return self.send(404, {"detail": "Not Found"})


class Comfy(Handler):
    """ComfyUI's HTTP API (the parts this program uses)."""

    def do_GET(self):
        srv, path = self.server, self.path.split("?")[0]
        srv.calls.append(("GET", path))
        if path == "/system_stats":
            return self.send(200, {"system": {"comfyui_version": "0.36.0", "os": "nt"}, "devices": []})
        if path == "/object_info/CheckpointLoaderSimple":
            spec = (["COMBO", {"options": srv.models}] if srv.new_combo else [srv.models, {}])
            return self.send(200, {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": spec}}}})
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[-1]
            if pid != "job-1" or time.time() < srv.ready_at:
                return self.send(200, {})
            return self.send(200, {pid: {"outputs": {"8": {"images": [{"filename": "LB3D_0001.png", "subfolder": "",
                                                                         "type": "temp"}]}},
                                         "status": {"status_str": "success", "completed": True, "messages": []}}})
        if path == "/view":
            return self.send(200, raw=png(painted(srv.uploaded)), ctype="image/png")
        if path == "/queue":
            return self.send(200, {"queue_running": [], "queue_pending": []})
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        srv, path = self.server, self.path.split("?")[0]
        data = self.body()
        srv.calls.append(("POST", path))
        if path == "/upload/image":
            start = data.index(b"\x89PNG")
            end = data.index(b"\r\n--", start)
            srv.uploaded = Image.open(io.BytesIO(data[start:end])).convert("RGB")
            srv.upload_fields = data[:start]
            return self.send(200, {"name": "lb3d_guide.png", "subfolder": "", "type": "input"})
        if path == "/prompt":
            graph = srv.graph = json.loads(data)["prompt"]
            name = graph["1"]["inputs"]["ckpt_name"]
            if name not in srv.models:
                return self.send(400, {"error": {"type": "prompt_outputs_failed_validation",
                                                 "message": "Prompt outputs failed validation"},
                                       "node_errors": {"1": {"errors": [{"message": "Value not in list",
                                                                         "details": f"ckpt_name: '{name}'"}]}}})
            srv.ready_at = time.time() + srv.delay
            return self.send(200, {"prompt_id": "job-1", "number": 1, "node_errors": {}})
        if path in ("/queue", "/interrupt"):
            return self.send(200, {})
        return self.send(404, {"error": "not found"})


def serve(handler, **attrs):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    srv.calls, srv.delay, srv.interrupted = [], 0.0, False
    for k, v in attrs.items():
        setattr(srv, k, v)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def a1111(**attrs):
    preview = base64.b64encode(png(Image.new("RGB", (64, 96), (90, 90, 90)))).decode()
    return serve(A1111, **{"api": True, "current": MODELS[0], "preview": preview, "last": None, "drop": 0, **attrs})


def comfy(**attrs):
    return serve(Comfy, **{"models": ["sdxl\\juggernautXL_v9.safetensors", "flux_dev.safetensors"],
                           "new_combo": True, "ready_at": 0.0, "uploaded": None, "graph": None, **attrs})


class Drawing(unittest.TestCase):
    def test_every_kind_of_case(self):
        for case in m.AI_CASES:
            guide, outline, windows = m.ai_guide(case, base=768)
            self.assertEqual((guide.width % 64, guide.height % 64), (0, 0), case)
            self.assertLess(abs(guide.width * guide.height / 768 ** 2 - 1), 0.15, case)
            for face in m.FACES:
                quad = windows[face]
                self.assertTrue(m.valid_quad(quad), (case, face))
                cx, cy = sum(p[0] for p in quad) / 4, sum(p[1] for p in quad) / 4
                self.assertEqual(outline.getpixel((int(cx), int(cy))), 255, (case, face))
            self.assertEqual(outline.getpixel((2, 2)), 0)

    def test_window_sits_inside_the_rim(self):
        art = Image.new("RGBA", (400, 560), (10, 200, 10, 255))
        face = m.case_face(art, "front", "#ff0000", 0.03)
        x0, y0, x1, y1 = m.case_window("front", face.size, 0.03)
        self.assertEqual(face.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))[:3], (10, 200, 10))
        self.assertEqual(face.getpixel(((x0 + x1) // 2, max(0, y0 - 6)))[:3], (255, 0, 0))
        self.assertEqual(face.getpixel((x0 + 1, y0 + 1))[3], 255)      # the line round the art is not see-through

    def test_painting_becomes_a_template(self):
        guide, outline, windows = m.ai_guide(base=768)
        tpl, quads = m.ai_template(painted(guide), outline, windows, 1.0, 1200)
        self.assertEqual(tpl.height, 1200)
        self.assertEqual(tpl.getpixel((1, 1))[3], 0)                   # the studio background is gone
        self.assertTrue(m.see_through(tpl, quads["front"]))            # so the light layer is used by itself
        alphas = list(tpl.getchannel("A").crop(tuple(map(int, (
            min(p[0] for p in quads["front"]), min(p[1] for p in quads["front"]),
            max(p[0] for p in quads["front"]), max(p[1] for p in quads["front"]))))).tobytes())
        self.assertGreater(max(alphas), 60)                            # the painted reflection stays
        self.assertLess(sorted(alphas)[len(alphas) // 2], 40)          # the rest of the cover is see-through
        rim = m.sub_quad(quads["front"], (100, 100), (-1, 50, -1, 50))[0]   # just left of the cover window
        self.assertGreater(tpl.getpixel((int(rim[0]) - 2, int(rim[1])))[3], 200)
        base = Image.new("RGBA", (600, 850), (30, 60, 200, 255))
        box, _ = m.render_box(m.default_profile(), tpl, quads, m.Pictures(front=base))
        self.assertEqual(box.size, tpl.size)

    def test_saved_with_its_corners(self):
        guide, outline, windows = m.ai_guide(base=768)
        tpl, quads = m.ai_template(guide, outline, windows, 1.0, 900)
        with tempfile.TemporaryDirectory() as tmp:
            first = m.save_ai_template(tpl, quads, "AI DVD: case?", {"seed": 7}, tmp)
            second = m.save_ai_template(tpl, quads, "AI DVD: case?", {"seed": 8}, tmp)
            self.assertEqual(first.name, "AI DVD_ case_.png")
            self.assertEqual(second.name, "AI DVD_ case_ 2.png")
            back = m.profile_quads(first, tpl.size)
            for face in m.FACES:
                for a, b in zip(back[face], quads[face]):
                    self.assertLess(m.dist(a, b), 0.75)
            data = json.loads(first.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(data["ai"]["seed"], 7)
            self.assertEqual(data["template_size"], {"width": tpl.width, "height": tpl.height})
            self.assertFalse(list(Path(tmp).glob("*.tmp")))

    def test_repaint_a_template(self):
        path = m.APP_DIR / "box model" / "box3d-dvd.png"
        if not path.is_file():
            self.skipTest("box3d-dvd.png not in box model")
        tpl = m.load_picture(path)
        quads = m.template_quads(path, tpl)
        guide, outline, windows = m.ai_guide_from_template(tpl, quads, 768)
        q = windows["front"]
        cx, cy = sum(p[0] for p in q) / 4, sum(p[1] for p in q) / 4
        self.assertEqual(guide.getpixel((int(cx), int(cy))), m.AI_COVER)   # the window painted as a blank cover
        self.assertEqual(outline.getpixel((int(cx), int(cy))), 255)
        made, mq = m.ai_template(painted(guide), outline, windows, 1.0, 1000)
        self.assertTrue(m.valid_quad(mq["front"]) and m.valid_quad(mq["spine"]))

    def test_settings_are_checked(self):
        cfg = {"ai": {"case": "nope", "size": 999, "steps": "x", "strength": 0.4, "preview": "bad", "url": 5}}
        s = m.ai_settings(cfg)
        self.assertEqual((s["case"], s["size"], s["steps"], s["strength"], s["preview"], s["url"]),
                         (m.AI_DEFAULT_CASE, 1024, 28, 0.4, "box", ""))
        self.assertIs(cfg["ai"], s)

    def test_model_choice(self):
        names = ["inpaintSDXLPony.safetensors", "flux_dev.safetensors", "juggernautXL_ragnarokBy.safetensors"]
        self.assertEqual(m.ai_default_model(names), "juggernautXL_ragnarokBy.safetensors")
        self.assertEqual(m.ai_default_model(names, "flux_dev.safetensors"), "flux_dev.safetensors")
        self.assertTrue(m.ai_fast_model("dreamshaperXL_lightningDPMSDE"))
        self.assertFalse(m.ai_fast_model("juggernautXL"))


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

    def test_nothing_there(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        start = time.time()
        self.assertIsNone(m.AIServer.detect(f"127.0.0.1:{port}"))
        self.assertLess(time.time() - start, 5)

    def test_web_ui_without_api(self):
        _srv, url = self.start(a1111, api=False)
        with self.assertRaises(m.AIError):
            m.AIServer.detect(url)

    def test_a1111(self):
        srv, url = self.start(a1111, delay=1.6)
        server = m.AIServer.detect(url)
        self.assertEqual(server.kind, "a1111")
        names, current = server.models()
        self.assertEqual((names, current), (MODELS, MODELS[0]))
        self.assertEqual(server.sampler_for(MODELS[0]), ("DPM++ 2M", "Karras"))
        self.assertEqual(server.sampler_for(MODELS[1]), ("DPM++ SDE", "Karras"))
        server.set_model(MODELS[1])
        self.assertEqual(srv.current, MODELS[1])
        guide, _outline, _windows = m.ai_guide(base=512)
        seen = []
        picture = server.img2img(guide, "a case", "text", model=MODELS[1], strength=0.45, steps=8, cfg=2.0, seed=42,
                                 progress=lambda f, p: seen.append((f, p)))
        self.assertEqual(picture.size, guide.size)
        self.assertTrue(seen and seen[0][0] == 0.5 and seen[0][1] is not None)
        sent = srv.last
        self.assertEqual((sent["width"], sent["height"]), guide.size)
        self.assertEqual((sent["denoising_strength"], sent["seed"], sent["sampler_name"], sent["scheduler"]),
                         (0.45, 42, "DPM++ SDE", "Karras"))
        self.assertFalse(sent["save_images"])

    def test_a1111_dropped_reply(self):
        srv, url = self.start(a1111, drop=1)
        server = m.AIServer.detect(url)
        server.models()
        guide = m.ai_guide(base=512)[0]
        picture = server.img2img(guide, "p", "n", model=MODELS[0], strength=0.5, steps=8, cfg=5, seed=3)
        self.assertEqual(picture.size, guide.size)                      # asked once more and got it
        self.assertEqual(srv.calls.count(("POST", "/sdapi/v1/img2img")), 2)
        srv.drop = 2
        with self.assertRaises(m.AIError) as ctx:                       # but not for ever
            server.img2img(guide, "p", "n", model=MODELS[0], strength=0.5, steps=8, cfg=5, seed=3)
        self.assertTrue(m._dropped(ctx.exception))
        self.assertEqual(srv.calls.count(("POST", "/sdapi/v1/img2img")), 4)

    def test_loaded_model_names(self):
        srv, url = self.start(a1111, current="sd\\juggernautXL_v9.safetensors")    # Forge: folder, no [hash]
        server = m.AIServer.detect(url)
        names, current = server.models()
        self.assertEqual(m.ai_default_model(names, current), MODELS[0])
        self.assertTrue(server.has_loaded(MODELS[0]))
        self.assertFalse(server.has_loaded(MODELS[1]))
        server.set_model(MODELS[0])                                     # already loaded: nothing sent
        self.assertNotIn(("POST", "/sdapi/v1/options"), srv.calls)
        self.assertEqual(m.model_key("SDXL\\juggernautXL_v9.safetensors [abc123]"), "juggernautxl_v9")
        self.assertFalse(m._dropped(m.AIError("x")))

    def test_a1111_stop(self):
        srv, url = self.start(a1111, delay=8)
        server = m.AIServer.detect(url)
        server.models()
        stop = threading.Event()

        def press_stop():
            stop.set()
            server.interrupt()

        threading.Timer(0.6, press_stop).start()
        start = time.time()
        with self.assertRaises(m.AIStopped):
            server.img2img(m.ai_guide(base=512)[0], "p", "n", model=MODELS[0], strength=0.5, steps=20, cfg=6, seed=1,
                           stop=stop)
        self.assertTrue(srv.interrupted)
        self.assertLess(time.time() - start, 5)

    def test_comfy(self):
        srv, url = self.start(comfy, delay=0.8)
        server = m.AIServer.detect(url)
        self.assertEqual((server.kind, server.name), ("comfy", "ComfyUI 0.36.0"))
        names, current = server.models()
        self.assertEqual((names, current), (srv.models, ""))
        guide = m.ai_guide(base=512)[0]
        ticks = []
        picture = server.img2img(guide, "a case", "text", model=srv.models[0], strength=0.5, steps=20, cfg=6.0,
                                 seed=9, progress=lambda f, p: ticks.append(f))
        self.assertEqual(picture.size, guide.size)
        self.assertEqual(srv.uploaded.size, guide.size)
        self.assertIn(b'name="overwrite"', srv.upload_fields)
        sampler = srv.graph["6"]["inputs"]
        self.assertEqual((sampler["denoise"], sampler["seed"], sampler["sampler_name"], sampler["scheduler"]),
                         (0.5, 9, "dpmpp_2m", "karras"))
        self.assertEqual(srv.graph["2"]["inputs"]["image"], "lb3d_guide.png")
        self.assertEqual(srv.graph["8"]["class_type"], "PreviewImage")    # nothing lands in ComfyUI's output
        self.assertTrue(ticks and ticks[0] is None)

    def test_comfy_old_list_and_bad_model(self):
        srv, url = self.start(comfy, new_combo=False)
        server = m.AIServer.detect(url)
        self.assertEqual(server.models()[0], srv.models)
        with self.assertRaises(m.AIError) as ctx:
            server.img2img(m.ai_guide(base=512)[0], "p", "n", model="missing.safetensors", strength=0.5, steps=4,
                           cfg=5, seed=1)
        self.assertIn("Value not in list", str(ctx.exception))


class StabilityMatrixFolder(unittest.TestCase):
    def test_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "StabilityMatrix.exe"
            exe.write_bytes(b"")
            data = Path(tmp) / "Data"
            data.mkdir()
            (data / ".sm-portable").write_text("")
            packages = [
                {"DisplayName": "Forge Neo", "PackageName": "forge-neo", "Id": "f1",
                 "LaunchArgs": [{"Name": "--server-name", "OptionValue": ""}, {"Name": "", "OptionValue": "--api"}]},
                {"DisplayName": "SD.Next", "PackageName": "automatic", "Id": "s1",
                 "LaunchArgs": [{"Name": "--port", "OptionValue": "7870"}]},
                {"DisplayName": "WebUI", "PackageName": "stable-diffusion-webui", "Id": "w1",
                 "LaunchArgs": [{"Name": "--api", "OptionValue": False}]},
                {"DisplayName": "ComfyUI1", "PackageName": "ComfyUI", "Id": "c1", "LaunchArgs": []},
                {"DisplayName": "Invoke", "PackageName": "InvokeAI", "Id": "i1", "LaunchArgs": []},
                "junk",
            ]
            (data / "settings.json").write_text(json.dumps({"InstalledPackages": packages,
                                                            "ActiveInstalledPackage": "c1"}), encoding="utf-8")
            self.assertEqual(m.find_stability_matrix(str(exe)), exe)
            self.assertEqual(m.sm_library(exe), data)
            found = {p["id"]: p for p in m.sm_packages(data)}
            self.assertEqual(sorted(found), ["c1", "f1", "s1", "w1"])
            self.assertEqual((found["f1"]["kind"], found["f1"]["url"], found["f1"]["api"]),
                             ("a1111", "http://127.0.0.1:7860", True))
            self.assertEqual((found["s1"]["url"], found["s1"]["api"]), ("http://127.0.0.1:7870", True))
            self.assertFalse(found["w1"]["api"])
            self.assertEqual((found["c1"]["kind"], found["c1"]["url"], found["c1"]["active"]),
                             ("comfy", "http://127.0.0.1:8188", True))
            self.assertEqual(len(found["f1"]["urls"]), 10)            # no --port: it may move to 7861…7869
            self.assertEqual(found["f1"]["urls"][1], "http://127.0.0.1:7861")
            self.assertEqual(found["s1"]["urls"], ["http://127.0.0.1:7870"])
            self.assertEqual(found["c1"]["urls"], ["http://127.0.0.1:8188"])
        self.assertEqual(m.sm_packages(None), [])

    def test_web_ui_on_the_next_port(self):
        srv, url = a1111()
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                closed = f"http://127.0.0.1:{s.getsockname()[1]}"
            server, problem = m.find_ai_server(closed, [closed, url])
            self.assertEqual((server.url, problem), (url, None))
            self.assertEqual(m.find_ai_server(closed, [closed]), (None, None))
        finally:
            srv.shutdown()
            srv.server_close()


class Window(unittest.TestCase):
    """The AI window with a made-up server: connect, paint two, save one, and the main window uses it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lb = make_lb(self.tmp.name, [("First: Game", "Europe")],
                          {"Box - Front": [("Europe", "First_ Game-01.png", cover((20, 80, 200)))]})
        self.saved = (m.CONFIG_PATH, m.MODEL_DIR, m.find_stability_matrix)
        m.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        m.MODEL_DIR = Path(self.tmp.name) / "box model"
        m.find_stability_matrix = lambda remembered="": None       # never the real Stability Matrix
        self.srv, self.url = a1111(delay=0.3)
        self.root = tk.Tk()
        self.app = m.App(self.root, {"lb": str(self.lb.root)})

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self.srv.shutdown()
        self.srv.server_close()
        m.CONFIG_PATH, m.MODEL_DIR, m.find_stability_matrix = self.saved
        self.tmp.cleanup()

    def wait(self, cond, seconds=30.0):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_paint_and_use(self):
        app = self.app
        self.assertTrue(self.wait(lambda: app.lb is not None), "LaunchBox not loaded")
        app.select_platform(PLATFORM)
        self.assertTrue(self.wait(lambda: app.pics is not None), "game not shown")
        app.cfg["ai"] = {"url": self.url, "variants": 2, "size": 768}
        app.open_ai_dialog()
        dlg = app.ai_dialog
        self.assertIsNotNone(dlg)
        self.assertTrue(self.wait(lambda: dlg.server is not None), dlg.server_label["text"])
        self.assertEqual(dlg.model_var.get(), MODELS[0])
        self.assertIn("Other address", dlg.server_var.get())
        dlg.show()
        self.assertIsNotNone(dlg.photo)                                # the drawing for the AI
        dlg.generate()
        self.assertTrue(dlg.busy)
        self.assertTrue(self.wait(lambda: not dlg.busy), dlg.status["text"])
        self.assertEqual(len(dlg.results), 2, dlg.status["text"])
        self.assertIs(dlg.chosen, dlg.results[0])
        for mode in m.AI_PREVIEWS:
            dlg.preview_var.set(mode)
            dlg.show()
            self.assertIsNotNone(dlg.photo, mode)
        dlg.choose(dlg.results[1])
        dlg.save()
        name = app.profile["template"]
        self.assertTrue((m.MODEL_DIR / name).is_file(), name)
        self.assertTrue((m.MODEL_DIR / name).with_suffix(".json").is_file())
        self.assertIsNotNone(app.template_img)
        _tpl, quads = dlg.made_template()
        for face in m.FACES:
            for a, b in zip(app.quads[face], quads[face]):
                self.assertLess(m.dist(a, b), 0.75)
        self.assertEqual(json.loads((m.MODEL_DIR / name).with_suffix(".json").read_text(encoding="utf-8"))
                         ["ai"]["seed"], dlg.results[1]["meta"]["seed"])
        app.draw()
        self.assertIsNotNone(app.photo)
        self.assertEqual(dlg.source_var.get(), "case")
        self.assertEqual(str(dlg.tpl_radio["state"]), "normal")         # the new template can be repainted
        dlg.close()
        self.assertIsNone(app.ai_dialog)
        self.assertEqual(app.cfg["ai"]["url"], self.url)


if __name__ == "__main__":
    unittest.main()
