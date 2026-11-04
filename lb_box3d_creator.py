#!/usr/bin/env python3
"""LB 3D Box Creator: 3D boxes for a LaunchBox library.

Builds "Box - 3D" pictures for LaunchBox games out of their "Box - Front" / "Box - Spine" images, either on a case
template (a picture of an empty case whose front and spine corners are known) or on a box drawn in perspective, and
saves them where LaunchBox looks for them. Games with no cover get a generic one; new templates can be painted by the
local Stable Diffusion that Stability Matrix runs. One file, tkinter + Pillow.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import io
import json
import math
import os
import queue
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat, ImageTk

APP_NAME = "LB 3D Box Creator"
APP_VERSION = "1.1.0"
CONFIG_PATH = Path.home() / ".lb_box3d_creator_config.json"
LOG_PATH = Path.home() / ".lb_box3d_creator.log"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BUNDLED_MODELS = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "box model"
MODEL_DIR = APP_DIR / "box model"
BACKUP_DIR_NAME = "LB 3D Box Creator"
GENERIC = "*generic*"
MAX_ROWS = 5000
FACES = ("front", "spine")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
FRONT_TYPES = ("Box - Front", "Box - Front - Reconstructed", "Fanart - Box - Front")
SPINE_TYPE, FULL_TYPE, LOGO_TYPE, OUT_TYPE = "Box - Spine", "Box - Full", "Clear Logo", "Box - 3D"
DISC_TYPE = "Disc"
MARQUEE_TYPE = "Arcade - Marquee"
LAYER_KINDS = ("text", "logo", "clearlogo", "marquee")
RECORD_TAGS = {"Game", "AdditionalApplication", "CustomField", "AlternateName", "GameControllerSupport"}
PLACEHOLDERS = ("title", "platform", "year", "developer", "publisher", "region", "genre", "series", "version")
FONT_FILES = {
    "Arial Bold": "arialbd.ttf", "Arial Black": "ariblk.ttf", "Arial": "arial.ttf", "Impact": "impact.ttf",
    "Segoe UI Bold": "segoeuib.ttf", "Verdana Bold": "verdanab.ttf", "Tahoma Bold": "tahomabd.ttf",
    "Trebuchet MS Bold": "trebucbd.ttf", "Georgia Bold": "georgiab.ttf", "Times New Roman Bold": "timesbd.ttf",
    "Courier New Bold": "courbd.ttf",
}
_BAD_CHARS = set('\\/:*?"<>|\'')
_GUID_RE = re.compile(r"^(?P<title>.*)\.(?P<gid>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")
_NUM_RE = re.compile(r"^(?P<name>.+)-(?P<num>\d{2,})$")

LANCZOS, BICUBIC, BILINEAR = Image.Resampling.LANCZOS, Image.Resampling.BICUBIC, Image.Resampling.BILINEAR
Image.MAX_IMAGE_PIXELS = 400_000_000


# --------------------------------------------------------------------------------------------------------- helpers
def clean_name(text: str) -> str:
    """A title as LaunchBox writes it in file names (\\ / : * ? " < > | ' become _)."""
    return "".join("_" if ch in _BAD_CHARS or ord(ch) < 32 else ch for ch in text)


def hex_rgb(value, default=(255, 255, 255)):
    try:
        v = str(value).strip().lstrip("#")
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return default


def rgb_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, c))) for c in rgb[:3])


def file_sha(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def ensure_model_dir() -> None:
    """The case templates live in "box model" next to the program; a lone exe puts its built-in ones there
    (or reads them where they were unpacked when that folder cannot be written)."""
    global MODEL_DIR
    try:
        if MODEL_DIR.is_dir() and any(p.suffix.lower() in IMAGE_EXTS for p in MODEL_DIR.iterdir()):
            return
    except OSError:
        pass
    if BUNDLED_MODELS.is_dir() and BUNDLED_MODELS.resolve() != MODEL_DIR.resolve():
        try:
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            for src in BUNDLED_MODELS.iterdir():     # pictures, their corner files (.json) and licences (.txt)
                if src.suffix.lower() in IMAGE_EXTS | {".json", ".txt"} and not (MODEL_DIR / src.name).exists():
                    shutil.copy2(src, MODEL_DIR / src.name)
        except OSError:
            MODEL_DIR = BUNDLED_MODELS


def app_icon(size: int = 256):
    """The program's icon: a blue box seen from the side, as in the header."""
    s = size / 34
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(6 * s, 7 * s), (13 * s, 3 * s), (13 * s, 31 * s), (6 * s, 28 * s)], fill=(10, 79, 176, 255))
    d.polygon([(13 * s, 3 * s), (30 * s, 6 * s), (30 * s, 28 * s), (13 * s, 31 * s)], fill=(7, 106, 239, 255))
    d.line([(13 * s, 3 * s), (13 * s, 31 * s)], fill=(159, 208, 255, 255), width=max(1, round(s)))
    return img


def log_line(text: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
    except OSError:
        pass


_tls = threading.local()


def load_font(name: str, size: float):
    """A TrueType font from Windows\\Fonts (one cache per thread: FreeType faces are not shared between threads)."""
    size = max(4, int(round(size)))
    cache = getattr(_tls, "fonts", None)
    if cache is None:
        cache = _tls.fonts = {}
    font = cache.get((name, size))
    if font is None:
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for fn in (FONT_FILES.get(name, "arialbd.ttf"), "arialbd.ttf", "DejaVuSans-Bold.ttf"):
            for candidate in (fonts_dir / fn, Path(fn)):
                try:
                    font = ImageFont.truetype(str(candidate), size)
                    break
                except OSError:
                    continue
            if font is not None:
                break
        if font is None:
            font = ImageFont.load_default(size)
        cache[(name, size)] = font
    return font


def load_picture(path, limit: int = 0):
    """Open an image as RGBA; JPEGs much larger than `limit` are decoded at a reduced size."""
    with Image.open(path) as im:
        if limit and im.format == "JPEG":
            im.draft("RGB", (limit, limit))
        im.load()
        img = im.convert("RGBA")
    if limit and max(img.size) > limit * 1.5:
        img.thumbnail((limit, limit), LANCZOS)
    return img


# -------------------------------------------------------------------------------------------------------- geometry
def solve_linear(a, b):
    n = len(b)
    m = [list(map(float, row)) + [float(v)] for row, v in zip(a, b)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("degenerate quad")
        m[c], m[p] = m[p], m[c]
        pivot = m[c]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c] / pivot[c]
                row = m[r]
                for k in range(c, n + 1):
                    row[k] -= f * pivot[k]
    return [m[i][n] / m[i][i] for i in range(n)]


def homography(src, dst):
    """The 8 coefficients of the projective map that sends the 4 src points onto the 4 dst points."""
    a, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return solve_linear(a, b)


def apply_h(h, x, y):
    d = h[6] * x + h[7] * y + 1.0
    return (h[0] * x + h[1] * y + h[2]) / d, (h[3] * x + h[4] * y + h[5]) / d


def dist(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def face_size(quad):
    """Width and height of a face: the longer of each pair of opposite edges (TL, TR, BR, BL order)."""
    tl, tr, br, bl = quad
    return max(dist(tl, tr), dist(bl, br)), max(dist(tl, bl), dist(tr, br))


def scale_quad(quad, s: float):
    return [(x * s, y * s) for x, y in quad]


def quad_area(quad) -> float:
    return abs(sum(quad[i][0] * quad[i - 1][1] - quad[i - 1][0] * quad[i][1] for i in range(4))) / 2


def valid_quad(quad) -> bool:
    try:
        if len(quad) != 4 or any(len(p) != 2 for p in quad):
            return False
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for p in quad for v in p):
            return False
        return quad_area(quad) > 16
    except TypeError:
        return False


def point_in_quad(quad, x, y) -> bool:
    inside = False
    for i in range(4):
        (x1, y1), (x2, y2) = quad[i - 1], quad[i]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            inside = not inside
    return inside


def quad_mask(size, quad, ss: int = 4):
    """Anti-aliased polygon mask."""
    w, h = size
    big = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(big).polygon([(x * ss, y * ss) for x, y in quad], fill=255)
    return big.reduce(ss)


# --------------------------------------------------------------------------- template corners (automatic detection)
def _near_mask(img, color, tol):
    rgb = img.convert("RGB")
    r, g, b = ImageChops.difference(rgb, Image.new("RGB", rgb.size, color)).split()
    near = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v <= tol else 0)
    opaque = img.getchannel("A").point(lambda v: 255 if v >= 200 else 0)
    return ImageChops.multiply(near, opaque)


def _run_at(buf, off, width, c):
    if c < 0 or c >= width or buf[off + c] == 0:
        return None
    left = buf.rfind(b"\x00", off, off + c)
    left = 0 if left < 0 else left - off + 1
    right = buf.find(b"\x00", off + c, off + width)
    right = width if right < 0 else right - off
    return left, right


def _scan(mask, cx, cy):
    """Rows of the region around (cx, cy), going up and down from it: [(y, left, right_exclusive)]."""
    w, h = mask.size
    buf = mask.tobytes()
    first = _run_at(buf, cy * w, w, cx)
    if not first:
        return []
    out = [(cy, *first)]
    for step in (-1, 1):
        c = (first[0] + first[1]) // 2
        y = cy + step
        while 0 <= y < h:
            run = _run_at(buf, y * w, w, c)
            if not run or run[1] - run[0] < 0.35 * (first[1] - first[0]):
                break
            out.append((y, *run))
            c = (run[0] + run[1]) // 2
            y += step
    out.sort()
    return out


def _fit_line(points):
    """Least squares s = a*t + b, dropping outliers."""
    pts = list(points)
    a, b = 0.0, 0.0
    for _ in range(3):
        n = len(pts)
        if n < 2:
            break
        mt = sum(p[0] for p in pts) / n
        ms = sum(p[1] for p in pts) / n
        var = sum((p[0] - mt) ** 2 for p in pts)
        a = sum((p[0] - mt) * (p[1] - ms) for p in pts) / var if var else 0.0
        b = ms - a * mt
        res = [abs(p[1] - (a * p[0] + b)) for p in pts]
        limit = max(1.5, 2.5 * statistics.median(res))
        keep = [p for p, e in zip(pts, res) if e <= limit]
        if len(keep) == len(pts):
            break
        pts = keep
    return a, b


def _middle(seq, frac=0.7):
    cut = int(len(seq) * (1 - frac) / 2)
    return seq[cut:len(seq) - cut] if len(seq) - 2 * cut >= 2 else seq


def _intersect(vertical, horizontal):
    a, b = vertical      # x = a*y + b
    c, d = horizontal    # y = c*x + d
    y = (c * b + d) / (1 - c * a)
    return (a * y + b, y)


def detect_window(img, seed, tol=24, clear=False):
    """Quad of the flat-coloured area around `seed` (the place where a cover goes on a case template); with
    clear=True, of the see-through window around it (templates laid over the art, like box3d's)."""
    x, y = seed
    if clear:
        mask = img.getchannel("A").point(lambda v: 255 if v < 32 else 0)
    else:
        patch = img.convert("RGB").crop((x - 3, y - 3, x + 4, y + 4))
        color = tuple(int(v) for v in ImageStat.Stat(patch).median)
        mask = _near_mask(img, color, tol)
    rows = _scan(mask, x, y)
    cols = _scan(mask.transpose(Image.Transpose.TRANSPOSE), y, x)
    if len(rows) < 10 or len(cols) < 10:
        return None
    left = _fit_line([(yy, l) for yy, l, r in _middle(rows)])
    right = _fit_line([(yy, r) for yy, l, r in _middle(rows)])
    top = _fit_line([(xx, t) for xx, t, b in _middle(cols)])
    bottom = _fit_line([(xx, b) for xx, t, b in _middle(cols)])
    try:
        quad = [_intersect(left, top), _intersect(right, top), _intersect(right, bottom), _intersect(left, bottom)]
    except ZeroDivisionError:
        return None
    return quad if valid_quad(quad) else None


def _row_runs(img, y, x_from, x_to, step_tol=7):
    """Flat-coloured runs on row y between x_from and x_to: [(x0, x1_exclusive)]."""
    row = img.crop((0, y, img.width, y + 1)).tobytes()
    runs, start = [], None
    for x in range(max(1, x_from), x_to):
        a, b = row[(x - 1) * 4:(x - 1) * 4 + 4], row[x * 4:x * 4 + 4]
        ok = a[3] >= 200 and b[3] >= 200 and max(abs(a[i] - b[i]) for i in range(3)) <= step_tol
        if ok and start is None:
            start = x - 1
        elif not ok and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, x_to))
    return runs


def _silhouette_span(img, x):
    col = img.getchannel("A").crop((x, 0, x + 1, img.height)).tobytes()
    ys = [i for i, v in enumerate(col) if v >= 128]
    return (ys[0], ys[-1] + 1) if ys else None


def detect_spine(img, front):
    """Quad of the case side left of the front: its widest flat area, else the whole visible side."""
    (tlx, tly), (trx, _), (brx, _), (blx, bly) = front
    front_w = ((trx - tlx) + (brx - blx)) / 2
    left_edge = min(tlx, blx)
    ymid = int((tly + bly) / 2)
    lo, hi = int(max(0, left_edge - 0.4 * front_w)), int(left_edge) - 1
    if hi - lo < 8:
        return None
    good = []
    for run in (r for r in _row_runs(img, ymid, lo, hi) if r[1] - r[0] >= 10):
        hits = 0
        for yy in (int(tly + (bly - tly) * 0.3), int(tly + (bly - tly) * 0.7)):
            if any(min(run[1], q[1]) - max(run[0], q[0]) >= 0.6 * (run[1] - run[0]) for q in _row_runs(img, yy, lo, hi)):
                hits += 1
        if hits == 2:
            good.append(run)
    if good:
        run = max(good, key=lambda q: q[1] - q[0])
        quad = detect_window(img, ((run[0] + run[1]) // 2, ymid), tol=20)
        if quad and max(p[0] for p in quad) <= left_edge + 3 and min(p[0] for p in quad) >= lo - 3:
            return quad
    alpha_row = img.getchannel("A").crop((0, ymid, img.width, ymid + 1)).tobytes()
    x0 = next((i for i, v in enumerate(alpha_row) if v >= 128), 0)
    if left_edge - x0 < 8:
        return None
    x0, x1 = x0 + 2, left_edge - 2
    s0, s1 = _silhouette_span(img, int(x0) + 2), _silhouette_span(img, int(x1) - 2)
    if not s0 or not s1:
        return None
    quad = [(x0, s0[0]), (x1, s1[0]), (x1, s1[1]), (x0, s0[1])]
    return quad if valid_quad(quad) else None


def default_quads(size):
    """A first guess when a template's corners are neither known nor found: a spine strip on the left and the front
    beside it, ready to be dragged into place."""
    w, h = size
    top, bottom = h * 0.06, h * 0.94
    return {"front": [(w * 0.13, top), (w * 0.95, top), (w * 0.95, bottom), (w * 0.13, bottom)],
            "spine": [(w * 0.04, top), (w * 0.11, top), (w * 0.11, bottom), (w * 0.04, bottom)]}


def detect_quads(img):
    """Front and spine corners of a case template, found from its flat (or see-through) cover areas."""
    img = img.convert("RGBA")
    w, h = img.size
    alpha = img.getchannel("A")
    front = None
    for fx, fy in ((0.5, 0.5), (0.55, 0.5), (0.5, 0.45), (0.6, 0.55), (0.45, 0.55)):
        seed = (int(w * fx), int(h * fy))
        clear = alpha.getpixel(seed) < 32
        front = detect_window(img, seed, clear=clear)
        inside = front and all(1 < x < w - 2 and 1 < y < h - 2 for x, y in front)   # a window, not the background
        if front and quad_area(front) > 0.12 * w * h and (inside or not clear):
            break
        front = None
    if not front:
        return default_quads(img.size)
    spine = detect_spine(img, front)
    return {"front": front, "spine": spine}


def _profile_corners(value):
    """Four corners from {"tl": [x, y], "tr": ..., "br": ..., "bl": ...} or [[x, y] x 4] (TL, TR, BR, BL)."""
    pts = [value.get(k) for k in ("tl", "tr", "br", "bl")] if isinstance(value, dict) else value
    try:
        quad = [(float(p[0]), float(p[1])) for p in pts]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return quad if valid_quad(quad) else None


def template_profile_files(path):
    """Where a template's corner file may be: <name>.json beside it, or profile.json beside a box3d template.png."""
    path = Path(path)
    candidates = [path.with_suffix(".json")]
    if path.stem.casefold() == "template":
        candidates.append(path.parent / "profile.json")
    return candidates


def template_profile_data(path):
    """The template's corner file as read (a dict) and where it is, or (None, None)."""
    for cand in template_profile_files(path):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data, cand
    return None, None


def profile_quads(path, size):
    """Corners kept in a file next to a template, scaled to the picture: a box3d profile (<name>.json, or
    profile.json beside template.png: "cover_quad" / "spine_quad") or {"quads": {"front": [...], "spine": [...]}}."""
    for cand in template_profile_files(path):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        ours = data.get("quads") if isinstance(data.get("quads"), dict) else {}
        front = _profile_corners(data.get("cover_quad")) or _profile_corners(ours.get("front"))
        if not front:
            continue
        spine = _profile_corners(data.get("spine_quad")) or _profile_corners(ours.get("spine"))
        made = data.get("template_size") or data.get("size")
        try:
            mw, mh = (made["width"], made["height"]) if isinstance(made, dict) else made
            sx, sy = size[0] / float(mw), size[1] / float(mh)
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            sx = sy = 1.0
        scale = (lambda q: [(x * sx, y * sy) for x, y in q]) if (sx, sy) != (1.0, 1.0) else (lambda q: q)
        return {"front": scale(front), "spine": scale(spine) if spine else None}
    return None


def template_quads(path, img):
    """A template's corners: from the file kept next to it, else found in the picture."""
    return profile_quads(path, img.size) or detect_quads(img)


SLOT_GAME_DEFAULT = (0.80, 0.32, 0.53, -90.0)   # box3d-like game slot: box w, box h, centre y (spine fractions), turn


def spine_slot_layers(path=None):
    """Spine logo layers from box3d's slots (top / game / bottom) of the template's profile, or one default game
    slot. The game slot shows the game's Arcade - Marquee (else its Clear Logo); top and bottom use the profile's
    assets (assets\\logo_top.*, logo_bottom.*). All are drawn only on spines this program makes up."""
    data, where = template_profile_data(path) if path else (None, None)
    data = data or {}
    layers = []
    layout = data.get("spine_layout") if isinstance(data.get("spine_layout"), dict) else {}
    try:
        sw, sh = float(data["spine"]["width"]), float(data["spine"]["height"])
    except (KeyError, TypeError, ValueError):
        sw = sh = 0.0
    if layout and sw > 0 and sh > 0:
        alpha = float(layout.get("logo_alpha", 0.85)) if isinstance(layout.get("logo_alpha", 0.85), (int, float)) else 0.85
        p = Path(path)
        dirs = [d for d in (where.parent / "assets", p.with_name(p.stem + "-assets"), p.with_name(p.stem + "_assets"))
                if d.is_dir()]
        for slot in ("top", "game", "bottom"):
            s = layout.get(slot)
            if not isinstance(s, dict):
                continue
            try:
                bw, bh = float(s["max_w"]) / sw, float(s["max_h"]) / sh
                cy, rot = float(s["center_y"]) / sh, float(s.get("rotate", 0))
            except (KeyError, TypeError, ValueError):
                continue
            layer = {"kind": "marquee", "size": 100.0, "box_w": min(1.0, bw), "box_h": min(1.0, bh), "x": 0.5,
                     "y": min(1.0, max(0.0, cy)), "rotation": rot, "opacity": max(0.0, min(1.0, alpha)),
                     "only_made": True, "slot": slot}
            if slot != "game":
                pic = next((f for d in dirs for f in sorted(d.glob(f"logo_{slot}.*")) if f.suffix.lower() in IMAGE_EXTS),
                           None)
                if pic is None:
                    continue
                layer.update(kind="logo", path=str(pic))
            layers.append(layer)
    if not any(ly["slot"] == "game" for ly in layers):
        bw, bh, cy, rot = SLOT_GAME_DEFAULT
        layers.insert(0 if not layers else 1, {"kind": "marquee", "size": 100.0, "box_w": bw, "box_h": bh, "x": 0.5,
                                               "y": cy, "rotation": rot, "opacity": 0.85, "only_made": True,
                                               "slot": "game"})
    return layers


def box3d_profile(name: str, size, quads: dict, profile: dict) -> dict:
    """A box3d profile.json for a template and its corners (box3d renders with it; this program reads it back)."""
    def ints(q):
        return {k: [int(round(x)), int(round(y))] for k, (x, y) in zip(("tl", "tr", "br", "bl"), q)}

    front = quads["front"]
    spine = quads.get("spine")
    if not spine:                         # box3d always has a spine: a thin strip left of the front
        tl, tr, br, bl = front
        width = max(8.0, dist(tl, tr) * 0.08)
        spine = [(max(0.0, tl[0] - width), tl[1] + 4), tl, bl, (max(0.0, bl[0] - width), bl[1] - 4)]
    fw, fh = face_size(front)
    sw, sh = (max(1, round(v)) for v in face_size(spine))
    layout, alpha = {}, 0.85
    for layer in profile["layers"].get("spine", []):
        slot = layer.get("slot")
        if slot in ("top", "game", "bottom") and slot not in layout:
            k = float(layer.get("size", 100.0)) / 100
            layout[slot] = {"max_w": max(1, round(sw * float(layer.get("box_w", 1.0)) * k)),
                            "max_h": max(1, round(sh * float(layer.get("box_h", 1.0)) * k)),
                            "center_y": min(sh, max(0, round(sh * float(layer.get("y", 0.5))))),
                            "rotate": int(round(float(layer.get("rotation", 0.0))))}
            alpha = float(layer.get("opacity", alpha))
    if "game" not in layout:
        bw, bh, cy, rot = SLOT_GAME_DEFAULT
        layout["game"] = {"max_w": max(1, round(sw * bw)), "max_h": max(1, round(sh * bh)),
                          "center_y": round(sh * cy), "rotate": int(rot)}
    layout["logo_alpha"] = round(max(0.0, min(1.0, alpha)), 2)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "template"
    fit = {"fill": "crop", "fit": "fit"}.get(profile["faces"]["front"].get("fit"), "stretch")
    return {"name": safe, "description": f"{name} (made with {APP_NAME})", "version": "1.0.0", "author": APP_NAME,
            "template_size": {"width": int(size[0]), "height": int(size[1])},
            "spine": {"width": sw, "height": sh}, "cover": {"width": max(1, round(fw)), "height": max(1, round(fh))},
            "spine_quad": ints(spine), "cover_quad": ints(front),
            "spine_source_frac": round(float(profile.get("band_frac", 0.2)), 3),
            "spine_source": profile.get("band_source", "left"), "cover_fit": fit, "spine_layout": layout}


# ------------------------------------------------------------------------------------------------------ rendering
def default_face(face: str) -> dict:
    return {"source": "launchbox", "clean": "original", "clean_color": "#ffffff", "color": "#202020",
            "fit": "stretch", "zoom": 1.0, "dx": 0.0, "dy": 0.0, "rotation": 0.0, "opacity": 1.0,
            "shade": 0.06 if face == "front" else 0.22, "flipx": False, "flipy": False}


CASE_COLORS = {
    "Xbox 360": "#7ab51d", "Xbox One / Series": "#107c10", "PlayStation 4 / 5 / Blu-ray": "#0b52c9",
    "PlayStation 2 / DVD": "#141414", "PlayStation 3": "#262626", "Wii / Wii U": "#f2f2f2", "Switch": "#e60012",
    "GameCube": "#1b1b1b", "PC DVD": "#1a1a1a", "Clear": "#d8dde2",
}


def default_profile() -> dict:
    return {
        "template": GENERIC,
        "generic": {"angle": 30.0, "thickness": 0.13, "auto_thickness": True, "perspective": 3.0, "edges": True,
                    "style": "box", "case_color": "#7ab51d", "rim": 0.022},
        "faces": {face: default_face(face) for face in FACES},
        "front_fallbacks": True,
        "match_region": True,
        "spine_from_full": True,
        "spine_generate": "logo",
        "spine_font": "Arial Bold",
        "layers": {face: [] for face in FACES},
        "sheen": True,
        "shadows": True,
        "overlay": 0.55,           # template details laid back over the art (cases with a flat cover area)
        "overlay_mode": "auto",    # auto | details | light (box3d: the template screened over the art)
        "light_strength": 1.0,
        "sharpen": True,           # unsharp mask after the perspective warp (as box3d)
        "tint": "",                # template colour: "" or #rrggbb
        "tint_mode": "multiply",   # multiply (box3d's RGB scale) | colorize
        "tint_amount": 1.0,
        "band_source": "left",     # box3d spine: band of the cover (left | center | right), blurred and darkened
        "band_frac": 0.20,
        "band_blur": 0.22,
        "band_dark": 0.70,
        "generic_cover": True,     # no Box - Front at all (applications, games without box art): a generic cover
        "gc_style": "silver",      # silver | dark (both with a diagonal mesh) | color | picture
        "gc_bg": "#d9dce1",        # ground of the "color" style
        "gc_picture": "",          # ground of the "picture" style
        "gc_ink": "#1d2a44",       # logo and name
        "gc_logo": "auto",         # auto (LaunchBox's platform logo, else drawn) | drawn | picture
        "gc_logo_file": "",
        "gc_maker": "",            # drawn logo: small line ("" = from the platform's name, "-" = none)
        "gc_name": "",             # drawn logo: big name ("" = from the platform's name)
        "gc_title": "title",       # title | logo (the game's Clear Logo, else its title)
        "gc_spine": True,          # black spine with the platform's name when the game has no spine picture
        "web_covers": "auto",      # no Box - Front: look on the web first (auto | libretro | steam | off)
        "web_system": "",          # libretro's name of the platform ("" = found from its name)
        "upscale": False,          # small covers made sharper with an upscale model (AI window's server)
        "upscale_below": 800,      # ... when less than this many pixels high
        "upscale_model": "",       # "" = the best one the server has
        "disc_kind": "auto",       # auto | cd | dvd | bluray | psx | gamecube | picture
        "disc_crop": "center",     # which square of the cover goes on the disc: top | center | bottom
        "disc_zoom": 1.0,
        "disc_logo": True,         # the game's Clear Logo on the disc
        "disc_logo_size": 0.55,
        "disc_text": "",           # a line along the edge ({title} {year} {publisher}…)
        "disc_text_pos": "bottom",
        "disc_text_color": "#ffffff",
        "disc_size": 1000,
    }


def _same_kind(value, default) -> bool:
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(value, bool) and isinstance(default, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and math.isfinite(value)
    return isinstance(value, type(default))


def merged_profile(data) -> dict:
    """A saved profile completed with today's defaults (older config files lack newer keys; wrong types are dropped)."""
    prof = default_profile()
    if not isinstance(data, dict):
        return prof
    for key, value in data.items():
        if key in prof and key not in ("generic", "faces", "layers") and _same_kind(value, prof[key]):
            prof[key] = value
    if isinstance(data.get("generic"), dict):
        for key, value in data["generic"].items():
            if key in prof["generic"] and _same_kind(value, prof["generic"][key]):
                prof["generic"][key] = value
    faces = data.get("faces") if isinstance(data.get("faces"), dict) else {}
    all_layers = data.get("layers") if isinstance(data.get("layers"), dict) else {}
    for face in FACES:
        src = faces.get(face)
        if isinstance(src, dict):
            for key, value in src.items():
                if key in prof["faces"][face] and _same_kind(value, prof["faces"][face][key]):
                    prof["faces"][face][key] = value
        layers = all_layers.get(face)
        if isinstance(layers, list):
            prof["layers"][face] = [dict(ly) for ly in layers
                                    if isinstance(ly, dict) and ly.get("kind") in LAYER_KINDS]
    return prof


def fit_into(src, w, h, cfg):
    """The picture laid on a w x h face as the face settings say (transparent where it does not reach)."""
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if src is None:
        return out
    im = src
    if cfg.get("flipx"):
        im = ImageOps.mirror(im)
    if cfg.get("flipy"):
        im = ImageOps.flip(im)
    iw, ih = im.size
    zoom = max(0.05, float(cfg.get("zoom", 1.0)))
    fit = cfg.get("fit", "stretch")
    if fit == "stretch":
        nw, nh = w * zoom, h * zoom
    else:
        s = (max if fit == "fill" else min)(w / iw, h / ih) * zoom
        nw, nh = iw * s, ih * s
    nw, nh = max(1, round(nw)), max(1, round(nh))
    if (nw, nh) != (iw, ih):
        im = im.resize((nw, nh), LANCZOS if nw < iw or nh < ih else BICUBIC)
    rotation = float(cfg.get("rotation", 0.0))
    if rotation:
        im = im.rotate(rotation, BICUBIC, expand=True)
    x = (w - im.width) / 2 + float(cfg.get("dx", 0.0)) * w
    y = (h - im.height) / 2 + float(cfg.get("dy", 0.0)) * h
    out.alpha_composite(im, (round(x), round(y)))
    return out


def expand_text(value: str, ctx: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(ctx.get(m.group(1).lower(), m.group(0))), value or "")


def text_picture(text, font, fill, stroke, stroke_fill):
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    box = probe.multiline_textbbox((0, 0), text, font=font, stroke_width=stroke, align="center")
    # several lines are measured in fractions of a pixel
    img = Image.new("RGBA", (math.ceil(box[2] - box[0]) + 4, math.ceil(box[3] - box[1]) + 4), (0, 0, 0, 0))
    ImageDraw.Draw(img).multiline_text((2 - box[0], 2 - box[1]), text, font=font, fill=fill, stroke_width=stroke,
                                       stroke_fill=stroke_fill, align="center")
    return img


_logo_cache: dict = {}
_logo_lock = threading.Lock()


def logo_file(path):
    with _logo_lock:
        hit = _logo_cache.get(path)
    if hit is None:
        try:
            hit = load_picture(path, 1600)
        except (OSError, ValueError):
            hit = False
        with _logo_lock:
            _logo_cache[path] = hit
    return hit or None


def draw_layers(canvas, layers, ctx, game_logo, marquee=None):
    """Texts and logos of one face, drawn on its art canvas (positions and sizes relative to the face).

    A logo layer may carry a slot box (box_w, box_h: fractions of the face, as box3d's spine logo slots); its size
    is then a percentage of that box. clearlogo uses the game's Clear Logo (else its Arcade - Marquee), marquee the
    other way round.
    """
    w, h = canvas.size
    for layer in layers:
        kind = layer.get("kind")
        try:
            if kind == "text":
                text = expand_text(layer.get("value", ""), ctx).replace("\\n", "\n").strip()
                if not text:
                    continue
                size = h * float(layer.get("size", 4.0)) / 100
                font = load_font(layer.get("font", "Arial Bold"), size)
                stroke = max(0, round(size * float(layer.get("stroke", 4.0)) / 100))
                pic = text_picture(text, font, hex_rgb(layer.get("color", "#ffffff")) + (255,), stroke,
                                   hex_rgb(layer.get("stroke_color", "#111111")) + (255,))
                limit = 0.96
            elif kind in ("logo", "clearlogo", "marquee"):
                if kind == "clearlogo":
                    pic = game_logo or marquee
                elif kind == "marquee":
                    pic = marquee or game_logo
                else:
                    pic = logo_file(layer.get("path", ""))
                if pic is None:
                    continue
                limit = float(layer.get("size", 60.0)) / 100
            else:
                continue
            rotation = float(layer.get("rotation", 0.0))
            if rotation:
                pic = pic.rotate(rotation, BICUBIC, expand=True)
            if kind == "text":
                box_w, box_h = w * limit, h * 0.96
            else:
                box_w = w * float(layer.get("box_w", 1.0)) * limit
                box_h = h * float(layer.get("box_h", 1.0)) * limit
            if kind != "text" or pic.width > box_w or pic.height > box_h:
                s = min(box_w / pic.width, box_h / pic.height)
                if kind == "text":
                    s = min(1.0, s)
                pic = pic.resize((max(1, round(pic.width * s)), max(1, round(pic.height * s))), LANCZOS)
            opacity = float(layer.get("opacity", 1.0))
            if opacity < 0.999:
                pic = pic.copy()
                pic.putalpha(pic.getchannel("A").point(lambda v: round(v * opacity)))
            x = w * float(layer.get("x", 0.5)) - pic.width / 2
            y = h * float(layer.get("y", 0.5)) - pic.height / 2
            canvas.alpha_composite(pic, (round(x), round(y)))
        except (OSError, ValueError, ZeroDivisionError) as exc:
            log_line(f"layer {kind}: {exc}")


def shade(img, amount: float, face: str):
    """Darken a face: the front a little towards its right edge, the spine more and towards its left edge."""
    if amount <= 0.001:
        return img
    if face == "front":
        ramp = [round(255 * (1 - amount * t / 255)) for t in range(256)]
    else:
        ramp = [round(255 * (1 - amount * (1 - 0.45 * t / 255))) for t in range(256)]
    line = Image.new("L", (256, 1))
    line.putdata(ramp)
    grad = line.resize(img.size, BILINEAR)
    rgb = ImageChops.multiply(img.convert("RGB"), Image.merge("RGB", (grad, grad, grad)))
    out = rgb.convert("RGBA")
    out.putalpha(img.getchannel("A"))
    return out


def warp_onto(base, art, quad, opacity: float = 1.0, ss: int = 2, sharpen: bool = False) -> None:
    """Lay `art` on `base` (in place) so that its corners land on the quad (TL, TR, BR, BL); `sharpen` gives back
    the crispness the resampling takes (box3d's unsharp mask, colour only)."""
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    x0, y0 = max(0, math.floor(min(xs)) - 1), max(0, math.floor(min(ys)) - 1)
    x1, y1 = min(base.width, math.ceil(max(xs)) + 1), min(base.height, math.ceil(max(ys)) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    w, h = art.size
    try:
        coeffs = homography([((x - x0) * ss, (y - y0) * ss) for x, y in quad], [(0, 0), (w, 0), (w, h), (0, h)])
    except ValueError:
        return
    out = art.convert("RGBa").transform(((x1 - x0) * ss, (y1 - y0) * ss), Image.Transform.PERSPECTIVE, coeffs,
                                        BICUBIC)
    if ss > 1:
        out = out.reduce(ss)
    out = out.convert("RGBA")
    if sharpen:
        r, g, b, a = out.split()
        rgb = Image.merge("RGB", (r, g, b)).filter(ImageFilter.UnsharpMask(radius=1.0, percent=80, threshold=3))
        out = Image.merge("RGBA", (*rgb.split(), a))
    if opacity < 0.999:
        out.putalpha(out.getchannel("A").point(lambda v: round(v * opacity)))
    base.alpha_composite(out, (x0, y0))


def unwarp(img, quad, size):
    """The face inside `quad` flattened back to a w x h rectangle (the 2D views)."""
    w, h = size
    coeffs = homography([(0, 0), (w, 0), (w, h), (0, h)], quad)
    return img.convert("RGBa").transform((w, h), Image.Transform.PERSPECTIVE, coeffs, BICUBIC).convert("RGBA")


def clean_area(base, quad, mode: str, color: str) -> None:
    """What becomes of the template's own picture under a face: kept, erased or painted over (in place)."""
    if mode not in ("transparent", "color"):
        return
    mask = quad_mask(base.size, quad)
    if mode == "transparent":
        base.putalpha(ImageChops.subtract(base.getchannel("A"), mask))
    else:
        base.paste(Image.new("RGBA", base.size, hex_rgb(color) + (255,)), (0, 0), mask)


def template_details(template, quad, strength: float):
    """What the case has on top of its flat cover area (clips, plastic edges), to lay back over the new cover."""
    if strength <= 0.01:
        return None
    mask = quad_mask(template.size, quad, 2)
    rgb = template.convert("RGB")
    fill = tuple(int(v) for v in ImageStat.Stat(rgb, mask).median)
    r, g, b = ImageChops.difference(rgb, Image.new("RGB", rgb.size, fill)).split()
    diff = ImageChops.lighter(ImageChops.lighter(r, g), b)
    lut = [0 if v < 16 else min(255, round((v - 16) * 4 * strength)) for v in range(256)]
    alpha = ImageChops.multiply(ImageChops.multiply(diff.point(lut), mask), template.getchannel("A"))
    if not alpha.getbbox():
        return None
    layer = template.copy()
    layer.putalpha(alpha)
    return layer


def light_layer(base, template, quads, strength: float) -> None:
    """box3d's way: the template laid over the art as light (screen blend weighted by the template's alpha), only
    on the faces, so its gloss and highlights shine on the new cover (in place)."""
    if strength <= 0.01 or not quads:
        return
    mask = None
    for quad in quads:
        m = quad_mask(base.size, quad, 2)
        mask = m if mask is None else ImageChops.lighter(mask, m)
    weight = ImageChops.multiply(mask, template.getchannel("A"))
    if strength < 0.999:
        weight = weight.point(lambda v: round(v * strength))
    if not weight.getbbox():
        return
    rgb = base.convert("RGB")
    lit = Image.composite(ImageChops.screen(rgb, template.convert("RGB")), rgb, weight).convert("RGBA")
    lit.putalpha(base.getchannel("A"))
    base.paste(lit)


def tint_picture(img, color: str, mode: str = "multiply", amount: float = 1.0):
    """The template recoloured: multiply = box3d's RGB scale (only darkens), colorize = the case's light and shade
    redrawn in the colour (turns a black or white case into a coloured one)."""
    if not color or amount <= 0.01:
        return img
    rgb, alpha = img.convert("RGB"), img.getchannel("A")
    c = hex_rgb(color, (255, 255, 255))
    if mode == "colorize":
        dark = tuple(round(v * 0.22) for v in c)
        light = tuple(round(v + (255 - v) * 0.85) for v in c)
        tinted = ImageOps.colorize(ImageOps.grayscale(rgb), black=dark, white=light, mid=c)
    else:
        tinted = ImageChops.multiply(rgb, Image.new("RGB", rgb.size, c))
    if amount < 0.999:
        tinted = Image.blend(rgb, tinted, amount)
    out = tinted.convert("RGBA")
    out.putalpha(alpha)
    return out


_memo_cache: dict = {}
_memo_lock = threading.Lock()


def _memo(key, keep, make):
    """A small shared cache for things made from a template (`keep` stays referenced, so ids in keys stay valid)."""
    with _memo_lock:
        hit = _memo_cache.get(key)
    if hit is not None:
        return hit[1]
    value = make()
    with _memo_lock:
        if len(_memo_cache) > 12:
            _memo_cache.clear()
        _memo_cache[key] = (keep, value)
    return value


def see_through(template, quad) -> bool:
    """Is the cover area mostly transparent (a template made to lie over the art, like box3d's)?"""
    def check():
        hist = template.getchannel("A").histogram(quad_mask(template.size, quad, 1))
        total = sum(hist)
        return bool(total) and sum(hist[:64]) / total > 0.5
    return _memo(("see", id(template), template.size, tuple(map(tuple, quad))), template, check)


def add_sheen(base, quad, strength: float = 1.0) -> None:
    """Soft plastic reflection across the front (in place)."""
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    qx0, qx1, qy0, qy1 = min(xs), max(xs), min(ys), max(ys)
    qw, qh = qx1 - qx0, qy1 - qy0
    if qw < 8 or qh < 8:
        return
    band = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(band)
    rise = 0.16 * qh
    for top, thick, alpha in ((0.13, 0.12, 34), (0.30, 0.035, 22)):
        y_l, y_r = qy0 + top * qh, qy0 + top * qh - rise
        d.polygon([(qx0 - 4, y_l), (qx1 + 4, y_r), (qx1 + 4, y_r + thick * qh), (qx0 - 4, y_l + thick * qh)],
                  fill=round(alpha * strength))
    band = band.filter(ImageFilter.GaussianBlur(max(1.0, qh * 0.025)))
    alpha = ImageChops.multiply(band, quad_mask(base.size, quad, 2))
    white = Image.new("RGBA", base.size, (255, 255, 255, 0))
    white.putalpha(alpha)
    base.alpha_composite(white)


def _looks_alike(a, b, limit: float = 30.0) -> bool:
    """Same picture, roughly (mean difference of small greyscale copies)."""
    size = (24, 32)
    sa = ImageOps.grayscale(a.convert("RGB")).resize(size, BILINEAR)
    sb = ImageOps.grayscale(b.convert("RGB")).resize(size, BILINEAR)
    return ImageStat.Stat(ImageChops.difference(sa, sb)).mean[0] <= limit


def spine_from_full(full, front):
    """The spine cut out of a "Box - Full" scan (back | spine | front): only when its width makes sense and the
    front half of the scan is this game's Box - Front (not another edition)."""
    if full is None or front is None or front.height == 0:
        return None
    fw = front.width * full.height / front.height
    sw = full.width - 2 * fw
    if sw < 0.025 * fw or sw > 0.35 * fw:
        return None
    if not _looks_alike(full.crop((round(full.width - fw), 0, full.width, full.height)), front):
        return None
    x0 = (full.width - sw) / 2
    return full.crop((round(x0), 0, round(x0 + sw), full.height))


def make_spine(front, logo, title: str, size, style: str, font_name: str = "Arial Bold", band=None,
               draw_logo: bool = True):
    """A spine for a game that has none: the front's edge colour with its Clear Logo or title, the edge itself, or
    box3d's band (a strip of the cover: band = (left|center|right, width fraction, blur, darkness), blurred and
    darkened, then the logo). draw_logo=False leaves the logo to the spine's own logo layers."""
    w, h = size
    if front is not None:
        strip = front.convert("RGB").crop((0, 0, max(1, front.width // 25), front.height))
    else:
        strip = Image.new("RGB", (1, 1), (32, 32, 32))
    if style == "edge" and front is not None:
        img = strip.resize((max(1, w // 6), h), BICUBIC).resize((w, h), BICUBIC)
        return img.filter(ImageFilter.GaussianBlur(max(1, w // 10))).convert("RGBA")
    if style == "band" and front is not None:
        source, frac, blur, dark = band or ("left", 0.20, 0.22, 0.70)
        fw, fh = front.size
        bw = max(4, min(fw, int(fw * float(frac))))
        x0 = {"right": fw - bw, "center": (fw - bw) // 2}.get(source, 0)
        img = front.convert("RGB").crop((x0, 0, x0 + bw, fh)).resize((w, h), LANCZOS)
        if blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(max(0.5, float(blur) * w)))
        img = img.convert("RGBA")
        if dark > 0:
            img.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, round(255 * min(1.0, float(dark))))))
        color = tuple(int(c) for c in ImageStat.Stat(img.convert("RGB")).mean)
        style = "logo" if draw_logo else "plain"
    else:
        color = tuple(int(c) for c in ImageStat.Stat(strip).mean)
        img = Image.new("RGBA", (w, h), color + (255,))
    if style not in ("logo", "title") or not draw_logo:
        return img
    light = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2] > 150
    if style == "logo" and logo is not None:
        pic = logo.rotate(-90, BICUBIC, expand=True)
        s = min(w * 0.84 / pic.width, h * 0.62 / pic.height)
        pic = pic.resize((max(1, round(pic.width * s)), max(1, round(pic.height * s))), LANCZOS)
        shadow = Image.new("RGBA", pic.size, (0, 0, 0, 0) if light else (0, 0, 0, 0))
        shadow.putalpha(pic.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, w // 40))).point(
            lambda v: v * (90 if light else 150) // 255))
        pos = ((w - pic.width) // 2, (h - pic.height) // 2)
        img.alpha_composite(shadow, (pos[0] + max(1, w // 60), pos[1] + max(1, w // 60)))
        img.alpha_composite(pic, pos)
    elif title:
        font = load_font(font_name, w * 0.5)
        pic = text_picture(title, font, (20, 20, 20, 255) if light else (245, 245, 245, 255),
                           max(1, round(w * 0.02)), (230, 230, 230, 255) if light else (10, 10, 10, 255))
        pic = pic.rotate(-90, BICUBIC, expand=True)
        s = min(1.0, w * 0.8 / pic.width, h * 0.88 / pic.height)
        if s < 1:
            pic = pic.resize((max(1, round(pic.width * s)), max(1, round(pic.height * s))), LANCZOS)
        img.alpha_composite(pic, ((w - pic.width) // 2, (h - pic.height) // 2))
    return img


def generic_layout(front_wh, depth: float, angle: float, perspective: float, height: int):
    """Corners of a box seen in perspective, its left side turned towards the viewer.

    front_wh: proportions of the front; depth: spine width / front width; angle: turn in degrees;
    perspective: camera distance in box sizes. Returns ((width, height), {'front': quad, 'spine': quad or None}).
    """
    fw, fh = front_wh
    w, h, d = 1.0, fh / max(1e-6, fw), max(0.0, depth)
    th = math.radians(angle)
    cos_t, sin_t = math.cos(th), math.sin(th)
    cam = max(1.2, perspective) * max(w, h)

    def proj(x, y, z):
        xr, zr = x * cos_t - z * sin_t, x * sin_t + z * cos_t
        k = cam / (cam + zr)
        return xr * k, y * k

    hw, hh, hd = w / 2, h / 2, d / 2
    front = [proj(-hw, -hh, -hd), proj(hw, -hh, -hd), proj(hw, hh, -hd), proj(-hw, hh, -hd)]
    spine = [proj(-hw, -hh, hd), proj(-hw, -hh, -hd), proj(-hw, hh, -hd), proj(-hw, hh, hd)]
    if d <= 0 or spine[1][0] - spine[0][0] < 1e-4:
        spine = None
    pts = front + (spine or [])
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    margin = max(2, round(height * 0.01))
    s = (height - 2 * margin) / (maxy - miny)
    size = (round((maxx - minx) * s) + 2 * margin, height)

    def px(q):
        return [((x - minx) * s + margin, (y - miny) * s + margin) for x, y in q]

    return size, {"front": px(front), "spine": px(spine) if spine else None}


def finish_picture(img, max_height: int = 0, trim: bool = True, fmt: str = "png", background: str = "#ffffff"):
    """The saved picture: transparent margins cut, height limited, flattened for JPEG."""
    if trim:
        box = img.getchannel("A").point(lambda v: 255 if v > 6 else 0).getbbox()
        if box:
            pad = 2
            img = img.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad),
                            min(img.height, box[3] + pad)))
    if max_height and img.height > max_height:
        img = img.resize((max(1, round(img.width * max_height / img.height)), max_height), LANCZOS)
    if fmt == "jpg":
        flat = Image.new("RGB", img.size, hex_rgb(background))
        flat.paste(img, (0, 0), img.getchannel("A"))
        return flat
    return img


class Pictures:
    """One game's pictures, as loaded for a box."""

    def __init__(self, front=None, spine=None, full=None, logo=None, ctx=None, marquee=None):
        self.front, self.spine, self.full, self.logo, self.marquee = front, spine, full, logo, marquee
        self.ctx = ctx or {}
        self.generic = False            # the front is a generic cover made by this program

    def spine_for(self, profile):
        """Spine art and where it came from: its own picture, cut from Box - Full, made up, or none."""
        if self.spine is not None:
            return self.spine, "spine"
        if profile.get("spine_from_full") and self.full is not None:
            cut = spine_from_full(self.full, self.front)
            if cut is not None:
                return cut, "full"
        if profile.get("spine_generate", "logo") != "none" and self.front is not None:
            return None, "generate"
        return None, None


# ------------------------------------------------------------------------------------------------ generic covers
# An entry with no Box - Front at all (applications, and games that never had a box) gets a cover in one look for the
# whole platform, like generic boxes made for old computers: the platform's logo at the top and the game's name at the
# bottom, on silver with a diagonal mesh, with a black spine carrying the platform's name.
GC_KINDS = ("games", "applications", "demos", "educational", "compilations", "homebrew", "utilities", "programs",
            "manuals", "books", "catalogs", "magazines", "hardware", "technical", "video", "commercials", "music")
GC_KEYS = ("gc_style", "gc_bg", "gc_picture", "gc_ink", "gc_logo", "gc_logo_file", "gc_maker", "gc_name", "gc_title",
           "gc_spine")
GC_HEIGHT = 1400                     # height of a generic cover in pixels
GC_SPINE, GC_LIGHT = (14, 14, 16), (222, 226, 234)
_platform_logos: dict = {}


def platform_names(platform: str):
    """(small maker's line, big name) for a platform's drawn logo, from its name: "Commodore VIC-20 [Games] [PRG]" ->
    ("COMMODORE", "VIC-20"); "Tandy Radio Shack - TRS-80 Color Computer - Manuals" -> ("TANDY RADIO SHACK",
    "TRS-80 COLOR COMPUTER"); "2600 & VCS - Games" -> ("", "2600 & VCS")."""
    name = re.sub(r"\s*[\[(][^\])]*[\])]", "", platform or "").strip()
    parts = [p.strip() for p in re.split(r"\s+-\s+", name) if p.strip()]
    if len(parts) >= 2:
        if parts[1].casefold().startswith(GC_KINDS):
            return "", parts[0].upper()
        return parts[0].upper(), parts[1].upper()
    words = name.split()
    if len(words) >= 2:
        return words[0].upper(), " ".join(words[1:]).upper()
    return "", name.upper()


def gc_names(profile: dict, ctx: dict):
    """The drawn logo's small line and big name: the user's, else from the platform's name ("-" = no small line)."""
    maker, name = platform_names(ctx.get("lb_platform") or ctx.get("platform") or "")
    own_maker, own_name = (profile.get("gc_maker") or "").strip(), (profile.get("gc_name") or "").strip()
    if own_maker:
        maker = "" if own_maker == "-" else own_maker
    return maker, own_name or name or "?"


def platform_logo_file(lb_root, platform: str) -> str:
    """LaunchBox's own logo of a platform (Images\\Platforms\\<platform>\\Clear Logo), if it has one."""
    key = (str(lb_root), platform)
    if key not in _platform_logos:
        folder = Path(lb_root) / "Images" / "Platforms" / clean_name(platform) / "Clear Logo"
        try:
            files = sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS), key=lambda p: p.name.casefold())
        except OSError:
            files = []
        _platform_logos[key] = str(files[0]) if files else ""
    return _platform_logos[key]


def _fit(pic, width=None, height=None, grow=True):
    """A picture scaled to fit width x height, keeping its shape."""
    s = min(width / pic.width if width else float("inf"), height / pic.height if height else float("inf"))
    if not grow:
        s = min(1.0, s)
    return pic.resize((max(1, round(pic.width * s)), max(1, round(pic.height * s))), LANCZOS)


def striped_text(text: str, color, size: int = 300):
    """Big letters cut by thin horizontal lines: the 80s computer logo look."""
    pic = text_picture(text, load_font("Arial Black", size), tuple(color) + (255,), 0, (0, 0, 0, 0))
    step = max(4, round(size * 0.11))
    lines = Image.new("L", pic.size, 255)
    d = ImageDraw.Draw(lines)
    for y in range(0, pic.height, step):
        d.rectangle((0, y, pic.width, y + max(1, round(step * 0.32)) - 1), fill=0)
    pic.putalpha(ImageChops.multiply(pic.getchannel("A"), lines))
    return pic


def drawn_platform_logo(maker: str, name: str, color):
    """A platform's name as an 80s logo: the name in big striped letters; a number at its end is set big and solid on
    the right with the maker's line small beside it (as "LASER / COLOR COMPUTER 500")."""
    def small(text):
        return text_picture(text, load_font("Arial Bold", 110), tuple(color) + (255,), 0, (0, 0, 0, 0))

    split = re.match(r"(?i)^(.*[A-Z].*?)[\s-]+(\d[\dA-Z/]{0,5})$", name)
    if split:
        big = striped_text(split.group(1).strip(), color)
        num = _fit(text_picture(split.group(2), load_font("Arial Black", 300), tuple(color) + (255,), 0,
                                (0, 0, 0, 0)), height=big.height * 0.62)
        gap = round(big.height * 0.12)
        mk = None
        if maker:
            mk = _fit(small(maker), max(big.width - num.width - gap, big.width * 0.35), num.height * 0.42, grow=False)
        width = max(big.width, num.width + (mk.width + gap if mk is not None else 0))
        block = Image.new("RGBA", (width, big.height + gap // 2 + num.height), (0, 0, 0, 0))
        block.alpha_composite(big, ((width - big.width) // 2, 0))
        y = big.height + gap // 2
        block.alpha_composite(num, (width - num.width, y))
        if mk is not None:
            block.alpha_composite(mk, (0, y + num.height - mk.height - round(num.height * 0.06)))
        return block
    lines, words = [name], name.split()
    if len(name) > 12 and len(words) > 1:          # a long name: two lines
        cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    pics = [striped_text(line, color) for line in lines]
    widest = max(p.width for p in pics)
    gap = round(pics[0].height * 0.10)
    mk = _fit(small(maker), widest, pics[0].height * 0.36, grow=False) if maker else None
    height = sum(p.height for p in pics) + gap * (len(pics) - 1) + (gap + mk.height if mk is not None else 0)
    block = Image.new("RGBA", (widest, height), (0, 0, 0, 0))
    y = 0
    for p in pics:
        block.alpha_composite(p, ((widest - p.width) // 2, y))
        y += p.height + gap
    if mk is not None:
        block.alpha_composite(mk, ((widest - mk.width) // 2, y))
    return block


def cover_title(title: str) -> str:
    """A title as a cover shows it: without the (year)(publisher) [tags] of TOSEC-style names."""
    return re.sub(r"\s*[\[(][^\])]*[\])]", "", title or "").strip(" -") or (title or "").strip()


def title_picture(title: str, color, width: float):
    """The game's name for a cover: bold, in two lines when one line would have to shrink a lot."""
    font = load_font("Arial Black", 150)
    light = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2] > 140
    outline = (0, 0, 0, 150) if light else (255, 255, 255, 190)
    text = cover_title(title) or "?"
    pic = text_picture(text, font, tuple(color) + (255,), 4, outline)
    words = text.split()
    if pic.width > width * 1.6 and len(words) > 1:
        cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        pic = text_picture(" ".join(words[:cut]) + "\n" + " ".join(words[cut:]), font, tuple(color) + (255,), 4,
                           outline)
    return pic


def gc_background(size, style: str = "silver", color: str = "", picture: str = ""):
    """A generic cover's ground: silver or dark with a diagonal mesh, a plain colour, or the user's own picture."""
    w, h = size
    if style == "picture" and picture:
        try:
            return ImageOps.fit(load_picture(picture, 3000), (w, h), LANCZOS).convert("RGBA")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            log_line(f"generic cover picture {picture}: {exc}")
    radial = Image.radial_gradient("L").resize((w, h), BICUBIC)        # 0 in the middle, 255 at the edges
    if style == "color":
        c = hex_rgb(color, (217, 220, 225))
        middle = tuple(min(255, round(v + (255 - v) * 0.18)) for v in c)
        return Image.composite(Image.new("RGB", size, tuple(round(v * 0.72) for v in c)),
                               Image.new("RGB", size, middle), radial).convert("RGBA")
    dark = style == "dark"
    middle, edge = ((58, 62, 70), (16, 18, 22)) if dark else ((252, 252, 253), (176, 178, 184))
    img = Image.composite(Image.new("RGB", size, edge), Image.new("RGB", size, middle), radial)
    mesh = Image.new("L", size, 0)
    d = ImageDraw.Draw(mesh)
    lw = max(1, round(w / 450))
    for x in range(-2 * h, w + 2 * h, max(8, round(w * 0.049))):
        d.line([(x, 0), (x + h * 0.62, h)], fill=90, width=lw)
    for x in range(-2 * h, w + 2 * h, max(8, round(w * 0.067))):
        d.line([(x, h), (x + h * 0.95, 0)], fill=75, width=lw)
    fade = Image.linear_gradient("L").resize(size).point(lambda v: round(40 + v * 0.75))    # stronger lower down
    mesh = ImageChops.multiply(mesh.filter(ImageFilter.GaussianBlur(0.7)), fade)
    lines = (150, 156, 166) if dark else (110, 116, 126)
    return Image.composite(Image.new("RGB", size, lines), img, mesh).convert("RGBA")


def gc_ink(profile: dict):
    """The colour of the logo and the name (light letters on the dark ground when the chosen colour is dark)."""
    ink = hex_rgb(profile.get("gc_ink"), (29, 42, 68))
    if profile.get("gc_style") == "dark" and 0.299 * ink[0] + 0.587 * ink[1] + 0.114 * ink[2] < 110:
        ink = GC_LIGHT
    return ink


def gc_platform_logo(profile: dict, ctx: dict):
    """The platform's logo as a picture (LaunchBox's or the user's file), or None when it is to be drawn."""
    mode = profile.get("gc_logo", "auto")
    path = (profile.get("gc_logo_file") if mode == "picture" else ctx.get("platform_logo") if mode == "auto"
            else "") or ""
    return logo_file(path) if path else None


def generic_front(profile: dict, ctx: dict, game_logo=None, size=(995, GC_HEIGHT)):
    """A cover for a game with no Box - Front: the ground, the platform's logo at the top, the game's name at the
    bottom (its title, or its Clear Logo when chosen and there is one)."""
    w, h = size
    ink = gc_ink(profile)
    img = gc_background(size, profile.get("gc_style", "silver"), profile.get("gc_bg", ""), profile.get("gc_picture", ""))
    logo = gc_platform_logo(profile, ctx)
    if logo is None:
        logo = drawn_platform_logo(*gc_names(profile, ctx), ink)
    logo = _fit(logo, w * 0.80, h * 0.28)
    img.alpha_composite(logo, ((w - logo.width) // 2, round(h * 0.06)))
    if profile.get("gc_title") == "logo" and game_logo is not None:
        name = _fit(game_logo, w * 0.84, h * 0.22)
    else:
        name = _fit(title_picture(ctx.get("title", ""), ink, w * 0.84), w * 0.84, h * 0.20, grow=False)
    img.alpha_composite(name, ((w - name.width) // 2, round(h * 0.80 - name.height / 2)))
    return img


def generic_spine(profile: dict, ctx: dict, size):
    """A black spine with the platform's name down it (its logo picture, when it has one)."""
    w, h = size
    img = Image.new("RGBA", size, GC_SPINE + (255,))
    top = round(h * 0.05)
    logo = gc_platform_logo(profile, ctx)
    if logo is not None:
        pic = _fit(logo.rotate(-90, BICUBIC, expand=True), w * 0.78, h * 0.45)
        img.alpha_composite(pic, ((w - pic.width) // 2, top))
        return img
    maker, name = gc_names(profile, ctx)
    big = _fit(striped_text(name, GC_LIGHT).rotate(-90, BICUBIC, expand=True), w * 0.60, h * 0.50)
    img.alpha_composite(big, ((w - big.width) // 2, top))
    if maker:
        small = text_picture(maker, load_font("Arial Bold", 110), GC_LIGHT + (255,), 0, (0, 0, 0, 0))
        small = _fit(small.rotate(-90, BICUBIC, expand=True), w * 0.32, h * 0.30)
        img.alpha_composite(small, ((w - small.width) // 2, top + big.height + round(w * 0.25)))
    return img


def generic_pictures(profile: dict, pics, template=None, quads=None):
    """The game's pictures with a generic cover — and a black spine with the platform's name when it has no spine
    picture — when it has no Box - Front at all and the settings ask for one; else the pictures as they are."""
    if pics.front is not None or not profile.get("generic_cover", True) or \
            profile["faces"]["front"].get("source") != "launchbox":
        return pics
    aspect, spine_aspect = 135 / 190, 0.14 * 135 / 190      # a DVD-size case, as thick as the one in the video
    if template is not None and quads and quads.get("front"):
        fw, fh = face_size(quads["front"])
        aspect = fw / max(1.0, fh)
        if quads.get("spine"):
            sw, sh = face_size(quads["spine"])
            spine_aspect = sw / max(1.0, sh)
    ctx = pics.ctx
    settings = tuple(str(profile.get(k)) for k in GC_KEYS)
    where = (ctx.get("lb_platform") or ctx.get("platform", ""), ctx.get("platform_logo", ""))
    fsize = (max(64, round(GC_HEIGHT * aspect)), GC_HEIGHT)
    front = _memo(("gc-front", fsize, ctx.get("title", ""), id(pics.logo)) + where + settings, pics.logo,
                  lambda: generic_front(profile, ctx, pics.logo, fsize))
    spine = pics.spine
    if spine is None and profile.get("gc_spine", True):
        ssize = (max(12, round(GC_HEIGHT * spine_aspect)), GC_HEIGHT)
        spine = _memo(("gc-spine", ssize) + where + settings, None, lambda: generic_spine(profile, ctx, ssize))
    out = Pictures(front, spine, pics.full, pics.logo, ctx, pics.marquee)
    out.generic = True
    return out


# --------------------------------------------------------------------------------------------------------- discs
# A game's disc for LaunchBox's "Disc" pictures: the cover's art printed on a round label, with the centre hole, the
# clear hub and the silver ring real discs have, the game's Clear Logo on it and a line of text along the edge.
DISC_KINDS = {   # kind: (hole radius, where the label starts, colour of the silver), radii as parts of the disc's
    "cd": (0.125, 0.36, (205, 208, 214)),
    "dvd": (0.125, 0.30, (205, 208, 214)),
    "bluray": (0.125, 0.30, (176, 192, 222)),
    "psx": (0.125, 0.19, (58, 60, 66)),             # PlayStation: black discs, printed to the hub
    "gamecube": (0.1875, 0.30, (205, 208, 214)),     # 8 cm disc: a bigger hole for its size
    "picture": (0.125, 0.135, (205, 208, 214)),      # printed right to the hole
}
DISC_AUTO = (("gamecube", "gamecube"), ("playstation 3", "bluray"), ("playstation 4", "bluray"),
             ("playstation 5", "bluray"), ("xbox one", "bluray"), ("xbox series", "bluray"), ("wii u", "bluray"),
             ("playstation 2", "dvd"), ("xbox", "dvd"), ("wii", "dvd"), ("playstation", "psx"), ("psx", "psx"))


def disc_kind(profile: dict, platform: str = "") -> str:
    """The disc's kind: the one chosen, or one from the platform's name (PS2: DVD, PS3: Blu-ray, PS1: black disc…)."""
    kind = profile.get("disc_kind", "auto")
    if kind in DISC_KINDS:
        return kind
    name = (platform or "").casefold()
    return next((k for word, k in DISC_AUTO if word in name), "cd")


def _circle(size: int, radius: float):
    m = Image.new("L", (size, size), 0)
    c = size / 2
    ImageDraw.Draw(m).ellipse((c - radius, c - radius, c + radius, c + radius), fill=255)
    return m


def _silver(size: int, tint):
    """A disc's mirror side: light and dark sectors round the centre, as light falls on a CD."""
    grey = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(grey)
    for a in range(0, 360, 2):
        t = math.radians(a)
        d.pieslice((0, 0, size - 1, size - 1), a, a + 2.5,
                   fill=int(max(0, min(255, 168 + 58 * math.cos(2 * t) + 18 * math.cos(6 * t + 1.0)))))
    grey = grey.filter(ImageFilter.GaussianBlur(size / 300))
    dark = tuple(round(v * 0.35) for v in tint)
    light = tuple(min(255, round(v * 1.22)) for v in tint)
    return ImageOps.colorize(grey, dark, light).convert("RGBA")


def _disc_art(art, size: int, crop: str = "center", zoom: float = 1.0):
    """A square of the cover for the round label: its middle (or top, or bottom), zoomed in when asked."""
    side = min(art.size) / max(1.0, zoom)
    cx = art.width / 2
    cy = {"top": side / 2, "bottom": art.height - side / 2}.get(crop, art.height / 2)
    box = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
    return art.convert("RGBA").resize((size, size), LANCZOS, box=box)


def _ring_text(img, text: str, radius: float, color, position: str = "bottom") -> None:
    """A line of text along the disc's edge, reading left to right (in place)."""
    c = img.width / 2
    size = radius * 0.055
    font = load_font("Arial Bold", size)
    widths = [font.getlength(ch) for ch in text]
    rr = radius * 0.955 - size * 0.7
    if sum(widths) / rr > math.pi * 1.5:                  # too long for the edge: smaller letters
        size *= math.pi * 1.5 * rr / sum(widths)
        font = load_font("Arial Bold", size)
        widths = [font.getlength(ch) for ch in text]
    span = sum(widths) / rr
    top = position == "top"
    angle = -math.pi / 2 - span / 2 if top else math.pi / 2 + span / 2
    step = 1 if top else -1
    for ch, cw in zip(text, widths):
        mid = angle + step * (cw / 2) / rr
        angle += step * cw / rr
        if not ch.strip():
            continue
        glyph = text_picture(ch, font, tuple(color) + (255,), max(1, round(size * 0.06)), (0, 0, 0, 150))
        turn = -math.degrees(mid + math.pi / 2) if top else math.degrees(math.pi / 2 - mid)
        glyph = glyph.rotate(turn, BICUBIC, expand=True)
        x, y = c + rr * math.cos(mid), c + rr * math.sin(mid)
        img.alpha_composite(glyph, (round(x - glyph.width / 2), round(y - glyph.height / 2)))


def tidy_line(text: str) -> str:
    """A line made of fields, some of them empty ("Combat · © "): no separator or © left at an end or twice in a
    row."""
    line = " ".join((text or "").split())
    while True:
        new = re.sub(r"[©℗](?=\s+[·•|/–—-](?:\s|$))", "", line)                    # "© ·": a year was empty
        new = re.sub(r"(?<=\s)([·•|/–—-])(?:\s+[·•|/–—-])+(?=\s|$)", r"\1", " ".join(new.split()))
        new = re.sub(r"^[·•|/–—,:-]\s*|\s*(?:[·•|/–—,:-]|[©℗])$", "", new).strip()
        if new == line:
            return new
        line = new


def make_disc(art, profile: dict, ctx=None, logo=None, platform: str = "", size=None):
    """A disc picture (RGBA, round, transparent hole) printed with `art`."""
    s = max(200, int(size or profile.get("disc_size", 1000)))
    w = s * 2                                        # drawn twice as big for smooth circles
    r = w / 2
    hole, inner, tint = DISC_KINDS[disc_kind(profile, platform)]
    disc = _silver(w, tint)
    label_ring = ImageChops.subtract(_circle(w, r * 0.985), _circle(w, r * inner))
    disc.paste(_disc_art(art, w, profile.get("disc_crop", "center"), float(profile.get("disc_zoom", 1.0))), (0, 0),
               label_ring)
    gloss = Image.new("L", (w, w), 0)
    ImageDraw.Draw(gloss).polygon([(0, w * 0.30), (w, w * 0.04), (w, w * 0.16), (0, w * 0.42)], fill=36)
    gloss = ImageChops.multiply(gloss.filter(ImageFilter.GaussianBlur(w / 28)), label_ring)
    shine = Image.new("RGBA", (w, w), (255, 255, 255, 0))
    shine.putalpha(gloss)
    disc.alpha_composite(shine)
    if logo is not None:
        pic = _fit(logo, w * float(profile.get("disc_logo_size", 0.55)), r * 0.40)
        x, y = (w - pic.width) // 2, max(0, round(r - r * 0.64 - pic.height / 2))
        shadow = Image.new("RGBA", pic.size, (0, 0, 0, 0))
        shadow.putalpha(pic.getchannel("A").filter(ImageFilter.GaussianBlur(w / 260)).point(lambda v: v * 140 // 255))
        disc.alpha_composite(shadow, (x + max(1, w // 400), y + max(1, w // 400)))
        disc.alpha_composite(pic, (x, y))
    text = tidy_line(expand_text(profile.get("disc_text", ""), ctx or {}))
    if text:
        _ring_text(disc, text, r, hex_rgb(profile.get("disc_text_color", "#ffffff")),
                   profile.get("disc_text_pos", "bottom"))
    alpha = _circle(w, r * 0.995)
    hub = min(0.19, inner)
    if hub > hole + 0.01:                            # the clear plastic round the hole, with its stacking ring
        clear = ImageChops.subtract(_circle(w, r * hub), _circle(w, r * hole))
        disc.paste((226, 231, 238, 255), None, clear)
        ring = ImageChops.subtract(_circle(w, r * (hole + (hub - hole) * 0.56)),
                                   _circle(w, r * (hole + (hub - hole) * 0.44)))
        disc.paste((150, 156, 166, 255), None, ring)
        alpha = ImageChops.subtract(alpha, clear.point(lambda v: v * 140 // 255))
    alpha = ImageChops.subtract(alpha, _circle(w, r * hole))
    disc.putalpha(alpha)
    return disc.convert("RGBa").resize((s, s), LANCZOS).convert("RGBA")


def generic_disc_art(profile: dict, ctx: dict, size: int):
    """The generic cover laid out for a round label: the platform's logo high up, the game's name low down, both kept
    inside the circle."""
    ink = gc_ink(profile)
    img = gc_background((size, size), profile.get("gc_style", "silver"), profile.get("gc_bg", ""),
                        profile.get("gc_picture", ""))
    logo = gc_platform_logo(profile, ctx)
    if logo is None:
        logo = drawn_platform_logo(*gc_names(profile, ctx), ink)
    logo = _fit(logo, size * 0.50, size * 0.16)        # between the edge and the hub (which starts at 0.32)
    img.alpha_composite(logo, ((size - logo.width) // 2, round(size * 0.205 - logo.height / 2)))
    name = _fit(title_picture(ctx.get("title", ""), ink, size * 0.6), size * 0.60, size * 0.13, grow=False)
    img.alpha_composite(name, ((size - name.width) // 2, round(size * 0.765 - name.height / 2)))
    return img


def render_disc(profile: dict, pics, platform: str = "", size=None):
    """The disc of one game: from its Box - Front, else from a generic cover when those are on; None when neither."""
    s = max(200, int(size or profile.get("disc_size", 1000)))
    logo = (pics.logo or pics.marquee) if profile.get("disc_logo", True) else None
    art = pics.front
    if art is None:
        if not profile.get("generic_cover", True) or profile["faces"]["front"].get("source") != "launchbox":
            return None
        settings = tuple(str(profile.get(k)) for k in GC_KEYS)
        art = _memo(("gc-disc", s, pics.ctx.get("title", ""), pics.ctx.get("lb_platform", "")) + settings, None,
                    lambda: generic_disc_art(profile, pics.ctx, s * 2))
        logo = None                                  # the generic label already has the platform's logo
        profile = dict(profile, disc_crop="center", disc_zoom=1.0)
    return make_disc(art, profile, pics.ctx, logo, platform, s)


def case_window(face: str, size, rim_frac: float):
    """Where the art sits inside a keep case's rim on a w x h face: (x0, y0, x1, y1)."""
    w, h = size
    rim = max(2, round(h * rim_frac))
    if face == "front":
        return max(1, round(rim * 0.55)), rim, w - rim, h - rim
    return round(w * 0.06), rim, w - round(w * 0.06), h - rim


def case_face(art, face: str, color: str, rim_frac: float):
    """The art behind a plastic keep case: a coloured rim around it (perspective box, "case" style)."""
    w, h = art.size
    rim = max(2, round(h * rim_frac))
    rgb = hex_rgb(color, (122, 181, 29))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    if face == "front":
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=rim * 2, fill=rgb + (255,))
    else:
        d.rectangle((0, 0, w - 1, h - 1), fill=rgb + (255,))
    box = case_window(face, (w, h), rim_frac)
    lines = Image.new("RGBA", (w, h), (0, 0, 0, 0))     # drawn apart and laid on: drawing on RGBA would cut holes
    ld = ImageDraw.Draw(lines)
    if box[2] - box[0] > 2 and box[3] - box[1] > 2:
        inner = art.resize((box[2] - box[0], box[3] - box[1]), LANCZOS)
        out.alpha_composite(inner, (box[0], box[1]))
        ld.rectangle(box, outline=(0, 0, 0, 80), width=max(1, rim // 8))
    out.alpha_composite(lines)
    light = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(light).rounded_rectangle((0, 0, w - 1, h - 1), radius=rim * 2 if face == "front" else 0,
                                            outline=(255, 255, 255, 80), width=max(1, rim // 5))
    out.alpha_composite(light)
    return out


def face_canvas(face, pics, profile, size, spine=(None, None), case=None):
    """The flat art of one face (picture, colour or made-up spine, then texts and logos), or None to keep the case.

    spine: (art, origin) from Pictures.spine_for, worked out once per box. case: (colour, rim) for the keep case look.
    """
    fcfg = profile["faces"][face]
    w, h = max(2, round(size[0])), max(2, round(size[1]))
    source = fcfg.get("source", "launchbox")
    layers = profile["layers"].get(face) or []
    real_spine = face == "spine" and source == "launchbox" and spine[1] in ("spine", "full")
    if real_spine:          # logo slots meant for made-up spines stay off a real one
        layers = [ly for ly in layers if not ly.get("only_made")]
    canvas = None
    if source == "launchbox":
        if face == "front":
            if pics.front is not None:
                canvas = fit_into(pics.front, w, h, fcfg)
        else:
            art, origin = spine
            if art is not None:
                canvas = fit_into(art, w, h, fcfg)
            elif origin == "generate":
                own_logo = any(ly.get("kind") in ("clearlogo", "marquee") for ly in layers)
                band = (profile.get("band_source", "left"), profile.get("band_frac", 0.2),
                        profile.get("band_blur", 0.22), profile.get("band_dark", 0.7))
                canvas = make_spine(pics.front, pics.logo or pics.marquee, pics.ctx.get("title", ""), (w, h),
                                    profile.get("spine_generate", "logo"), profile.get("spine_font", "Arial Bold"),
                                    band, draw_logo=not own_logo)
    elif source == "color":
        canvas = Image.new("RGBA", (w, h), hex_rgb(fcfg.get("color", "#202020")) + (255,))
    if layers:
        if canvas is None:
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_layers(canvas, layers, pics.ctx, pics.logo, pics.marquee)
    if case is not None:
        if canvas is None:
            canvas = Image.new("RGBA", (w, h), hex_rgb(fcfg.get("color", "#202020")) + (255,))
        canvas = case_face(canvas, face, case[0], case[1])
    if canvas is not None and profile.get("shadows", True):
        canvas = shade(canvas, float(fcfg.get("shade", 0.0)), face)
    return canvas


def render_box(profile, template, quads, pics, *, height=1000, scale=1.0, ss=2, fast=False):
    """Draw one 3D box. template: the case (RGBA) or None for a box drawn in perspective.

    quads: corners in template pixels (template mode). height: box height in pixels (perspective mode).
    scale: render size relative to the template (previews). Returns (picture, quads in picture pixels).
    """
    pics = generic_pictures(profile, pics, template, quads)
    spine = pics.spine_for(profile) if profile["faces"]["spine"].get("source") == "launchbox" else (None, None)
    if template is None:
        gen = profile["generic"]
        front_wh = pics.front.size if pics.front is not None else (700, 1000)
        depth = float(gen.get("thickness", 0.13))
        art = spine[0]
        if gen.get("auto_thickness", True) and art is not None and pics.front is not None:
            ratio = (art.width / art.height) / (pics.front.width / pics.front.height)
            if 0.02 <= ratio <= 0.45:
                depth = ratio
        if profile["faces"]["spine"].get("source") == "none":
            depth = 0.0
        size, used = generic_layout(front_wh, depth, float(gen.get("angle", 24)), float(gen.get("perspective", 4)),
                                    max(16, round(height * scale)))
        base = Image.new("RGBA", size, (0, 0, 0, 0))
        tpl, light = None, False
    else:
        tint = (profile.get("tint") or "", profile.get("tint_mode", "multiply"), float(profile.get("tint_amount", 1.0)))
        if tint[0] and tint[2] > 0.01:
            template = _memo(("tint", id(template), template.size) + tint, template,
                             lambda: tint_picture(template, *tint))
        tpl = template if scale == 1 else _memo(
            ("scaled", id(template), template.size, round(scale, 4), fast), template,
            lambda: template.resize((max(1, round(template.width * scale)), max(1, round(template.height * scale))),
                                    BILINEAR if fast else LANCZOS))
        base = tpl.copy()
        used = {f: scale_quad(quads[f], scale) if quads.get(f) else None for f in FACES}
        mode = profile.get("overlay_mode", "auto")
        light = mode == "light" or (mode == "auto" and bool(quads.get("front")) and see_through(template, quads["front"]))
    sharpen = bool(profile.get("sharpen", True)) and not fast
    for face in ("spine", "front"):
        quad = used.get(face)
        fcfg = profile["faces"][face]
        if not quad or fcfg.get("source") == "none" or quad_area(quad) < 4:
            continue
        fw, fh = face_size(quad)
        case = None
        if tpl is None and profile["generic"].get("style") == "case":
            case = (profile["generic"].get("case_color", "#7ab51d"), float(profile["generic"].get("rim", 0.022)))
        art = face_canvas(face, pics, profile, (fw * ss, fh * ss), spine, case)
        if art is None:
            if tpl is None:   # perspective box without art for this face: plain colour
                art = Image.new("RGBA", (max(2, round(fw)), max(2, round(fh))), hex_rgb(fcfg.get("color", "#202020")) + (255,))
                art = shade(art, float(fcfg.get("shade", 0.0)), face) if profile.get("shadows", True) else art
            else:
                continue
        if tpl is not None:
            clean_area(base, quad, fcfg.get("clean", "original"), fcfg.get("clean_color", "#ffffff"))
        warp_onto(base, art, quad, float(fcfg.get("opacity", 1.0)), ss, sharpen)
        if tpl is not None and not fast and not light:
            details = _details_cached(template, scale, tpl, quad, float(profile.get("overlay", 0.0)))
            if details is not None:
                base.alpha_composite(details)
    if tpl is not None and not fast and light:
        faces = [used[f] for f in FACES if used.get(f) and profile["faces"][f].get("source") != "none"]
        light_layer(base, tpl, faces, float(profile.get("light_strength", 1.0)))
    if tpl is None and profile["generic"].get("edges", True) and used.get("front"):
        _box_edges(base, used, profile["generic"].get("style") == "case")
    if profile.get("sheen", True) and used.get("front") and not fast:
        add_sheen(base, used["front"])
    return base, used


_details_cache: dict = {}
_details_lock = threading.Lock()


def _details_cached(template, scale, tpl, quad, strength):
    """template_details for a case and corner set already seen (a batch reuses it for every game)."""
    key = (id(template), template.size, round(scale, 4), tuple((round(x, 2), round(y, 2)) for x, y in quad),
           round(strength, 3))
    with _details_lock:
        hit = _details_cache.get(key)
    if hit is not None:
        return hit[1]
    layer = template_details(tpl, quad, strength)
    with _details_lock:
        if len(_details_cache) > 12:
            _details_cache.clear()
        _details_cache[key] = (template, layer)   # the template stays referenced, so its id is not reused
    return layer


def _box_edges(base, quads, case_style: bool) -> None:
    """Thin light edge where front and spine meet; darker outer edges on a cardboard box (perspective box)."""
    ss = 3
    w, h = base.size
    lines = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(lines)
    width = max(1, round(h * ss / 700))
    front = [(x * ss, y * ss) for x, y in quads["front"]]
    spine = [(x * ss, y * ss) for x, y in quads["spine"]] if quads.get("spine") else None
    d.line([front[0], front[3]], fill=(255, 255, 255, 120), width=width)
    if not case_style:
        outline = (0, 0, 0, 70)
        d.line([front[0], front[1], front[2], front[3]], fill=outline, width=width)
        if spine:
            d.line([spine[1], spine[0], spine[3], spine[2]], fill=outline, width=width)
    base.alpha_composite(lines.reduce(ss))


# ------------------------------------------------------------------------------------------------- LaunchBox data
class Game:
    __slots__ = ("title", "gid", "platform", "region", "year", "developer", "publisher", "genre", "series", "version",
                 "key", "db_id")

    def __init__(self, el, platform):
        def text(tag):
            return (el.findtext(tag) or "").strip()
        self.title = text("Title")
        self.gid = text("ID")
        self.platform = text("Platform") or platform
        self.region = text("Region")
        self.year = text("ReleaseDate")[:4]
        self.developer = text("Developer")
        self.publisher = text("Publisher")
        self.genre = text("Genre")
        self.series = text("Series")
        self.version = text("Version")
        self.db_id = text("DatabaseID")
        self.key = clean_name(self.title).casefold()

    def context(self) -> dict:
        return {"title": self.title, "platform": self.platform, "year": self.year, "developer": self.developer,
                "publisher": self.publisher, "region": self.region, "genre": self.genre, "series": self.series,
                "version": self.version}


class MediaIndex:
    """Pictures of one LaunchBox media folder (and its region subfolders), by game title."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.items: dict[str, list] = {}
        self.lock = threading.Lock()
        try:
            top = list(os.scandir(folder))
        except OSError:
            return
        for entry in top:
            try:
                if entry.is_dir():
                    for sub in os.scandir(entry.path):
                        if sub.is_file():
                            self._add(entry.name, sub.name, sub.path)
                elif entry.is_file():
                    self._add("", entry.name, entry.path)
            except OSError:
                continue

    def _add(self, region, filename, path):
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in IMAGE_EXTS:
            return
        m = _NUM_RE.match(stem)
        name, num = (m.group("name"), int(m.group("num"))) if m else (stem, 0)
        item = (region, num, path)
        self.items.setdefault(name.casefold(), []).append(item)
        g = _GUID_RE.match(name)
        if g:
            self.items.setdefault(g.group("gid").casefold(), []).append(item)
            self.items.setdefault(g.group("title").casefold(), []).append(item)

    def add(self, region, path) -> None:
        with self.lock:
            self._add(region, os.path.basename(path), path)

    def all(self, game) -> list:
        with self.lock:
            hits = list(self.items.get(game.gid.casefold(), [])) if game.gid else []
            for item in self.items.get(game.key, []):
                if item not in hits:
                    hits.append(item)
        return hits

    def best(self, game, prefer: str | None = None):
        """(path, region folder) of the picture to use: the `prefer` region folder first (when given), then the
        main folder, then the game's region, then any other."""
        hits = self.all(game)
        if not hits:
            return None
        region = game.region.casefold()
        prefer = prefer.casefold() if prefer is not None else None

        def rank(item):
            r, num, path = item
            rc = r.casefold()
            if prefer is not None and rc == prefer:
                tier = -1
            else:
                tier = 0 if not r else 1 if rc == region else 2
            return (tier, num, path.casefold())

        r, _, path = min(hits, key=rank)
        return path, r


def same_region(a: str, b: str) -> bool:
    """Both pictures come from the same region folder (or both from the main folder)."""
    return (a or "").casefold() == (b or "").casefold()


class LaunchBox:
    """The parts of a LaunchBox folder this program uses: platforms, their games and their media folders."""

    def __init__(self, root):
        self.root = Path(root)
        self.platforms: list[str] = []
        self.xml_files: dict[str, str] = {}
        self.folders: dict = {}
        self.official: dict[str, str] = {}      # platform -> the LaunchBox Games DB name it is scraped as
        self._indexes: dict = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_launchbox(root) -> bool:
        return bool(root) and (Path(root) / "Data" / "Platforms").is_dir()

    def load(self) -> None:
        data = self.root / "Data"
        names = []
        platforms_xml = data / "Platforms.xml"
        if platforms_xml.is_file():
            for _, el in ET.iterparse(platforms_xml):
                if el.tag == "Platform" and el.find("Name") is not None:
                    name = (el.findtext("Name") or "").strip()
                    names.append(name)
                    self.official[name] = (el.findtext("ScrapeAs") or "").strip()
                    el.clear()
                elif el.tag == "PlatformFolder":
                    p, t, f = el.findtext("Platform"), el.findtext("MediaType"), el.findtext("FolderPath")
                    if p and t and f:
                        self.folders[(p.strip().casefold(), t.strip().casefold())] = f.strip()
                    el.clear()
        files = {}
        try:
            for entry in os.scandir(data / "Platforms"):
                if entry.is_file() and entry.name.lower().endswith(".xml"):
                    files[entry.name[:-4].casefold()] = entry.path
        except OSError:
            pass
        result, used = {}, set()
        for name in names:
            for key in (name.casefold(), clean_name(name).casefold()):
                if key in files:
                    result[name] = files[key]
                    used.add(key)
                    break
        for key, path in files.items():
            if key not in used:
                result[Path(path).stem] = path
        self.xml_files = result
        self.platforms = sorted(result, key=str.casefold)

    def media_folder(self, platform: str, media_type: str) -> Path:
        folder = self.folders.get((platform.casefold(), media_type.casefold()))
        path = Path(folder) if folder else Path("Images") / clean_name(platform) / media_type
        return path if path.is_absolute() else self.root / path

    def games(self, platform: str, stop=None) -> list[Game]:
        out = []
        path = self.xml_files.get(platform)
        if not path:
            return out
        for _, el in ET.iterparse(path):
            if el.tag in RECORD_TAGS:
                if el.tag == "Game":
                    game = Game(el, platform)
                    if game.title:
                        out.append(game)
                el.clear()
                if stop is not None and stop.is_set():
                    break
        return out

    def index(self, platform: str, media_type: str, refresh: bool = False) -> MediaIndex:
        folder = self.media_folder(platform, media_type)
        key = str(folder).casefold()
        with self._lock:
            idx = None if refresh else self._indexes.get(key)
        if idx is None:
            idx = MediaIndex(folder)
            with self._lock:
                self._indexes[key] = idx
        return idx

    def forget_indexes(self) -> None:
        with self._lock:
            self._indexes.clear()

    def find(self, platform: str, game: Game, profile: dict) -> dict:
        """Paths of the pictures a game's box is made from, and its Box - 3D pictures already there."""
        found = {"region": ""}
        for media_type in (FRONT_TYPES if profile.get("front_fallbacks", True) else FRONT_TYPES[:1]):
            hit = self.index(platform, media_type).best(game)
            if hit:
                found["front"], found["region"], found["front_type"] = hit[0], hit[1], media_type
                break
        region = found["region"]
        for key, media_type in (("spine", SPINE_TYPE), ("full", FULL_TYPE), ("logo", LOGO_TYPE),
                                ("marquee", MARQUEE_TYPE)):
            hit = self.index(platform, media_type).best(game, region)
            if not hit:
                continue
            # a Box - Full is checked against the front picture itself when the spine is cut out of it
            if key == "spine" and profile.get("match_region", True) and not same_region(region, hit[1]):
                found["spine_other_region"] = hit[0]
                continue
            found[key] = hit[0]
        found["box3d"] = [item[2] for item in self.index(platform, OUT_TYPE).all(game)]
        found["disc"] = [item[2] for item in self.index(platform, DISC_TYPE).all(game)]
        return found


def find_launchbox() -> str:
    """A LaunchBox folder on this PC: the one the user's other LaunchBox tools use first, then drive roots."""
    candidates = [r"D:\LaunchBox"]
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
        for name in ("LaunchBox", "Launchbox", "LaunchBox 2", "Games\\LaunchBox"):
            candidates.append(f"{letter}:\\{name}")
    for cand in candidates:
        try:
            if LaunchBox.is_launchbox(cand) and (Path(cand) / "LaunchBox.exe").is_file():
                return cand
        except OSError:
            continue
    return ""


def load_pictures(lb: LaunchBox, platform: str, game: Game, profile: dict, found: dict | None = None,
                  limit: int = 3000) -> tuple[Pictures, dict]:
    found = found if found is not None else lb.find(platform, game, profile)
    pics = Pictures(ctx=dict(game.context(), lb_platform=platform, platform_logo=platform_logo_file(lb.root, platform)))
    for key in ("front", "spine", "full", "logo", "marquee"):
        path = found.get(key)
        if path:
            try:
                setattr(pics, key, load_picture(path, limit if key not in ("logo", "marquee") else 1600))
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                log_line(f"cannot open {path}: {exc}")
    if pics.front is not None:
        pics.front = UPSCALER.apply(pics.front, found.get("front"), profile)     # small covers made sharper
    return pics, found


# ------------------------------------------------------------------------------------------- covers from the web
# A game with no Box - Front at all can get its real cover from the web before a generic one is made: libretro's
# thumbnail collection (box art named after No-Intro / Redump titles, for consoles and home computers) or Steam's
# library capsule (PC games). A cover found is saved as the game's Box - Front, as LaunchBox's own download would.
LIBRETRO_URL = "https://thumbnails.libretro.com"
STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/?term={term}&l=english&cc=US"
STEAM_ART = ("https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/library_600x900_2x.jpg",
             "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{id}/library_600x900_2x.jpg",
             "https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/library_600x900.jpg")
WEB_MODES = ("auto", "libretro", "steam", "off")
WEB_AGENT = f"LB3DBoxCreator/{APP_VERSION}"
CACHE_DIR = Path.home() / ".lb_box3d_creator_cache"
LIBRETRO_SYSTEMS = {   # LaunchBox Games DB platform names -> libretro's (others are matched by their words)
    "3do interactive multiplayer": "The 3DO Company - 3DO", "amstrad cpc": "Amstrad - CPC",
    "amstrad gx4000": "Amstrad - GX4000", "arcade": "MAME", "atari 2600": "Atari - 2600", "atari 5200": "Atari - 5200",
    "atari 7800": "Atari - 7800", "atari 800": "Atari - 8-bit", "atari xegs": "Atari - 8-bit",
    "atari jaguar": "Atari - Jaguar", "atari jaguar cd": "Atari - Jaguar", "atari lynx": "Atari - Lynx",
    "atari st": "Atari - ST", "bandai wonderswan": "Bandai - WonderSwan",
    "bandai wonderswan color": "Bandai - WonderSwan Color", "coleco colecovision": "Coleco - ColecoVision",
    "colecovision": "Coleco - ColecoVision", "commodore 64": "Commodore - 64", "commodore amiga": "Commodore - Amiga",
    "commodore amiga cd32": "Commodore - CD32", "amiga cd32": "Commodore - CD32", "commodore cdtv": "Commodore - CDTV",
    "commodore pet": "Commodore - PET", "commodore plus 4": "Commodore - Plus-4", "commodore vic-20": "Commodore - VIC-20",
    "emerson arcadia 2001": "Emerson - Arcadia 2001", "entex adventure vision": "Entex - Adventure Vision",
    "epoch super cassette vision": "Epoch - Super Cassette Vision", "fairchild channel f": "Fairchild - Channel F",
    "gce vectrex": "GCE - Vectrex", "magnavox odyssey 2": "Magnavox - Odyssey2", "philips videopac+": "Philips - Videopac+",
    "mattel intellivision": "Mattel - Intellivision", "microsoft msx": "Microsoft - MSX", "microsoft msx2": "Microsoft - MSX2",
    "microsoft xbox": "Microsoft - Xbox", "microsoft xbox 360": "Microsoft - Xbox 360", "ms-dos": "DOS",
    "nec pc-8801": "NEC - PC-8001 - PC-8801", "nec pc-9801": "NEC - PC-98", "nec pc-fx": "NEC - PC-FX",
    "nec turbografx-16": "NEC - PC Engine - TurboGrafx 16", "nec pc engine": "NEC - PC Engine - TurboGrafx 16",
    "nec turbografx-cd": "NEC - PC Engine CD - TurboGrafx-CD", "nec pc engine supergrafx": "NEC - PC Engine SuperGrafx",
    "nec supergrafx": "NEC - PC Engine SuperGrafx", "nintendo 3ds": "Nintendo - Nintendo 3DS",
    "nintendo 64": "Nintendo - Nintendo 64", "nintendo 64dd": "Nintendo - Nintendo 64DD", "nintendo ds": "Nintendo - Nintendo DS",
    "nintendo entertainment system": "Nintendo - Nintendo Entertainment System",
    "nintendo famicom disk system": "Nintendo - Family Computer Disk System", "nintendo game boy": "Nintendo - Game Boy",
    "nintendo game boy advance": "Nintendo - Game Boy Advance", "nintendo game boy color": "Nintendo - Game Boy Color",
    "nintendo gamecube": "Nintendo - GameCube", "nintendo pokemon mini": "Nintendo - Pokemon Mini",
    "nintendo satellaview": "Nintendo - Satellaview", "nintendo sufami turbo": "Nintendo - Sufami Turbo",
    "super nintendo entertainment system": "Nintendo - Super Nintendo Entertainment System",
    "nintendo virtual boy": "Nintendo - Virtual Boy", "nintendo wii": "Nintendo - Wii", "nintendo wii u": "Nintendo - Wii U",
    "philips cd-i": "Philips - CD-i", "rca studio ii": "RCA - Studio II", "sega 32x": "Sega - 32X",
    "sega cd": "Sega - Mega-CD - Sega CD", "sega dreamcast": "Sega - Dreamcast", "sega game gear": "Sega - Game Gear",
    "sega genesis": "Sega - Mega Drive - Genesis", "sega mega drive": "Sega - Mega Drive - Genesis",
    "sega master system": "Sega - Master System - Mark III", "sega naomi": "Sega - Naomi", "sega pico": "Sega - PICO",
    "sega saturn": "Sega - Saturn", "sega sg-1000": "Sega - SG-1000", "sharp x1": "Sharp - X1",
    "sharp x68000": "Sharp - X68000", "sinclair zx-81": "Sinclair - ZX 81", "sinclair zx spectrum": "Sinclair - ZX Spectrum",
    "snk neo geo aes": "SNK - Neo Geo", "snk neo geo mvs": "SNK - Neo Geo", "snk neo geo cd": "SNK - Neo Geo CD",
    "snk neo geo pocket": "SNK - Neo Geo Pocket", "snk neo geo pocket color": "SNK - Neo Geo Pocket Color",
    "sony playstation": "Sony - PlayStation", "sony playstation 2": "Sony - PlayStation 2",
    "sony playstation 3": "Sony - PlayStation 3", "sony playstation 4": "Sony - PlayStation 4",
    "sony psp": "Sony - PlayStation Portable", "sony playstation vita": "Sony - PlayStation Vita",
    "spectravideo": "Spectravideo - SVI-318 - SVI-328", "thomson mo/to": "Thomson - MOTO",
    "tiger game.com": "Tiger - Game.com", "vtech creativision": "VTech - CreatiVision", "vtech v.smile": "VTech - V.Smile",
    "watara supervision": "Watara - Supervision", "casio pv-1000": "Casio - PV-1000", "casio loopy": "Casio - Loopy",
    "funtech super acan": "Funtech - Super Acan", "hartung game master": "Hartung - Game Master",
    "gamepark gp32": "GamePark - GP32", "scummvm": "ScummVM", "sinclair zx81": "Sinclair - ZX 81",
    "nintendo super game boy": "Nintendo - Game Boy", "nintendo dsi": "Nintendo - Nintendo DSi",
    "sega naomi 2": "Sega - Naomi 2", "sammy atomiswave": "Atomiswave", "arduboy": "Arduboy Inc - Arduboy",
    "amiga cdtv": "Commodore - CDTV", "nintendo famicom": "Nintendo - Nintendo Entertainment System",
    "nintendo super famicom": "Nintendo - Super Nintendo Entertainment System", "sega mark iii":
    "Sega - Master System - Mark III", "sega mega-cd": "Sega - Mega-CD - Sega CD",
    "leapfrog leapster": "LeapFrog - Leapster Learning Game System",
}
REGION_TAGS = {   # a game's region in LaunchBox: the words of No-Intro / Redump / TOSEC names that fit it, best first
    "north america": {"usa", "us", "canada", "ca"}, "united states": {"usa", "us"}, "canada": {"canada", "ca", "usa", "us"},
    "europe": {"europe", "eu", "uk", "gb", "germany", "de", "france", "fr"}, "united kingdom": {"uk", "gb", "europe", "eu"},
    "germany": {"germany", "de", "europe", "eu"}, "france": {"france", "fr", "europe", "eu"},
    "spain": {"spain", "es", "europe", "eu"}, "italy": {"italy", "it", "europe", "eu"},
    "australia": {"australia", "au", "europe", "eu"}, "japan": {"japan", "jp"}, "world": {"world"},
    "brazil": {"brazil", "br", "usa", "us"}, "korea": {"korea", "kr"}, "asia": {"asia"}}
REGION_NAMES = {"usa", "europe", "japan", "world", "asia", "korea", "brazil", "canada", "australia", "germany", "france",
                "spain", "italy", "uk", "netherlands", "sweden", "china", "taiwan", "hong", "kong", "russia", "poland",
                "scandinavia", "latin", "america", "denmark", "finland", "norway", "portugal", "greece", "unknown"}
BAD_TAGS = re.compile(r"\b(beta|proto(type)?|demo|sample|hack(ed)?|pirate|promo|kiosk)\b")
EDITION_WORDS = {"edition", "complete", "definitive", "remastered", "remaster", "enhanced", "legacy", "goty", "game",
                 "of", "the", "year", "deluxe", "gold", "ultimate", "anniversary", "directors", "director", "cut", "hd",
                 "special", "classic", "redux", "premium", "standard", "digital", "expanded"}
_web_lock = threading.Lock()
_web_next = [0.0]
_web_down: dict = {}       # host: until when it is not asked again (it did not answer three times in a row)
WEB_DOWN_SECONDS = 120
WEB_GAP = 0.25             # seconds between two downloads (four a second at most)
_cache_lock = threading.Lock()
_cache_mem: dict = {}


def web_get(url: str, timeout: float = 40.0, tries: int = 3) -> bytes:
    """One download from the web, spaced out (four a second at most) and tried again after a dropped connection;
    "not found" (urllib.error.HTTPError) comes back at once. A server that does not answer at all is left alone for
    two minutes, so a batch with no internet does not wait on every game."""
    host = urllib.parse.urlsplit(url).netloc
    if _web_down.get(host, 0.0) > time.time():
        raise OSError(f"{host} did not answer a moment ago")
    for attempt in range(tries):
        with _web_lock:
            wait = _web_next[0] - time.time()
            if wait > 0:
                time.sleep(wait)
            _web_next[0] = time.time() + WEB_GAP
        try:
            req = urllib.request.Request(url, headers={"User-Agent": WEB_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 403, 404, 410) or attempt == tries - 1:
                raise
            exc.close()
        except (OSError, http.client.HTTPException):
            if attempt == tries - 1:
                _web_down[host] = time.time() + WEB_DOWN_SECONDS
                raise
        time.sleep(1.5 * (attempt + 1))
    raise OSError("no answer")


def _cached_list(name: str, days: float, make, refresh: bool = False) -> list:
    """A list downloaded once and kept (in memory and in the cache folder) for `days`."""
    with _cache_lock:
        if not refresh and name in _cache_mem:
            return _cache_mem[name]
        path = CACHE_DIR / name
        if not refresh:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if time.time() - float(data["time"]) < days * 86400 and isinstance(data["items"], list):
                    _cache_mem[name] = data["items"]
                    return data["items"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        items = make()
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps({"time": time.time(), "items": items}), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
        _cache_mem[name] = items
        return items


def _listing(url: str) -> list:
    """The entries of a web server's folder page."""
    page = web_get(url).decode("utf-8", "replace")
    return [urllib.parse.unquote(h) for h in re.findall(r'href="([^"?/][^"]*)"', page)]


def libretro_systems(refresh: bool = False) -> list:
    return _cached_list("libretro-systems.json", 14, lambda: [h[:-1] for h in _listing(LIBRETRO_URL + "/")
                                                              if h.endswith("/")], refresh)


def libretro_names(system: str, refresh: bool = False) -> list:
    """The box art libretro has for a system: its file names without ".png" (No-Intro / Redump style)."""
    url = f"{LIBRETRO_URL}/{urllib.parse.quote(system)}/Named_Boxarts/"
    key = re.sub(r"[^A-Za-z0-9]+", "_", system).strip("_")

    def make():
        try:
            return [h[:-4] for h in _listing(url) if h.lower().endswith(".png")]
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 404, 410):
                raise
            exc.close()
            return []                                 # no such system (or no box art for it): kept as "none"

    return _cached_list(f"libretro-{key}.json", 14, make, refresh)


def title_key(title: str) -> str:
    """A title reduced for matching: lower case, without tags, accents and punctuation, "&" as "and", a moved-back
    article put first again ("Legend of Zelda, The - A Link to the Past")."""
    t = re.sub(r"\s*[\[(][^\])]*[\])]", " ", title or "")
    moved = re.match(r"^(.*?), (The|A|An)\b(.*)$", t, re.IGNORECASE)
    if moved:
        t = f"{moved.group(2)} {moved.group(1)}{moved.group(3)}"
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^0-9a-z]+", " ", t.replace("'", "")).split())


def _region_words(name: str) -> set:
    """The region words of a No-Intro / Redump / TOSEC name — "(USA, Europe)", "(GB)", "(DE-GB)" — and never the
    words of a publisher such as "(US Gold)"."""
    words = set()
    for tag in re.findall(r"\(([^)]*)\)", name):
        parts = [p for p in re.split(r"[\s,\-]+", tag.casefold()) if p]
        if parts and all(p in REGION_NAMES or len(p) == 2 and p.isalpha() for p in parts):
            words.update(parts)
    return words


def libretro_match(title: str, region: str, names) -> str:
    """The libretro name for a game: the same title (only spaces and punctuation may differ: a near title can be
    another game, "Monster Mash" is not "Monster Smash!"), the game's own region first, never a beta or demo when
    there is a release; "" when there is none."""
    key = title_key(title)
    if not key:
        return ""
    index = _memo(("libretro-index", id(names)), names, lambda: _key_index(names))
    hits = index.get(key) or index.get("~" + key.replace(" ", ""), [])
    if not hits:
        return ""
    want = REGION_TAGS.get((region or "").casefold(), set())

    def rank(name):
        inside = " ".join(re.findall(r"[\[(]([^\])]*)[\])]", name)).casefold()
        regions = _region_words(name)
        score = (4 if regions & want else 0) + (2 if "world" in regions else 0) + \
            (1 if regions & {"usa", "us", "europe", "eu"} else 0) - (6 if BAD_TAGS.search(inside) else 0) - \
            (1 if "[" in name else 0)
        return score, -len(name)

    return max(hits, key=rank)


def _key_index(names) -> dict:
    """Names by their title key, and by that key without spaces ("~pacman": "Pac-Man" and "PacMan" are one)."""
    index: dict = {}
    for name in names:
        key = title_key(name)
        index.setdefault(key, []).append(name)
        index.setdefault("~" + key.replace(" ", ""), []).append(name)
    return index


def platform_base(platform: str, official: str = "") -> str:
    """The plain name of a platform: LaunchBox's own (ScrapeAs), else its name, without [tags]."""
    return re.sub(r"\s*[\[(][^\])]*[\])]", "", official or platform or "").strip()


NOT_GAMES = ("manual", "magazine", "book", "catalog", "catalogue", "hardware", "video", "commercial", "comic",
             "newsletter", "overlay", "artwork", "technical", "bulletin", "flyer", "poster", "soundtrack", "music",
             "guide", "advert", "scan", "map", "brochure", "documentation", "photo", "wallpaper")


def _words(text: str) -> list:
    return re.findall(r"[0-9a-z]+", (text or "").casefold())


def not_games(platform: str) -> bool:
    """A platform of manuals, magazines, books, videos and the like: their entries are named after games, but a
    game's box is not their cover, so the web is never asked for them on its own."""
    return any(w in NOT_GAMES or w.endswith("s") and w[:-1] in NOT_GAMES for w in _words(platform))


def libretro_system(platform: str, official: str = "", systems=None) -> str:
    """libretro's name for a platform: from the table, else the system whose model the platform's name starts with,
    after its maker or not ("ZX Spectrum - Games" and "Atari 2600/VCS" are "Sinclair - ZX Spectrum" and "Atari -
    2600"; numbers must agree, so never "Atari - 7800"; "Nintendo Game & Watch" is not "Nintendo - Game Boy", nor
    "Your 64" a Commodore 64); "" when none fits, and for platforms of manuals, magazines, videos…"""
    if not_games(platform) or not_games(official):
        return ""
    base = platform_base(platform, official)
    hit = LIBRETRO_SYSTEMS.get(base.casefold())
    if hit:
        return hit
    words = _words(base)
    numbers = {w for w in words if w.isdigit()}
    best, best_rank = "", (0, 0.0)
    for system in systems or sorted(set(LIBRETRO_SYSTEMS.values())):
        parts = system.split(" - ")
        sw = set(_words(system))
        if len(parts) < 2 or numbers - sw:
            continue                                   # "DOOM", "MAME": only from the table
        maker = _words(parts[0])
        for part in parts[1:]:
            model = _words(part)
            if model and (words[:len(model)] == model or words[:len(maker) + len(model)] == maker + model):
                rank = (len(model), len(set(words) & sw) / len(set(words) | sw))     # the fullest model first
                if rank > best_rank:
                    best, best_rank = system, rank
    return best


def web_source(platform: str, official: str = "", mode: str = "auto", system: str = "") -> str:
    """Where a platform's missing covers are looked for on the web, in words ("" = nowhere)."""
    if mode not in WEB_MODES or mode == "off":
        return ""
    places = []
    if mode in ("auto", "libretro"):
        system = system or libretro_system(platform, official)
        if system:
            places.append(f"libretro: {system}")
    if mode == "steam" or mode == "auto" and is_pc_platform(platform, official) and not not_games(platform):
        places.append("Steam")
    return ", ".join(places)


def is_pc_platform(platform: str, official: str = "") -> bool:
    base = platform_base(platform, official).casefold()
    return base.startswith(("windows", "microsoft windows", "ms-dos", "dos", "pc games", "steam")) or base == "pc"


def steam_cover(title: str):
    """(picture bytes, ".jpg", where) of a game's portrait cover on Steam (its 600x900 library capsule), or None."""
    term = cover_title(title)
    found = json.loads(web_get(STEAM_SEARCH.format(term=urllib.parse.quote(term))).decode("utf-8") or "{}")
    items = [i for i in found.get("items") or [] if isinstance(i, dict) and i.get("type") == "app" and i.get("id")]
    key = title_key(term)
    if not key:
        return None

    def fit(item):
        """0 for the same title, the length of an edition's words ("— Remastered", "Enhanced") added, else None."""
        k = title_key(str(item.get("name") or ""))
        if k == key or k.replace(" ", "") == key.replace(" ", ""):
            return 0
        if k.startswith(key + " ") and set(k[len(key) + 1:].split()) <= EDITION_WORDS:
            return len(k) - len(key)
        return None

    ranked = sorted((fit(item), n) for n, item in enumerate(items) if fit(item) is not None)
    if not ranked:
        return None
    pick = items[ranked[0][1]]
    for url in STEAM_ART:
        try:
            data = web_get(url.format(id=int(pick["id"])))
        except urllib.error.HTTPError as exc:
            exc.close()
            continue
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.height > im.width:
                    return data, ".jpg", f"Steam: {pick.get('name')} ({pick['id']})"
        except (OSError, ValueError):
            continue
    return None


PLATFORM_REGIONS = {"eu": "Europe", "europe": "Europe", "pal": "Europe", "usa": "North America", "us": "North America",
                    "jp": "Japan", "jap": "Japan", "japan": "Japan"}


def platform_region(platform: str) -> str:
    """The region a platform's name tells ("Sony Playstation EU", "NES [Games][USA]"), for games without their own."""
    return next((PLATFORM_REGIONS[w] for w in _words(platform) if w in PLATFORM_REGIONS), "")


def find_cover_online(platform: str, official: str, game, mode: str = "auto", system: str = ""):
    """A missing Box - Front from the web: (picture bytes, extension, where it came from), or None."""
    if mode == "off":
        return None
    pc = is_pc_platform(platform, official) and not not_games(platform)
    if mode in ("auto", "libretro"):
        system = system or libretro_system(platform, official)
        if system:
            name = libretro_match(game.title, game.region or platform_region(platform), libretro_names(system))
            if name:
                url = f"{LIBRETRO_URL}/{urllib.parse.quote(system)}/Named_Boxarts/{urllib.parse.quote(name)}.png"
                return web_get(url), ".png", f"libretro: {system} / {name}"
    if mode == "steam" or (mode == "auto" and pc):
        return steam_cover(game.title)
    return None


def save_web_cover(lb: LaunchBox, platform: str, game, data: bytes, ext: str) -> Path:
    """A cover from the web saved as the game's Box - Front (main folder, LaunchBox's naming, never over a file)."""
    with Image.open(io.BytesIO(data)) as im:
        im.verify()                                   # a picture, not an error page
    folder = lb.media_folder(platform, FRONT_TYPES[0])
    folder.mkdir(parents=True, exist_ok=True)
    base, n = clean_name(game.title), 1
    path = folder / f"{base}-01{ext}"
    while path.exists():
        n += 1
        path = folder / f"{base}-{n:02d}{ext}"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    lb.index(platform, FRONT_TYPES[0]).add("", str(path))
    return path


def fetch_missing_cover(lb: LaunchBox, platform: str, game, profile: dict, found: dict):
    """When a game has no Box - Front at all: its cover from the web, saved into LaunchBox, with `found` updated.
    Returns (path or None, what happened)."""
    if found.get("front") or profile.get("web_covers", "auto") == "off":
        return None, ""
    hit = find_cover_online(platform, lb.official.get(platform, ""), game, profile.get("web_covers", "auto"),
                            profile.get("web_system", ""))
    if hit is None:
        return None, "not found"
    data, ext, where = hit
    path = save_web_cover(lb, platform, game, data, ext)
    found.update(front=str(path), region="", front_type=FRONT_TYPES[0])
    return path, where


# ------------------------------------------------------------------------------------------------ saving to LaunchBox
def output_target(lb: LaunchBox, platform: str, game: Game, found: dict, export: dict, media_type: str = OUT_TYPE):
    """Where a new Box - 3D (or Disc) goes: (path, region folder, existing file it replaces or None), or None to
    skip."""
    folder = lb.media_folder(platform, media_type)
    ext = ".jpg" if export.get("format", "png") == "jpg" else ".png"
    base = clean_name(game.title)
    existing = found.get("disc" if media_type == DISC_TYPE else "box3d") or []
    policy = export.get("existing", "skip")
    if existing and policy == "skip":
        return None
    if existing and policy == "replace":
        hit = lb.index(platform, media_type).best(game)     # the picture LaunchBox shows first
        if hit:
            old = Path(hit[0])
            return old.with_suffix(ext), hit[1], [str(old)]
    region = found.get("region", "") if export.get("region", "same") == "same" else ""
    target_dir = folder / region if region else folder
    numbers, in_dir = [], []
    for path in existing:
        m = _NUM_RE.match(Path(path).stem)
        if m:
            numbers.append(int(m.group("num")))
    try:
        for entry in os.scandir(target_dir):
            stem, e = os.path.splitext(entry.name)
            m = _NUM_RE.match(stem)
            if m and m.group("name").casefold() == base.casefold() and e.lower() in IMAGE_EXTS:
                in_dir.append((int(m.group("num")), entry.path))
                numbers.append(int(m.group("num")))
    except OSError:
        pass
    if policy == "next" and numbers:
        return target_dir / f"{base}-{max(numbers) + 1:02d}{ext}", region, None
    return target_dir / f"{base}-01{ext}", region, [p for n, p in in_dir if n == 1]


def batch_make(lb: LaunchBox, platform: str, games, profile: dict, template, quads: dict, export: dict,
               stop: threading.Event, backup: Path, height: int, progress=None) -> dict:
    """Make and save the Box - 3D and / or the Disc of many games (several threads). A game with no Box - Front gets
    its cover from the web first when the settings say so, else a generic cover. Returns counts of what happened."""
    counts = {"saved": 0, "discs": 0, "covers": 0, "generic": 0, "skipped": 0, "nofront": 0, "errors": 0, "dup": 0}
    targets, lock = set(), threading.Lock()
    fmt = export.get("format", "png")
    max_h = int(export.get("max_height") or 0)
    kinds = [kind for kind, on in ((OUT_TYPE, export.get("make_box", True)), (DISC_TYPE, export.get("make_disc", False)))
             if on]
    for kind in kinds:
        lb.index(platform, kind, refresh=True)
    needs_front = profile["faces"]["front"].get("source") == "launchbox"

    def claim(path):
        with lock:
            key = str(path).casefold()
            if key in targets:
                return False
            targets.add(key)
            return True

    def one(game):
        if stop.is_set():
            return ["stopped"], game, ""
        try:
            found = lb.find(platform, game, profile)
            plan = [(kind, output_target(lb, platform, game, found, export, kind)) for kind in kinds]
            plan = [(kind, target) for kind, target in plan if target is not None]
            if not plan:
                return ["skipped"], game, ""
            done_here, info = [], ""
            if needs_front and not found.get("front"):
                try:
                    cover, info = fetch_missing_cover(lb, platform, game, profile, found)
                except (OSError, ValueError, http.client.HTTPException) as exc:    # the web is out of reach
                    cover, info = None, f"{TEXTS['web_failed']}: {exc}"
                if cover is not None:
                    done_here.append("covers")
                elif profile.get("generic_cover", True):
                    done_here.append("generic")
                else:
                    return ["nofront"], game, info
            pics, _ = load_pictures(lb, platform, game, profile, found)
            for kind, (path, region, replaced) in plan:
                if not claim(path):
                    done_here.append("dup")
                    continue
                if kind == DISC_TYPE:
                    img = render_disc(profile, pics, platform)
                    if img is None:
                        continue
                    out = finish_picture(img, 0, False, fmt, export.get("jpg_bg", "#ffffff"))
                else:
                    img, _ = render_box(profile, template, quads, pics, height=height)
                    out = finish_picture(img, max_h, bool(export.get("trim", True)), fmt,
                                         export.get("jpg_bg", "#ffffff"))
                save_picture(out, path, replaced, backup if replaced else None, lb.root, fmt)
                lb.index(platform, kind).add(region, str(path))
                done_here.append("discs" if kind == DISC_TYPE else "saved")
            return done_here, game, info
        except Exception as exc:  # noqa: BLE001 - one bad picture must not stop the rest
            log_line(f"{game.title}: {traceback.format_exc()}")
            return ["errors"], game, f"{type(exc).__name__}: {exc}"

    done = in_a_row = made_games = error_games = 0
    aborted = ""
    threads = max(1, min(16, int(export.get("threads") or 1)))
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(one, g) for g in games]
        for fut in as_completed(futures):
            happened, game, info = fut.result()
            done += 1
            for what in happened:
                if what in counts:
                    counts[what] += 1
            # box3d's circuit breaker: something is wrong (disk full, folder gone...) when games keep failing
            if "errors" in happened:
                in_a_row += 1
                error_games += 1
            elif "saved" in happened or "discs" in happened:
                in_a_row = 0
                made_games += 1
            tried = made_games + error_games
            if not aborted and (in_a_row >= ABORT_IN_A_ROW or tried >= 10 and error_games > ABORT_SHARE * tried):
                aborted = "in_a_row" if in_a_row >= ABORT_IN_A_ROW else "share"
                stop.set()
            if progress is not None:
                status = "errors" if "errors" in happened else (happened[0] if happened else "")
                progress(done, len(games), counts, status, game, info)
    counts["aborted"] = aborted
    return counts


ABORT_IN_A_ROW, ABORT_SHARE = 10, 0.20


def batch_plan(found_list, existing: str = "skip", need_front: bool = True, generic: bool = False,
               kinds=(OUT_TYPE,), web: bool = False):
    """What a run would do: (games to make something for, games skipped as all they need is there, games left out
    as they have no Box - Front, games among those to make that have no Box - Front: a cover from the web or a
    generic one)."""
    make = skip = nofront = covers = 0
    for found in found_list:
        missing = need_front and not found.get("front")
        if missing and not (generic or web):
            nofront += 1
            continue
        todo = [k for k in kinds if not (existing == "skip" and found.get("disc" if k == DISC_TYPE else "box3d"))]
        if not todo:
            skip += 1
        else:
            make += 1
            covers += missing
    return make, skip, nofront, covers


def save_picture(img, path: Path, replaced, backup_root: Path | None, lb_root: Path, fmt: str) -> None:
    """Write atomically; files it replaces go to the backup folder first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in replaced or []:
        old = Path(old)
        if backup_root is not None and old.is_file():
            try:
                rel = old.relative_to(lb_root)
            except ValueError:
                rel = Path(old.name)
            dest = backup_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, dest)
    tmp = path.with_name(path.name + ".tmp")
    if fmt == "jpg":
        img.save(tmp, "JPEG", quality=93, optimize=True)
    else:
        img.save(tmp, "PNG", compress_level=6)
    os.replace(tmp, path)
    for old in replaced or []:
        if Path(old) != path and os.path.isfile(old):
            os.remove(old)


# =================================================================================================== AI templates
# A case template painted by a local Stable Diffusion that Stability Matrix runs: Forge / SD.Next / Automatic1111
# (their /sdapi/v1 API, on when they start with --api) or ComfyUI. The program draws the empty case in perspective
# (or takes the current template), the AI repaints that picture as a photo (img2img: the case stays where it was
# drawn), and the result is cut out along the drawn outline. The cover areas become see-through except for the
# reflections the AI painted on them (laid over the art as light, like box3d's templates); their corners, known from
# the drawing, go into a box3d profile next to the picture.
AI_CASES = {   # name: (prompt words, front width / height, spine width / front width, look, case colour)
    "DVD case (black) — PS2, Xbox, GameCube, PC": ("black plastic DVD keep case", 135 / 190, 0.10, "case", "#161616"),
    "Xbox 360 case (green)": ("green plastic Xbox 360 game case", 135 / 190, 0.10, "case", "#64a019"),
    "Xbox One / Series case (green)": ("green plastic Xbox One game case", 135 / 170, 0.09, "case", "#107c10"),
    "Blu-ray case (blue) — PS4, PS5": ("blue transparent plastic Blu-ray game case", 135 / 170, 0.09, "case",
                                       "#0b52c9"),
    "PS3 case (black)": ("black plastic PlayStation 3 Blu-ray game case", 135 / 170, 0.09, "case", "#202020"),
    "Wii case (white)": ("white plastic Nintendo Wii game case", 135 / 190, 0.10, "case", "#f0f0f0"),
    "Wii U case (blue)": ("blue plastic Nintendo Wii U game case", 135 / 170, 0.09, "case", "#1d8bd6"),
    "Switch case (red)": ("red plastic Nintendo Switch game case", 105 / 170, 0.10, "case", "#e60012"),
    "DS / 3DS case (white)": ("white plastic Nintendo DS game case", 125 / 137, 0.11, "case", "#ececec"),
    "PSP / PS Vita case (clear)": ("clear plastic PSP game case", 105 / 180, 0.12, "case", "#d8dde2"),
    "CD jewel case — PS1, Saturn, Mega-CD, PC": ("clear plastic CD jewel case", 142 / 125, 0.07, "case", "#d8dde2"),
    "Mega Drive / Genesis case (black)": ("black plastic Sega Mega Drive clamshell game case", 136 / 188, 0.15,
                                          "case", "#161616"),
    "Big box (PC, cardboard)": ("cardboard PC game big box", 190 / 235, 0.25, "box", "#cfcfcf"),
    "Cartridge box (NES, SNES, N64, cardboard)": ("cardboard video game cartridge box", 127 / 178, 0.28, "box",
                                                  "#cfcfcf"),
    "Steelbook (metal)": ("metal steelbook game case", 135 / 175, 0.06, "case", "#8a8f96"),
}
AI_DEFAULT_CASE = "DVD case (black) — PS2, Xbox, GameCube, PC"
AI_NEGATIVE = ("text, letters, words, logo, label, artwork, picture on the cover, watermark, signature, hands, person, "
               "several objects, cropped, blurry, low resolution, deformed, bent, cartoon, drawing")
AI_BG_TOP, AI_BG_BOTTOM, AI_COVER = (220, 222, 226), (176, 179, 184), (36, 39, 44)
AI_SIZES = (768, 1024, 1280)
AI_PREVIEWS = ("box", "template", "picture", "guide")
AI_FAST_WORDS = ("lightning", "turbo", "hyper", "lcm", "dmd")
AI_DEFAULTS = {"url": "", "package": "", "sm_exe": "", "source": "case", "case": AI_DEFAULT_CASE, "angle": 30.0,
               "thickness": 0.10, "color": "", "model": "", "prompt": "", "negative": AI_NEGATIVE, "strength": 0.6,
               "steps": 28, "cfg": 6.0, "variants": 2, "seed": "", "size": 1024, "gloss": 1.0, "height": 1500,
               "preview": "box"}
SM_EXE = "StabilityMatrix.exe"
SM_WEBUIS = {"stable-diffusion-webui", "stable-diffusion-webui-forge", "forge-neo", "reforge", "automatic",
             "stable-diffusion-webui-directml", "stable-diffusion-webui-amdgpu-forge", "sd-webui-forge-classic"}
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # local servers: never through a proxy


class AIError(Exception):
    """A message for the user: the AI server is not there, has no API, failed…"""


class AIStopped(Exception):
    """The user stopped the painting."""


def ai_settings(cfg: dict) -> dict:
    """The AI window's settings as kept in the config, completed and checked."""
    raw = cfg.get("ai") if isinstance(cfg.get("ai"), dict) else {}
    out = dict(AI_DEFAULTS)
    for key, value in raw.items():
        if key in out and _same_kind(value, out[key]):
            out[key] = value
    if out["case"] not in AI_CASES:
        out["case"] = AI_DEFAULT_CASE
    if out["source"] not in ("case", "template"):
        out["source"] = "case"
    if out["size"] not in AI_SIZES:
        out["size"] = 1024
    if out["preview"] not in AI_PREVIEWS:
        out["preview"] = "box"
    cfg["ai"] = out
    return out


def ai_prompt(case: str) -> str:
    """The prompt for a kind of case (it asks for a blank cover: the game's own art goes there)."""
    words, _ratio, _thick, look, _color = AI_CASES.get(case, AI_CASES[AI_DEFAULT_CASE])
    cover = ("blank glossy dark cover under a clear plastic sleeve, no print" if look == "case"
             else "blank dark unprinted sides, no print")
    return (f"studio product photo of an empty {words}, three-quarter view with the spine on the left, {cover}, "
            "soft studio lighting, subtle reflections, plain light grey background, sharp focus, photorealistic, "
            "high detail")


def ai_fast_model(name: str) -> bool:
    """A distilled model (Lightning, Turbo, Hyper, LCM): a few steps at a low CFG."""
    return any(word in (name or "").casefold() for word in AI_FAST_WORDS)


def model_key(name: str) -> str:
    """A checkpoint's name without folder, [hash] and extension: servers report the same model differently."""
    base = re.sub(r"\s*\[[0-9a-fA-F]+\]\s*$", "", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf|sft)$", "", base, flags=re.IGNORECASE).casefold()


def ai_default_model(names, current: str = "") -> str:
    """The checkpoint to start with: the one the server has loaded, else a photo-style SDXL one."""
    if current:
        same = next((n for n in names if model_key(n) == model_key(current)), None)
        if same:
            return same
    for want in ("juggernautxl", "realvisxl", "albedobase", "epicrealismxl", "dreamshaperxl", "sdxl", "xl"):
        for name in names:
            key = name.casefold()
            if want in key and not any(bad in key for bad in ("inpaint", "refiner", "pony", "flux", "unet")):
                return name
    return names[0] if names else ""


def sub_quad(quad, size, box):
    """Where the part box = (x0, y0, x1, y1) of a w x h face lands on its quad."""
    w, h = size
    hm = homography([(0, 0), (w, 0), (w, h), (0, h)], quad)
    x0, y0, x1, y1 = box
    return [apply_h(hm, x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]


def _ai_canvas(aspect: float, base: int):
    """A picture size of about base x base pixels (what the models are made for), in steps of 64."""
    aspect = max(0.25, min(4.0, aspect))
    h = math.sqrt(base * base / aspect)
    return max(256, int(round(aspect * h / 64)) * 64), max(256, int(round(h / 64)) * 64)


def _ai_place(src_size, base: int, room: float):
    """The canvas for a picture of src_size with `room` (a fraction of its height) around it, and how the picture
    goes in: (canvas size, scale, x offset, y offset)."""
    bw, bh = src_size
    pad = room * bh
    size = _ai_canvas((bw + 2 * pad) / (bh + 2 * pad), base)
    s = min(size[0] / (bw + 2 * pad), size[1] / (bh + 2 * pad))
    return size, s, (size[0] - bw * s) / 2, (size[1] - bh * s) / 2


def _ai_background(size):
    """Studio grey, lighter at the top."""
    column = Image.new("RGB", (1, 256))
    column.putdata([tuple(round(a + (b - a) * t / 255) for a, b in zip(AI_BG_TOP, AI_BG_BOTTOM)) for t in range(256)])
    return column.resize(size, BILINEAR)


def ai_guide(case: str = AI_DEFAULT_CASE, angle: float = 30.0, thickness: float | None = None, color: str = "",
             base: int = 1024, rim: float = 0.022):
    """The picture the AI starts from: an empty case of an AI_CASES kind drawn in perspective on studio grey.
    Returns (guide RGB, the case's outline L, cover areas {"front", "spine"}), all in guide pixels."""
    _words, ratio, thick, look, case_color = AI_CASES.get(case, AI_CASES[AI_DEFAULT_CASE])
    depth = thick if thickness is None else max(0.0, float(thickness))
    (bw, bh), faces = generic_layout((ratio * 1000, 1000), depth, float(angle), 3.0, 1000)
    size, s, ox, oy = _ai_place((bw, bh), base, 0.08)
    faces = {f: [(ox + x * s, oy + y * s) for x, y in q] if q else None for f, q in faces.items()}
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    windows = {"front": None, "spine": None}
    for face in ("spine", "front"):
        quad = faces.get(face)
        if not quad:
            continue
        fw, fh = face_size(quad)
        w, h = max(2, round(fw * 2)), max(2, round(fh * 2))
        art = Image.new("RGBA", (w, h), AI_COVER + (255,))
        if look == "case":
            art = case_face(art, face, color or case_color, rim)
            windows[face] = sub_quad(quad, (w, h), case_window(face, (w, h), rim))
        else:
            windows[face] = [tuple(p) for p in quad]
        warp_onto(layer, shade(art, 0.06 if face == "front" else 0.22, face), quad, 1.0, 2)
    if faces.get("front"):
        _box_edges(layer, faces, look == "case")
    guide = _ai_background(size).convert("RGBA")
    guide.alpha_composite(layer)
    return guide.convert("RGB"), layer.getchannel("A"), windows


def ai_guide_from_template(template, quads, base: int = 1024):
    """A template as the AI's starting picture: on studio grey, its cover areas painted the blank cover colour.
    Returns (guide, outline, cover areas) like ai_guide."""
    tw, th = template.size
    size, s, ox, oy = _ai_place((tw, th), base, 0.05)
    nw, nh = max(1, round(tw * s)), max(1, round(th * s))
    x0, y0 = round(ox), round(oy)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.paste(template.convert("RGBA").resize((nw, nh), LANCZOS), (x0, y0))
    windows = {}
    for face in FACES:
        q = quads.get(face)
        windows[face] = [(x0 + x * nw / tw, y0 + y * nh / th) for x, y in q] if q and valid_quad(q) else None
        if windows[face]:
            layer.paste(AI_COVER + (255,), None, quad_mask(size, windows[face], 2))
    guide = _ai_background(size).convert("RGBA")
    guide.alpha_composite(layer)
    return guide.convert("RGB"), layer.getchannel("A"), windows


def _hist_percentile(hist, q: float) -> int:
    total = sum(hist)
    if not total:
        return 0
    acc, goal = 0, total * q
    for value, n in enumerate(hist):
        acc += n
        if acc >= goal:
            return value
    return len(hist) - 1


def ai_template(picture, outline, windows, gloss: float = 1.0, height: int = 1500):
    """The AI's picture made into a case template: cut along the drawn outline, the cover areas see-through except
    for the reflections the AI painted on them (they light the art, like box3d's templates), cropped, `height` px
    high. Returns (RGBA template, its corners {"front", "spine"})."""
    size = outline.size
    rgb = picture.convert("RGB")
    if rgb.size != size:
        rgb = rgb.resize(size, LANCZOS)
    alpha = outline.filter(ImageFilter.MinFilter(3))        # a pixel in: no studio-grey fringe
    masks = {f: quad_mask(size, q, 2) for f, q in windows.items() if q}
    if masks:
        win = None
        for m in masks.values():
            win = m if win is None else ImageChops.lighter(win, m)
        lum = ImageOps.grayscale(rgb).filter(ImageFilter.GaussianBlur(1.2))
        hist = lum.histogram(win.point(lambda v: 255 if v > 160 else 0))
        floor, peak = _hist_percentile(hist, 0.4), _hist_percentile(hist, 0.995)
        # the brightest reflections become ~43 % white; a soft sheen is raised at most 4x so it shows at all
        k = min(4.0, 110.0 / max(1, peak - floor)) * max(0.0, float(gloss))
        shine = lum.point(lambda v: 0 if v <= floor else min(230, round((v - floor) * k)))
        front = masks.get("front")
        if front is not None:      # mostly see-through, so the program lays it over the art as light by itself
            top = _hist_percentile(shine.histogram(front.point(lambda v: 255 if v > 160 else 0)), 0.55)
            if top > 48:
                shine = shine.point(lambda v, f=48 / top: round(v * f))
        rgb = Image.composite(Image.new("RGB", size, (255, 255, 255)), rgb, win.point(lambda v: 255 if v >= 128 else 0))
        alpha = Image.composite(shine, alpha, win)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    box = outline.point(lambda v: 255 if v > 8 else 0).getbbox() or (0, 0) + tuple(size)
    x0, y0 = max(0, box[0] - 4), max(0, box[1] - 4)
    x1, y1 = min(size[0], box[2] + 4), min(size[1], box[3] + 4)
    out = out.crop((x0, y0, x1, y1))
    quads = {f: [(x - x0, y - y0) for x, y in q] if q else None for f, q in windows.items()}
    if height and out.height != height:
        s = height / out.height
        out = out.convert("RGBa").resize((max(1, round(out.width * s)), int(height)), LANCZOS).convert("RGBA")
        quads = {f: scale_quad(q, s) if q else None for f, q in quads.items()}
    return out, {f: quads.get(f) for f in FACES}


def save_ai_template(img, quads, name: str, meta: dict, folder=None) -> Path:
    """Write an AI template and its box3d profile (the corners known from the drawing) into the templates folder,
    never over another file."""
    folder = Path(folder or MODEL_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .") or "AI case"
    path, n = folder / f"{stem}.png", 2
    while path.exists() or path.with_suffix(".json").exists():
        path, n = folder / f"{stem} {n}.png", n + 1
    data = box3d_profile(path.stem, img.size, quads, default_profile())
    data["description"] = f"{name} (painted by AI, made with {APP_NAME})"
    data["ai"] = meta
    tmp = path.with_name(path.name + ".tmp")
    img.save(tmp, "PNG", compress_level=6)
    os.replace(tmp, path)
    tmp = path.with_name(path.stem + ".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path.with_suffix(".json"))
    return path


# ---------------------------------------------------------------------------------------------- Stability Matrix
def find_stability_matrix(remembered: str = ""):
    """StabilityMatrix.exe: the one chosen before, else on a drive root or in a StabilityMatrix folder there, or in
    the user's Programs / Downloads / Desktop."""
    candidates = [Path(remembered)] if remembered else []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
        candidates += [Path(f"{letter}:\\") / SM_EXE, Path(f"{letter}:\\") / "StabilityMatrix" / SM_EXE]
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "StabilityMatrix" / SM_EXE)
    home = Path.home()
    candidates += [home / "Downloads" / SM_EXE, home / "Desktop" / SM_EXE, home / "StabilityMatrix" / SM_EXE]
    for cand in candidates:
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def sm_library(exe):
    """Stability Matrix's data folder: Data beside a portable exe, else the one %APPDATA%\\StabilityMatrix names."""
    if exe:
        data = Path(exe).parent / "Data"
        if (data / ".sm-portable").exists() or (data / "settings.json").is_file():
            return data
    home = Path(os.environ.get("APPDATA", str(Path.home()))) / "StabilityMatrix"
    for name, key in (("library.json", "LibraryPath"), ("global.json", "LibraryDir")):
        try:
            value = json.loads((home / name).read_text(encoding="utf-8-sig")).get(key)
        except (OSError, ValueError, AttributeError):
            continue
        if value and (Path(value) / "settings.json").is_file():
            return Path(value)
    return None


def sm_packages(library) -> list:
    """The packages Stability Matrix has installed that can paint for this program — web UIs with the Automatic1111
    API and ComfyUI — with the address each one listens on (only their names, ids and launch options are read)."""
    if not library:
        return []
    try:
        data = json.loads((Path(library) / "settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    active = str(data.get("ActiveInstalledPackage") or "")
    found = []
    for pkg in data.get("InstalledPackages") or []:
        if not isinstance(pkg, dict):
            continue
        package = str(pkg.get("PackageName") or "")
        key = package.casefold()
        if key.startswith("comfyui"):
            kind, port, api = "comfy", 8188, True
        elif key in SM_WEBUIS or "forge" in key or "webui" in key:
            kind, port, api = "a1111", 7860, key == "automatic"        # SD.Next has its API on all the time
        else:
            continue
        port_given = False
        for arg in pkg.get("LaunchArgs") or []:
            if not isinstance(arg, dict):
                continue
            name, value = str(arg.get("Name") or ""), arg.get("OptionValue")
            text = value if isinstance(value, str) else ""
            if name == "--port" and text.strip().isdigit():
                port, port_given = int(text.strip()), True
            elif name == "--api" and value is True:
                api = True
            if re.search(r"(^|\s)--api(\s|$)", text):
                api = True
            given = re.search(r"--port[= ](\d+)", text)
            if given:
                port, port_given = int(given.group(1)), True
        pid = str(pkg.get("Id") or "")
        url = f"http://127.0.0.1:{port}"
        # a web UI started without --port takes the next free port when 7860 is taken (on this PC other programs'
        # own connections can hold it), so those are looked at too
        more = [f"http://127.0.0.1:{p}" for p in range(7861, 7870)] if kind == "a1111" and not port_given else []
        found.append({"name": str(pkg.get("DisplayName") or package), "id": pid, "package": package, "kind": kind,
                      "url": url, "urls": [url] + more, "api": api, "active": bool(pid) and pid == active})
    return found


def find_ai_server(url: str, others=()):
    """(server, None) for the server at url or at one of a package's other likely addresses, else (None, the
    problem at url: a web UI without its API) or (None, None) when nothing answers."""
    url = AIServer.normalize(url)
    problem = None
    for address in [url] + [a for a in others if AIServer.normalize(a) != url]:
        try:
            server = AIServer.detect(address, timeout=3.0 if address == url else 1.5)
        except AIError as exc:
            if address == url:
                problem = exc
            continue
        if server is not None:
            return server, None
    return None, problem


def sm_running() -> bool:
    """Is Stability Matrix open? (It lets only one copy run.)"""
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {SM_EXE}", "/NH", "/FO", "CSV"], capture_output=True,
                             text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return SM_EXE.casefold() in (out.stdout or "").casefold()


def sm_launch(exe, package_id: str) -> None:
    """Open Stability Matrix and have it start one of its packages (its --launch-package switch)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe), "--launch-package", package_id], cwd=str(Path(exe).parent), close_fds=True,
                     creationflags=flags)


# ------------------------------------------------------------------------------------------- the AI server
def _http(url: str, data=None, timeout: float = 10.0, headers=None) -> bytes:
    """One request to a local server: POST when there is data (JSON for a dict or list, bytes as they are)."""
    hdrs = dict(headers or {})
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data is not None else "GET")
    with _NO_PROXY.open(req, timeout=timeout) as resp:
        return resp.read()


def _json_call(url: str, data=None, timeout: float = 10.0):
    raw = _http(url, data, timeout)
    return json.loads(raw.decode("utf-8")) if raw.strip() else None


def _png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _b64_picture(data):
    """A picture sent as base64 (with or without a data: header), or None."""
    if not isinstance(data, str) or not data:
        return None
    try:
        return Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[-1]))).convert("RGB")
    except (ValueError, OSError):
        return None


def _multipart(fields: dict, files: dict):
    """A multipart/form-data body (ComfyUI's picture upload) and its Content-Type."""
    boundary = "----lb3d" + uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    for key, (filename, blob, ctype) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                     f'Content-Type: {ctype}\r\n\r\n'.encode() + blob + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _server_error(exc) -> str:
    """What a failed request says, short."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
        except (ValueError, OSError):
            body = None
        finally:
            exc.close()
        text = ""
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):                   # ComfyUI
                text = str(err.get("message") or err.get("type") or "")
                details = []
                for node in (body.get("node_errors") or {}).values():
                    for e in (node.get("errors") or []) if isinstance(node, dict) else []:
                        if isinstance(e, dict):
                            details.append(f"{e.get('message', '')}: {e.get('details', '')}".strip(": "))
                if details:
                    text += " — " + "; ".join(details[:3])
            else:                                       # the web UIs (FastAPI)
                text = str(body.get("detail") or body.get("errors") or err or "")
        return f"HTTP {exc.code}: {text or exc.reason}"[:600]
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return str(exc) or type(exc).__name__


def _dropped(exc) -> bool:
    """Did the server close the connection instead of answering? (Not: refused, timed out or said no.)"""
    cause = exc.__cause__ if isinstance(exc, AIError) else exc
    if isinstance(cause, urllib.error.HTTPError):
        return False
    if isinstance(cause, urllib.error.URLError):
        cause = cause.reason
    return isinstance(cause, (ConnectionResetError, ConnectionAbortedError, http.client.IncompleteRead,
                              http.client.RemoteDisconnected))


def _comfy_failure(status: dict) -> str:
    for item in status.get("messages") or []:
        if isinstance(item, list) and len(item) == 2 and item[0] == "execution_error" and isinstance(item[1], dict):
            info = item[1]
            return f"{info.get('node_type', '')}: {info.get('exception_message', '')}".strip(": ")[:600]
    return "ComfyUI could not paint the picture"


class AIServer:
    """A local Stable Diffusion server: a web UI with the Automatic1111 API (Forge, SD.Next, A1111: /sdapi/v1, on
    when started with --api) or ComfyUI (/prompt). Stability Matrix starts them on 127.0.0.1:7860 and :8188."""

    def __init__(self, url: str, kind: str, name: str = ""):
        self.url, self.kind = url.rstrip("/"), kind
        self.name = name or ("ComfyUI" if kind == "comfy" else "Stable Diffusion WebUI")
        self.current = ""                  # the checkpoint a web UI has loaded
        self.samplers: list = []
        self.schedulers: list = []
        self.client_id = uuid.uuid4().hex
        self.prompt_id = ""

    @staticmethod
    def normalize(url: str) -> str:
        url = (url or "").strip().rstrip("/")
        if url and "://" not in url:
            url = "http://" + url
        return url

    def call(self, path: str, data=None, timeout: float = 30.0):
        try:
            return _json_call(self.url + path, data, timeout)
        except (OSError, ValueError, http.client.HTTPException) as exc:   # URLError and HTTPError are OSErrors
            raise AIError(_server_error(exc)) from exc

    @classmethod
    def detect(cls, url: str, timeout: float = 3.0):
        """The server at url, or None when nothing answers there; AIError for a web UI without its API."""
        url = cls.normalize(url)
        if not url:
            return None
        try:
            stats = _json_call(url + "/system_stats", timeout=timeout)
        except urllib.error.HTTPError as exc:      # answers, but is not ComfyUI
            exc.close()
            stats = None
        except ValueError:
            stats = None
        except OSError:
            return None
        if isinstance(stats, dict) and isinstance(stats.get("system"), dict):
            return cls(url, "comfy", f"ComfyUI {stats['system'].get('comfyui_version') or ''}".strip())
        try:
            state = _json_call(url + "/sdapi/v1/progress?skip_current_image=true", timeout=timeout)
        except urllib.error.HTTPError as exc:
            exc.close()
            state = None
        except ValueError:
            state = None
        except OSError:
            return None
        if isinstance(state, dict) and "progress" in state:
            return cls(url, "a1111")
        raise AIError(TEXTS["ai_no_api"].format(url=url))

    def models(self):
        """(checkpoint names, the one a web UI has loaded or "")."""
        if self.kind == "comfy":
            info = self.call("/object_info/CheckpointLoaderSimple") or {}
            try:
                spec = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"]
            except (KeyError, TypeError):
                return [], ""
            names = []
            if isinstance(spec, list) and spec:
                if isinstance(spec[0], list):                               # [[names], {...}]
                    names = spec[0]
                elif len(spec) > 1 and isinstance(spec[1], dict):           # ["COMBO", {"options": [names]}]
                    names = spec[1].get("options") or []
            return [str(n) for n in names], ""
        items = self.call("/sdapi/v1/sd-models") or []
        names = [str(m.get("title") or m.get("model_name")) for m in items if isinstance(m, dict)]
        for path, attr in (("/sdapi/v1/samplers", "samplers"), ("/sdapi/v1/schedulers", "schedulers")):
            try:
                found = self.call(path) or []
            except AIError:
                found = []
            setattr(self, attr, [str(x.get("label") or x.get("name")) if attr == "schedulers" else str(x.get("name"))
                                 for x in found if isinstance(x, dict)])
        try:
            self.current = str((self.call("/sdapi/v1/options") or {}).get("sd_model_checkpoint") or "")
        except AIError:
            self.current = ""
        return names, self.current

    def sampler_for(self, model: str):
        """(sampler, scheduler) for a model, from those the server has."""
        fast = ai_fast_model(model)
        if self.kind == "comfy":
            return ("dpmpp_sde" if fast else "dpmpp_2m"), "karras"
        wanted = ("DPM++ SDE", "DPM++ SDE Karras", "Euler a") if fast else ("DPM++ 2M", "DPM++ 2M Karras", "Euler a")
        sampler = next((s for s in wanted if s in self.samplers), self.samplers[0] if self.samplers else "Euler a")
        scheduler = "Karras" if "Karras" in self.schedulers and "Karras" not in sampler else ""
        return sampler, scheduler

    def has_loaded(self, name: str) -> bool:
        """Is this the checkpoint the web UI has loaded? (Forge reports it with or without folder and [hash].)"""
        return bool(self.current) and model_key(name) == model_key(self.current)

    def set_model(self, name: str) -> None:
        """Have a web UI load another checkpoint (it stays loaded afterwards, as when chosen on its own page)."""
        if self.kind != "a1111" or not name or self.has_loaded(name):
            return
        self.call("/sdapi/v1/options", {"sd_model_checkpoint": name}, timeout=1800)
        self.current = name

    def img2img(self, guide, prompt: str, negative: str, *, model: str, strength: float, steps: int, cfg: float,
                seed: int, progress=None, stop=None):
        """One picture painted over `guide` (same size). progress(fraction or None, preview or None) is called
        while it works; `stop` (an Event) ends it with AIStopped."""
        if self.kind == "comfy":
            return self._comfy(guide, prompt, negative, model, strength, steps, cfg, seed, progress, stop)
        sampler, scheduler = self.sampler_for(model)
        payload = {"init_images": [base64.b64encode(_png_bytes(guide)).decode("ascii")], "prompt": prompt,
                   "negative_prompt": negative, "denoising_strength": float(strength), "steps": int(steps),
                   "cfg_scale": float(cfg), "width": guide.width, "height": guide.height, "seed": int(seed),
                   "sampler_name": sampler, "batch_size": 1, "n_iter": 1, "resize_mode": 0, "save_images": False,
                   "send_images": True}
        if scheduler:
            payload["scheduler"] = scheduler
        answer = None
        for attempt in (1, 2):
            done = threading.Event()
            if progress is not None:
                threading.Thread(target=self._watch, args=(done, progress), daemon=True).start()
            try:
                answer = self.call("/sdapi/v1/img2img", payload, timeout=1800)
                break
            except AIError as exc:
                if stop is not None and stop.is_set():
                    raise AIStopped() from exc
                # a busy web UI on Windows now and then drops a finished reply: ask once more (same seed, same picture)
                if attempt == 2 or not _dropped(exc):
                    raise
                log_line(f"AI: {self.url} dropped its reply ({exc}); asking again")
            finally:
                done.set()
        if stop is not None and stop.is_set():
            raise AIStopped()
        images = (answer or {}).get("images") if isinstance(answer, dict) else None
        pictures = [p for p in (_b64_picture(i) for i in images or []) if p is not None]
        if not pictures:
            raise AIError("the server sent no picture")
        return pictures[0]

    def _watch(self, done, progress):
        """Ask the web UI how far it is, over one kept-open connection: a new connection for every question means
        many connections opened and closed next to the waiting one, which a busy web UI on Windows handles badly."""
        parts = urllib.parse.urlsplit(self.url)
        make = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        path = parts.path.rstrip("/") + "/sdapi/v1/progress?skip_current_image=false"
        conn = None
        try:
            while not done.wait(1.0):
                try:
                    if conn is None:
                        conn = make(parts.hostname, parts.port, timeout=8)
                    conn.request("GET", path)
                    state = json.loads(conn.getresponse().read().decode("utf-8"))
                except (OSError, ValueError, http.client.HTTPException):
                    if conn is not None:
                        conn.close()
                    conn = None
                    continue
                if isinstance(state, dict) and not done.is_set():
                    progress(float(state.get("progress") or 0.0), _b64_picture(state.get("current_image")))
        finally:
            if conn is not None:
                conn.close()

    def _comfy_upload(self, img, name: str) -> str:
        """A picture put into ComfyUI's input folder (overwriting this program's own file); its name there."""
        body, ctype = _multipart({"overwrite": "true", "type": "input"}, {"image": (name, _png_bytes(img), "image/png")})
        try:
            sent = json.loads(_http(self.url + "/upload/image", body, 60, {"Content-Type": ctype}).decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise AIError(_server_error(exc)) from exc
        image = str(sent.get("name") or name) if isinstance(sent, dict) else name
        if isinstance(sent, dict) and sent.get("subfolder"):
            image = f"{sent['subfolder']}/{image}"
        return image

    def upscalers(self) -> list:
        """The upscale models (ESRGAN and the like) the server can use."""
        if self.kind == "comfy":
            info = self.call("/object_info/UpscaleModelLoader") or {}
            try:
                spec = info["UpscaleModelLoader"]["input"]["required"]["model_name"]
            except (KeyError, TypeError):
                return []
            names = []
            if isinstance(spec, list) and spec:
                if isinstance(spec[0], list):                               # [[names], {...}]
                    names = spec[0]
                elif len(spec) > 1 and isinstance(spec[1], dict):           # ["COMBO", {"options": [names]}]
                    names = spec[1].get("options") or []
            return [str(n) for n in names]
        items = self.call("/sdapi/v1/upscalers") or []
        return [str(u.get("name")) for u in items if isinstance(u, dict) and u.get("name") not in
                (None, "None", "Lanczos", "Nearest")]

    def upscale(self, img, model: str, scale: float = 4.0):
        """A picture made bigger and sharper by an upscale model (the server's own resize to `scale`)."""
        if self.kind == "comfy":
            image = self._comfy_upload(img.convert("RGB"), "lb3d_upscale.png")
            graph = {"1": {"class_type": "LoadImage", "inputs": {"image": image}},
                     "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model}},
                     "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
                     "4": {"class_type": "PreviewImage", "inputs": {"images": ["3", 0]}}}
            return self._comfy_run(graph, None, None)
        payload = {"image": base64.b64encode(_png_bytes(img.convert("RGB"))).decode("ascii"), "resize_mode": 0,
                   "upscaling_resize": float(scale), "upscaler_1": model, "show_extras_results": True}
        answer = self.call("/sdapi/v1/extra-single-image", payload, timeout=900)
        picture = _b64_picture((answer or {}).get("image") if isinstance(answer, dict) else None)
        if picture is None:
            raise AIError("the server sent no picture")
        return picture

    def _comfy(self, guide, prompt, negative, model, strength, steps, cfg, seed, progress, stop):
        if not model:
            raise AIError(TEXTS["ai_no_model"])
        image = self._comfy_upload(guide, "lb3d_guide.png")
        sampler, scheduler = self.sampler_for(model)
        graph = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
            "2": {"class_type": "LoadImage", "inputs": {"image": image}},
            "3": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
            "6": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                                                        "latent_image": ["3", 0], "seed": int(seed),
                                                        "steps": int(steps), "cfg": float(cfg),
                                                        "sampler_name": sampler, "scheduler": scheduler,
                                                        "denoise": float(strength)}},
            "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
            "8": {"class_type": "PreviewImage", "inputs": {"images": ["7", 0]}},
        }
        return self._comfy_run(graph, progress, stop)

    def _comfy_run(self, graph: dict, progress=None, stop=None):
        """Queue a ComfyUI job and wait for its first picture."""
        queued = self.call("/prompt", {"prompt": graph, "client_id": self.client_id}, timeout=60) or {}
        pid = self.prompt_id = str(queued.get("prompt_id") or "") if isinstance(queued, dict) else ""
        if not pid:
            raise AIError("ComfyUI did not take the job")
        start = time.time()
        while time.time() - start < 1800:
            if stop is not None and stop.is_set():
                self.interrupt()
                raise AIStopped()
            history = self.call(f"/history/{pid}", timeout=30)
            entry = history.get(pid) if isinstance(history, dict) else None
            if isinstance(entry, dict):
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise AIError(_comfy_failure(status))
                for output in (entry.get("outputs") or {}).values():
                    for im in (output or {}).get("images") or []:
                        query = urllib.parse.urlencode({"filename": im.get("filename", ""),
                                                        "subfolder": im.get("subfolder", ""),
                                                        "type": im.get("type", "temp")})
                        try:
                            return Image.open(io.BytesIO(_http(f"{self.url}/view?{query}", timeout=120))).convert("RGB")
                        except (OSError, ValueError) as exc:
                            raise AIError(_server_error(exc)) from exc
                if status.get("completed"):
                    raise AIError("ComfyUI finished without a picture")
            if progress is not None:
                progress(None, None)
            time.sleep(0.7)
        raise AIError("ComfyUI took too long")

    def interrupt(self) -> None:
        """Stop this program's painting (quietly: the server may be gone). ComfyUI: only our own job."""
        try:
            if self.kind == "comfy":
                if not self.prompt_id:
                    return
                _http(self.url + "/queue", {"delete": [self.prompt_id]}, 10)
                state = _json_call(self.url + "/queue", timeout=10) or {}
                running = [item[1] for item in state.get("queue_running") or []
                           if isinstance(item, list) and len(item) > 1]
                if self.prompt_id in running:
                    _http(self.url + "/interrupt", {"prompt_id": self.prompt_id}, 10)
            else:
                _http(self.url + "/sdapi/v1/interrupt", b"", 10)
        except (OSError, ValueError, AttributeError):
            pass


UPSCALE_WANTED = ("ultrasharp", "realesrgan_x4plus", "realesrgan x4plus", "r-esrgan 4x+", "remacri", "4x_nmkd",
                  "esrgan_4x", "swinir", "4x", "x4")


def pick_upscaler(names, wanted: str = "") -> str:
    """The upscale model to use: the one chosen, else a good photo one (never an anime one), else the first."""
    if wanted and wanted in names:
        return wanted
    for want in UPSCALE_WANTED:
        for name in names:
            key = name.casefold()
            if want in key and "anime" not in key:
                return name
    return names[0] if names else ""


class Upscaler:
    """Makes small covers bigger and sharper with an upscale model on the AI server of the AI window (one picture at
    a time), keeping each result in the cache folder; without a server or a model the cover stays as it is."""

    def __init__(self):
        self.lock = threading.Lock()
        self.url = ""
        self.resolver = None             # gives the address when none was set (the window's AI server)
        self.server = None
        self.models: list = []
        self.retry_at = 0.0
        self.note = ""                   # why nothing was upscaled, for the log

    def configure(self, url: str) -> None:
        url = AIServer.normalize(url)
        if url != self.url:
            with self.lock:
                self.url, self.server, self.models, self.retry_at = url, None, [], 0.0

    def _connect(self):
        if self.server is not None:
            return self.server
        if not self.url and self.resolver is not None:
            try:
                self.url = AIServer.normalize(self.resolver())
            except Exception as exc:  # noqa: BLE001 - no address: no upscaling
                log_line(f"upscale address: {exc}")
        if time.time() < self.retry_at or not self.url:
            return None
        problem = ""
        try:
            server = AIServer.detect(self.url)
            self.models = server.upscalers() if server is not None else []
        except AIError as exc:
            server, problem = None, str(exc)
        if server is None:
            self.retry_at = time.time() + 60                 # not on every game of a batch
            self.note = problem or TEXTS["up_no_server"].format(url=self.url)
            return None
        self.server = server
        return server

    def apply(self, img, src_path, profile: dict):
        """The cover upscaled when it is smaller than the settings say (from the cache when it was done before)."""
        if img is None or not profile.get("upscale") or img.height >= int(profile.get("upscale_below", 800) or 0):
            return img
        try:
            digest = file_sha(src_path)[7:23] if src_path else hashlib.sha256(img.tobytes()).hexdigest()[:16]
        except OSError:
            return img
        wanted = profile.get("upscale_model", "")
        for done in sorted(CACHE_DIR.glob(f"up-{digest}-*.jpg")) if CACHE_DIR.is_dir() else []:
            if not wanted or done.stem.endswith(re.sub(r"[^A-Za-z0-9]+", "_", wanted)[:40]):
                try:
                    return load_picture(done)
                except (OSError, ValueError):
                    break
        with self.lock:
            server = self._connect()
            if server is None:
                return img
            model = pick_upscaler(self.models, wanted)
            if not model:
                self.note = TEXTS["up_no_model"]
                return img
            try:
                big = server.upscale(img.convert("RGB"), model, 4.0 if img.height * 4 <= 3200 else 2.0)
            except AIError as exc:
                self.note = str(exc)
                self.server = None
                return img
        if big.height > 2400:
            big.thumbnail((2400 * big.width // big.height, 2400), LANCZOS)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = CACHE_DIR / f"up-{digest}-{re.sub(r'[^A-Za-z0-9]+', '_', model)[:40]}.jpg"
            tmp = path.with_name(path.name + ".tmp")
            big.convert("RGB").save(tmp, "JPEG", quality=94)
            os.replace(tmp, path)
        except OSError as exc:
            log_line(f"upscale cache: {exc}")
        self.note = ""
        return big.convert("RGBA")


UPSCALER = Upscaler()


# ======================================================================================================== GUI
BG, PANEL, PANEL2, BLUE, FG, MUTED = "#08131d", "#0d1c2a", "#142536", "#076aef", "#eaf4ff", "#95a8bf"
ENTRY, TROUGH, LINE, SOFT, CANVAS_BG = "#0a1724", "#293e51", "#1d3247", "#a7c9eb", "#1b2633"
FACE_COLORS = {"front": "#00ffc7", "spine": "#ffcf4a"}

TEXTS = {
    "undo": "↶ Undo", "redo": "↷ Redo",
    "lb_section": "LaunchBox", "lb_folder": "LaunchBox folder", "browse": "Browse…", "reload": "↻ Reload",
    "platform": "Platform (type to narrow the list)", "search": "Search games", "show": "Show",
    "filter_all": "All games", "filter_missing": "Without Box - 3D", "filter_has": "With Box - 3D",
    "filter_nofront": "Without Box - Front",
    "col_title": "Title", "col_region": "Region", "col_front": "Front", "col_spine": "Spine", "col_3d": "3D",
    "count": "{shown} of {total} games", "count_cap": "{shown} of {total} games (first {cap} shown — narrow with search)",
    "legend": "Front: ✓ Box - Front, ≈ fallback · Spine: ✓ Box - Spine, F Box - Full only · 3D: number of pictures",
    "closing": "Finishing the current boxes and closing…", "close_ask": "Boxes are being made. Stop and close the program?",
    "plat_info": "{games} games · with front {front} · with Box - 3D {has3d}",
    "loading_platforms": "Loading LaunchBox platforms…", "loading_games": "Loading games: {name}…",
    "platforms_loaded": "LaunchBox: {n} platforms ({root})", "games_loaded": "{name}: {n} games",
    "no_lb": "LaunchBox not found — choose its folder.",
    "not_lb": "Not a LaunchBox folder (no Data\\Platforms).",
    "view_3d": "3D view", "view_front": "Front 2D", "view_spine": "Spine 2D", "fit_view": "⤢ Fit",
    "help": "Drag the coloured corners to fit the perspective · wheel: zoom · right button: pan · "
            "arrow keys: move a corner by 1 px (Shift: 10 px)",
    "help_disc": "The Disc tab sets the disc · wheel: zoom · right button: pan · double click: fit",
    "info_disc": "Disc",
    "no_game": "Pick a platform and a game in the list on the left.",
    "info_front": "front", "info_spine": "spine", "info_3d": "Box - 3D",
    "src_spine": "Box - Spine", "src_full": "cut from Box - Full", "src_generate": "made up",
    "src_none": "none", "src_override": "own picture", "src_other_region": "(only in another region)",
    "has3d": "yes ({n})", "no3d": "none yet", "no_front_pic": "no Box - Front",
    "tab_template": "Box", "tab_art": "Artwork", "tab_text": "Text / Logo", "tab_export": "Save",
    "tpl_section": "1. Case (for this platform)", "tpl_generic": "Box drawn in perspective (no template)",
    "tpl_load": "Load template…", "tpl_folder": "Templates folder",
    "tpl_note": "Templates are PNG pictures of empty cases (their cover area flat or see-through) from the “box "
                "model” folder.",
    "face_section": "2. Active side", "face_front": "Front", "face_spine": "Spine",
    "corners_detect": "⌖ Detect corners automatically", "corners_reset": "↺ Reset corners (from the template's profile)",
    "corners_note": "Corners are remembered for each template.",
    "gen_section": "3. Perspective box", "gen_style": "Look", "style_box": "Cardboard box",
    "style_case": "Plastic case", "case_color": "Case colour…", "case_preset": "Presets",
    "rim": "Rim", "angle": "Turn", "perspective": "Perspective", "thickness": "Thickness",
    "auto_thickness": "Thickness from the spine picture's shape", "edges": "Edge lines",
    "out_height": "Box height (px)",
    "display_section": "4. Look and preview", "guides": "Show corners", "shadows": "Shading",
    "sheen": "Plastic reflection", "overlay": "Template details over the artwork", "hq": "High-quality preview",
    "art_for": "Settings of: {face}", "source_section": "1. Picture source",
    "src_launchbox": "LaunchBox picture", "src_color": "Plain colour",
    "src_template": "Keep the template's side", "src_none_opt": "None (no such side)",
    "choose_color": "Colour…", "clean_section": "2. The template's own picture under this side",
    "clean_original": "Keep it", "clean_transparent": "Erase it (see-through)",
    "clean_color": "Paint over it", "neutral": "Light on both sides",
    "fit_section": "3. Picture fit", "fit_stretch": "Stretch", "fit_fill": "Fill (crop)", "fit_fit": "Fit whole",
    "zoom": "Zoom", "pos_x": "Position X", "pos_y": "Position Y", "rotation": "Rotation", "opacity": "Opacity",
    "shade": "Shadow", "reset": "↺ Reset", "flipx": "⇋ Mirror", "flipy": "⇵ Flip",
    "spine_section": "4. When a game has no Box - Spine",
    "from_full": "Cut the spine out of Box - Full (when it matches the front)",
    "gen_logo": "Cover edge colour + Clear Logo (or title)", "gen_title": "Cover edge colour + title",
    "gen_edge": "Blurred cover edge", "gen_color": "Cover edge colour only", "gen_none": "Don't make one",
    "spine_font": "Title font",
    "gc_section": "5. When a game has no Box - Front at all",
    "gc_on": "Make a generic cover: platform logo + the game's name",
    "gc_ground": "Background", "gc_silver": "Silver with a mesh", "gc_dark": "Dark with a mesh",
    "gc_color": "Plain colour", "gc_picture": "Own picture", "gc_bg": "Colour…", "gc_choose": "Picture…",
    "gc_ink": "Logo and name colour…", "gc_logo": "Platform logo",
    "gc_logo_auto": "LaunchBox's platform logo, else drawn from the name", "gc_logo_drawn": "Drawn from the name",
    "gc_logo_picture": "Picture", "gc_name": "Big name", "gc_maker": "Small line",
    "gc_auto": "Empty = from the platform's name: “{name}” / “{maker}” (small line “-” = none).",
    "gc_title": "Game's name", "gc_title_text": "Title", "gc_title_logo": "Its Clear Logo (else the title)",
    "gc_spine": "Black spine with the platform's name (when the game has no spine picture)",
    "gc_note": "For applications and games without box art. Games with a Box - Front keep their own cover. Used "
               "for one game and for whole platforms.",
    "src_generic_cover": "generic cover", "src_generic_spine": "black, platform's name",
    "pics_section": "6. Picking pictures",
    "match_region": "Box - Spine only from the front's region folder",
    "front_fallbacks": "No Box - Front: use Box - Front - Reconstructed / Fanart - Box - Front",
    "override_section": "8. This game only", "override_load": "Own picture…",
    "override_clear": "Remove own pictures",
    "text_section": "1. Add text to: {face}",
    "text_value": "Text — {title} {year} {platform} {developer} {publisher} {region} {genre} {series} {version}",
    "font": "Font", "size": "Size", "text_color": "Colour…", "stroke_color": "Outline…",
    "text_add": "＋ Add text", "logo_section": "2. Add a logo", "logo_file": "＋ Logo from file…",
    "logo_game": "＋ Game's Clear Logo", "layers_section": "3. Layers of: {face}",
    "up": "▲", "down": "▼", "delete": "✕ Delete", "layer_props": "4. Selected layer",
    "apply_text": "Change text", "layer_text": "Text: {v}", "layer_logo": "Logo: {v}",
    "layer_clearlogo": "Game's Clear Logo (else Marquee)", "no_layers": "No layers — add a text or a logo.",
    "out_section": "2. Where to save", "region_same": "In the region folder the front comes from",
    "region_root": "In the main folder (no region folder)",
    "existing_section": "3. When a game already has the picture", "ex_skip": "Skip it",
    "ex_replace": "Replace the picture LaunchBox shows (old one to Backups)",
    "ex_next": "Add as another picture (-02, -03…; the current one stays first)",
    "format_section": "4. File", "fmt_png": "PNG (transparent)", "fmt_jpg": "JPG", "jpg_bg": "JPG background…",
    "max_height": "Max height of a Box - 3D (px, 0 = no limit)", "trim": "Trim transparent margins",
    "threads": "Threads", "go_section": "5. Make", "save_one": "💾 Save this game to LaunchBox",
    "export_one": "Export this game to a file…", "make_selected": "Make for the selected games ({n})",
    "make_shown": "Make for the games in the list ({n})", "make_all": "Make for the whole platform ({n})",
    "profile_section": "6. Settings (project)", "profile_default": "Use as default for new platforms",
    "profile_export": "Save settings to a file…", "profile_import": "Load settings from a file…",
    "profile_reset": "Restore factory settings", "log_section": "Log",
    "stop": "■ Stop", "ready": "Ready.",
    "batch_progress": "{done}/{total} · 3D {saved} · discs {discs} · web covers {covers} · generic {generic} · "
                      "skipped {skipped} · errors {errors}",
    "batch_done": "Done ({platform}): Box - 3D {saved}, discs {discs}, covers from the web {covers}, generic covers "
                  "{generic}, skipped (all there) {skipped}, no Box - Front {nofront}, repeated titles {dup}, errors "
                  "{errors}.",
    "batch_stopped": "Stopped.",
    "confirm_batch": "Make pictures for {n} games?\n\nPlatform: {platform}\nMaking: {what}\nBox: {template}\n"
                     "When the picture is there: {policy}\nFolder: {folder}\n\n"
                     "Expected: {make} games to make · {skip} skipped (all there) · {nofront} left out (no Box - Front)"
                     "{extra}",
    "confirm_missing_web": "\n{generic} of them have no Box - Front: their cover is looked for on the web ({where}) "
                           "and saved as their Box - Front",
    "confirm_missing_generic": ", else a generic cover is made.",
    "confirm_missing_only_generic": "\n{generic} of them have no Box - Front: they get a generic cover.",
    "confirm_missing_end": ".",
    "web_failed": "the web could not be reached",
    "up_no_server": "Upscaling: no AI server answers at {url} (start one, see the AI window)",
    "up_no_model": "Upscaling: the AI server has no upscale model (Stability Matrix: Model Browser, an ESRGAN model "
                   "such as 4x-UltraSharp)",
    "web_title": "No Box - Front at all: look on the web first", "web_auto": "Automatic (libretro; Steam for PC)",
    "web_libretro": "libretro-thumbnails", "web_steam": "Steam", "web_off": "Off", "web_system": "libretro system",
    "web_system_auto": "Empty = automatic: {name}", "web_system_none": "Empty = automatic: none fits, choose one",
    "web_system_not_games": "Empty = automatic: none (manuals, magazines, videos… are not looked for on their own)",
    "web_find": "🔎 Find this game's cover on the web", "web_searching": "Looking for {title} on the web…",
    "web_found": "Cover found ({where}) and saved as Box - Front: {path}", "web_none": "No cover found for {title}.",
    "web_has_front": "This game already has a Box - Front.",
    "web_note": "A cover found is saved as the game's Box - Front in LaunchBox (as LaunchBox's own download would). "
                "Only the same title counts (a near one is often another game); games with none found get the "
                "generic cover.",
    "up_section": "7. Sharper small covers (AI)",
    "up_on": "Make covers sharper with an AI upscale model when they are less than this high (px):",
    "up_model": "Model", "up_refresh": "↻ Ask the AI server", "up_models": "{n} upscale models on {server}.",
    "up_note": "Uses the AI server of the AI window (Forge, SD.Next, A1111 or ComfyUI with an ESRGAN-type model). "
               "Each cover is done once; the results are kept in {cache}.",
    "tab_disc": "Disc", "view_disc": "Disc",
    "disc_kind_section": "1. Kind of disc", "disc_auto": "From the platform (now: {kind})", "disc_cd": "CD, silver centre",
    "disc_dvd": "DVD", "disc_bluray": "Blu-ray, blue silver", "disc_psx": "PlayStation, black, printed to the hub",
    "disc_gamecube": "GameCube, 8 cm", "disc_picture": "Picture disc, printed to the hole",
    "disc_art_section": "2. The picture", "disc_crop": "Part of the cover", "disc_top": "Top", "disc_center": "Middle",
    "disc_bottom": "Bottom", "disc_zoom": "Zoom", "disc_more_section": "3. On the disc",
    "disc_logo": "Game's Clear Logo (else its Marquee)", "disc_logo_size": "Logo size",
    "disc_text": "Text along the edge — {title} {year} {publisher} {developer} {region}…", "disc_text_pos": "Where",
    "disc_text_top": "Top", "disc_text_bottom": "Bottom", "disc_text_color": "Text colour…",
    "disc_size": "Disc size (px)",
    "disc_note": "Discs are saved as LaunchBox's “Disc” pictures (Save tab: What to make). A game with no Box - Front "
                 "gets a disc from its generic cover.",
    "what_section": "1. What to make", "make_box": "Box - 3D", "make_disc": "Disc",
    "disc_show": "👁 Show the disc in the preview",
    "nothing_chosen": "Choose what to make (Box - 3D or Disc) at the top of the Save tab.",
    "nothing_to_make": "Nothing to make: of {n} games, {skip} already have a Box - 3D and {nofront} have no "
                       "Box - Front.",
    "aborted_in_a_row": "Stopped after {n} errors in a row — see the log (disk full? folder gone?).",
    "aborted_share": "Stopped: more than {pct}% of the boxes failed — see the log.",
    "saved_one": "Saved: {path}", "exported": "Exported: {path}",
    "exists_ask": "This game already has:\n{path}\n\nYes = replace it (the old file goes to Backups)\n"
                  "No = add as another picture\nCancel = do nothing",
    "no_front": "This game has no Box - Front picture.", "busy": "Boxes are being made — wait or stop.",
    "refresh_note": "LaunchBox shows new pictures after a restart (or an image refresh).",
    "error": "Error", "tpl_missing": "Template {name} is missing — using the perspective box.",
    "default_saved": "These settings are now the default for platforms without their own.",
    "reset_ask": "Restore factory settings for this platform?", "select_games": "Select games in the list.",
    "template_label": "template {name}", "generic_label": "perspective box",
    "ex_skip_short": "skip", "ex_replace_short": "replace", "ex_next_short": "add as the next one",
    "pick_picture": "Choose a picture", "pick_template": "Choose a case template", "profile_files": "Settings",
    "images": "Images", "all_files": "All files", "presets_none": "—",
    "tint_section": "Template colour (tint)", "tint_color": "Colour…", "tint_none": "No tint",
    "tint_multiply": "Multiply (box3d)", "tint_colorize": "Recolour the case", "tint_amount": "Amount",
    "tint_note": "Multiply darkens channels like box3d's RGB setting; Recolour turns a black or white case into the "
                 "colour.",
    "export_box3d": "Save corners as a box3d profile…", "box3d_saved": "box3d profile saved: {path}",
    "overlay_mode": "Template layer", "overlay_auto": "Auto", "overlay_details": "Details over the art",
    "overlay_light": "Light over the art (box3d)", "light_strength": "Template light (box3d)",
    "sharpen": "Sharpen the covers (box3d)",
    "overlay_note": "Auto: light for see-through templates (box3d's and the AI ones), details for ones with a flat "
                    "cover area.",
    "gen_band": "Blurred band of the cover, darkened, + logo (box3d)", "band_source": "Band",
    "band_left": "Left", "band_center": "Centre", "band_right": "Right", "band_frac": "Band width",
    "band_blur": "Blur", "band_dark": "Darkness",
    "logo_marquee": "＋ Game's Marquee", "slots_add": "Spine logo slots (box3d)",
    "slots_note": "Slots come from the template's box3d profile (top / game / bottom); the game slot shows the "
                  "Arcade - Marquee, else the Clear Logo. They show only on spines this program makes up.",
    "layer_marquee": "Game's Marquee (else Clear Logo)", "layer_slot": "[{slot} slot] ", "only_made":
        "Only on made-up spines",
    "ai_open": "✨ Make a template with AI (Stability Matrix)…", "ai_title": "Make a template with AI",
    "ai_server": "1. AI server (Stability Matrix)", "ai_sm": "Stability Matrix: {path}",
    "ai_sm_none": "Stability Matrix not found — Browse… to its StabilityMatrix.exe (or type a server's address).",
    "ai_browse_sm": "Choose StabilityMatrix.exe", "ai_other": "Other address (type it below)",
    "ai_no_api_short": "no API", "ai_connect": "Connect", "ai_start": "▶ Start in Stability Matrix",
    "ai_checking": "Looking for a server at {url}…",
    "ai_not_running": "Nothing answers at {url}. Start {name} with “▶ Start in Stability Matrix” (or Launch it in "
                      "Stability Matrix), then Connect.",
    "ai_no_api": "{url} answers, but not as ComfyUI nor with the web UI API: start the web UI with --api "
                 "(Stability Matrix: the package's ⚙ Launch options).",
    "ai_pkg_noapi": "{name} starts without its API: in Stability Matrix open its ⚙ Launch options, tick --api (or "
                    "add it to the extra launch arguments) and start it again.",
    "ai_connected": "Connected: {name} at {url} · {n} models",
    "ai_sm_open": "Stability Matrix is open: press Launch on “{name}” there. This window connects as soon as it "
                  "answers… {s} s",
    "ai_starting": "Starting {name} in Stability Matrix… {s} s (the first start can take a few minutes)",
    "ai_start_timeout": "{name} did not answer within {m} minutes — see its console in Stability Matrix.",
    "ai_pick_pkg": "Choose one of Stability Matrix's packages in the list first.",
    "ai_case_section": "2. Case", "ai_src_case": "A new case:",
    "ai_src_template": "Repaint the current template ({name})",
    "ai_no_template": "Repaint the current template (choose one in the Box tab first)",
    "ai_turn": "Turn", "ai_thickness": "Thickness", "ai_case_color": "Case colour…", "ai_case_default": "Kind's colour",
    "ai_note": "The program draws the empty case (dashed: where the covers go); the AI paints over it as a photo and "
               "keeps its shape, so the corners stay exact. The lower “How much the AI may change”, the closer it "
               "stays to the drawing.",
    "ai_ai_section": "3. AI painting", "ai_model": "Model (checkpoint)", "ai_prompt": "What to paint (prompt)",
    "ai_prompt_reset": "↺ Prompt for this kind of case", "ai_negative": "What to leave out (negative prompt)",
    "ai_strength": "How much the AI may change", "ai_steps": "Steps", "ai_cfg": "Prompt weight (CFG)",
    "ai_variants": "Variants", "ai_seed": "Seed (empty = random)", "ai_size": "Painting size",
    "ai_generate": "✨ Paint", "ai_stop": "■ Stop",
    "ai_loading_model": "Loading the model {name}… (the first time can take a minute)",
    "ai_painting": "Painting {i} of {n}…", "ai_done": "Done: {n} painted. Pick one below, then save it as a template.",
    "ai_stopped": "Stopped.", "ai_failed": "The AI could not paint: {error}", "ai_no_model": "Choose a model first.",
    "ai_preview_box": "Box with this game", "ai_preview_template": "Template", "ai_preview_picture": "AI picture",
    "ai_preview_guide": "Drawing for the AI", "ai_gloss": "Reflections on the cover", "ai_name": "Name",
    "ai_save": "💾 Save as template and use it", "ai_saved": "AI template saved and chosen: {path}",
    "ai_save_note": "Saved into the “box model” folder with its corners (a box3d profile), so it needs no corner work.",
    "ai_pick_result": "Paint a case first.",
}


def ui_font(size=10, bold=False):
    return ("Segoe UI", size, "bold" if bold else "normal")


def load_config() -> dict:
    cfg = {"lb_root": "", "last_platform": "", "geometry": "", "templates": {}, "profiles": {},
           "default_profile": None, "custom_templates": [],
           "export": {"region": "same", "existing": "skip", "format": "png", "jpg_bg": "#ffffff", "max_height": 1000,
                      "trim": True, "threads": max(1, min(6, (os.cpu_count() or 4) - 1)), "make_box": True,
                      "make_disc": False},
           "display": {"guides": True, "hq": True}, "ai": {}}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if key in ("export", "display") and isinstance(value, dict):
                cfg[key].update({k: v for k, v in value.items() if k in cfg[key] and _same_kind(v, cfg[key][k])})
            elif key in cfg and (cfg[key] is None or isinstance(value, type(cfg[key]))):
                cfg[key] = value
    return cfg


def save_config(cfg: dict) -> None:
    try:
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except OSError as exc:
        log_line(f"config: {exc}")


class App:
    def __init__(self, root, options=None):
        self.root = root
        self.options = options or {}
        self.cfg = load_config()
        self.lb: LaunchBox | None = None
        self.platform = ""
        self.games: list[Game] = []
        self.found: dict[int, dict] = {}
        self.rows: list[int] = []
        self.sort = ("title", False)
        self.profile = merged_profile(self.cfg.get("default_profile"))
        self.template_img = None
        self.template_key = ""
        self.quads: dict = {}
        self.current: Game | None = None
        self.current_index = -1
        self.current_found: dict = {}
        self.pics: Pictures | None = None
        self.overrides: dict = {}
        self.face = "front"
        self.view = "3d"
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.drag = self.pan_drag = self.handle = None
        self.view_origin, self.view_fit = (0.0, 0.0), 1.0
        self.shown_quads: dict = {}
        self.photo = None
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._edit_tag = None
        self._edit_timer = None
        self._draw_job = None
        self._fast = False
        self._save_job = None
        self._filter_job = None
        self._syncing = False
        self.bound: list = []
        self.queue: queue.Queue = queue.Queue()
        self.load_token = None
        self.pics_token = None
        self.batch_stop: threading.Event | None = None
        self.batch_running = False
        self.scrollers: dict = {}
        self.log_lines: list[str] = []
        self.status_text = ""
        self.layer_index = -1
        self.ai_dialog = None
        UPSCALER.configure((self.cfg.get("ai") or {}).get("url", "") if isinstance(self.cfg.get("ai"), dict) else "")
        UPSCALER.resolver = self.ai_url
        self.shot_state = "start" if self.options.get("screenshot") and not self.options.get("ai") else None
        root.title(f"{APP_NAME} {APP_VERSION}")
        self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(self.cfg.get("geometry") or f"{min(sw - 60, self.px(1560))}x{min(sh - 100, self.px(960))}")
        root.minsize(min(sw - 60, self.px(1180)), min(sh - 100, self.px(720)))
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.setup_style()
        self.build()
        root.bind_all("<MouseWheel>", self.on_wheel, add="+")
        root.bind_class("TCombobox", "<MouseWheel>", self.on_wheel_break)
        root.bind_all("<Control-z>", lambda e: self.undo())
        root.bind_all("<Control-y>", lambda e: self.redo())
        root.bind_all("<Control-Z>", lambda e: self.redo())
        root.after(60, self.pump)
        root.after(150, self.startup)

    # ------------------------------------------------------------------------------------------- small helpers
    def px(self, n) -> int:
        """Pixels for this screen's DPI (sizes below are for a 96 dpi screen)."""
        return int(round(n * self.k))

    def t(self, key, **kw):
        text = TEXTS.get(key, key)
        return text.format(**kw) if kw else text

    def setup_style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=PANEL, foreground=FG, fieldbackground=ENTRY, bordercolor=LINE,
                     lightcolor=PANEL2, darkcolor=PANEL, troughcolor=TROUGH, font=ui_font(9))
        line = tkfont.Font(root=self.root, font=ui_font(9)).metrics("linespace")
        st.configure("Treeview", background=PANEL2, fieldbackground=PANEL2, foreground=FG, rowheight=line + self.px(5),
                     borderwidth=0)
        st.map("Treeview", background=[("selected", BLUE)], foreground=[("selected", "white")])
        st.configure("Treeview.Heading", background=PANEL, foreground=SOFT, relief="flat", font=ui_font(9, True))
        st.map("Treeview.Heading", background=[("active", PANEL2)])
        st.configure("TCombobox", fieldbackground=ENTRY, background=PANEL2, foreground=FG, arrowcolor=FG,
                     selectbackground=ENTRY, selectforeground=FG, insertcolor=FG)
        st.map("TCombobox", fieldbackground=[("readonly", ENTRY)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", ENTRY)], selectforeground=[("readonly", FG)])
        st.configure("TNotebook", background=PANEL, borderwidth=0, tabmargins=(4, 4, 4, 0))
        st.configure("TNotebook.Tab", background=PANEL2, foreground=MUTED, padding=(12, 6), font=ui_font(9, True))
        st.map("TNotebook.Tab", background=[("selected", BLUE)], foreground=[("selected", "white")])
        st.configure("Horizontal.TProgressbar", troughcolor=TROUGH, background=BLUE, bordercolor=TROUGH,
                     lightcolor=BLUE, darkcolor=BLUE)
        st.configure("Vertical.TScrollbar", background="#24476b", troughcolor=PANEL, arrowcolor=SOFT, bordercolor=PANEL,
                     lightcolor="#24476b", darkcolor="#24476b", gripcount=0)
        st.map("Vertical.TScrollbar", background=[("active", "#2f5c8a")])
        self.root.option_add("*TCombobox*Listbox.background", ENTRY)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font", ui_font(9))

    def section(self, parent, title, bg=PANEL2):
        frame = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=LINE)
        frame.pack(fill="x", padx=8, pady=(8, 0))
        label = tk.Label(frame, text=title, bg=bg, fg=FG, font=ui_font(10, True), anchor="w")
        label.pack(fill="x", padx=10, pady=(8, 4))
        body = tk.Frame(frame, bg=bg)
        body.pack(fill="x", padx=10, pady=(0, 10))
        body.title_label = label
        return body

    def button(self, parent, text, command, kind="normal", **kw):
        colors = {"normal": ("#1b3550", FG, "#24476b"), "blue": (BLUE, "white", "#148aff"),
                  "red": ("#7a1f2b", "white", "#9b2a39"), "green": ("#17663b", "white", "#1f8a50")}
        bg, fg, active = colors[kind]
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=active,
                         activeforeground="white", relief="flat", bd=0, padx=10, pady=5, cursor="hand2",
                         font=ui_font(9, kind != "normal"), disabledforeground="#5f7389", **kw)

    def label(self, parent, text, color=SOFT, size=9, bold=False, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color, font=ui_font(size, bold), anchor="w",
                        justify="left", **kw)

    def check(self, parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=parent["bg"], fg=FG, selectcolor=ENTRY,
                              activebackground=parent["bg"], activeforeground=FG, anchor="w", font=ui_font(9),
                              highlightthickness=0, bd=0)

    def radio(self, parent, text, var, value):
        return tk.Radiobutton(parent, text=text, variable=var, value=value, bg=parent["bg"], fg=FG,
                              selectcolor=ENTRY, activebackground=parent["bg"], activeforeground=FG, anchor="w",
                              font=ui_font(9), highlightthickness=0, bd=0)

    def scrollable(self, parent):
        outer = tk.Frame(parent, bg=PANEL)
        canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=PANEL)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.scrollers[str(canvas)] = canvas
        self.scrollers[str(inner)] = canvas
        return outer, inner

    def slider(self, parent, text, scope, key, lo, hi, res, fmt, default=None):
        row = tk.Frame(parent, bg=parent["bg"])
        row.pack(fill="x", pady=(5, 0))
        self.label(row, text).pack(side="left")
        value = tk.Label(row, text="", bg=parent["bg"], fg=FG, font=ui_font(9, True))
        value.pack(side="right")
        var = tk.DoubleVar(value=lo)
        scale = tk.Scale(parent, variable=var, from_=lo, to=hi, resolution=res, showvalue=0, orient="horizontal",
                         bg=BLUE, fg=FG, highlightthickness=0, troughcolor=TROUGH, activebackground="#148aff",
                         bd=0, sliderlength=self.px(16), width=self.px(10), sliderrelief="flat")
        scale.pack(fill="x")
        if default is not None:
            scale.bind("<Button-3>", lambda e: var.set(default))
        scale.bind("<ButtonRelease-1>", lambda e: self.request_draw())
        self.bind_var(var, scope, key, float, fmt=fmt, value_label=value, slider=True)
        return scale

    def color_button(self, parent, text, scope, key):
        var = tk.StringVar()
        btn = self.button(parent, text, None)

        def pick():
            current = var.get() or "#ffffff"
            res = colorchooser.askcolor(color=current, parent=self.root)
            if res and res[1]:
                var.set(res[1])

        def show(*_):
            v = var.get()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", v or ""):
                r, g, b = hex_rgb(v)
                btn.configure(bg=v, activebackground=v, fg="#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff")

        btn.configure(command=pick)
        var.trace_add("write", show)
        self.bind_var(var, scope, key, str)
        return btn

    def bind_var(self, var, scope, key, conv=None, fmt=None, value_label=None, slider=False, after=None):
        """Tie a tk variable to a setting; the setting changes when the variable does."""
        self.bound.append((var, scope, key, fmt, value_label))

        def changed(*_):
            if self._syncing:
                return
            try:
                value = var.get()
                if conv is not None:
                    value = conv(value)
            except (tk.TclError, ValueError):
                return
            if value_label is not None and fmt:
                value_label.configure(text=fmt(value))
            target = self.target(scope)
            if target is None or target.get(key) == value:
                return
            if scope in ("face", "generic", "profile", "layer"):
                self.remember_once((scope, key, self.face, self.layer_index))
            target[key] = value
            self.setting_changed(scope, key, slider)
            if after is not None:
                after()

        var.trace_add("write", changed)

    def target(self, scope):
        if scope == "face":
            return self.profile["faces"][self.face]
        if scope == "generic":
            return self.profile["generic"]
        if scope == "profile":
            return self.profile
        if scope == "export":
            return self.cfg["export"]
        if scope == "display":
            return self.cfg["display"]
        if scope == "layer":
            return self.selected_layer()
        return None

    def sync_controls(self):
        self._syncing = True
        try:
            for var, scope, key, fmt, value_label in self.bound:
                target = self.target(scope)
                if target is None or key not in target:
                    continue
                value = target[key]
                try:
                    var.set(value)
                except tk.TclError:
                    continue
                if value_label is not None and fmt:
                    value_label.configure(text=fmt(value))
        finally:
            self._syncing = False
        self.update_face_texts()
        self.refresh_layers()
        self.update_template_controls()
        if hasattr(self, "gc_auto_label"):
            maker, name = platform_names(self.platform)
            self.gc_auto_label.configure(text=self.t("gc_auto", name=name or "—", maker=maker or "—"))
        self.update_platform_labels()

    def setting_changed(self, scope, key, slider=False):
        if scope in ("profile",) and key in ("front_fallbacks", "match_region"):
            self.refresh_statuses()
            self.load_current()
        if scope == "profile" and key in ("upscale", "upscale_below", "upscale_model") and not slider:
            self.load_current()                      # the cover shown, upscaled or not
        if scope == "profile" and (key == "generic_cover" or key.startswith("gc_")):
            self.update_info()
        if scope == "export":
            self.update_output_label()
            if key in ("make_box", "make_disc"):
                self.update_info()
        if scope == "layer":
            self.refresh_layers(keep=True)
        self.schedule_save()
        self.request_draw(fast=slider)

    # ------------------------------------------------------------------------------------------- undo / redo
    def snapshot(self):
        return {"profile": copy.deepcopy(self.profile), "quads": copy.deepcopy(self.quads),
                "template_key": self.template_key}

    def remember(self):
        self.undo_stack.append(self.snapshot())
        del self.undo_stack[:-80]
        self.redo_stack.clear()

    def remember_once(self, tag):
        if tag != self._edit_tag:
            self.remember()
            self._edit_tag = tag
        if self._edit_timer is not None:
            self.root.after_cancel(self._edit_timer)
        self._edit_timer = self.root.after(700, self._end_edit)

    def _end_edit(self):
        self._edit_tag = None
        self._edit_timer = None

    def restore(self, state):
        template_changed = state["profile"].get("template") != self.profile.get("template")
        self.profile = state["profile"]
        if self.platform:
            self.cfg["profiles"][self.platform] = self.profile
        if template_changed:
            self.load_template(keep_quads=True)
        self.quads = state["quads"]
        self.store_quads()
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    def undo(self):
        if self.undo_stack and not self.drag:
            self.redo_stack.append(self.snapshot())
            self.restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack and not self.drag:
            self.undo_stack.append(self.snapshot())
            self.restore(self.redo_stack.pop())

    # ------------------------------------------------------------------------------------------- building the UI
    def build(self):
        for child in self.root.winfo_children():
            if not isinstance(child, tk.Toplevel):      # the AI window stays open
                child.destroy()
        self.bound = []
        self.scrollers = {}
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=14, pady=(10, 4))
        k = self.k
        icon = tk.Canvas(head, width=self.px(34), height=self.px(34), bg=BG, highlightthickness=0)
        icon.create_polygon(*[v * k for v in (6, 7, 13, 3, 13, 31, 6, 28)], fill="#0a4fb0", outline="")
        icon.create_polygon(*[v * k for v in (13, 3, 30, 6, 30, 28, 13, 31)], fill=BLUE, outline="")
        icon.create_line(13 * k, 3 * k, 13 * k, 31 * k, fill="#9fd0ff")
        icon.pack(side="left", padx=(0, 8))
        tk.Label(head, text="LB 3D BOX CREATOR", bg=BG, fg=FG, font=ui_font(15, True)).pack(side="left")
        self.button(head, self.t("redo"), self.redo).pack(side="right")
        self.button(head, self.t("undo"), self.undo).pack(side="right", padx=(0, 6))

        status = tk.Frame(self.root, bg=PANEL)
        status.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(status, orient="horizontal", mode="determinate", length=self.px(260))
        self.status_label = tk.Label(status, text=self.status_text or self.t("ready"), bg=PANEL, fg=SOFT,
                                     font=ui_font(9), anchor="w")
        self.stop_button = self.button(status, self.t("stop"), self.stop_batch, "red")
        self.status_label.pack(side="left", fill="x", expand=True, padx=10, pady=5)

        panes = tk.PanedWindow(self.root, orient="horizontal", bg=BG, sashwidth=6, bd=0, sashrelief="flat")
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        left = tk.Frame(panes, bg=PANEL, width=self.px(400))
        center = tk.Frame(panes, bg=BG)
        right = tk.Frame(panes, bg=PANEL, width=self.px(440))
        panes.add(left, minsize=self.px(300), width=self.px(400))
        panes.add(center, minsize=self.px(380))
        panes.add(right, minsize=self.px(380), width=self.px(440))
        self.build_left(left)
        self.build_center(center)
        self.build_right(right)
        if self.batch_running:
            self.show_progress(True)
        self.after_build()

    def after_build(self):
        if self.lb is not None:
            self.lb_var.set(str(self.lb.root))
            self.plat_combo["values"] = self.lb.platforms
        if self.platform:
            self.plat_var.set(self.platform)
            self.update_platform_info()
            self.apply_filter(keep_selection=True)
        self.sync_controls()
        self.update_output_label()
        self.update_info()
        for line in self.log_lines[-200:]:
            self.log_widget_append(line)
        self.request_draw()

    def build_left(self, parent):
        body = self.section(parent, self.t("lb_section"), PANEL2)
        self.label(body, self.t("lb_folder")).pack(fill="x")
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(2, 6))
        self.lb_var = tk.StringVar(value=str(self.lb.root) if self.lb else self.cfg.get("lb_root", ""))
        tk.Entry(row, textvariable=self.lb_var, state="readonly", readonlybackground=ENTRY, fg=FG, relief="flat",
                 font=ui_font(9)).pack(side="left", fill="x", expand=True, ipady=4)
        self.button(row, self.t("browse"), self.choose_lb).pack(side="left", padx=(6, 0))
        self.button(body, self.t("reload"), lambda: self.open_launchbox(self.lb_var.get())).pack(fill="x")
        self.label(body, self.t("platform")).pack(fill="x", pady=(8, 2))
        self.plat_var = tk.StringVar(value=self.platform)
        self.plat_combo = ttk.Combobox(body, textvariable=self.plat_var, height=24, font=ui_font(10))
        self.plat_combo.pack(fill="x", ipady=3)
        self.plat_combo.bind("<<ComboboxSelected>>", lambda e: self.select_platform(self.plat_var.get()))
        self.plat_combo.bind("<Return>", self.on_platform_enter)
        self.plat_combo.bind("<KeyRelease>", self.on_platform_typed)
        self.plat_info = self.label(body, "", MUTED, 8)
        self.plat_info.pack(fill="x", pady=(3, 0))

        body2 = self.section(parent, self.t("search"), PANEL2)
        self.search_var = tk.StringVar()
        tk.Entry(body2, textvariable=self.search_var, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                 font=ui_font(10)).pack(fill="x", ipady=4)
        self.search_var.trace_add("write", lambda *_: self.schedule_filter())
        row = tk.Frame(body2, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.label(row, self.t("show")).pack(side="left")
        self.filter_keys = ["all", "missing", "has", "nofront"]
        self.filter_var = tk.StringVar(value=self.t("filter_" + getattr(self, "filter_mode", "all")))
        combo = ttk.Combobox(row, textvariable=self.filter_var, state="readonly",
                             values=[self.t("filter_" + k) for k in self.filter_keys])
        combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        combo.bind("<<ComboboxSelected>>", lambda e: self.on_filter_mode())

        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        cols = ("title", "region", "front", "spine", "box3d")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        heads = {"title": "col_title", "region": "col_region", "front": "col_front", "spine": "col_spine",
                 "box3d": "col_3d"}
        widths = {k: self.px(v) for k, v in {"title": 150, "region": 76, "front": 44, "spine": 54, "box3d": 34}.items()}
        for c in cols:
            self.tree.heading(c, text=self.t(heads[c]), command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=widths[c], stretch=c == "title", anchor="w" if c in ("title", "region") else "center")
        bar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.tag_configure("has3d", foreground="#7fe0a8")
        self.tree.tag_configure("nofront", foreground="#7b8da1")
        self.tree.bind("<<TreeviewSelect>>", self.on_game_select)
        self.count_label = self.label(parent, "", MUTED, 8, wraplength=self.px(370))
        parent.bind("<Configure>", lambda e: self.count_label.configure(wraplength=max(120, e.width - self.px(24))),
                    add="+")
        self.count_label.pack(fill="x", padx=12, pady=(0, 8))

    def build_center(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", pady=(0, 4))
        self.view_buttons = {}
        for key, text in (("3d", "view_3d"), ("front", "view_front"), ("spine", "view_spine"), ("disc", "view_disc")):
            b = self.button(bar, self.t(text), lambda k=key: self.set_view(k), "blue" if self.view == key else "normal")
            b.pack(side="left", padx=(0, 4))
            self.view_buttons[key] = b
        self.button(bar, self.t("fit_view"), self.fit_view).pack(side="left", padx=(8, 0))
        self.zoom_label = tk.Label(bar, text="", bg=BG, fg=MUTED, font=ui_font(9))
        self.zoom_label.pack(side="right")
        self.canvas = tk.Canvas(parent, bg=CANVAS_BG, highlightthickness=0, bd=0, takefocus=1)
        self.canvas.pack(fill="both", expand=True)
        self.info_label = tk.Label(parent, text="", bg=BG, fg=SOFT, font=ui_font(9), anchor="w", justify="left")
        self.info_label.pack(fill="x", pady=(4, 0))
        self.help_label = tk.Label(parent, text=self.t("help"), bg=BG, fg=MUTED, font=ui_font(8), anchor="w",
                                   justify="left")
        self.help_label.pack(fill="x")
        parent.bind("<Configure>", lambda e: self.info_label.configure(wraplength=max(200, e.width - 10)))
        c = self.canvas
        c.bind("<Configure>", lambda e: self.request_draw())
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_motion)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<ButtonPress-3>", self.on_pan_start)
        c.bind("<B3-Motion>", self.on_pan)
        c.bind("<ButtonRelease-3>", lambda e: setattr(self, "pan_drag", None))
        c.bind("<Double-Button-1>", lambda e: self.fit_view())
        for key in ("Left", "Right", "Up", "Down"):
            c.bind(f"<KeyPress-{key}>", self.on_key)
            c.bind(f"<Shift-KeyPress-{key}>", self.on_key)

    def build_right(self, parent):
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)
        tabs = {}
        for key in ("tab_template", "tab_art", "tab_text", "tab_disc", "tab_export"):
            outer, inner = self.scrollable(self.notebook)
            self.notebook.add(outer, text=self.t(key))
            tabs[key] = inner
        self.build_template_tab(tabs["tab_template"])
        self.build_art_tab(tabs["tab_art"])
        self.build_text_tab(tabs["tab_text"])
        self.build_disc_tab(tabs["tab_disc"])
        self.build_export_tab(tabs["tab_export"])
        tab = self.options.get("tab")
        if tab is not None:
            try:
                self.notebook.select(int(tab))
            except (ValueError, tk.TclError):
                pass

    def build_template_tab(self, parent):
        body = self.section(parent, self.t("tpl_section"))
        self.tpl_var = tk.StringVar()
        self.tpl_combo = ttk.Combobox(body, textvariable=self.tpl_var, state="readonly", height=20)
        self.tpl_combo.pack(fill="x", ipady=2)
        self.tpl_combo.bind("<<ComboboxSelected>>", lambda e: self.on_template_chosen())
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.button(row, self.t("tpl_load"), self.browse_template).pack(side="left", fill="x", expand=True)
        self.button(row, self.t("tpl_folder"), self.open_template_folder).pack(side="left", fill="x", expand=True,
                                                                               padx=(6, 0))
        self.button(body, self.t("ai_open"), self.open_ai_dialog, "blue").pack(fill="x", pady=(6, 0))
        self.label(body, self.t("tpl_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(6, 0))

        body = self.section(parent, self.t("tint_section"))
        self.tint_body = body
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        self.color_button(row, self.t("tint_color"), "profile", "tint").pack(side="left")
        self.button(row, self.t("tint_none"), self.clear_tint).pack(side="left", padx=(6, 0))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(4, 0))
        var = tk.StringVar()
        self.radio(row, self.t("tint_multiply"), var, "multiply").pack(side="left")
        self.radio(row, self.t("tint_colorize"), var, "colorize").pack(side="left", padx=(10, 0))
        self.bind_var(var, "profile", "tint_mode", str)
        self.slider(body, self.t("tint_amount"), "profile", "tint_amount", 0, 1, 0.01, lambda v: f"{v * 100:.0f}%",
                    1.0)
        self.label(body, self.t("tint_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(4, 0))

        body = self.section(parent, self.t("face_section"))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        self.face_var = tk.StringVar(value=self.face)
        for face in FACES:
            rb = tk.Radiobutton(row, text=self.t("face_" + face), variable=self.face_var, value=face,
                                command=lambda: self.set_face(self.face_var.get()), indicatoron=0, bg="#1b3550",
                                fg=FG, selectcolor=BLUE, activebackground="#24476b", activeforeground="white",
                                relief="flat", bd=0, padx=10, pady=5, font=ui_font(9, True))
            rb.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.corner_buttons = []
        b = self.button(body, self.t("corners_detect"), self.detect_corners, "blue")
        b.pack(fill="x", pady=(8, 0))
        self.corner_buttons.append(b)
        b = self.button(body, self.t("corners_reset"), self.reset_corners)
        b.pack(fill="x", pady=(4, 0))
        self.corner_buttons.append(b)
        b = self.button(body, self.t("export_box3d"), self.export_box3d_profile)
        b.pack(fill="x", pady=(4, 0))
        self.corner_buttons.append(b)
        self.label(body, self.t("corners_note"), MUTED, 8).pack(fill="x", pady=(4, 0))

        body = self.section(parent, self.t("gen_section"))
        self.gen_body = body
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        self.label(row, self.t("gen_style")).pack(side="left")
        var = tk.StringVar()
        self.radio(row, self.t("style_box"), var, "box").pack(side="left", padx=(10, 0))
        self.radio(row, self.t("style_case"), var, "case").pack(side="left", padx=(10, 0))
        self.bind_var(var, "generic", "style", str)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.color_button(row, self.t("case_color"), "generic", "case_color").pack(side="left")
        self.preset_var = tk.StringVar(value=self.t("case_preset"))
        presets = ttk.Combobox(row, textvariable=self.preset_var, state="readonly", values=list(CASE_COLORS))
        presets.pack(side="left", fill="x", expand=True, padx=(6, 0))
        presets.bind("<<ComboboxSelected>>", lambda e: self.apply_case_preset())
        self.slider(body, self.t("rim"), "generic", "rim", 0.005, 0.06, 0.001, lambda v: f"{v * 100:.1f}%", 0.022)
        self.slider(body, self.t("angle"), "generic", "angle", 0, 60, 1, lambda v: f"{v:.0f}°", 30)
        self.slider(body, self.t("perspective"), "generic", "perspective", 1.5, 10, 0.1, lambda v: f"{v:.1f}", 3.0)
        self.slider(body, self.t("thickness"), "generic", "thickness", 0.0, 0.45, 0.005, lambda v: f"{v * 100:.1f}%",
                    0.13)
        var = tk.BooleanVar()
        self.check(body, self.t("auto_thickness"), var).pack(fill="x", pady=(4, 0))
        self.bind_var(var, "generic", "auto_thickness", bool)
        var = tk.BooleanVar()
        self.check(body, self.t("edges"), var).pack(fill="x")
        self.bind_var(var, "generic", "edges", bool)

        body = self.section(parent, self.t("display_section"))
        for scope, key in (("display", "guides"), ("profile", "shadows"), ("profile", "sheen"), ("profile", "sharpen"),
                           ("display", "hq")):
            var = tk.BooleanVar()
            self.check(body, self.t(key), var).pack(fill="x")
            self.bind_var(var, scope, key, bool)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.label(row, self.t("overlay_mode")).pack(side="left")
        var = tk.StringVar()
        for value, key in (("auto", "overlay_auto"), ("details", "overlay_details"), ("light", "overlay_light")):
            self.radio(body if value != "auto" else row, self.t(key), var, value).pack(
                side="left" if value == "auto" else "top", anchor="w", padx=(10, 0) if value == "auto" else 0,
                fill="x" if value != "auto" else None)
        self.bind_var(var, "profile", "overlay_mode", str)
        self.slider(body, self.t("overlay"), "profile", "overlay", 0, 1, 0.01, lambda v: f"{v * 100:.0f}%", 0.55)
        self.slider(body, self.t("light_strength"), "profile", "light_strength", 0, 1, 0.01,
                    lambda v: f"{v * 100:.0f}%", 1.0)
        self.label(body, self.t("overlay_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(4, 0))

    def build_art_tab(self, parent):
        self.art_title = self.label(parent, "", FG, 11, True)
        self.art_title.pack(fill="x", padx=12, pady=(10, 0))
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=8, pady=(6, 0))
        for face in FACES:
            tk.Radiobutton(row, text=self.t("face_" + face), variable=self.face_var, value=face,
                           command=lambda: self.set_face(self.face_var.get()), indicatoron=0, bg="#1b3550", fg=FG,
                           selectcolor=BLUE, activebackground="#24476b", activeforeground="white", relief="flat",
                           bd=0, padx=10, pady=5, font=ui_font(9, True)).pack(side="left", fill="x", expand=True,
                                                                             padx=(0, 4))
        body = self.section(parent, self.t("source_section"))
        var = tk.StringVar()
        self.source_radios = {}
        for value, key in (("launchbox", "src_launchbox"), ("color", "src_color"), ("template", "src_template"),
                           ("none", "src_none_opt")):
            rb = self.radio(body, self.t(key), var, value)
            rb.pack(fill="x")
            self.source_radios[value] = rb
        self.bind_var(var, "face", "source", str)
        self.color_button(body, self.t("choose_color"), "face", "color").pack(anchor="w", pady=(4, 0))

        body = self.section(parent, self.t("clean_section"))
        self.clean_body = body
        var = tk.StringVar()
        for value, key in (("original", "clean_original"), ("transparent", "clean_transparent"),
                           ("color", "clean_color")):
            self.radio(body, self.t(key), var, value).pack(fill="x")
        self.bind_var(var, "face", "clean", str)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(4, 0))
        self.color_button(row, self.t("choose_color"), "face", "clean_color").pack(side="left")
        self.button(row, self.t("neutral"), self.neutral_preset).pack(side="left", padx=(6, 0))

        body = self.section(parent, self.t("fit_section"))
        var = tk.StringVar()
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        for value, key in (("stretch", "fit_stretch"), ("fill", "fit_fill"), ("fit", "fit_fit")):
            self.radio(row, self.t(key), var, value).pack(side="left", padx=(0, 8))
        self.bind_var(var, "face", "fit", str)
        self.slider(body, self.t("zoom"), "face", "zoom", 0.1, 4.0, 0.01, lambda v: f"{v * 100:.0f}%", 1.0)
        self.slider(body, self.t("pos_x"), "face", "dx", -1.0, 1.0, 0.005, lambda v: f"{v:+.2f}", 0.0)
        self.slider(body, self.t("pos_y"), "face", "dy", -1.0, 1.0, 0.005, lambda v: f"{v:+.2f}", 0.0)
        self.slider(body, self.t("rotation"), "face", "rotation", -180, 180, 0.5, lambda v: f"{v:+.0f}°", 0.0)
        self.slider(body, self.t("opacity"), "face", "opacity", 0, 1, 0.01, lambda v: f"{v * 100:.0f}%", 1.0)
        self.slider(body, self.t("shade"), "face", "shade", 0, 0.7, 0.01, lambda v: f"{v * 100:.0f}%", None)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(8, 0))
        self.button(row, self.t("reset"), self.reset_face).pack(side="left", fill="x", expand=True)
        self.button(row, self.t("flipx"), lambda: self.toggle_face("flipx")).pack(side="left", fill="x", expand=True,
                                                                               padx=(6, 0))
        self.button(row, self.t("flipy"), lambda: self.toggle_face("flipy")).pack(side="left", fill="x", expand=True,
                                                                               padx=(6, 0))

        body = self.section(parent, self.t("spine_section"))
        var = tk.BooleanVar()
        self.check(body, self.t("from_full"), var).pack(fill="x")
        self.bind_var(var, "profile", "spine_from_full", bool)
        var = tk.StringVar()
        for value, key in (("logo", "gen_logo"), ("band", "gen_band"), ("title", "gen_title"), ("edge", "gen_edge"),
                           ("color", "gen_color"), ("none", "gen_none")):
            self.radio(body, self.t(key), var, value).pack(fill="x")
        self.bind_var(var, "profile", "spine_generate", str)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.label(row, self.t("band_source")).pack(side="left")
        var = tk.StringVar()
        for value, key in (("left", "band_left"), ("center", "band_center"), ("right", "band_right")):
            self.radio(row, self.t(key), var, value).pack(side="left", padx=(10, 0))
        self.bind_var(var, "profile", "band_source", str)
        self.slider(body, self.t("band_frac"), "profile", "band_frac", 0.05, 0.5, 0.01, lambda v: f"{v * 100:.0f}%",
                    0.20)
        self.slider(body, self.t("band_blur"), "profile", "band_blur", 0, 0.6, 0.01, lambda v: f"{v * 100:.0f}%", 0.22)
        self.slider(body, self.t("band_dark"), "profile", "band_dark", 0, 1, 0.01, lambda v: f"{v * 100:.0f}%", 0.70)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(4, 0))
        self.label(row, self.t("spine_font")).pack(side="left")
        var = tk.StringVar()
        ttk.Combobox(row, textvariable=var, state="readonly", values=list(FONT_FILES)).pack(side="left", fill="x",
                                                                                          expand=True, padx=(8, 0))
        self.bind_var(var, "profile", "spine_font", str)

        body = self.section(parent, self.t("gc_section"))
        var = tk.BooleanVar()
        self.check(body, self.t("gc_on"), var).pack(fill="x")
        self.bind_var(var, "profile", "generic_cover", bool)
        self.label(body, self.t("gc_ground")).pack(fill="x", pady=(6, 0))
        grid = tk.Frame(body, bg=PANEL2)
        grid.pack(fill="x")
        var = tk.StringVar()
        for i, (value, key) in enumerate((("silver", "gc_silver"), ("dark", "gc_dark"), ("color", "gc_color"),
                                          ("picture", "gc_picture"))):
            self.radio(grid, self.t(key), var, value).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 14))
        self.bind_var(var, "profile", "gc_style", str)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(4, 0))
        self.color_button(row, self.t("gc_bg"), "profile", "gc_bg").pack(side="left")
        self.button(row, self.t("gc_choose"), lambda: self.choose_gc_file("gc_picture", "gc_style")).pack(
            side="left", padx=(6, 0))
        self.color_button(row, self.t("gc_ink"), "profile", "gc_ink").pack(side="left", padx=(6, 0))
        self.label(body, self.t("gc_logo")).pack(fill="x", pady=(8, 0))
        var = tk.StringVar()
        for value, key in (("auto", "gc_logo_auto"), ("drawn", "gc_logo_drawn")):
            self.radio(body, self.t(key), var, value).pack(fill="x")
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        self.radio(row, self.t("gc_logo_picture"), var, "picture").pack(side="left")
        self.button(row, self.t("gc_choose"), lambda: self.choose_gc_file("gc_logo_file", "gc_logo")).pack(
            side="left", padx=(8, 0))
        self.bind_var(var, "profile", "gc_logo", str)
        grid = tk.Frame(body, bg=PANEL2)
        grid.pack(fill="x", pady=(6, 0))
        grid.columnconfigure(1, weight=1)
        for r, key in enumerate(("gc_name", "gc_maker")):
            self.label(grid, self.t(key)).grid(row=r, column=0, sticky="w")
            var = tk.StringVar()
            tk.Entry(grid, textvariable=var, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                     font=ui_font(10)).grid(row=r, column=1, sticky="ew", padx=(8, 0), pady=2, ipady=2)
            self.bind_var(var, "profile", key, str)
        self.gc_auto_label = self.label(body, "", MUTED, 8, wraplength=self.px(370))
        self.gc_auto_label.pack(fill="x")
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.label(row, self.t("gc_title")).pack(side="left")
        var = tk.StringVar()
        for value, key in (("title", "gc_title_text"), ("logo", "gc_title_logo")):
            self.radio(row, self.t(key), var, value).pack(side="left", padx=(10, 0))
        self.bind_var(var, "profile", "gc_title", str)
        var = tk.BooleanVar()
        self.check(body, self.t("gc_spine"), var).pack(fill="x", pady=(6, 0))
        self.bind_var(var, "profile", "gc_spine", bool)
        self.label(body, self.t("gc_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(4, 0))

        body = self.section(parent, self.t("pics_section"))
        for key in ("front_fallbacks", "match_region"):
            var = tk.BooleanVar()
            self.check(body, self.t(key), var).pack(fill="x")
            self.bind_var(var, "profile", key, bool)
        self.label(body, self.t("web_title"), SOFT, 9, True).pack(fill="x", pady=(8, 0))
        grid = tk.Frame(body, bg=PANEL2)
        grid.pack(fill="x")
        var = tk.StringVar()
        for i, (value, key) in enumerate((("auto", "web_auto"), ("libretro", "web_libretro"), ("steam", "web_steam"),
                                          ("off", "web_off"))):
            self.radio(grid, self.t(key), var, value).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 14))
        self.bind_var(var, "profile", "web_covers", str)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(4, 0))
        self.label(row, self.t("web_system")).pack(side="left")
        var = tk.StringVar()
        self.web_system_combo = ttk.Combobox(row, textvariable=var, height=20,
                                             values=[""] + sorted(set(LIBRETRO_SYSTEMS.values())),
                                             postcommand=self.load_libretro_systems)
        self.web_system_combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.bind_var(var, "profile", "web_system", str)
        self.web_auto_label = self.label(body, "", MUTED, 8, wraplength=self.px(370))
        self.web_auto_label.pack(fill="x")
        self.web_button = self.button(body, self.t("web_find"), self.find_web_cover)
        self.web_button.pack(fill="x", pady=(4, 0))
        self.label(body, self.t("web_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(4, 0))

        body = self.section(parent, self.t("up_section"))
        var = tk.BooleanVar()
        self.check(body, self.t("up_on"), var).pack(fill="x")
        self.bind_var(var, "profile", "upscale", bool)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(2, 0))
        var = tk.IntVar()
        tk.Spinbox(row, from_=200, to=3000, increment=50, textvariable=var, width=7, bg=ENTRY, fg=FG,
                   buttonbackground=PANEL2, relief="flat", insertbackground=FG).pack(side="left", padx=(20, 0))
        self.bind_var(var, "profile", "upscale_below", int)
        self.label(row, self.t("up_model")).pack(side="left", padx=(14, 0))
        var = tk.StringVar()
        self.up_model_combo = ttk.Combobox(row, textvariable=var, height=16, values=[""])
        self.up_model_combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.bind_var(var, "profile", "upscale_model", str)
        self.button(body, self.t("up_refresh"), self.refresh_upscalers).pack(anchor="w", pady=(6, 0))
        self.up_label = self.label(body, "", MUTED, 8, wraplength=self.px(370))
        self.up_label.pack(fill="x")
        self.label(body, self.t("up_note", cache=CACHE_DIR), MUTED, 8, wraplength=self.px(370)).pack(fill="x",
                                                                                                  pady=(4, 0))

        body = self.section(parent, self.t("override_section"))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        self.button(row, self.t("override_load"), self.load_override).pack(side="left", fill="x", expand=True)
        self.button(row, self.t("override_clear"), self.clear_overrides).pack(side="left", fill="x", expand=True,
                                                                              padx=(6, 0))

    def build_text_tab(self, parent):
        body = self.section(parent, self.t("text_section", face=self.t("face_" + self.face)))
        self.text_section_body = body
        self.label(body, self.t("text_value"), MUTED, 8, wraplength=self.px(370)).pack(fill="x")
        self.text_var = tk.StringVar(value=getattr(self, "_text_value", "{title}"))
        tk.Entry(body, textvariable=self.text_var, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                 font=ui_font(10)).pack(fill="x", ipady=4, pady=(2, 6))
        grid = tk.Frame(body, bg=PANEL2)
        grid.pack(fill="x")
        self.label(grid, self.t("font")).grid(row=0, column=0, sticky="w")
        self.new_font = tk.StringVar(value="Arial Bold")
        ttk.Combobox(grid, textvariable=self.new_font, state="readonly", values=list(FONT_FILES), width=18).grid(
            row=0, column=1, sticky="we", padx=(8, 0))
        self.label(grid, self.t("size")).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.new_size = tk.DoubleVar(value=4.5)
        tk.Spinbox(grid, from_=1, to=30, increment=0.5, textvariable=self.new_size, width=6, bg=ENTRY, fg=FG,
                   buttonbackground=PANEL2, relief="flat", insertbackground=FG).grid(row=1, column=1, sticky="w",
                                                                                   padx=(8, 0), pady=(4, 0))
        grid.columnconfigure(1, weight=1)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.new_color = "#ffffff"
        self.new_stroke = "#111111"
        self.new_color_btn = self.button(row, self.t("text_color"), lambda: self.pick_new_color("new_color"))
        self.new_color_btn.pack(side="left")
        self.new_stroke_btn = self.button(row, self.t("stroke_color"), lambda: self.pick_new_color("new_stroke"))
        self.new_stroke_btn.pack(side="left", padx=(6, 0))
        self.paint_new_colors()
        self.button(body, self.t("text_add"), self.add_text, "blue").pack(fill="x", pady=(8, 0))

        body = self.section(parent, self.t("logo_section"))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        self.button(row, self.t("logo_file"), self.add_logo_file).pack(side="left", fill="x", expand=True)
        self.button(row, self.t("logo_game"), self.add_game_logo).pack(side="left", fill="x", expand=True,
                                                                       padx=(6, 0))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.button(row, self.t("logo_marquee"), self.add_game_marquee).pack(side="left", fill="x", expand=True)
        self.button(row, self.t("slots_add"), self.add_spine_slots, "blue").pack(side="left", fill="x", expand=True,
                                                                                 padx=(6, 0))
        self.label(body, self.t("slots_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(4, 0))

        body = self.section(parent, self.t("layers_section", face=self.t("face_" + self.face)))
        self.layers_body = body
        self.layer_list = tk.Listbox(body, height=6, bg=ENTRY, fg=FG, selectbackground=BLUE, selectforeground="white",
                                     relief="flat", highlightthickness=0, font=ui_font(9), activestyle="none",
                                     exportselection=False)
        self.layer_list.pack(fill="x")
        self.layer_list.bind("<<ListboxSelect>>", self.on_layer_select)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.button(row, self.t("up"), lambda: self.move_layer(-1)).pack(side="left")
        self.button(row, self.t("down"), lambda: self.move_layer(1)).pack(side="left", padx=(6, 0))
        self.button(row, self.t("delete"), self.delete_layer, "red").pack(side="right")

        body = self.section(parent, self.t("layer_props"))
        self.layer_text_var = tk.StringVar()
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self.layer_text_var, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                 font=ui_font(9)).pack(side="left", fill="x", expand=True, ipady=3)
        self.button(row, self.t("apply_text"), self.apply_layer_text).pack(side="left", padx=(6, 0))
        self.slider(body, self.t("pos_x"), "layer", "x", 0, 1, 0.005, lambda v: f"{v:.2f}", 0.5)
        self.slider(body, self.t("pos_y"), "layer", "y", 0, 1, 0.005, lambda v: f"{v:.2f}", 0.5)
        self.slider(body, self.t("size"), "layer", "size", 1, 100, 0.5, lambda v: f"{v:.1f}%", None)
        self.slider(body, self.t("rotation"), "layer", "rotation", -180, 180, 1, lambda v: f"{v:+.0f}°", 0.0)
        self.slider(body, self.t("opacity"), "layer", "opacity", 0, 1, 0.01, lambda v: f"{v * 100:.0f}%", 1.0)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        self.color_button(row, self.t("text_color"), "layer", "color").pack(side="left")
        self.color_button(row, self.t("stroke_color"), "layer", "stroke_color").pack(side="left", padx=(6, 0))
        var = tk.StringVar()
        ttk.Combobox(row, textvariable=var, state="readonly", values=list(FONT_FILES), width=16).pack(
            side="left", fill="x", expand=True, padx=(6, 0))
        self.bind_var(var, "layer", "font", str)
        var = tk.BooleanVar()
        self.check(body, self.t("only_made"), var).pack(fill="x", pady=(6, 0))
        self.bind_var(var, "layer", "only_made", bool)

    def build_disc_tab(self, parent):
        body = self.section(parent, self.t("disc_kind_section"))
        var = tk.StringVar()
        self.disc_auto_radio = self.radio(body, "", var, "auto")
        self.disc_auto_radio.pack(fill="x")
        for kind in DISC_KINDS:
            self.radio(body, self.t("disc_" + kind), var, kind).pack(fill="x")
        self.bind_var(var, "profile", "disc_kind", str)

        body = self.section(parent, self.t("disc_art_section"))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        self.label(row, self.t("disc_crop")).pack(side="left")
        var = tk.StringVar()
        for value in ("top", "center", "bottom"):
            self.radio(row, self.t("disc_" + value), var, value).pack(side="left", padx=(10, 0))
        self.bind_var(var, "profile", "disc_crop", str)
        self.slider(body, self.t("disc_zoom"), "profile", "disc_zoom", 1.0, 3.0, 0.05, lambda v: f"{v * 100:.0f}%", 1.0)

        body = self.section(parent, self.t("disc_more_section"))
        var = tk.BooleanVar()
        self.check(body, self.t("disc_logo"), var).pack(fill="x")
        self.bind_var(var, "profile", "disc_logo", bool)
        self.slider(body, self.t("disc_logo_size"), "profile", "disc_logo_size", 0.2, 0.9, 0.01,
                    lambda v: f"{v * 100:.0f}%", 0.55)
        self.label(body, self.t("disc_text"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(8, 2))
        var = tk.StringVar()
        tk.Entry(body, textvariable=var, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                 font=ui_font(10)).pack(fill="x", ipady=3)
        self.bind_var(var, "profile", "disc_text", str)
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(4, 0))
        self.label(row, self.t("disc_text_pos")).pack(side="left")
        var = tk.StringVar()
        for value in ("top", "bottom"):
            self.radio(row, self.t("disc_text_" + value), var, value).pack(side="left", padx=(10, 0))
        self.bind_var(var, "profile", "disc_text_pos", str)
        self.color_button(row, self.t("disc_text_color"), "profile", "disc_text_color").pack(side="right")
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x", pady=(8, 0))
        self.label(row, self.t("disc_size")).pack(side="left")
        var = tk.IntVar()
        tk.Spinbox(row, from_=200, to=3000, increment=100, textvariable=var, width=7, bg=ENTRY, fg=FG,
                   buttonbackground=PANEL2, relief="flat", insertbackground=FG).pack(side="right")
        self.bind_var(var, "profile", "disc_size", int)
        self.label(body, self.t("disc_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x", pady=(8, 0))
        self.button(body, self.t("disc_show"), lambda: self.set_view("disc")).pack(anchor="w", pady=(6, 0))

    def build_export_tab(self, parent):
        body = self.section(parent, self.t("what_section"))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        for key in ("make_box", "make_disc"):
            var = tk.BooleanVar()
            self.check(row, self.t(key), var).pack(side="left", padx=(0, 18))
            self.bind_var(var, "export", key, bool)

        body = self.section(parent, self.t("out_section"))
        self.out_label = self.label(body, "", FG, 8, wraplength=self.px(370))
        self.out_label.pack(fill="x", pady=(0, 4))
        var = tk.StringVar()
        self.radio(body, self.t("region_same"), var, "same").pack(fill="x")
        self.radio(body, self.t("region_root"), var, "root").pack(fill="x")
        self.bind_var(var, "export", "region", str)

        body = self.section(parent, self.t("existing_section"))
        var = tk.StringVar()
        for value, key in (("skip", "ex_skip"), ("replace", "ex_replace"), ("next", "ex_next")):
            self.radio(body, self.t(key), var, value).pack(fill="x")
        self.bind_var(var, "export", "existing", str)

        body = self.section(parent, self.t("format_section"))
        row = tk.Frame(body, bg=PANEL2)
        row.pack(fill="x")
        var = tk.StringVar()
        self.radio(row, self.t("fmt_png"), var, "png").pack(side="left")
        self.radio(row, self.t("fmt_jpg"), var, "jpg").pack(side="left", padx=(10, 0))
        self.bind_var(var, "export", "format", str)
        self.color_button(row, self.t("jpg_bg"), "export", "jpg_bg").pack(side="right")
        grid = tk.Frame(body, bg=PANEL2)
        grid.pack(fill="x", pady=(6, 0))
        self.label(grid, self.t("max_height")).grid(row=0, column=0, sticky="w")
        var = tk.IntVar()
        tk.Spinbox(grid, from_=0, to=6000, increment=50, textvariable=var, width=7, bg=ENTRY, fg=FG,
                   buttonbackground=PANEL2, relief="flat", insertbackground=FG).grid(row=0, column=1, sticky="e")
        self.bind_var(var, "export", "max_height", int)
        self.label(grid, self.t("threads")).grid(row=1, column=0, sticky="w", pady=(4, 0))
        var = tk.IntVar()
        tk.Spinbox(grid, from_=1, to=16, textvariable=var, width=7, bg=ENTRY, fg=FG, buttonbackground=PANEL2,
                   relief="flat", insertbackground=FG).grid(row=1, column=1, sticky="e", pady=(4, 0))
        self.bind_var(var, "export", "threads", int)
        grid.columnconfigure(0, weight=1)
        var = tk.BooleanVar()
        self.check(body, self.t("trim"), var).pack(fill="x", pady=(4, 0))
        self.bind_var(var, "export", "trim", bool)

        body = self.section(parent, self.t("go_section"))
        self.go_buttons = []
        for text, cmd, kind in (("save_one", lambda: self.save_one(False), "blue"),
                                ("export_one", lambda: self.save_one(True), "normal"),
                                ("make_selected", lambda: self.make_boxes("selected"), "green"),
                                ("make_shown", lambda: self.make_boxes("shown"), "green"),
                                ("make_all", lambda: self.make_boxes("all"), "green")):
            b = self.button(body, self.t(text, n=0), cmd, kind)
            b.pack(fill="x", pady=(0, 5))
            b.text_key = text
            self.go_buttons.append(b)
        self.label(body, self.t("refresh_note"), MUTED, 8, wraplength=self.px(370)).pack(fill="x")

        body = self.section(parent, self.t("profile_section"))
        for text, cmd in (("profile_default", self.profile_as_default), ("profile_export", self.export_profile),
                          ("profile_import", self.import_profile), ("profile_reset", self.reset_profile)):
            self.button(body, self.t(text), cmd).pack(fill="x", pady=(0, 5))

        body = self.section(parent, self.t("log_section"))
        self.log_text = tk.Text(body, height=12, bg=ENTRY, fg=SOFT, relief="flat", font=("Consolas", 8),
                                wrap="word", state="disabled", highlightthickness=0)
        self.log_text.pack(fill="x")

    # ------------------------------------------------------------------------------------------- LaunchBox
    def startup(self):
        root = self.options.get("lb") or self.cfg.get("lb_root") or ""
        if not LaunchBox.is_launchbox(root):
            root = find_launchbox()
        if root:
            self.open_launchbox(root)
        else:
            self.set_status(self.t("no_lb"))
            if not self.shot_state and not self.options.get("screenshot"):
                self.root.after(300, self.choose_lb)
        if self.options.get("ai"):
            self.root.after(300, self.open_ai_dialog)

    def choose_lb(self):
        if self.batch_running:
            return
        folder = filedialog.askdirectory(parent=self.root, title=self.t("lb_folder"),
                                         initialdir=self.lb_var.get() or "C:\\")
        if not folder:
            return
        if not LaunchBox.is_launchbox(folder):
            messagebox.showerror(APP_NAME, self.t("not_lb"), parent=self.root)
            return
        self.open_launchbox(folder)

    def open_launchbox(self, folder):
        if self.batch_running or not folder:
            return
        if not LaunchBox.is_launchbox(folder):
            self.set_status(self.t("not_lb"))
            return
        self.lb_var.set(folder)
        self.set_status(self.t("loading_platforms"))
        token = self.load_token = object()

        def work():
            try:
                lb = LaunchBox(folder)
                lb.load()
                self.queue.put(("lb", token, lb, None))
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.queue.put(("lb", token, None, f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def on_platform_typed(self, event):
        if event.keysym in ("Return", "Up", "Down", "Escape", "Tab"):
            return
        if not self.lb:
            return
        q = self.plat_var.get().strip().casefold()
        self.plat_combo["values"] = [p for p in self.lb.platforms if q in p.casefold()] if q else self.lb.platforms

    def on_platform_enter(self, _event=None):
        if not self.lb:
            return
        name = self.plat_var.get().strip()
        if name in self.lb.xml_files:
            self.select_platform(name)
            return
        values = list(self.plat_combo["values"])
        if values:
            self.plat_var.set(values[0])
            self.select_platform(values[0])

    def profile_for(self, name):
        saved = self.cfg["profiles"].get(name)
        prof = merged_profile(saved if saved is not None else self.cfg.get("default_profile"))
        self.cfg["profiles"][name] = prof
        return prof

    def select_platform(self, name):
        if not self.lb or name not in self.lb.xml_files:
            return
        if self.batch_running:
            self.set_status(self.t("busy"))
            self.plat_var.set(self.platform)
            return
        self.plat_combo["values"] = self.lb.platforms
        self.platform = name
        self.cfg["last_platform"] = name
        self.profile = self.profile_for(name)
        if self.options.get("template"):
            self.profile["template"] = self.options.pop("template")
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.load_template()
        self.games, self.found, self.rows = [], {}, []
        self.current, self.current_index, self.pics, self.current_found = None, -1, None, {}
        self.overrides = {}
        self.fill_tree([])
        self.sync_controls()
        self.update_output_label()
        self.update_info()
        self.schedule_save()
        self.set_status(self.t("loading_games", name=name))
        token = self.load_token = object()
        lb, profile = self.lb, copy.deepcopy(self.profile)

        def work():
            try:
                games = lb.games(name)
                found = {i: lb.find(name, g, profile) for i, g in enumerate(games)}
                self.queue.put(("games", token, name, games, found, None))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("games", token, name, [], {}, f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()
        self.request_draw()

    def refresh_statuses(self, then_select=None):
        """Work out again which pictures each game has (after saving boxes or changing how pictures are picked)."""
        if not self.lb or not self.platform or not self.games:
            return
        token = self.load_token = object()
        lb, name, games, profile = self.lb, self.platform, list(self.games), copy.deepcopy(self.profile)

        def work():
            try:
                lb.index(name, OUT_TYPE, refresh=True)
                found = {i: lb.find(name, g, profile) for i, g in enumerate(games)}
                self.queue.put(("statuses", token, name, found))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("log", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def update_platform_info(self):
        if not self.games:
            self.plat_info.configure(text="")
            return
        front = sum(1 for f in self.found.values() if f.get("front"))
        has3d = sum(1 for f in self.found.values() if f.get("box3d"))
        self.plat_info.configure(text=self.t("plat_info", games=len(self.games), front=front, has3d=has3d))
        self.update_go_buttons()

    # ------------------------------------------------------------------------------------------- game list
    def schedule_filter(self):
        if self._filter_job is not None:
            self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(250, self.apply_filter)

    def on_filter_mode(self):
        texts = [self.t("filter_" + k) for k in self.filter_keys]
        try:
            self.filter_mode = self.filter_keys[texts.index(self.filter_var.get())]
        except ValueError:
            self.filter_mode = "all"
        self.apply_filter()

    def sort_by(self, column):
        col, desc = self.sort
        self.sort = (column, not desc if col == column else False)
        self.apply_filter(keep_selection=True)

    def row_values(self, i):
        g, f = self.games[i], self.found.get(i, {})
        front = "✓" if f.get("front_type") == FRONT_TYPES[0] else ("≈" if f.get("front") else "–")
        spine = "✓" if f.get("spine") else ("F" if f.get("full") else "–")
        box3d = str(len(f["box3d"])) if f.get("box3d") else "–"
        return (g.title, g.region, front, spine, box3d)

    def apply_filter(self, keep_selection=False):
        self._filter_job = None
        q = self.search_var.get().strip().casefold() if hasattr(self, "search_var") else ""
        mode = getattr(self, "filter_mode", "all")
        rows = []
        for i, g in enumerate(self.games):
            if q and q not in g.title.casefold():
                continue
            f = self.found.get(i, {})
            if mode == "missing" and f.get("box3d") or mode == "has" and not f.get("box3d"):
                continue
            if mode == "nofront" and f.get("front"):
                continue
            rows.append(i)
        col, desc = self.sort
        index = {"title": 0, "region": 1, "front": 2, "spine": 3, "box3d": 4}[col]
        rows.sort(key=lambda i: (str(self.row_values(i)[index]).casefold(), self.games[i].title.casefold()),
                  reverse=desc)
        self.rows = rows
        selected = set(self.tree.selection()) if keep_selection else set()
        self.fill_tree(rows)
        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
            self.tree.see(keep[0])
        elif self.current_index >= 0 and self.tree.exists(str(self.current_index)):
            self.tree.selection_set(str(self.current_index))
            self.tree.see(str(self.current_index))
        elif rows and self.current is None:
            self.tree.selection_set(str(rows[0]))
        self.update_go_buttons()

    def fill_tree(self, rows):
        tree = self.tree
        tree.delete(*tree.get_children())
        for i in rows[:MAX_ROWS]:
            f = self.found.get(i, {})
            tags = ("has3d",) if f.get("box3d") else ("nofront",) if not f.get("front") else ()
            tree.insert("", "end", iid=str(i), values=self.row_values(i), tags=tags)
        if not self.games:
            text = ""
        elif len(rows) > MAX_ROWS:
            text = self.t("count_cap", shown=len(rows), total=len(self.games), cap=MAX_ROWS)
        else:
            text = self.t("count", shown=len(rows), total=len(self.games))
        self.count_label.configure(text=(text + "\n" if text else "") + self.t("legend"))

    def update_row(self, i):
        if self.tree.exists(str(i)):
            f = self.found.get(i, {})
            tags = ("has3d",) if f.get("box3d") else ("nofront",) if not f.get("front") else ()
            self.tree.item(str(i), values=self.row_values(i), tags=tags)

    def on_game_select(self, _event=None):
        self.update_go_buttons()
        sel = self.tree.focus() or (self.tree.selection()[0] if self.tree.selection() else "")
        if not sel or not sel.isdigit():
            return
        i = int(sel)
        if i == self.current_index or i >= len(self.games):
            return
        self.current_index = i
        self.current = self.games[i]
        self.overrides = {}
        self.pics = None
        self.update_info()
        self.load_current()

    def load_current(self):
        if not self.current or not self.lb:
            return
        token = self.pics_token = object()
        lb, name, game, profile = self.lb, self.platform, self.current, copy.deepcopy(self.profile)

        def work():
            try:
                pics, found = load_pictures(lb, name, game, profile, limit=1600)
                self.queue.put(("pics", token, game, pics, found, None))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("pics", token, game, None, {}, f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def update_go_buttons(self):
        if not hasattr(self, "go_buttons"):
            return
        counts = {"make_selected": len(self.tree.selection()), "make_shown": len(self.rows),
                  "make_all": len(self.games)}
        for b in self.go_buttons:
            b.configure(text=self.t(b.text_key, n=counts.get(b.text_key, 0)),
                        state="disabled" if self.batch_running else "normal")

    def generic_wanted(self, found=None):
        """Does this game get a generic cover (no Box - Front at all, and the setting is on)?"""
        f = found if found is not None else (self.current_found or self.found.get(self.current_index, {}))
        return (not f.get("front") and "front" not in self.overrides and bool(self.profile.get("generic_cover", True))
                and self.profile["faces"]["front"].get("source") == "launchbox")

    def update_info(self):
        if not hasattr(self, "info_label"):
            return
        g = self.current
        if g is None:
            self.info_label.configure(text="")
            return
        f = self.current_found or self.found.get(self.current_index, {})
        parts = [f"{g.title}" + (f"  [{g.region}]" if g.region else "")]
        generic = self.generic_wanted(f)
        if f.get("front"):
            where = f.get("region") or "—"
            parts.append(f"{self.t('info_front')}: {f.get('front_type', FRONT_TYPES[0])} ({where})")
        elif generic:
            parts.append(f"{self.t('info_front')}: {self.t('src_generic_cover')}")
        else:
            parts.append(self.t("no_front_pic"))
        origin = None
        if "spine" in self.overrides:
            origin = "override"
        elif self.pics is not None:
            origin = self.pics.spine_for(self.profile)[1]
            if generic and self.pics.spine is None and self.profile.get("gc_spine", True):
                origin = "generic"
        names = {"spine": self.t("src_spine"), "full": self.t("src_full"), "generate": self.t("src_generate"),
                 None: self.t("src_none"), "override": self.t("src_override"), "generic": self.t("src_generic_spine")}
        spine_text = f"{self.t('info_spine')}: {names.get(origin, origin)}"
        if f.get("spine_other_region") and origin != "spine":
            spine_text += " " + self.t("src_other_region")
        parts.append(spine_text)
        n3d = len(f.get("box3d") or [])
        parts.append(f"{self.t('info_3d')}: " + (self.t("has3d", n=n3d) if n3d else self.t("no3d")))
        ndisc = len(f.get("disc") or [])
        if ndisc or self.view == "disc" or self.cfg["export"].get("make_disc"):
            parts.append(f"{self.t('info_disc')}: " + (self.t("has3d", n=ndisc) if ndisc else self.t("no3d")))
        self.info_label.configure(text="   ·   ".join(parts))

    # ------------------------------------------------------------------------------------------- templates
    def template_names(self):
        names = []
        try:
            names = sorted((p.name for p in MODEL_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS),
                           key=str.casefold)
        except OSError:
            pass
        for path in self.cfg.get("custom_templates", []):
            if path not in names and Path(path).is_file():
                names.append(path)
        return names

    def template_path(self, name):
        p = Path(name)
        return p if p.is_absolute() else MODEL_DIR / name

    def update_template_controls(self):
        if not hasattr(self, "tpl_combo"):
            return
        names = self.template_names()
        self.tpl_display = [self.t("tpl_generic")] + names
        self.tpl_values = [GENERIC] + names
        self.tpl_combo["values"] = self.tpl_display
        current = self.profile.get("template", GENERIC)
        if current in self.tpl_values:
            self.tpl_var.set(self.tpl_display[self.tpl_values.index(current)])
        else:
            self.tpl_var.set(current)
        generic = self.template_img is None
        for b in self.corner_buttons:
            b.configure(state="disabled" if generic else "normal")
        state = "normal" if not generic else "disabled"
        self.source_radios["template"].configure(state=state)
        for body in (self.clean_body, self.tint_body):
            for child in body.winfo_children():
                self._set_state(child, state)
        gen_state = "normal" if generic else "disabled"
        for child in self.gen_body.winfo_children():
            self._set_state(child, gen_state)

    def _set_state(self, widget, state):
        try:
            widget.configure(state=state if not isinstance(widget, ttk.Combobox) else
                             ("readonly" if state == "normal" else "disabled"))
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._set_state(child, state)

    def on_template_chosen(self):
        try:
            value = self.tpl_values[self.tpl_display.index(self.tpl_var.get())]
        except (ValueError, AttributeError):
            return
        if value == self.profile.get("template"):
            return
        self.remember()
        self.profile["template"] = value
        self.load_template()
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    def browse_template(self):
        path = filedialog.askopenfilename(parent=self.root, title=self.t("pick_template"),
                                          initialdir=str(MODEL_DIR) if MODEL_DIR.is_dir() else None,
                                          filetypes=[(self.t("images"), "*.png *.webp *.jpg *.jpeg *.bmp"),
                                                     (self.t("all_files"), "*.*")])
        if not path:
            return
        p = Path(path)
        try:
            value = p.name if p.parent.resolve() == MODEL_DIR.resolve() else str(p)
        except OSError:
            value = str(p)
        if value == str(p) and value not in self.cfg["custom_templates"]:
            self.cfg["custom_templates"].append(value)
        self.remember()
        self.profile["template"] = value
        self.load_template()
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    def open_template_folder(self):
        try:
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(MODEL_DIR))  # noqa: S606 - opening a folder in Explorer
        except (OSError, AttributeError) as exc:
            self.log(f"{exc}")

    def choose_gc_file(self, key, mode_key):
        """A picture for the generic cover (its ground or the platform's logo); that choice is switched on with it."""
        path = filedialog.askopenfilename(parent=self.root, title=self.t("pick_picture"),
                                          filetypes=[(self.t("images"), "*.png *.webp *.jpg *.jpeg *.bmp"),
                                                     (self.t("all_files"), "*.*")])
        if not path:
            return
        self.remember()
        self.profile[key] = path
        self.profile[mode_key] = "picture"
        self.sync_controls()
        self.schedule_save()
        self.update_info()
        self.request_draw()

    def ai_url(self) -> str:
        """The AI server's address: the AI window's, else that of Stability Matrix's active package."""
        url = (self.cfg.get("ai") or {}).get("url", "") if isinstance(self.cfg.get("ai"), dict) else ""
        if url:
            return url
        packages = sm_packages(sm_library(find_stability_matrix((self.cfg.get("ai") or {}).get("sm_exe", ""))))
        active = next((p for p in packages if p["active"]), packages[0] if packages else None)
        return active["url"] if active else "http://127.0.0.1:7860"

    def find_web_cover(self):
        """Look on the web for the cover of the game shown (one with no Box - Front) and save it into LaunchBox."""
        if self.current is None or self.lb is None:
            return
        found = dict(self.current_found or self.found.get(self.current_index, {}))
        if found.get("front"):
            self.set_status(self.t("web_has_front"))
            return
        game, index, lb, name, profile = self.current, self.current_index, self.lb, self.platform, copy.deepcopy(
            self.profile)
        if profile.get("web_covers", "auto") == "off":
            profile["web_covers"] = "auto"                 # the button asks for it even when batches don't
        self.set_status(self.t("web_searching", title=game.title))
        self.web_button.configure(state="disabled")

        def work():
            try:
                path, where = fetch_missing_cover(lb, name, game, profile, found)
                self.queue.put(("webcover", index, game, path, where, found, None))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("webcover", index, game, None, "", None, f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def load_libretro_systems(self):
        """libretro's full list of systems for the combobox (from the web, kept two weeks)."""
        if getattr(self, "_systems_asked", False):
            return
        self._systems_asked = True

        def work():
            try:
                self.queue.put(("systems", libretro_systems()))
            except (OSError, ValueError, http.client.HTTPException) as exc:
                self.queue.put(("log", f"libretro: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def refresh_upscalers(self):
        """Ask the AI server which upscale models it has."""
        url = self.ai_url()
        UPSCALER.configure(url)
        self.up_label.configure(text=self.t("ai_checking", url=url))

        def work():
            try:
                server = AIServer.detect(url)
                if server is None:
                    self.queue.put(("upmodels", [], "", TEXTS["up_no_server"].format(url=url)))
                    return
                self.queue.put(("upmodels", server.upscalers(), server.name, ""))
            except AIError as exc:
                self.queue.put(("upmodels", [], "", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def update_platform_labels(self):
        """The hints that depend on the platform: libretro's system and the disc's kind when left automatic."""
        if hasattr(self, "web_auto_label"):
            official = self.lb.official.get(self.platform, "") if self.lb else ""
            system = libretro_system(self.platform, official)
            if system:
                text = self.t("web_system_auto", name=system)
            elif not_games(self.platform) or not_games(official):
                text = self.t("web_system_not_games")
            elif is_pc_platform(self.platform, official):
                text = self.t("web_system_auto", name="Steam")
            else:
                text = self.t("web_system_none")
            self.web_auto_label.configure(text=text)
        if hasattr(self, "disc_auto_radio"):
            kind = disc_kind({"disc_kind": "auto"}, self.platform)
            self.disc_auto_radio.configure(text=self.t("disc_auto", kind=self.t("disc_" + kind)))

    def open_ai_dialog(self):
        if self.ai_dialog is not None and not self.ai_dialog.closed:
            self.ai_dialog.win.deiconify()
            self.ai_dialog.win.lift()
            self.ai_dialog.win.focus_force()
            return
        self.ai_dialog = AIDialog(self)

    def use_template(self, value):
        """Choose a template for this platform (a name in "box model" or a full path)."""
        if value != Path(value).name and value not in self.cfg["custom_templates"]:
            self.cfg["custom_templates"].append(value)
        self.remember()
        self.profile["template"] = value
        self.load_template()
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    def load_template(self, keep_quads=False):
        name = self.profile.get("template", GENERIC)
        self.template_img, self.template_key = None, ""
        if not keep_quads:
            self.quads = {}
        if name == GENERIC:
            self.update_template_controls()
            return
        path = self.template_path(name)
        try:
            img = Image.open(path)
            img.load()
            self.template_img = img.convert("RGBA")
            self.template_key = file_sha(path)
        except (OSError, ValueError) as exc:
            self.log(self.t("tpl_missing", name=name) + f" ({exc})")
            self.template_img = None
            self.update_template_controls()
            return
        if not keep_quads:
            saved = self.cfg["templates"].get(self.template_key, {}).get("quads")
            quads = None
            if isinstance(saved, dict) and valid_quad(saved.get("front") or []):
                quads = {f: [tuple(p) for p in saved[f]] if saved.get(f) and valid_quad(saved[f]) else None
                         for f in FACES}
            if quads is None:      # corners nobody moved yet: not stored, so a profile added later still counts
                quads = profile_quads(path, self.template_img.size) or detect_quads(self.template_img)
            self.quads = quads
        self.update_template_controls()

    def store_quads(self):
        if self.template_img is None or not self.template_key:
            return
        self.cfg["templates"][self.template_key] = {
            "name": Path(self.profile.get("template", "")).name, "size": list(self.template_img.size),
            "quads": {f: [list(map(float, p)) for p in q] if q else None for f, q in self.quads.items()}}
        self.schedule_save()

    def detect_corners(self):
        if self.template_img is None:
            return
        self.remember()
        self.quads = detect_quads(self.template_img)
        self.store_quads()
        self.request_draw()

    def reset_corners(self):
        if self.template_img is None:
            return
        self.remember()
        size = self.template_img.size
        self.quads = profile_quads(self.template_path(self.profile.get("template", "")), size) or default_quads(size)
        self.store_quads()
        self.request_draw()

    def ensure_spine_quad(self):
        """A template without spine corners gets a narrow strip left of the front, ready to be dragged."""
        if self.template_img is None or self.quads.get("spine") or not self.quads.get("front"):
            return
        tl, tr, br, bl = self.quads["front"]
        width = max(8.0, (dist(tl, tr) + dist(bl, br)) / 2 * 0.08)
        x1 = min(tl[0], bl[0]) - 2
        x0 = max(0.0, x1 - width)
        self.quads["spine"] = [(x0, tl[1] + 4), (x1, tl[1]), (x1, bl[1]), (x0, bl[1] - 4)]
        self.store_quads()

    # ------------------------------------------------------------------------------------------- face settings
    def set_face(self, face):
        if face not in FACES:
            return
        self.face = face
        if hasattr(self, "face_var"):
            self.face_var.set(face)
        if face == "spine":
            self.ensure_spine_quad()
        self.layer_index = -1
        self.sync_controls()
        self.request_draw()

    def update_face_texts(self):
        name = self.t("face_" + self.face)
        if hasattr(self, "art_title"):
            self.art_title.configure(text=self.t("art_for", face=name))
        if hasattr(self, "text_section_body"):
            self.text_section_body.title_label.configure(text=self.t("text_section", face=name))
            self.layers_body.title_label.configure(text=self.t("layers_section", face=name))

    def reset_face(self):
        self.remember()
        fcfg = self.profile["faces"][self.face]
        fcfg.update({"zoom": 1.0, "dx": 0.0, "dy": 0.0, "rotation": 0.0, "opacity": 1.0, "flipx": False,
                     "flipy": False})
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    def toggle_face(self, key):
        self.remember()
        fcfg = self.profile["faces"][self.face]
        fcfg[key] = not fcfg.get(key, False)
        self.schedule_save()
        self.request_draw()

    def neutral_preset(self):
        """Both sides of the template painted light, so nothing of its own picture shows through the art."""
        self.remember()
        for face, color in (("front", "#f8f9fc"), ("spine", "#e6e9f3")):
            self.profile["faces"][face]["clean"] = "color"
            self.profile["faces"][face]["clean_color"] = color
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    def apply_case_preset(self):
        color = CASE_COLORS.get(self.preset_var.get())
        if color:
            self.remember()
            self.profile["generic"]["case_color"] = color
            self.profile["generic"]["style"] = "case"
            self.sync_controls()
            self.schedule_save()
            self.request_draw()
        self.preset_var.set(self.t("case_preset"))

    def load_override(self):
        if self.current is None:
            return
        path = filedialog.askopenfilename(parent=self.root, title=self.t("pick_picture"),
                                          filetypes=[(self.t("images"), "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                                                     (self.t("all_files"), "*.*")])
        if not path:
            return
        try:
            self.overrides[self.face] = load_picture(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        self.update_info()
        self.request_draw()

    def clear_overrides(self):
        self.overrides = {}
        self.update_info()
        self.request_draw()

    # ------------------------------------------------------------------------------------------- layers
    def layers(self):
        return self.profile["layers"].setdefault(self.face, [])

    def selected_layer(self):
        layers = self.profile["layers"].get(self.face) or []
        return layers[self.layer_index] if 0 <= self.layer_index < len(layers) else None

    def refresh_layers(self, keep=False):
        if not hasattr(self, "layer_list"):
            return
        layers = self.layers()
        lst = self.layer_list
        lst.delete(0, "end")
        for ly in layers:
            prefix = self.t("layer_slot", slot=ly["slot"]) if ly.get("slot") else ""
            if ly.get("kind") == "text":
                lst.insert("end", prefix + self.t("layer_text", v=ly.get("value", "")))
            elif ly.get("kind") == "logo":
                lst.insert("end", prefix + self.t("layer_logo", v=Path(ly.get("path", "")).name))
            elif ly.get("kind") == "marquee":
                lst.insert("end", prefix + self.t("layer_marquee"))
            else:
                lst.insert("end", prefix + self.t("layer_clearlogo"))
        if not layers:
            lst.insert("end", self.t("no_layers"))
            self.layer_index = -1
        if 0 <= self.layer_index < len(layers):
            lst.selection_set(self.layer_index)
            if not keep:
                self.sync_layer_controls()

    def sync_layer_controls(self):
        layer = self.selected_layer()
        self._syncing = True
        try:
            self.layer_text_var.set(layer.get("value", "") if layer and layer.get("kind") == "text" else "")
            for var, scope, key, fmt, value_label in self.bound:
                if scope != "layer" or layer is None:
                    continue
                if key in layer:
                    var.set(layer[key])
                    if value_label is not None and fmt:
                        value_label.configure(text=fmt(layer[key]))
                elif key == "only_made":
                    var.set(False)
        finally:
            self._syncing = False

    def on_layer_select(self, _event=None):
        sel = self.layer_list.curselection()
        if not sel or sel[0] >= len(self.layers()):
            return
        self.layer_index = sel[0]
        self.sync_layer_controls()

    def add_layer(self, layer):
        self.remember()
        self.layers().append(layer)
        self.layer_index = len(self.layers()) - 1
        self.refresh_layers()
        self.schedule_save()
        self.request_draw()

    def add_text(self):
        value = self.text_var.get().strip()
        if not value:
            return
        self._text_value = value
        spine = self.face == "spine"
        try:
            size = min(30.0, max(1.0, float(self.new_size.get())))
        except (tk.TclError, ValueError):
            size = 4.5
        self.add_layer({"kind": "text", "value": value, "font": self.new_font.get() or "Arial Bold",
                        "size": size, "color": self.new_color, "stroke": 4.0,
                        "stroke_color": self.new_stroke, "rotation": -90.0 if spine else 0.0, "x": 0.5,
                        "y": 0.5 if spine else 0.9, "opacity": 1.0})

    def add_logo_file(self):
        path = filedialog.askopenfilename(parent=self.root, title=self.t("pick_picture"),
                                          filetypes=[(self.t("images"), "*.png *.webp *.jpg *.jpeg *.bmp *.gif"),
                                                     (self.t("all_files"), "*.*")])
        if path:
            spine = self.face == "spine"
            self.add_layer({"kind": "logo", "path": path, "size": 85.0 if spine else 40.0,
                            "rotation": -90.0 if spine else 0.0, "x": 0.5, "y": 0.12 if not spine else 0.85,
                            "opacity": 1.0})

    def add_game_logo(self, kind="clearlogo"):
        spine = self.face == "spine"
        self.add_layer({"kind": kind, "size": 88.0 if spine else 60.0, "rotation": -90.0 if spine else 0.0,
                        "x": 0.5, "y": 0.5 if spine else 0.18, "opacity": 1.0})

    def add_game_marquee(self):
        self.add_game_logo("marquee")

    def add_spine_slots(self):
        """box3d's spine logo slots (from the template's profile, else one game slot) as spine layers."""
        path = self.template_path(self.profile["template"]) if self.template_img is not None else None
        slots = spine_slot_layers(path)
        self.remember()
        spine = self.profile["layers"].setdefault("spine", [])
        spine[:] = [ly for ly in spine if not ly.get("slot")] + slots
        if self.face != "spine":
            self.set_face("spine")
        self.layer_index = len(spine) - len(slots)
        self.refresh_layers()
        self.schedule_save()
        self.request_draw()

    def clear_tint(self):
        if self.profile.get("tint"):
            self.remember()
            self.profile["tint"] = ""
            self.sync_controls()
            self.schedule_save()
            self.request_draw()

    def export_box3d_profile(self):
        """Save the template's corners (and spine logo slots) as a box3d profile.json; saved next to the template
        as <name>.json it is also the corner file this program reads back."""
        if self.template_img is None or not self.quads.get("front"):
            return
        tpath = self.template_path(self.profile["template"])
        target = template_profile_files(tpath)[-1 if tpath.stem.casefold() == "template" else 0]
        path = filedialog.asksaveasfilename(parent=self.root, title=self.t("export_box3d"),
                                            initialdir=str(target.parent), initialfile=target.name,
                                            defaultextension=".json", filetypes=[("box3d profile", "*.json")])
        if not path:
            return
        data = box3d_profile(tpath.stem, self.template_img.size, self.quads, self.profile)
        try:
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        self.log(self.t("box3d_saved", path=path))
        self.set_status(self.t("box3d_saved", path=path))

    def move_layer(self, step):
        layers = self.layers()
        i = self.layer_index
        j = i + step
        if 0 <= i < len(layers) and 0 <= j < len(layers):
            self.remember()
            layers[i], layers[j] = layers[j], layers[i]
            self.layer_index = j
            self.refresh_layers()
            self.schedule_save()
            self.request_draw()

    def delete_layer(self):
        layers = self.layers()
        if 0 <= self.layer_index < len(layers):
            self.remember()
            del layers[self.layer_index]
            self.layer_index = min(self.layer_index, len(layers) - 1)
            self.refresh_layers()
            self.schedule_save()
            self.request_draw()

    def apply_layer_text(self):
        layer = self.selected_layer()
        if layer and layer.get("kind") == "text":
            self.remember()
            layer["value"] = self.layer_text_var.get()
            self.refresh_layers(keep=True)
            self.schedule_save()
            self.request_draw()

    def pick_new_color(self, attr):
        res = colorchooser.askcolor(color=getattr(self, attr), parent=self.root)
        if res and res[1]:
            setattr(self, attr, res[1])
            self.paint_new_colors()

    def paint_new_colors(self):
        for btn, value in ((self.new_color_btn, self.new_color), (self.new_stroke_btn, self.new_stroke)):
            r, g, b = hex_rgb(value)
            btn.configure(bg=value, activebackground=value,
                          fg="#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff")

    # ------------------------------------------------------------------------------------------- preview
    def set_view(self, view):
        self.view = view
        for key, b in self.view_buttons.items():
            b.configure(bg=BLUE if key == view else "#1b3550", fg="white" if key == view else FG)
        if hasattr(self, "help_label"):
            self.help_label.configure(text=self.t("help_disc" if view == "disc" else "help"))
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.update_info()
        self.request_draw()

    def fit_view(self):
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.request_draw()

    def request_draw(self, fast=False):
        if not hasattr(self, "canvas"):
            return
        self._fast = fast
        if self._draw_job is not None:
            self.root.after_cancel(self._draw_job)
        self._draw_job = self.root.after(12 if fast else 40, self.draw)

    def render_pics(self):
        p = self.pics or Pictures(ctx=self.current.context() if self.current else {})
        if self.overrides:
            p = Pictures(self.overrides.get("front", p.front), self.overrides.get("spine", p.spine), p.full, p.logo,
                         p.ctx)
        return p

    def generic_height(self):
        h = int(self.cfg["export"].get("max_height") or 0)
        return h if h >= 64 else 1000

    def draw(self):
        self._draw_job = None
        c = self.canvas
        try:
            cw, ch = c.winfo_width(), c.winfo_height()
        except tk.TclError:
            return
        if cw < 40 or ch < 40:
            return
        if self.current is not None and self.pics is None:
            return      # the game's pictures are still loading: keep the last picture
        c.delete("all")
        self.shown_quads = {}
        if self.current is None and self.template_img is None:
            c.create_text(cw // 2, ch // 2, text=self.t("no_game"), fill=MUTED, font=ui_font(12))
            self.zoom_label.configure(text="")
            return
        fast = self._fast or self.drag is not None
        hq = self.cfg["display"].get("hq", True)
        m = self.px(40)
        pics = self.render_pics()
        height = self.generic_height()
        if self.template_img is not None:
            nat_w, nat_h = self.template_img.size
            fit = min((cw - m) / nat_w, (ch - m) / nat_h) * self.zoom
        else:
            fit = (ch - m) / height * self.zoom
        scale = min(1.0, fit) * (0.55 if fast else 1.0)
        try:
            if self.view == "disc":
                img = render_disc(self.profile, pics, self.platform, 400 if fast else
                                  max(200, min(900, round(min(cw, ch) - m))))
                used, scale = {}, 1.0
            else:
                img, used = render_box(self.profile, self.template_img, self.quads, pics, height=height,
                                       scale=max(0.05, scale), ss=1 if fast or not hq else 2, fast=fast)
        except Exception as exc:  # noqa: BLE001 - a bad setting must not kill the preview
            c.create_text(cw // 2, ch // 2, text=f"{type(exc).__name__}: {exc}", fill="#ff8080", font=ui_font(10),
                          width=cw - 40)
            log_line(traceback.format_exc())
            return
        if img is None:                      # a disc for a game with no cover and no generic one
            c.create_text(cw // 2, ch // 2, text=self.t("no_front_pic"), fill=MUTED, font=ui_font(12))
            return
        if self.view == "disc":
            disp = min((cw - m) / img.width, (ch - m) / img.height) * self.zoom
        elif self.view in ("front", "spine"):
            quad = used.get(self.view)
            if not quad:
                c.create_text(cw // 2, ch // 2, text="—", fill=MUTED, font=ui_font(14))
                return
            fw, fh = face_size(quad)
            img = unwarp(img, quad, (max(2, round(fw)), max(2, round(fh))))
            disp = min((cw - m) / img.width, (ch - m) / img.height) * self.zoom
        elif self.template_img is not None:
            disp = fit / scale
        else:
            disp = fit * height / max(1, img.height)
        dw, dh = img.width * disp, img.height * disp
        x0, y0 = (cw - dw) / 2 + self.pan[0], (ch - dh) / 2 + self.pan[1]
        # only the part inside the canvas becomes a Tk image (zoomed-in previews stay small)
        vx0, vy0 = max(0.0, -x0), max(0.0, -y0)
        vx1, vy1 = min(dw, cw - x0), min(dh, ch - y0)
        if vx1 - vx0 >= 1 and vy1 - vy0 >= 1:
            box = (vx0 / disp, vy0 / disp, vx1 / disp, vy1 / disp)
            size = (max(1, round(vx1 - vx0)), max(1, round(vy1 - vy0)))
            part = img.resize(size, BILINEAR if fast or not hq else LANCZOS, box=box)
            self.photo = ImageTk.PhotoImage(part)
            c.create_image(x0 + vx0, y0 + vy0, anchor="nw", image=self.photo)
        self.view_origin = (x0, y0)
        self.view_fit = scale * disp
        if self.view == "3d":
            self.shown_quads = {f: [(x0 + x * disp, y0 + y * disp) for x, y in q] for f, q in used.items() if q}
            if self.cfg["display"].get("guides", True):
                for face in sorted(self.shown_quads, key=lambda f: f == self.face):
                    pts = self.shown_quads[face]
                    color = FACE_COLORS[face]
                    c.create_polygon(*[v for p in pts for v in p], outline=color, fill="",
                                     width=self.px(2) if face == self.face else 1,
                                     dash=() if face == self.face else (4, 3))
                    if face == self.face and self.template_img is not None:
                        for i, (px, py) in enumerate(pts):
                            active = self.handle == (face, i)
                            r = self.px(8 if active else 7)
                            c.create_oval(px - r, py - r, px + r, py + r, fill=color,
                                          outline="white" if not active else "#ff3b6b", width=2)
        self.zoom_label.configure(text=f"{round(self.zoom * 100)}%")
        if self.shot_state == "drawn" and not fast:
            self.root.after(500, self.take_screenshot)

    # ------------------------------------------------------------------------------------------- mouse / keys
    def on_press(self, e):
        self.canvas.focus_set()
        if self.view != "3d" or not self.shown_quads:
            return
        if self.template_img is not None and self.cfg["display"].get("guides", True):
            q = self.shown_quads.get(self.face)
            if q:
                i = min(range(4), key=lambda k: (q[k][0] - e.x) ** 2 + (q[k][1] - e.y) ** 2)
                if (q[i][0] - e.x) ** 2 + (q[i][1] - e.y) ** 2 <= self.px(14) ** 2:
                    self.remember()
                    self.drag = self.handle = (self.face, i)
                    return
        for face in (self.face,) + tuple(f for f in FACES if f != self.face):
            q = self.shown_quads.get(face)
            if q and point_in_quad(q, e.x, e.y):
                if face != self.face:
                    self.set_face(face)
                return

    def on_motion(self, e):
        if not self.drag or self.template_img is None:
            return
        face, i = self.drag
        x0, y0 = self.view_origin
        f = max(1e-6, self.view_fit)
        w, h = self.template_img.size
        x = min(max((e.x - x0) / f, -0.25 * w), 1.25 * w)
        y = min(max((e.y - y0) / f, -0.25 * h), 1.25 * h)
        quad = list(self.quads.get(face) or [])
        if len(quad) == 4:
            quad[i] = (x, y)
            self.quads[face] = quad
            self.request_draw(fast=True)

    def on_release(self, _e):
        if self.drag:
            self.drag = None
            self.store_quads()
            self.request_draw()

    def on_key(self, e):
        if not self.handle or self.template_img is None:
            return
        face, i = self.handle
        dx, dy = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}.get(e.keysym, (0, 0))
        step = 10 if e.state & 0x1 else 1
        quad = list(self.quads.get(face) or [])
        if len(quad) != 4:
            return
        self.remember_once(("nudge", face, i))
        quad[i] = (quad[i][0] + dx * step, quad[i][1] + dy * step)
        self.quads[face] = quad
        self.store_quads()
        self.request_draw()
        return "break"

    def on_pan_start(self, e):
        self.pan_drag = (e.x, e.y, self.pan[0], self.pan[1])

    def on_pan(self, e):
        if self.pan_drag:
            x, y, px, py = self.pan_drag
            self.pan = [px + e.x - x, py + e.y - y]
            self.request_draw(fast=True)

    def on_wheel(self, e):
        widget = self.root.winfo_containing(e.x_root, e.y_root)
        while widget is not None:
            if widget is getattr(self, "canvas", None):
                self.wheel_zoom(e)
                return
            if isinstance(widget, (ttk.Treeview, tk.Listbox, tk.Text)):
                return
            canvas = self.scrollers.get(str(widget))
            if canvas is not None:
                canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
                return
            widget = widget.master

    def on_wheel_break(self, e):
        self.on_wheel(e)
        return "break"

    def wheel_zoom(self, e):
        old = self.zoom
        self.zoom = max(0.3, min(6.0, self.zoom * (1.12 if e.delta > 0 else 1 / 1.12)))
        k = self.zoom / old
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        cx, cy = cw / 2 + self.pan[0], ch / 2 + self.pan[1]
        ncx, ncy = e.x - (e.x - cx) * k, e.y - (e.y - cy) * k
        self.pan = [ncx - cw / 2, ncy - ch / 2]
        self.request_draw()

    # ------------------------------------------------------------------------------------------- saving
    def batch_settings(self):
        return (copy.deepcopy(self.profile), self.template_img, copy.deepcopy(self.quads),
                dict(self.cfg["export"]))

    def update_output_label(self):
        if not hasattr(self, "out_label"):
            return
        if self.lb and self.platform:
            export = self.cfg["export"]
            kinds = [kind for kind, on in ((OUT_TYPE, export.get("make_box", True)),
                                           (DISC_TYPE, export.get("make_disc", False))) if on] or [OUT_TYPE]
            self.out_label.configure(text="\n".join(str(self.lb.media_folder(self.platform, k)) for k in kinds))
        else:
            self.out_label.configure(text="—")

    def save_one(self, to_file):
        if self.current is None or self.lb is None:
            return
        if self.batch_running:
            self.set_status(self.t("busy"))
            return
        game, profile, template, quads, export = (self.current,) + self.batch_settings()
        overrides = dict(self.overrides)
        lb, name = self.lb, self.platform
        needs_front = profile["faces"]["front"].get("source") == "launchbox"
        if needs_front and not (self.current_found.get("front") or "front" in overrides) and not profile.get(
                "generic_cover", True) and profile.get("web_covers", "auto") == "off":
            messagebox.showwarning(APP_NAME, self.t("no_front"), parent=self.root)
            return
        if to_file:          # the picture shown: the disc in the Disc view, else the box
            kinds = [DISC_TYPE] if self.view == "disc" else [OUT_TYPE]
        else:
            kinds = [kind for kind, on in ((OUT_TYPE, export.get("make_box", True)),
                                           (DISC_TYPE, export.get("make_disc", False))) if on]
        if not kinds:
            self.inform(self.t("nothing_chosen"))
            return
        dest = None
        if to_file:
            ext = ".jpg" if export.get("format") == "jpg" else ".png"
            dest = filedialog.asksaveasfilename(parent=self.root, initialfile=clean_name(game.title) + ext,
                                                defaultextension=ext,
                                                filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
            if not dest:
                return
            export["format"] = "jpg" if dest.lower().endswith((".jpg", ".jpeg")) else "png"
        else:
            found = lb.find(name, game, profile)
            there = [p for kind in kinds for p in (found.get("disc" if kind == DISC_TYPE else "box3d") or [])[:1]]
            if there and export.get("existing") == "skip":
                answer = messagebox.askyesnocancel(APP_NAME, self.t("exists_ask", path="\n".join(there)),
                                                   parent=self.root)
                if answer is None:
                    return
                export["existing"] = "replace" if answer else "next"
        index = self.current_index
        self.set_status("…")
        height = self.generic_height()

        def work():
            try:
                found = lb.find(name, game, profile)
                if needs_front and not found.get("front") and "front" not in overrides:
                    try:
                        cover, where = fetch_missing_cover(lb, name, game, profile, found)
                        if cover is not None:
                            self.queue.put(("log", self.t("web_found", where=where, path=cover)))
                    except (OSError, ValueError, http.client.HTTPException) as exc:
                        self.queue.put(("log", f"{self.t('web_failed')}: {exc}"))
                    if not found.get("front") and not profile.get("generic_cover", True):
                        self.queue.put(("saved", index, [], bool(dest), self.t("no_front"), found))
                        return
                pics, _ = load_pictures(lb, name, game, profile, found)
                if "front" in overrides:
                    pics.front = overrides["front"]
                if "spine" in overrides:
                    pics.spine = overrides["spine"]
                fmt, saved = export.get("format", "png"), []
                backup = lb.root / "Backups" / BACKUP_DIR_NAME / time.strftime("%Y-%m-%d %H-%M-%S")
                for kind in kinds:
                    if kind == DISC_TYPE:
                        img = render_disc(profile, pics, name)
                        if img is None:
                            continue
                        out = finish_picture(img, 0, False, fmt, export.get("jpg_bg", "#ffffff"))
                    else:
                        img, _ = render_box(profile, template, quads, pics, height=height)
                        out = finish_picture(img, int(export.get("max_height") or 0), bool(export.get("trim", True)),
                                             fmt, export.get("jpg_bg", "#ffffff"))
                    if dest:
                        save_picture(out, Path(dest), None, None, lb.root, fmt)
                        saved.append((kind, dest))
                        continue
                    target = output_target(lb, name, game, found, export, kind)
                    if target is None:
                        continue
                    path, region, replaced = target
                    save_picture(out, path, replaced, backup if replaced else None, lb.root, fmt)
                    lb.index(name, kind).add(region, str(path))
                    saved.append((kind, str(path)))
                self.queue.put(("saved", index, saved, bool(dest), None if saved else "skip", found))
            except Exception as exc:  # noqa: BLE001
                log_line(traceback.format_exc())
                self.queue.put(("saved", index, [], bool(dest), f"{type(exc).__name__}: {exc}", None))

        threading.Thread(target=work, daemon=True).start()

    def make_boxes(self, which):
        if self.lb is None or not self.platform or not self.games:
            return
        if self.batch_running:
            self.set_status(self.t("busy"))
            return
        if which == "selected":
            idx = [int(i) for i in self.tree.selection() if i.isdigit()]
        elif which == "shown":
            idx = list(self.rows)
        else:
            idx = list(range(len(self.games)))
        if not idx:
            self.inform(self.t("select_games"))
            return
        profile, template, quads, export = self.batch_settings()
        tname = self.t("generic_label") if template is None else self.t(
            "template_label", name=Path(profile.get("template", "")).name)
        policy = self.t("ex_" + {"skip": "skip", "replace": "replace", "next": "next"}.get(
            export.get("existing"), "skip") + "_short")
        kinds = tuple(kind for kind, on in ((OUT_TYPE, export.get("make_box", True)),
                                            (DISC_TYPE, export.get("make_disc", False))) if on)
        if not kinds:
            self.inform(self.t("nothing_chosen"))
            return
        needs_front = profile["faces"]["front"].get("source") == "launchbox"
        where = web_source(self.platform, self.lb.official.get(self.platform, ""), profile.get("web_covers", "auto"),
                           profile.get("web_system", "")) if needs_front else ""
        web = bool(where)
        generic = bool(profile.get("generic_cover", True))
        make, skip, nofront, covers = batch_plan([self.found.get(i, {}) for i in idx], export.get("existing", "skip"),
                                                 needs_front, generic, kinds, web)
        if not make:
            self.inform(self.t("nothing_to_make", n=len(idx), skip=skip, nofront=nofront))
            return
        extra = ""
        if covers and web:
            extra = self.t("confirm_missing_web", generic=covers, where=where) + self.t(
                "confirm_missing_generic" if generic else "confirm_missing_end")
        elif covers:
            extra = self.t("confirm_missing_only_generic", generic=covers)
        what = " + ".join(self.t("make_box" if kind == OUT_TYPE else "make_disc") for kind in kinds)
        folders = "\n".join(str(self.lb.media_folder(self.platform, kind)) for kind in kinds)
        if not self.options.get("yes") and not messagebox.askyesno(APP_NAME, self.t(
                "confirm_batch", n=len(idx), platform=self.platform, what=what, template=tname, policy=policy,
                folder=folders, make=make, skip=skip, nofront=nofront, extra=extra), parent=self.root):
            return
        games = [self.games[i] for i in idx]
        self.batch_stop = threading.Event()
        self.batch_running = True
        self.update_go_buttons()
        self.show_progress(True)
        self.progress.configure(maximum=len(games), value=0)
        backup = self.lb.root / "Backups" / BACKUP_DIR_NAME / time.strftime("%Y-%m-%d %H-%M-%S")
        args = (self.lb, self.platform, games, profile, template, quads, export, self.batch_stop, backup,
                self.generic_height())
        threading.Thread(target=self.batch_work, args=args, daemon=True).start()

    def batch_work(self, lb, name, games, profile, template, quads, export, stop, backup, height):
        def progress(done, total, counts, status, game, info):
            if status == "errors":
                self.queue.put(("log", f"✕ {game.title}: {info}"))
            self.queue.put(("progress", done, total, dict(counts)))

        counts = batch_make(lb, name, games, profile, template, quads, export, stop, backup, height, progress)
        self.queue.put(("batch_done", name, counts, stop.is_set()))

    def stop_batch(self):
        if self.batch_stop is not None:
            self.batch_stop.set()

    def show_progress(self, on):
        if on:
            self.progress.pack(side="left", padx=(10, 0), pady=5)
            self.stop_button.pack(side="right", padx=8, pady=3)
        else:
            self.progress.pack_forget()
            self.stop_button.pack_forget()

    # ------------------------------------------------------------------------------------------- settings files
    def profile_as_default(self):
        self.cfg["default_profile"] = copy.deepcopy(self.profile)
        self.schedule_save()
        self.log(self.t("default_saved"))

    def export_profile(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                            initialfile=clean_name(self.platform or "settings") + ".lb3d.json",
                                            filetypes=[(self.t("profile_files"), "*.json")])
        if not path:
            return
        data = {"app": APP_NAME, "version": APP_VERSION, "profile": self.profile}
        if self.template_img is not None:
            data["template_quads"] = {f: [list(p) for p in q] if q else None for f, q in self.quads.items()}
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            self.log(self.t("exported", path=path))
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)

    def import_profile(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[(self.t("profile_files"), "*.json"),
                                                                       (self.t("all_files"), "*.*")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        self.remember()
        self.profile = merged_profile(data.get("profile", data))
        if self.platform:
            self.cfg["profiles"][self.platform] = self.profile
        self.load_template()
        quads = data.get("template_quads")
        if self.template_img is not None and isinstance(quads, dict) and valid_quad(quads.get("front") or []):
            self.quads = {f: [tuple(p) for p in quads[f]] if quads.get(f) else None for f in FACES}
            self.store_quads()
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    def reset_profile(self):
        if not messagebox.askyesno(APP_NAME, self.t("reset_ask"), parent=self.root):
            return
        self.remember()
        self.profile = default_profile()
        if self.platform:
            self.cfg["profiles"][self.platform] = self.profile
        self.load_template()
        self.sync_controls()
        self.schedule_save()
        self.request_draw()

    # ------------------------------------------------------------------------------------------- misc
    def set_status(self, text):
        self.status_text = text
        if hasattr(self, "status_label"):
            self.status_label.configure(text=text)

    def inform(self, text):
        """A message box, or only the status line when started not to ask (the tests)."""
        self.set_status(text)
        if not self.options.get("yes"):
            messagebox.showinfo(APP_NAME, text, parent=self.root)

    def log(self, text):
        line = time.strftime("%H:%M:%S ") + text
        self.log_lines.append(line)
        del self.log_lines[:-500]
        log_line(text)
        self.log_widget_append(line)

    def log_widget_append(self, line):
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(1200, self.save_now)

    def save_now(self):
        self._save_job = None
        try:
            self.cfg["geometry"] = self.root.geometry()
        except tk.TclError:
            pass
        save_config(self.cfg)

    def close(self):
        if self.batch_running and self.batch_stop is not None:
            if not messagebox.askyesno(APP_NAME, self.t("close_ask"), parent=self.root):
                return
            self.batch_stop.set()
            self.closing = True
            self.set_status(self.t("closing"))
            self.root.after(20000, self.finish_close)    # never wait for ever
            return
        self.finish_close()

    def finish_close(self):
        self.save_now()
        try:
            self.root.destroy()
        finally:
            os._exit(0)

    # ------------------------------------------------------------------------------------------- queue pump
    def pump(self):
        try:
            for _ in range(400):
                msg = self.queue.get_nowait()
                self.handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(60, self.pump)

    def handle_message(self, msg):
        kind = msg[0]
        if kind == "lb":
            _, token, lb, error = msg
            if token is not self.load_token:
                return
            if error or lb is None:
                self.set_status(f"{self.t('error')}: {error}")
                self.log(f"{self.t('error')}: {error}")
                return
            self.lb = lb
            self.cfg["lb_root"] = str(lb.root)
            self.plat_combo["values"] = lb.platforms
            self.set_status(self.t("platforms_loaded", n=len(lb.platforms), root=lb.root))
            self.log(self.t("platforms_loaded", n=len(lb.platforms), root=lb.root))
            self.schedule_save()
            wanted = self.options.get("platform") or self.cfg.get("last_platform")
            if wanted in lb.xml_files:
                self.plat_var.set(wanted)
                self.select_platform(wanted)
            self.update_output_label()
        elif kind == "games":
            _, token, name, games, found, error = msg
            if token is not self.load_token or name != self.platform:
                return
            if error:
                self.set_status(f"{self.t('error')}: {error}")
                self.log(f"{name}: {error}")
            self.games, self.found = games, found
            self.update_platform_info()
            self.set_status(self.t("games_loaded", name=name, n=len(games)))
            wanted = self.options.pop("game", None) if self.shot_state else None
            if wanted:
                for i, g in enumerate(games):
                    if g.title.casefold() == wanted.casefold():
                        self.current_index, self.current = -1, None
                        self.search_var.set("")
                        self.apply_filter()
                        self.tree.selection_set(str(i))
                        self.tree.focus(str(i))
                        self.tree.see(str(i))
                        self.on_game_select()
                        break
                else:
                    self.apply_filter()
            else:
                self.apply_filter()
        elif kind == "statuses":
            _, token, name, found = msg
            if token is not self.load_token or name != self.platform:
                return
            self.found = found
            self.update_platform_info()
            self.apply_filter(keep_selection=True)
            if 0 <= self.current_index < len(self.games):
                self.current_found = found.get(self.current_index, self.current_found)
            self.update_info()
        elif kind == "pics":
            _, token, game, pics, found, error = msg
            if token is not self.pics_token or game is not self.current:
                return
            if error:
                self.log(f"{game.title}: {error}")
            self.pics = pics or Pictures(ctx=game.context())
            self.current_found = found or {}
            self.update_info()
            if self.shot_state == "start":
                self.shot_state = "drawn"
                if self.options.get("face"):
                    self.set_face(self.options.pop("face"))
                if self.options.get("view"):
                    self.set_view(self.options.pop("view"))
            self.request_draw()
        elif kind == "saved":
            _, index, saved, to_file, error, found = msg
            if found and not to_file and 0 <= index < len(self.games) and found.get("front") and not \
                    self.found.get(index, {}).get("front"):        # a cover came from the web on the way
                self.found[index] = found
                if index == self.current_index:
                    self.current_found = found
                    self.load_current()
            if error == "skip":
                self.set_status(self.t("ex_skip_short"))
            elif error:
                self.set_status(f"{self.t('error')}: {error}")
                self.log(f"{self.t('error')}: {error}")
                messagebox.showerror(APP_NAME, error, parent=self.root)
            else:
                text = "   ".join(self.t("exported" if to_file else "saved_one", path=path) for _kind, path in saved)
                self.set_status(text)
                self.log(text)
                if not to_file and 0 <= index < len(self.games):
                    f = self.found.setdefault(index, {})
                    for media, path in saved:
                        f.setdefault("disc" if media == DISC_TYPE else "box3d", [])
                        if path not in f["disc" if media == DISC_TYPE else "box3d"]:
                            f["disc" if media == DISC_TYPE else "box3d"].append(path)
                    if index == self.current_index:
                        self.current_found = f
                    self.update_row(index)
                    self.update_platform_info()
                    self.update_info()
        elif kind == "webcover":
            _, index, game, path, where, found, error = msg
            if hasattr(self, "web_button"):
                self.web_button.configure(state="normal")
            if error:
                text = f"{self.t('error')}: {error}"
            elif path is None:
                text = self.t("web_none", title=game.title)
            else:
                text = self.t("web_found", where=where, path=path)
                if 0 <= index < len(self.games) and found:
                    self.found[index] = found
                    self.update_row(index)
                    self.update_platform_info()
                if game is self.current:
                    self.current_found = found or self.current_found
                    self.load_current()
            self.set_status(text)
            self.log(text)
        elif kind == "systems":
            if hasattr(self, "web_system_combo"):
                self.web_system_combo["values"] = [""] + list(msg[1])
        elif kind == "upmodels":
            _, models, server, problem = msg
            if hasattr(self, "up_model_combo"):
                self.up_model_combo["values"] = [""] + list(models)
                self.up_label.configure(text=problem or (self.t("up_models", n=len(models), server=server) + (
                    "" if models else " " + TEXTS["up_no_model"])))
        elif kind == "progress":
            _, done, total, counts = msg
            self.progress.configure(maximum=total, value=done)
            self.set_status(self.t("batch_progress", done=done, total=total, **counts))
        elif kind == "batch_done":
            _, name, counts, stopped = msg
            self.batch_running = False
            self.batch_stop = None
            self.show_progress(False)
            self.update_go_buttons()
            text = self.t("batch_done", platform=name, **counts)
            if counts.get("aborted") == "in_a_row":
                text = self.t("aborted_in_a_row", n=ABORT_IN_A_ROW) + " " + text
            elif counts.get("aborted") == "share":
                text = self.t("aborted_share", pct=round(ABORT_SHARE * 100)) + " " + text
            elif stopped:
                text = self.t("batch_stopped") + " " + text
            self.set_status(text)
            self.log(text)
            if getattr(self, "closing", False):
                self.finish_close()
                return
            self.refresh_statuses()
            if not self.options.get("yes"):
                messagebox.showinfo(APP_NAME, text + "\n\n" + self.t("refresh_note"), parent=self.root)
        elif kind == "log":
            self.log(msg[1])

    # ------------------------------------------------------------------------------------------- screenshots
    def take_screenshot(self):
        if self.shot_state != "drawn":
            return
        self.shot_state = "done"
        out = self.options.get("screenshot")
        try:
            self.root.update()
            grab_window(self.root).save(out)
        except Exception as exc:  # noqa: BLE001
            log_line(f"screenshot: {exc}")
        self.root.after(200, lambda: os._exit(0))


WARN, GOOD = "#ffb4a8", "#7fe0a8"


class AIDialog:
    """“Make a template with AI”: the program draws the empty case, Stable Diffusion (run by Stability Matrix) paints
    over it as a photo, and the picture chosen is saved with its exact corners into “box model”."""

    MAX_RESULTS = 8

    def __init__(self, app):
        self.app, self.t, self.px = app, app.t, app.px
        self.s = ai_settings(app.cfg)
        self.server = None
        self.choices: list = []
        self.results: list = []
        self.chosen = None              # the painting shown and saved
        self.made = None                # (painting, gloss, template, corners) of the chosen one
        self.guide = None
        self.live = None
        self.busy = False
        self.closed = False
        self.stop = threading.Event()
        self.waiting = None
        self.q: queue.Queue = queue.Queue()
        self.photo = None
        self._show_job = self._guide_job = None
        self._demo = None
        self._auto_name = ""
        self.sm_exe = find_stability_matrix(self.s["sm_exe"])
        self.packages = sm_packages(sm_library(self.sm_exe))
        self.win = tk.Toplevel(app.root)
        self.build()
        self.preview_var.set("guide")          # nothing painted yet: the drawing is what there is to see
        self.fill_servers()
        try:
            self.guide = self.make_guide()
        except Exception:  # noqa: BLE001 - shown as "—" until a setting changes
            log_line(traceback.format_exc())
        self.update_buttons()
        # timers go on the main window, which outlives this one; close() cancels them
        self._pump_job = app.root.after(80, self.pump)
        app.root.after(250, self.connect)
        if app.options.get("screenshot") and app.options.get("ai"):
            self.win.after(int(app.options.get("ai_wait") or 7000), self.take_screenshot)

    # ------------------------------------------------------------------------------------------- building
    def build(self):
        app, win, t, px = self.app, self.win, self.t, self.px
        win.title(f"{t('ai_title')} — {APP_NAME}")
        win.configure(bg=BG)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{min(sw - 80, px(1260))}x{min(sh - 120, px(900))}")
        win.minsize(min(sw - 80, px(900)), min(sh - 120, px(620)))
        if getattr(app.root, "_icon", None) is not None:
            win.iconphoto(False, app.root._icon)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        win.bind("<FocusIn>", lambda e: self.refresh_template_choice())

        panes = tk.PanedWindow(win, orient="horizontal", bg=BG, sashwidth=6, bd=0, sashrelief="flat")
        panes.pack(fill="both", expand=True, padx=8, pady=8)
        left, right = tk.Frame(panes, bg=PANEL), tk.Frame(panes, bg=BG)
        panes.add(left, minsize=px(380), width=px(470))
        panes.add(right, minsize=px(380))

        go = tk.Frame(left, bg=PANEL)
        go.pack(side="bottom", fill="x", padx=8, pady=(4, 8))
        self.progress = ttk.Progressbar(go, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.status = app.label(go, "", SOFT, 9)
        self.status.pack(fill="x", pady=(4, 0))
        self.wrap(self.status, go)
        row = tk.Frame(go, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        self.go_button = app.button(row, t("ai_generate"), self.generate, "blue")
        self.go_button.pack(side="left", fill="x", expand=True)
        self.stop_button = app.button(row, t("ai_stop"), self.stop_now, "red")
        self.stop_button.pack(side="left", padx=(6, 0))
        outer, body = app.scrollable(left)
        outer.pack(fill="both", expand=True)

        sec = app.section(body, t("ai_server"))
        self.sm_label = app.label(sec, "", MUTED, 8)
        self.sm_label.pack(fill="x")
        self.wrap(self.sm_label, sec)
        row = tk.Frame(sec, bg=PANEL2)
        row.pack(fill="x", pady=(4, 0))
        self.server_var = tk.StringVar()
        self.server_combo = ttk.Combobox(row, textvariable=self.server_var, state="readonly", height=12)
        self.server_combo.pack(side="left", fill="x", expand=True)
        self.server_combo.bind("<<ComboboxSelected>>", lambda e: self.on_server_chosen())
        app.button(row, t("browse"), self.browse_sm).pack(side="left", padx=(6, 0))
        self.url_var = tk.StringVar(value=self.s["url"])
        entry = tk.Entry(sec, textvariable=self.url_var, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                         font=ui_font(10))
        entry.pack(fill="x", ipady=3, pady=(6, 0))
        entry.bind("<Return>", lambda e: self.connect())
        row = tk.Frame(sec, bg=PANEL2)
        row.pack(fill="x", pady=(6, 0))
        app.button(row, t("ai_connect"), self.connect).pack(side="left", fill="x", expand=True)
        self.start_button = app.button(row, t("ai_start"), self.start_sm, "green")
        self.start_button.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.server_label = app.label(sec, "", SOFT, 9)
        self.server_label.pack(fill="x", pady=(6, 0))
        self.wrap(self.server_label, sec)

        sec = app.section(body, t("ai_case_section"))
        self.source_var = tk.StringVar(value=self.s["source"])
        app.radio(sec, t("ai_src_case"), self.source_var, "case").pack(fill="x")
        self.case_var = tk.StringVar(value=self.s["case"])
        combo = ttk.Combobox(sec, textvariable=self.case_var, state="readonly", values=list(AI_CASES), height=20)
        combo.pack(fill="x", pady=(2, 0), padx=(px(20), 0))
        combo.bind("<<ComboboxSelected>>", lambda e: self.on_case_chosen())
        self.tpl_radio = app.radio(sec, "", self.source_var, "template")
        self.tpl_radio.pack(fill="x", pady=(6, 0))
        self.angle_var = tk.DoubleVar(value=self.s["angle"])
        self.slider(sec, t("ai_turn"), self.angle_var, 5, 60, 1, lambda v: f"{v:.0f}°", self.redraw_guide)
        self.thick_var = tk.DoubleVar(value=self.s["thickness"])
        self.slider(sec, t("ai_thickness"), self.thick_var, 0.03, 0.4, 0.005, lambda v: f"{v * 100:.1f}%",
                    self.redraw_guide)
        row = tk.Frame(sec, bg=PANEL2)
        row.pack(fill="x", pady=(8, 0))
        self.color_var = tk.StringVar(value=self.s["color"])
        self.color_button = app.button(row, t("ai_case_color"), self.pick_color)
        self.color_button.pack(side="left")
        app.button(row, t("ai_case_default"), self.default_color).pack(side="left", padx=(6, 0))
        note = app.label(sec, t("ai_note"), MUTED, 8)
        note.pack(fill="x", pady=(8, 0))
        self.wrap(note, sec)

        sec = app.section(body, t("ai_ai_section"))
        app.label(sec, t("ai_model")).pack(fill="x")
        self.model_var = tk.StringVar(value=self.s["model"])
        self.model_combo = ttk.Combobox(sec, textvariable=self.model_var, state="readonly", height=20)
        self.model_combo.pack(fill="x", pady=(2, 0))
        self.model_combo.bind("<<ComboboxSelected>>", lambda e: self.model_defaults(self.model_var.get()))
        app.label(sec, t("ai_prompt")).pack(fill="x", pady=(8, 2))
        self.prompt_text = self.text_box(sec, 5, self.s["prompt"] or ai_prompt(self.s["case"]))
        app.button(sec, t("ai_prompt_reset"), self.reset_prompt).pack(anchor="w", pady=(4, 0))
        app.label(sec, t("ai_negative")).pack(fill="x", pady=(8, 2))
        self.negative_text = self.text_box(sec, 3, self.s["negative"])
        self.strength_var = tk.DoubleVar(value=self.s["strength"])
        self.slider(sec, t("ai_strength"), self.strength_var, 0.2, 0.85, 0.01, lambda v: f"{v * 100:.0f}%")
        self.steps_var = tk.IntVar(value=int(self.s["steps"]))
        self.slider(sec, t("ai_steps"), self.steps_var, 4, 60, 1, lambda v: f"{v:.0f}")
        self.cfg_var = tk.DoubleVar(value=self.s["cfg"])
        self.slider(sec, t("ai_cfg"), self.cfg_var, 1, 12, 0.5, lambda v: f"{v:.1f}")
        row = tk.Frame(sec, bg=PANEL2)
        row.pack(fill="x", pady=(8, 0))
        app.label(row, t("ai_variants")).pack(side="left")
        self.variants_var = tk.IntVar(value=max(1, min(6, int(self.s["variants"]))))
        tk.Spinbox(row, from_=1, to=6, textvariable=self.variants_var, width=3, bg=ENTRY, fg=FG, insertbackground=FG,
                   buttonbackground=PANEL2, relief="flat", font=ui_font(10)).pack(side="left", padx=(6, 14))
        app.label(row, t("ai_seed")).pack(side="left")
        self.seed_var = tk.StringVar(value=self.s["seed"])
        tk.Entry(row, textvariable=self.seed_var, width=11, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                 font=ui_font(10)).pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=2)
        row = tk.Frame(sec, bg=PANEL2)
        row.pack(fill="x", pady=(8, 0))
        app.label(row, t("ai_size")).pack(side="left")
        self.size_var = tk.IntVar(value=int(self.s["size"]))
        for value in AI_SIZES:
            app.radio(row, f"{value}", self.size_var, value).pack(side="left", padx=(10, 0))

        bar = tk.Frame(right, bg=BG)
        bar.pack(fill="x")
        self.preview_var = tk.StringVar(value=self.s["preview"])
        for key in AI_PREVIEWS:
            tk.Radiobutton(bar, text=t("ai_preview_" + key), variable=self.preview_var, value=key,
                           command=self.request_show, indicatoron=0, bg="#1b3550", fg=FG, selectcolor=BLUE,
                           activebackground="#24476b", activeforeground="white", relief="flat", bd=0, padx=10, pady=5,
                           font=ui_font(9, True)).pack(side="left", padx=(0, 4))
        self.canvas = tk.Canvas(right, bg=CANVAS_BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, pady=(4, 0))
        self.canvas.bind("<Configure>", lambda e: self.request_show())
        self.thumbs = tk.Frame(right, bg=BG)
        self.thumbs.pack(fill="x", pady=(6, 0))
        frame = tk.Frame(right, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        frame.pack(fill="x", pady=(6, 0))
        inner = tk.Frame(frame, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=8)
        self.gloss_var = tk.DoubleVar(value=self.s["gloss"])
        self.slider(inner, t("ai_gloss"), self.gloss_var, 0, 2, 0.05, lambda v: f"{v * 100:.0f}%", self.request_show)
        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        app.label(row, t("ai_name")).pack(side="left")
        self.name_var = tk.StringVar()
        tk.Entry(row, textvariable=self.name_var, bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                 font=ui_font(10)).pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=3)
        self.save_button = app.button(row, t("ai_save"), self.save, "green")
        self.save_button.pack(side="left", padx=(6, 0))
        note = app.label(inner, t("ai_save_note"), MUTED, 8)
        note.pack(fill="x", pady=(4, 0))
        self.wrap(note, inner)
        self.show_color()
        self.refresh_template_choice()
        self.auto_name()
        self.source_var.trace_add("write", lambda *_: (self.auto_name(), self.redraw_guide()))
        self.size_var.trace_add("write", lambda *_: self.redraw_guide())

    def wrap(self, label, parent):
        parent.bind("<Configure>", lambda e: label.configure(wraplength=max(120, e.width - self.px(6))), add="+")

    def slider(self, parent, text, var, lo, hi, res, fmt, on_release=None):
        row = tk.Frame(parent, bg=parent["bg"])
        row.pack(fill="x", pady=(5, 0))
        self.app.label(row, text).pack(side="left")
        value = tk.Label(row, text="", bg=parent["bg"], fg=FG, font=ui_font(9, True))
        value.pack(side="right")

        def show(*_):
            try:
                value.configure(text=fmt(float(var.get())))
            except (tk.TclError, ValueError):
                pass

        var.trace_add("write", show)
        show()
        scale = tk.Scale(parent, variable=var, from_=lo, to=hi, resolution=res, showvalue=0, orient="horizontal",
                         bg=BLUE, fg=FG, highlightthickness=0, troughcolor=TROUGH, activebackground="#148aff", bd=0,
                         sliderlength=self.px(16), width=self.px(10), sliderrelief="flat")
        scale.pack(fill="x")
        if on_release is not None:
            scale.bind("<ButtonRelease-1>", lambda e: on_release())
        return scale

    def text_box(self, parent, lines, value):
        box = tk.Text(parent, height=lines, wrap="word", bg=ENTRY, fg=FG, insertbackground=FG, relief="flat",
                      font=ui_font(9), padx=6, pady=4, undo=True)
        box.pack(fill="x")
        box.insert("1.0", value)
        return box

    # ------------------------------------------------------------------------------------------- the server
    def fill_servers(self):
        self.choices = []
        for pkg in self.packages:
            label = f"{pkg['name']} · {pkg['url'].split('://', 1)[-1]}"
            if not pkg["api"]:
                label += " · " + self.t("ai_no_api_short")
            self.choices.append((label, pkg))
        self.choices.append((self.t("ai_other"), None))
        self.server_combo["values"] = [label for label, _pkg in self.choices]
        pick = next((i for i, (_l, p) in enumerate(self.choices) if p and p["id"] == self.s["package"]), None)
        if pick is None and not self.s["url"]:
            pick = next((i for i, (_l, p) in enumerate(self.choices) if p and p["active"]), 0 if self.packages else None)
        if pick is None:
            pick = len(self.choices) - 1
        self.server_var.set(self.choices[pick][0])
        pkg = self.choices[pick][1]
        if pkg is not None:
            self.url_var.set(pkg["url"])
            self.s["package"] = pkg["id"]
        elif not self.url_var.get():
            self.url_var.set("http://127.0.0.1:7860")
        self.sm_label.configure(text=self.t("ai_sm", path=self.sm_exe) if self.sm_exe else self.t("ai_sm_none"))

    def chosen_package(self):
        return next((pkg for label, pkg in self.choices if label == self.server_var.get()), None)

    def on_server_chosen(self):
        pkg = self.chosen_package()
        if pkg is not None:
            self.url_var.set(pkg["url"])
        self.s["package"] = pkg["id"] if pkg else ""
        self.server = None
        self.connect()

    def browse_sm(self):
        path = filedialog.askopenfilename(parent=self.win, title=self.t("ai_browse_sm"),
                                          initialdir=str(self.sm_exe.parent) if self.sm_exe else None,
                                          filetypes=[("Stability Matrix", SM_EXE), (self.t("all_files"), "*.*")])
        if not path:
            return
        self.sm_exe = Path(path)
        self.s["sm_exe"] = str(self.sm_exe)
        self.packages = sm_packages(sm_library(self.sm_exe))
        self.fill_servers()
        self.store()
        self.connect()

    def connect(self):
        if self.closed:
            return
        url = AIServer.normalize(self.url_var.get())
        if not url:
            return
        if self.waiting is not None:
            self.waiting.set()
            self.waiting = None
        pkg = self.chosen_package()
        name = pkg["name"] if pkg else url
        self.server_label.configure(text=self.t("ai_checking", url=url), fg=SOFT)

        others = pkg.get("urls") or () if pkg and AIServer.normalize(pkg["url"]) == url else ()

        def work():
            try:
                server, problem = find_ai_server(url, others)
                if server is None:
                    if problem is not None:
                        raise problem
                    self.q.put(("server_fail", self.t("ai_not_running", url=url, name=name)))
                    return
                names, current = server.models()
                self.q.put(("server", server, names, current))
            except AIError as exc:
                self.q.put(("server_fail", str(exc)))
            except Exception as exc:  # noqa: BLE001
                log_line(traceback.format_exc())
                self.q.put(("server_fail", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def start_sm(self):
        pkg = self.chosen_package()
        if pkg is None:
            self.server_label.configure(text=self.t("ai_pick_pkg"), fg=WARN)
            return
        if self.sm_exe is None:
            self.browse_sm()
            if self.sm_exe is None:
                return
        if sm_running():
            key = "ai_sm_open"
        else:
            try:
                sm_launch(self.sm_exe, pkg["id"])
            except OSError as exc:
                self.server_label.configure(text=f"{self.t('error')}: {exc}", fg=WARN)
                return
            key = "ai_starting"
            self.app.log(f"Stability Matrix: --launch-package {pkg['name']}")
        self.wait_for(pkg, key)
        if not pkg["api"]:
            self.server_label.configure(text=self.t("ai_pkg_noapi", name=pkg["name"]), fg=WARN)

    def wait_for(self, pkg, key, minutes=15):
        """Keep looking for the package's server until it answers (it takes a while to start)."""
        if self.waiting is not None:
            self.waiting.set()
        stop = self.waiting = threading.Event()
        url, name = pkg["url"], pkg["name"]

        def loop():
            start = time.time()
            while not stop.is_set() and time.time() - start < minutes * 60:
                server, problem = find_ai_server(url, pkg.get("urls") or ())
                if problem is not None and time.time() - start > 120:   # web UIs open their page before their API
                    self.q.put(("server_fail", str(problem)))
                    return
                if server is not None:
                    try:
                        names, current = server.models()
                    except AIError as exc:
                        self.q.put(("server_fail", str(exc)))
                        return
                    if not stop.is_set():
                        self.q.put(("server", server, names, current))
                    return
                if not stop.is_set():
                    self.q.put(("server_wait", self.t(key, name=name, s=int(time.time() - start))))
                stop.wait(2.5)
            if not stop.is_set():
                self.q.put(("server_fail", self.t("ai_start_timeout", name=name, m=minutes)))

        threading.Thread(target=loop, daemon=True).start()

    def model_defaults(self, name):
        """Steps and CFG for the model: few and low for Lightning / Turbo models, the usual ones otherwise."""
        try:
            steps, cfg = int(self.steps_var.get()), float(self.cfg_var.get())
        except (tk.TclError, ValueError):
            steps, cfg = 28, 6.0
        if ai_fast_model(name):
            self.steps_var.set(8)
            self.cfg_var.set(2.0)
        elif steps <= 10 and cfg <= 2.5:
            self.steps_var.set(28)
            self.cfg_var.set(6.0)

    # ------------------------------------------------------------------------------------------- the case
    def case_color(self):
        return self.color_var.get() or AI_CASES.get(self.case_var.get(), AI_CASES[AI_DEFAULT_CASE])[4]

    def show_color(self):
        c = self.case_color()
        r, g, b = hex_rgb(c)
        self.color_button.configure(bg=c, activebackground=c,
                                    fg="#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff")

    def pick_color(self):
        res = colorchooser.askcolor(color=self.case_color(), parent=self.win)
        if res and res[1]:
            self.color_var.set(res[1])
            self.show_color()
            self.redraw_guide()

    def default_color(self):
        self.color_var.set("")
        self.show_color()
        self.redraw_guide()

    def on_case_chosen(self):
        self.thick_var.set(AI_CASES.get(self.case_var.get(), AI_CASES[AI_DEFAULT_CASE])[2])
        self.color_var.set("")
        self.show_color()
        self.reset_prompt()
        self.source_var.set("case")
        self.auto_name()
        self.redraw_guide()

    def reset_prompt(self):
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", ai_prompt(self.case_var.get()))

    def default_name(self):
        if self.source_var.get() == "template" and self.app.template_img is not None:
            return "AI " + Path(self.app.profile.get("template", "case")).stem
        return "AI " + self.case_var.get().split(" — ")[0]

    def auto_name(self):
        """The template's name follows the case until the user types their own."""
        if self.name_var.get() in ("", self._auto_name):
            self._auto_name = self.default_name()
            self.name_var.set(self._auto_name)

    def refresh_template_choice(self):
        if self.closed:
            return
        app = self.app
        if app.template_img is not None and (app.quads or {}).get("front"):
            self.tpl_radio.configure(text=self.t("ai_src_template", name=Path(app.profile.get("template", "")).name),
                                     state="normal")
        else:
            self.tpl_radio.configure(text=self.t("ai_no_template"), state="disabled")
            if self.source_var.get() == "template":
                self.source_var.set("case")

    def make_guide(self):
        try:
            base = int(self.size_var.get())
        except (tk.TclError, ValueError):
            base = 1024
        app = self.app
        if self.source_var.get() == "template" and app.template_img is not None and (app.quads or {}).get("front"):
            return ai_guide_from_template(app.template_img, app.quads, base)
        return ai_guide(self.case_var.get(), float(self.angle_var.get()), float(self.thick_var.get()),
                        self.case_color(), base)

    def redraw_guide(self):
        if self.closed:
            return
        if self._guide_job is not None:
            self.app.root.after_cancel(self._guide_job)
        self._guide_job = self.app.root.after(60, self._redraw_guide)

    def _redraw_guide(self):
        self._guide_job = None
        if self.closed:
            return
        try:
            self.guide = self.make_guide()
        except Exception as exc:  # noqa: BLE001
            log_line(traceback.format_exc())
            self.set_status(f"{self.t('error')}: {exc}")
            return
        if not self.busy:
            self.preview_var.set("guide")
        self.request_show()

    # ------------------------------------------------------------------------------------------- painting
    def generate(self):
        if self.busy or self.closed:
            return
        try:
            guide, outline, windows = self.guide = self.make_guide()
            strength, steps, cfg = float(self.strength_var.get()), int(self.steps_var.get()), float(self.cfg_var.get())
            count = max(1, min(6, int(self.variants_var.get())))
        except (tk.TclError, ValueError) as exc:
            self.set_status(f"{self.t('error')}: {exc}")
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        negative = self.negative_text.get("1.0", "end").strip()
        seed_text = self.seed_var.get().strip()
        seed = int(seed_text) if seed_text.isdigit() else random.randint(1, 2 ** 31 - 64)
        source = self.source_var.get()
        meta = {"case": self.case_var.get() if source == "case" else "",
                "from_template": Path(self.app.profile.get("template", "")).name if source == "template" else "",
                "prompt": prompt, "negative": negative, "strength": strength, "steps": steps, "cfg": cfg,
                "size": list(guide.size)}
        self.store()
        self.busy = True
        self.stop.clear()
        self.live = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.update_buttons()
        self.set_status(self.t("ai_painting", i=1, n=count))
        if self.chosen is None:
            self.preview_var.set("guide")
        self.request_show()
        threading.Thread(target=self.work, daemon=True,
                         args=(AIServer.normalize(self.url_var.get()), self.model_var.get().strip(), guide, outline,
                               windows, seed, count, (prompt, negative, strength, steps, cfg), meta)).start()

    def work(self, url, model, guide, outline, windows, seed, count, params, meta):
        post, (prompt, negative, strength, steps, cfg) = self.q.put, params
        made = 0
        try:
            server = self.server
            if server is None or server.url != url:
                server = AIServer.detect(url)
                if server is None:
                    raise AIError(self.t("ai_not_running", url=url, name=url))
                names, current = server.models()
                post(("server", server, names, current))
                if model not in names:
                    model = ai_default_model(names, current)
            if not model:
                raise AIError(self.t("ai_no_model"))
            if server.kind == "a1111" and not server.has_loaded(model):
                post(("status", self.t("ai_loading_model", name=model)))
                server.set_model(model)
            for i in range(count):
                if self.stop.is_set():
                    raise AIStopped()
                post(("status", self.t("ai_painting", i=i + 1, n=count)))
                picture = server.img2img(guide, prompt, negative, model=model, strength=strength, steps=steps, cfg=cfg,
                                         seed=seed + i, stop=self.stop,
                                         progress=lambda f, p, i=i: post(("progress", i, count, f, p)))
                made += 1
                post(("result", {"picture": picture, "outline": outline, "windows": windows,
                                 "meta": dict(meta, model=model, seed=seed + i, server=server.name)}, i == 0))
            post(("done", None, made))
        except AIStopped:
            post(("done", "stopped", made))
        except AIError as exc:
            post(("done", str(exc), made))
        except Exception as exc:  # noqa: BLE001
            log_line(traceback.format_exc())
            post(("done", f"{type(exc).__name__}: {exc}", made))

    def stop_now(self):
        if not self.busy:
            return
        self.stop.set()
        self.set_status(self.t("ai_stopped"))
        if self.server is not None:
            threading.Thread(target=self.server.interrupt, daemon=True).start()

    def update_buttons(self):
        self.go_button.configure(state="disabled" if self.busy else "normal")
        self.stop_button.configure(state="normal" if self.busy else "disabled")
        self.save_button.configure(state="normal" if self.chosen is not None else "disabled")

    def set_status(self, text):
        self.status.configure(text=text)

    def add_result(self, item):
        while len(self.results) >= self.MAX_RESULTS:
            old = self.results.pop(0)
            old["widget"].destroy()
            if old is self.chosen:
                self.chosen = self.made = None
        pic = item["picture"].copy()
        pic.thumbnail((self.px(92), self.px(92)), LANCZOS)
        item["photo"] = ImageTk.PhotoImage(pic)
        label = tk.Label(self.thumbs, image=item["photo"], bg=BG, bd=0, highlightthickness=self.px(3),
                         highlightbackground=BG, highlightcolor=BG, cursor="hand2")
        label.pack(side="left", padx=(0, 6))
        label.bind("<Button-1>", lambda e, it=item: self.choose(it))
        item["widget"] = label
        self.results.append(item)

    def choose(self, item):
        self.chosen = item
        for r in self.results:
            r["widget"].configure(highlightbackground=BLUE if r is item else BG)
        if self.preview_var.get() == "guide":
            self.preview_var.set("box")
        self.update_buttons()
        self.request_show()

    def made_template(self):
        """The chosen painting as a template (with the current reflections setting)."""
        item = self.chosen
        if item is None:
            return None
        try:
            gloss = float(self.gloss_var.get())
        except (tk.TclError, ValueError):
            gloss = 1.0
        if self.made is None or self.made[0] is not item or self.made[1] != gloss:
            tpl, quads = ai_template(item["picture"], item["outline"], item["windows"], gloss, int(self.s["height"]))
            self.made = (item, gloss, tpl, quads)
        return self.made[2], self.made[3]

    def sample_pics(self):
        """The game shown in the main window, or a made-up cover."""
        app = self.app
        if app.current is not None and app.pics is not None and app.pics.front is not None:
            return app.render_pics()
        if self._demo is None:
            img = Image.new("RGBA", (600, 850), (22, 64, 140, 255))
            d = ImageDraw.Draw(img)
            d.rectangle((50, 80, 550, 430), fill=(240, 196, 40, 255))
            d.text((300, 640), "GAME", fill=(255, 255, 255, 255), anchor="mm", font=load_font("Arial Black", 110))
            self._demo = Pictures(front=img, ctx={"title": "Game"})
        return self._demo

    def save(self):
        made = self.made_template()
        if made is None:
            self.set_status(self.t("ai_pick_result"))
            return
        tpl, quads = made
        name = self.name_var.get().strip() or self.default_name()
        meta = dict(self.chosen["meta"], gloss=round(float(self.gloss_var.get()), 2))
        try:
            path = save_ai_template(tpl, quads, name, meta)
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.win)
            return
        try:
            value = path.name if path.parent.resolve() == MODEL_DIR.resolve() else str(path)
        except OSError:
            value = str(path)
        self.app.use_template(value)
        text = self.t("ai_saved", path=path)
        self.app.log(text)
        self.app.set_status(text)
        self.set_status(text)
        self.refresh_template_choice()
        self.store()

    # ------------------------------------------------------------------------------------------- preview
    def request_show(self):
        if self.closed:
            return
        if self._show_job is not None:
            self.app.root.after_cancel(self._show_job)
        self._show_job = self.app.root.after(50, self.show)

    def show(self):
        if self._show_job is not None:          # called directly: the pending redraw is not needed any more
            try:
                self.app.root.after_cancel(self._show_job)
            except tk.TclError:
                pass
            self._show_job = None
        if self.closed:
            return
        c = self.canvas
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 40 or ch < 40:
            return
        c.delete("all")
        mode = self.preview_var.get()
        img, marks = None, None
        try:
            if self.busy and self.live is not None and (mode == "picture" or self.chosen is None):
                img = self.live
            elif mode == "guide" or self.chosen is None:
                if self.guide is not None:
                    img, marks = self.guide[0], self.guide[2]
            elif mode == "picture":
                img = self.chosen["picture"]
            else:
                tpl, quads = self.made_template()
                if mode == "template":
                    img = Image.new("RGBA", tpl.size, hex_rgb(CANVAS_BG) + (255,))
                    img.alpha_composite(tpl)
                    marks = quads
                else:
                    s = min(1.0, (ch - 16) / tpl.height, (cw - 16) / tpl.width)
                    img, _ = render_box(self.app.profile, tpl, quads, self.sample_pics(), scale=max(0.05, s), ss=2)
        except Exception as exc:  # noqa: BLE001 - a bad picture must not break the window
            log_line(traceback.format_exc())
            c.create_text(cw // 2, ch // 2, text=f"{type(exc).__name__}: {exc}", fill="#ff8080", width=cw - 40,
                          font=ui_font(10))
            return
        if img is None:
            c.create_text(cw // 2, ch // 2, text="—", fill=MUTED, font=ui_font(14))
            return
        fit = min((cw - 16) / img.width, (ch - 16) / img.height)
        dw, dh = max(1, round(img.width * fit)), max(1, round(img.height * fit))
        self.photo = ImageTk.PhotoImage(img.resize((dw, dh), LANCZOS))
        x0, y0 = (cw - dw) // 2, (ch - dh) // 2
        c.create_image(x0, y0, anchor="nw", image=self.photo)
        for face, quad in (marks or {}).items():
            if quad:
                c.create_polygon(*[v for x, y in quad for v in (x0 + x * fit, y0 + y * fit)], outline=FACE_COLORS[face],
                                 fill="", dash=(5, 3), width=max(1, self.px(1.5)))

    # ------------------------------------------------------------------------------------------- messages
    def pump(self):
        if self.closed:
            return
        try:
            for _ in range(100):
                self.handle(self.q.get_nowait())
        except queue.Empty:
            pass
        self._pump_job = self.app.root.after(80, self.pump)

    def handle(self, msg):
        kind = msg[0]
        if kind == "server":
            _, server, names, current = msg
            self.server = server
            self.model_combo["values"] = names
            if self.model_var.get() not in names:
                self.model_var.set(ai_default_model(names, current))
                self.model_defaults(self.model_var.get())
            if self.waiting is not None:
                self.waiting.set()
                self.waiting = None
            if AIServer.normalize(self.url_var.get()) != server.url:      # found on the package's next port
                self.url_var.set(server.url)
            self.server_label.configure(text=self.t("ai_connected", name=server.name, url=server.url, n=len(names)),
                                        fg=GOOD)
        elif kind == "server_fail":
            self.server = None
            self.server_label.configure(text=msg[1], fg=WARN)
        elif kind == "server_wait":
            self.server_label.configure(text=msg[1], fg=SOFT)
        elif kind == "status":
            self.set_status(msg[1])
        elif kind == "progress":
            _, i, n, frac, preview = msg
            if frac is None:                  # ComfyUI says nothing about its steps
                if str(self.progress["mode"]) != "indeterminate":
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(15)
            else:
                if str(self.progress["mode"]) != "determinate":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                self.progress.configure(value=100 * (i + max(0.0, min(1.0, frac))) / max(1, n))
            if preview is not None:
                self.live = preview
                if self.preview_var.get() == "picture" or self.chosen is None:
                    self.request_show()
        elif kind == "result":
            _, item, first = msg
            self.live = None
            self.add_result(item)
            if first or self.chosen is None:
                self.choose(item)
        elif kind == "done":
            _, error, made = msg
            self.busy = False
            self.live = None
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0 if error else 100)
            if error == "stopped":
                text = self.t("ai_stopped")
            elif error:
                text = self.t("ai_failed", error=error)
                self.app.log(text)
            else:
                text = self.t("ai_done", n=made)
            self.set_status(text)
            self.update_buttons()
            self.request_show()

    def store(self):
        """The window's settings into the config (saved with the program's other settings)."""
        def num(var, kind, default):
            try:
                return kind(var.get())
            except (tk.TclError, ValueError):
                return default

        s = self.s
        s.update(url=AIServer.normalize(self.url_var.get()), source=self.source_var.get(), case=self.case_var.get(),
                 angle=num(self.angle_var, float, 30.0), thickness=num(self.thick_var, float, 0.1),
                 color=self.color_var.get(), model=self.model_var.get(),
                 prompt=self.prompt_text.get("1.0", "end").strip(),
                 negative=self.negative_text.get("1.0", "end").strip(), strength=num(self.strength_var, float, 0.5),
                 steps=num(self.steps_var, int, 28), cfg=num(self.cfg_var, float, 6.0),
                 variants=num(self.variants_var, int, 2), seed=self.seed_var.get().strip(),
                 size=num(self.size_var, int, 1024), gloss=num(self.gloss_var, float, 1.0),
                 preview=self.preview_var.get(), sm_exe=str(self.sm_exe or ""))
        self.app.cfg["ai"] = s
        UPSCALER.configure(s["url"])                     # covers are upscaled on the same server
        self.app.schedule_save()

    def close(self):
        if self.closed:
            return
        try:
            self.store()
        except tk.TclError:
            pass
        self.closed = True
        self.stop.set()
        if self.waiting is not None:
            self.waiting.set()
        if self.busy and self.server is not None:
            threading.Thread(target=self.server.interrupt, daemon=True).start()
        for job in (self._pump_job, self._show_job, self._guide_job):
            if job is not None:
                try:
                    self.app.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.app.ai_dialog = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def take_screenshot(self):
        try:
            self.win.update()
            grab_window(self.win).save(self.app.options.get("screenshot"))
        except Exception as exc:  # noqa: BLE001
            log_line(f"screenshot: {exc}")
        self.win.after(200, lambda: os._exit(0))


def grab_window(root):
    """Picture of the program's own window only (Windows PrintWindow), even when other windows cover it."""
    import ctypes
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    handle = ctypes.c_void_p
    user32.GetAncestor.restype = handle
    user32.GetAncestor.argtypes = [handle, ctypes.c_uint]
    user32.GetClientRect.argtypes = [handle, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.argtypes = [handle, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [handle, ctypes.POINTER(wintypes.POINT)]
    user32.GetDC.restype = handle
    user32.GetDC.argtypes = [handle]
    user32.ReleaseDC.argtypes = [handle, handle]
    user32.PrintWindow.argtypes = [handle, handle, ctypes.c_uint]
    gdi32.CreateCompatibleDC.restype = handle
    gdi32.CreateCompatibleDC.argtypes = [handle]
    gdi32.CreateCompatibleBitmap.restype = handle
    gdi32.CreateCompatibleBitmap.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = handle
    gdi32.SelectObject.argtypes = [handle, handle]
    gdi32.GetDIBits.argtypes = [handle, handle, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint]
    gdi32.DeleteObject.argtypes = [handle]
    gdi32.DeleteDC.argtypes = [handle]

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                    ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    client = handle(root.winfo_id())
    top = user32.GetAncestor(client, 2)                  # GA_ROOT: the window with the title bar
    win, area, origin = wintypes.RECT(), wintypes.RECT(), wintypes.POINT(0, 0)
    user32.GetWindowRect(top, ctypes.byref(win))
    user32.GetClientRect(client, ctypes.byref(area))
    user32.ClientToScreen(client, ctypes.byref(origin))
    w, h = win.right - win.left, win.bottom - win.top
    screen_dc = user32.GetDC(top)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bitmap)
    try:
        user32.PrintWindow(top, mem_dc, 2)               # PW_RENDERFULLCONTENT
        info = BitmapInfoHeader(ctypes.sizeof(BitmapInfoHeader), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(info), 0)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(top, screen_dc)
    shot = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    x, y = origin.x - win.left, origin.y - win.top
    return shot.crop((x, y, x + area.right, y + area.bottom))


# ------------------------------------------------------------------------------------------------------ self-test
def selftest(report: str) -> int:
    """Render boxes from made-up pictures in a made-up LaunchBox folder; the build script runs this on the exe."""
    import tempfile
    lines, ok = [f"{APP_NAME} {APP_VERSION}"], True
    ensure_model_dir()

    def check(name, cond, extra=""):
        nonlocal ok
        ok = ok and bool(cond)
        lines.append(f"{'OK  ' if cond else 'FAIL'} {name} {extra}".rstrip())

    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "LaunchBox"
            (root / "Data" / "Platforms").mkdir(parents=True)
            title = "Tom Clancy's Test: Edition?"
            (root / "Data" / "Platforms.xml").write_text(
                "<?xml version=\"1.0\" standalone=\"yes\"?>\n<LaunchBox><Platform><Name>Test Platform</Name></Platform>"
                "</LaunchBox>", encoding="utf-8")
            (root / "Data" / "Platforms" / "Test Platform.xml").write_text(
                "<?xml version=\"1.0\" standalone=\"yes\"?>\n<LaunchBox><Game><Title>Tom Clancy&apos;s Test: Edition?"
                "</Title><ID>11111111-2222-3333-4444-555555555555</ID><Platform>Test Platform</Platform><Region>Europe"
                "</Region></Game></LaunchBox>", encoding="utf-8")
            front_dir = root / "Images" / "Test Platform" / "Box - Front" / "Europe"
            front_dir.mkdir(parents=True)
            front = Image.new("RGB", (480, 680), (30, 90, 200))
            ImageDraw.Draw(front).rectangle((40, 60, 440, 300), fill=(240, 200, 40))
            front.save(front_dir / (clean_name(title) + "-01.jpg"))
            lb = LaunchBox(root)
            lb.load()
            check("platforms", lb.platforms == ["Test Platform"], str(lb.platforms))
            games = lb.games("Test Platform")
            check("games", len(games) == 1 and games[0].title == title)
            prof = default_profile()
            found = lb.find("Test Platform", games[0], prof)
            check("front found", bool(found.get("front")) and found.get("region") == "Europe", str(found))
            pics, _ = load_pictures(lb, "Test Platform", games[0], prof, found)
            img, used = render_box(prof, None, None, pics, height=600)
            check("perspective box", img.mode == "RGBA" and img.height == 600 and used.get("spine"), str(img.size))
            prof_case = default_profile()
            prof_case["generic"]["style"] = "case"
            img2, _ = render_box(prof_case, None, None, pics, height=500)
            check("plastic case", img2.height == 500)
            target = output_target(lb, "Test Platform", games[0], found, {"region": "same", "existing": "skip",
                                                                          "format": "png"})
            check("output name", target is not None and target[0].name == "Tom Clancy_s Test_ Edition_-01.png"
                  and target[0].parent.name == "Europe", str(target))
            out = finish_picture(img, 500)
            save_picture(out, target[0], target[2], None, root, "png")
            check("saved", target[0].is_file())
            lb.index("Test Platform", OUT_TYPE, refresh=True)
            again = lb.find("Test Platform", games[0], prof)
            check("box 3d seen", len(again.get("box3d", [])) == 1)
            check("skip existing", output_target(lb, "Test Platform", games[0], again,
                                                 {"region": "same", "existing": "skip", "format": "png"}) is None)
        templates = sorted(p for p in MODEL_DIR.glob("*.png")) if MODEL_DIR.is_dir() else []
        for path in templates:
            tpl = Image.open(path).convert("RGBA")
            from_file = profile_quads(path, tpl.size)
            quads = from_file or detect_quads(tpl)
            img, _ = render_box(default_profile(), tpl, quads, Pictures(front=front.convert("RGBA")), height=600)
            check(f"template {path.name}", valid_quad(quads["front"]) and img.size == tpl.size,
                  f"corners={'profile' if from_file else 'found'} spine={'yes' if quads.get('spine') else 'no'}")
        if not templates:
            lines.append(f"(no templates in {MODEL_DIR})")
        bare = Pictures(ctx={"title": "Rocket Command", "lb_platform": "Commodore VIC-20 [Applications]"})
        img, _ = render_box(default_profile(), None, None, bare, height=500)
        made = generic_pictures(default_profile(), bare)
        check("generic cover (no Box - Front)", made.generic and made.spine is not None and img.height == 500,
              f"{platform_names('Commodore VIC-20 [Applications]')} {made.front.size}")
        guide, outline, windows = ai_guide(AI_DEFAULT_CASE, base=512)
        tpl, quads = ai_template(guide, outline, windows, 1.0, 700)    # the drawing itself as the "AI painting"
        img, _ = render_box(default_profile(), tpl, quads, Pictures(front=front.convert("RGBA")))
        check("AI template (no server)", valid_quad(quads["front"]) and valid_quad(quads["spine"]) and tpl.height == 700
              and see_through(tpl, quads["front"]) and img.size == tpl.size, f"drawing {guide.size} -> {tpl.size}")
        prof = dict(default_profile(), disc_text="{title} · © {year}")
        disc = render_disc(prof, Pictures(front=front.convert("RGBA"), ctx={"title": "Combat", "year": ""}),
                           "Sony Playstation 2", 400)
        check("disc", disc.size == (400, 400) and disc.getpixel((200, 200))[3] == 0 and disc.getpixel((0, 0))[3] == 0
              and disc.getpixel((340, 200))[3] == 255, f"kind {disc_kind(prof, 'Sony Playstation 2')}")
        check("generic disc", render_disc(default_profile(), bare, "", 300).size == (300, 300))
        names = ["Combat (USA)", "Combat (Europe)", "Combat (USA) (Beta)", "Pac-Man (USA)"]
        check("web title matching", libretro_match("Combat", "Europe", names) == "Combat (Europe)"
              and libretro_match("PacMan", "", names) == "Pac-Man (USA)" and libretro_match("Combat 2", "", names) == ""
              and libretro_system("Atari 2600 [Games]") == "Atari - 2600" and not libretro_system("Atari 2600 Manuals"))
        check("upscale off without a server", Upscaler().apply(front, None, dict(default_profile(), upscale=True,
                                                                                  upscale_below=99999)) is front)
    except Exception:  # noqa: BLE001
        ok = False
        lines.append(traceback.format_exc())
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    try:
        Path(report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def log_crash(kind, value, tb) -> None:
    log_line("CRASH " + "".join(traceback.format_exception(kind, value, tb)))


# Developer switches: --selftest <report>; --screenshot <file.png> [--platform P] [--game T] [--tab N]
# [--lb <LaunchBox folder>] (opens the window, picks the game, saves a picture of the window, quits);
# --ai opens the AI template window (with --screenshot: a picture of that window after --ai-wait ms, default 7000)
def main(argv=None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    sys.excepthook = log_crash
    threading.excepthook = lambda a: log_crash(a.exc_type, a.exc_value, a.exc_traceback)
    if args[:1] == ["--selftest"]:
        os._exit(selftest(args[1] if len(args) > 1 else "selftest.txt"))
    options = {}
    names = {"--screenshot": "screenshot", "--platform": "platform", "--game": "game", "--tab": "tab",
             "--lb": "lb", "--template": "template", "--face": "face", "--view": "view", "--ai-wait": "ai_wait"}
    i = 0
    while i < len(args):
        if args[i] == "--ai":
            options["ai"] = True
            i += 1
        elif args[i] in names and i + 1 < len(args):
            options[names[args[i]]] = args[i + 1]
            i += 2
        else:
            i += 1
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - older Windows
        pass
    ensure_model_dir()
    root = tk.Tk()
    try:
        root._icon = ImageTk.PhotoImage(app_icon(64))
        root.iconphoto(True, root._icon)
    except tk.TclError:
        pass
    App(root, options)
    if options.get("screenshot"):
        root.after(40000, lambda: os._exit(3))   # never hang a scripted run
    root.mainloop()
    os._exit(0)


if __name__ == "__main__":
    main()
