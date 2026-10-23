"""
Desktop Companion  -  a friendly animated pet that lives on your desktop.

A transparent, always-on-top overlay for Windows with a real app experience:

  * Several characters to choose from (robot, cat, ghost, slime, duck).
  * A system-tray icon with a full right-click menu.
  * A settings window - pick your pet, size, and which features are on.
  * Drag the pet anywhere; its spot is remembered between runs.
  * Speech bubbles with friendly, encouraging messages.
  * A built-in Pomodoro focus timer and gentle "stand up and stretch"
    break reminders - the bit that turns a toy into something useful.
  * Optional start-with-Windows.

This is the consumer-facing, zero-setup product in the suite. It needs no
accounts, no tokens, nothing to configure before it works - it just runs.

Design notes
------------
* Characters are drawn with PIL at 4x and downsampled, so they stay crisp at
  any display scaling (most laptops run 150-200%). Frames are pre-rendered
  once and cycled, because a 4x render per frame cannot hold 25 fps.
* Windows gives a borderless window only colour-key transparency (no partial
  alpha), so each frame is matted against the outline colour and
  hard-thresholded; edges read as a soft rim rather than a coloured halo.
* Everything persists to %APPDATA%\\DesktopCompanion\\settings.json.

Run it:            python desktop_companion.py
Run headless test: python desktop_companion.py --selftest
"""

import json
import math
import os
import random
import sys
import time

import suite_common

# Pillow is required; the rest of the GUI stack is stdlib.
from PIL import Image, ImageDraw, ImageFilter

APP_NAME = "Desktop Companion"
APP_ID = "DesktopCompanion"
TRANSPARENT = "magenta"          # this exact colour becomes see-through
SS = 4                           # supersampling factor for crisp art


# ============================================================================
#  Settings - persisted to %APPDATA% so they survive restarts and packaging
# ============================================================================

def config_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_ID)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


SETTINGS_PATH = os.path.join(config_dir(), "settings.json")

DEFAULTS = {
    "character": "robot",        # robot | cat | ... | duck | custom
    "custom_image": "",          # path of the ACTIVE custom pet (character="custom")
    "custom_pets": [],           # your saved gallery: [{"name": str, "path": str}, ...]
    "cutout_pets": True,         # auto-remove the background when adding an image
    "show_builtin_pets": False,  # also list the built-in cartoon characters
    "size": 150,                 # pet box width in logical px (height scales)
    "x": None,                   # last position; None = auto top-right
    "y": None,
    "speech": True,              # show friendly speech bubbles
    "speech_every": 45,          # seconds between unprompted lines
    "break_reminders": True,     # "stand up and stretch" nudges
    "break_every": 50,           # minutes between break reminders
    "pomodoro_focus": 25,        # minutes of focus
    "pomodoro_break": 5,         # minutes of break
    "start_with_windows": False,
    "clickthrough_hint_shown": False,
    "sound": True,               # play little sound effects

    # --- pet care / mini-game state ---
    "care_enabled": True,        # hunger/happiness that you tend to
    "hunger": 30.0,              # 0 = full, 100 = starving
    "happiness": 80.0,           # 0 = sad, 100 = delighted
    "stats_time": None,          # epoch of last stats update (for decay)
    "high_score": 0,             # best Catch-the-Treats score
}


def _coerce(default, value):
    """Return value converted to the type of default, or raise ValueError.

    settings.json is a plain file a user can hand-edit (or that can get
    corrupted), so nothing in it is trusted to have the right type.
    """
    is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
    # Reject Infinity / NaN (json.load accepts them): int(inf) raises
    # OverflowError and NaN positions break placement later on.
    if is_num and not math.isfinite(value):
        raise ValueError
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
    elif isinstance(default, int):
        if is_num:
            return int(value)
    elif isinstance(default, float) or default is None:
        # floats (hunger, happiness) and the nullable numbers x / y /
        # stats_time - stats_time is an epoch float, so keep floats as-is
        if is_num or (default is None and value is None):
            return value if default is None else float(value)
    elif isinstance(default, list):
        # the custom-pet gallery; its entries are sanitised in load_settings
        if isinstance(value, list):
            return value
    elif isinstance(default, str):
        if isinstance(value, str):
            return value
    raise ValueError


def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return data
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key in DEFAULTS:
                try:
                    data[key] = _coerce(DEFAULTS[key], value)
                except ValueError:
                    pass                    # bad value -> keep the default
    # Sanitise the custom-pet gallery: keep only entries that still name a
    # readable image file on disk, with no duplicate paths.
    pets, seen = [], set()
    for item in data.get("custom_pets", []):
        if not isinstance(item, dict):
            continue
        name, path = item.get("name"), item.get("path")
        if (isinstance(name, str) and isinstance(path, str)
                and path not in seen and os.path.exists(path)):
            pets.append({"name": name, "path": path})
            seen.add(path)
    # Migrate a pre-gallery single custom image into the gallery.
    ci = data.get("custom_image")
    if isinstance(ci, str) and ci and os.path.exists(ci) and ci not in seen:
        pets.append({"name": _name_from_path(ci), "path": ci})
        seen.add(ci)
    data["custom_pets"] = pets

    if data["character"] == "custom":
        # keep the custom pet only if we still have a usable image for it
        ci = data.get("custom_image")
        if not (isinstance(ci, str) and ci and os.path.exists(ci)):
            data["custom_image"] = pets[0]["path"] if pets else ""
        if not data["custom_image"]:
            data["character"] = DEFAULTS["character"]
    elif data["character"] not in CHARACTERS:
        data["character"] = DEFAULTS["character"]

    # If the built-in characters are hidden and you have your own pets, don't
    # start up showing a (now invisible) built-in - switch to a custom pet.
    if (not data.get("show_builtin_pets", False) and pets
            and data["character"] != "custom"):
        data["character"] = "custom"
        data["custom_image"] = pets[0]["path"]
    return data


# ============================================================================
#  Custom pet from an uploaded image
# ============================================================================

MAX_PET_PX = 1024          # a pet is shown at ~150px; no need to keep more


def load_custom_image(path):
    """Open an image as RGBA, downscaled to a sane size, or None if unreadable.

    Full-size photos (a 12 MP camera shot is tens of MB as RGBA) were being cut
    out, saved and then decoded on the UI thread, freezing the pet; the pure
    Python fallback cut-out looped over every pixel. Thumbnailing on load keeps
    all of that bounded.
    """
    try:
        img = Image.open(path)
        img.draft("RGB", (MAX_PET_PX, MAX_PET_PX))   # fast pre-shrink for JPEGs
        img = img.convert("RGBA")
        if max(img.size) > MAX_PET_PX:
            img.thumbnail((MAX_PET_PX, MAX_PET_PX), Image.LANCZOS)
        return img
    except Exception:
        return None


def _name_from_path(path):
    """A friendly pet name guessed from a file name: iron-man.png -> Iron Man."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = stem.replace("_", " ").replace("-", " ").strip()
    return (stem[:24].strip() or "My pet").title()


def _unique_pet_name(name, pets):
    """Make `name` unique among the gallery by adding ' (2)', ' (3)', ..."""
    existing = {p.get("name") for p in pets}
    if name not in existing:
        return name
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def custom_frames(src, width, height, breath_frames, breath_depth):
    """Breathing frames from a user image: fit it into the pet box, then
    squash vertically each frame (keeping volume by widening), feet on the
    ground. Transparency is preserved; a cutout PNG looks best."""
    base = src.copy()
    base.thumbnail((width, height), Image.LANCZOS)
    frames = []
    for i in range(breath_frames):
        squash = 1.0 - breath_depth * (
            1 - math.cos(2 * math.pi * i / breath_frames)) / 2
        w = max(1, int(base.width / math.sqrt(squash)))
        h = max(1, int(base.height * squash))
        sc = base.resize((w, h), Image.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.alpha_composite(sc, ((width - w) // 2, height - h))
        frames.append(canvas)
    return frames


# ============================================================================
#  Automatic background removal - turn any photo into a clean cut-out pet
# ============================================================================
#
# Uses the U2-Net saliency model through ONNX Runtime (the same model the
# popular "rembg" tool uses), but driven directly so we only need onnxruntime
# + numpy - no heavy extra packages. The ~168 MB model is downloaded once on
# first use and cached beside the settings, then works offline. If onnxruntime
# or the model is unavailable, we fall back to a plain-background heuristic, and
# if even that fails the original image is used unchanged.

BG_MODEL_URL = ("https://github.com/danielgatis/rembg/releases/download/"
                "v0.0.0/u2net.onnx")
BG_MODEL_MIN = 1_000_000    # a valid u2net.onnx is ~168 MB; this rules out stubs
BG_MEAN = (0.485, 0.456, 0.406)
BG_STD = (0.229, 0.224, 0.225)
_bg_session = None          # cached onnxruntime session (or False if it failed)
import threading as _threading
_bg_model_lock = _threading.Lock()   # serialises download AND session creation


def _bg_model_path():
    return os.path.join(config_dir(), "u2net.onnx")


def _bg_bundled_model():
    """A model shipped beside the exe / in the PyInstaller bundle, if any."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "u2net.onnx")


def ensure_bg_model(progress=None):
    """Return a path to u2net.onnx, downloading it once if needed, else None.

    The download is guarded by a lock so adding several images at once can't
    start two downloads writing the same .part file (the second os.replace would
    fail on Windows). A download is accepted only if it finished (its size
    matches Content-Length when the server gives one) and is plausibly large, so
    a truncated file isn't cached and then trusted forever.
    """
    for p in (_bg_model_path(), _bg_bundled_model()):
        if os.path.exists(p) and os.path.getsize(p) > BG_MODEL_MIN:
            return p
    dest = _bg_model_path()
    with _bg_model_lock:
        # another thread may have finished while we waited for the lock
        if os.path.exists(dest) and os.path.getsize(dest) > BG_MODEL_MIN:
            return dest
        tmp = dest + ".part"
        try:
            import urllib.request
            req = urllib.request.Request(
                BG_MODEL_URL, headers={"User-Agent": "DesktopCompanion"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done, total)
            size = os.path.getsize(tmp)
            if size < BG_MODEL_MIN or (total and size != total):
                raise OSError("incomplete model download")
            os.replace(tmp, dest)
            return dest
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return None


def _get_bg_session():
    global _bg_session
    if _bg_session is not None:
        return _bg_session or None
    path = ensure_bg_model()
    if not path:
        # Download failed (e.g. offline). Leave _bg_session as None so a later
        # add-image attempt can retry, rather than falling back for good.
        return None
    try:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.log_severity_level = 3
        _bg_session = ort.InferenceSession(
            path, sess_options=so, providers=["CPUExecutionProvider"])
    except Exception:
        # The cached file loads but isn't a valid model (corrupt/tampered).
        # Drop it so the next run re-downloads instead of failing forever.
        try:
            p = _bg_model_path()
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
        _bg_session = False
    return _bg_session or None


def _heuristic_cutout(img, tol=36):
    """Pure-Pillow fallback: flood-fill the background in from the four corners
    and make it transparent. Works for fairly plain backgrounds."""
    try:
        from PIL import ImageDraw
        rgb = img.convert("RGB")
        w, h = rgb.size
        key = (0, 254, 1)       # a colour unlikely to appear in a real photo
        work = rgb.copy()
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            ImageDraw.floodfill(work, corner, key, thresh=tol)
        base = img.convert("RGBA")
        bp, wp = base.load(), work.load()
        for y in range(h):
            for x in range(w):
                if wp[x, y] == key:
                    r, g, b, _ = bp[x, y]
                    bp[x, y] = (r, g, b, 0)
        return base
    except Exception:
        return img.convert("RGBA")


def remove_background(img):
    """Return an RGBA cut-out of the main subject with the background made
    transparent. Never raises: falls back to a heuristic, then to the original."""
    try:
        sess = _get_bg_session()
        if sess is not None:
            import numpy as np
            im = img.convert("RGB").resize((320, 320), Image.LANCZOS)
            a = np.asarray(im).astype(np.float64)
            a = a / max(a.max(), 1e-6)
            t = np.zeros((320, 320, 3))
            for c in range(3):
                t[:, :, c] = (a[:, :, c] - BG_MEAN[c]) / BG_STD[c]
            t = t.transpose(2, 0, 1)[None].astype(np.float32)
            out = sess.run(None, {sess.get_inputs()[0].name: t})[0]
            p = out[0, 0]
            p = (p - p.min()) / (p.max() - p.min() + 1e-8)
            mask = Image.fromarray((p * 255).astype("uint8"), "L").resize(
                img.size, Image.LANCZOS)
            rgba = img.convert("RGBA")
            rgba.putalpha(mask)
            return rgba
    except Exception:
        pass
    return _heuristic_cutout(img)


def save_settings(data):
    # Atomic write: a crash, power cut or kill mid-save must not leave an empty
    # or half-written settings.json (which load_settings would discard, losing
    # the whole pet gallery, position, stats and high score).
    try:
        suite_common.atomic_write_text(
            SETTINGS_PATH, json.dumps(data, indent=2))
    except OSError:
        pass


# ============================================================================
#  Character artwork - each returns an RGBA frame at (W, H)
# ============================================================================
#
# Every character implements draw(box, squash, blink) where:
#   box    = (W, H) supersampled pixel size of the frame
#   squash = 1.0 neutral, <1 compressed (breathing)
#   blink  = 0.0 eyes open .. 1.0 eyes shut
#
# A shared coordinate helper maps a 100x133 design space onto the frame with
# the breathing squash applied towards the feet, so volume looks constant.

CHARACTERS = ("robot", "cat", "ghost", "slime", "duck",
              "fox", "penguin", "dino", "bunny")
CHARACTER_LABELS = {
    "robot": "Chip the Robot",
    "cat": "Momo the Cat",
    "ghost": "Boo the Ghost",
    "slime": "Gloop the Slime",
    "duck": "Puddles the Duck",
    "fox": "Rusty the Fox",
    "penguin": "Pip the Penguin",
    "dino": "Rex the Dino",
    "bunny": "Clover the Bunny",
    "custom": "My own image",
}


def _mapper(W, H, squash):
    """Return a function mapping design coords (0..100, 0..133) to pixels."""
    ground = 128.0
    stretch = 1.0 / math.sqrt(squash)

    def P(x, y):
        x = 50 + (x - 50) * stretch
        y = ground - (ground - y) * squash
        return (x / 100.0 * W, y / 133.0 * H)
    return P


def _capsule(d, p0, p1, width, fill):
    r = width // 2
    d.line([p0, p1], fill=fill, width=width)
    for (x, y) in (p0, p1):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _eyes(d, P, cx_left, cx_right, cy, r, blink, colour=(26, 26, 32),
          joiner=False):
    """Two dot eyes that close to a line when blink -> 1."""
    open_h = r * (1.0 - blink)
    if joiner:
        d.line([P(cx_left, cy), P(cx_right, cy)], fill=colour,
               width=max(1, int(r * 0.6)))
    for cx in (cx_left, cx_right):
        if open_h < r * 0.35:
            (x0, y0), (x1, y1) = P(cx - r, cy), P(cx + r, cy)
            d.line([(x0, y0), (x1, y1)], fill=colour, width=max(1, int(r * 0.6)))
        else:
            d.ellipse([*P(cx - r, cy - open_h), *P(cx + r, cy + open_h)],
                      fill=colour)


def draw_robot(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    skin, outline = (248, 248, 250), (198, 200, 210)
    # body
    d.ellipse([*P(16, 46), *P(84, 122)], fill=skin, outline=outline,
              width=max(1, int(0.02 * W)))
    # arms + legs
    _capsule(d, P(22, 68), P(8, 96), int(0.14 * W), skin)
    _capsule(d, P(78, 68), P(92, 96), int(0.14 * W), skin)
    _capsule(d, P(38, 110), P(37, 128), int(0.18 * W), skin)
    _capsule(d, P(62, 110), P(63, 128), int(0.18 * W), skin)
    # head
    d.ellipse([*P(27, 12), *P(73, 50)], fill=skin, outline=outline,
              width=max(1, int(0.02 * W)))
    # antenna
    d.line([P(50, 12), P(50, 4)], fill=outline, width=max(1, int(0.015 * W)))
    d.ellipse([*P(47, 1), *P(53, 7)], fill=(255, 120, 120))
    _eyes(d, P, 41, 59, 32, 5.5, blink, joiner=True)
    return img


def draw_cat(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    fur, outline, inner = (255, 196, 120), (120, 80, 40), (255, 150, 150)
    # tail
    _capsule(d, P(80, 118), P(96, 86), int(0.08 * W), fur)
    # body
    d.ellipse([*P(20, 70), *P(80, 128)], fill=fur, outline=outline,
              width=max(1, int(0.015 * W)))
    # head
    d.ellipse([*P(26, 24), *P(74, 74)], fill=fur, outline=outline,
              width=max(1, int(0.015 * W)))
    # ears
    d.polygon([P(30, 34), P(26, 10), P(44, 26)], fill=fur, outline=outline)
    d.polygon([P(70, 34), P(74, 10), P(56, 26)], fill=fur, outline=outline)
    d.polygon([P(32, 30), P(31, 16), P(40, 26)], fill=inner)
    d.polygon([P(68, 30), P(69, 16), P(60, 26)], fill=inner)
    # face
    _eyes(d, P, 40, 60, 46, 5.0, blink, colour=(40, 90, 50))
    d.polygon([P(47, 54), P(53, 54), P(50, 59)], fill=inner)   # nose
    wh = max(1, int(0.008 * W))
    for sx in (-1, 1):
        for dy in (-3, 0, 3):
            d.line([P(50 + sx * 3, 58), P(50 + sx * 22, 58 + dy)],
                   fill=outline, width=wh)
    return img


def draw_ghost(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    body, outline = (236, 238, 248), (150, 156, 180)
    # rounded dome + wavy hem
    d.pieslice([*P(18, 16), *P(82, 116)], 180, 360, fill=body)
    d.rectangle([*P(18, 66), *P(82, 108)], fill=body)
    hem = []
    scallops = 4
    for i in range(scallops + 1):
        x = 18 + (82 - 18) * i / scallops
        hem.append(P(x, 108 if i % 2 == 0 else 118))
    hem += [P(82, 66), P(18, 66)]
    d.polygon(hem, fill=body)
    # soft outline
    d.arc([*P(18, 16), *P(82, 116)], 180, 360, fill=outline,
          width=max(1, int(0.012 * W)))
    _eyes(d, P, 40, 60, 54, 6.0, blink, colour=(70, 76, 110))
    d.ellipse([*P(46, 66), *P(54, 74)], fill=(70, 76, 110))      # mouth
    return img


def draw_slime(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    body, outline, hi = (120, 220, 170), (40, 150, 110), (210, 255, 230)
    d.pieslice([*P(14, 44), *P(86, 150)], 180, 360, fill=body)
    d.rectangle([*P(14, 96), *P(86, 124)], fill=body)
    d.ellipse([*P(14, 108), *P(86, 128)], fill=body, outline=outline,
              width=max(1, int(0.012 * W)))
    d.arc([*P(14, 44), *P(86, 150)], 180, 360, fill=outline,
          width=max(1, int(0.012 * W)))
    d.ellipse([*P(30, 60), *P(44, 78)], fill=hi)                 # shine
    _eyes(d, P, 40, 60, 86, 5.5, blink, colour=(30, 60, 50))
    d.arc([*P(44, 90), *P(56, 100)], 0, 180, fill=(30, 60, 50),
          width=max(1, int(0.01 * W)))                           # smile
    return img


def draw_duck(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    body, outline, beak = (255, 214, 90), (200, 150, 30), (250, 150, 40)
    # body
    d.ellipse([*P(20, 66), *P(84, 126)], fill=body, outline=outline,
              width=max(1, int(0.014 * W)))
    # tail
    d.polygon([P(80, 84), P(94, 78), P(82, 94)], fill=body, outline=outline)
    # head
    d.ellipse([*P(30, 20), *P(72, 62)], fill=body, outline=outline,
              width=max(1, int(0.014 * W)))
    # beak
    d.polygon([P(66, 38), P(86, 42), P(66, 50)], fill=beak, outline=outline)
    _eyes(d, P, 46, 58, 36, 4.6, blink)
    return img


def draw_fox(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    fur, outline, white, dark = (235, 130, 50), (150, 70, 20), \
        (250, 245, 240), (60, 40, 30)
    # bushy tail with white tip
    _capsule(d, P(78, 120), P(96, 90), int(0.1 * W), fur)
    d.ellipse([*P(90, 84), *P(100, 98)], fill=white)
    # body
    d.ellipse([*P(22, 72), *P(78, 128)], fill=fur, outline=outline,
              width=max(1, int(0.012 * W)))
    d.ellipse([*P(36, 96), *P(64, 128)], fill=white)        # belly
    # head
    d.ellipse([*P(28, 26), *P(72, 70)], fill=fur, outline=outline,
              width=max(1, int(0.012 * W)))
    # ears
    d.polygon([P(30, 36), P(24, 8), P(46, 28)], fill=fur, outline=outline)
    d.polygon([P(70, 36), P(76, 8), P(54, 28)], fill=fur, outline=outline)
    d.polygon([P(32, 30), P(30, 16), P(40, 27)], fill=dark)
    d.polygon([P(68, 30), P(70, 16), P(60, 27)], fill=dark)
    # white snout
    d.polygon([P(40, 52), P(60, 52), P(50, 70)], fill=white)
    _eyes(d, P, 41, 59, 46, 4.6, blink, colour=dark)
    d.polygon([P(47, 62), P(53, 62), P(50, 67)], fill=dark)  # nose
    return img


def draw_penguin(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    body, belly, beak = (40, 44, 58), (245, 246, 250), (250, 160, 40)
    # feet
    d.ellipse([*P(34, 122), *P(48, 130)], fill=beak)
    d.ellipse([*P(52, 122), *P(66, 130)], fill=beak)
    # body
    d.ellipse([*P(22, 30), *P(78, 126)], fill=body)
    d.ellipse([*P(32, 46), *P(68, 122)], fill=belly)        # white front
    # flippers
    _capsule(d, P(24, 70), P(16, 100), int(0.07 * W), body)
    _capsule(d, P(76, 70), P(84, 100), int(0.07 * W), body)
    # face area
    d.ellipse([*P(34, 36), *P(66, 64)], fill=belly)
    d.polygon([P(46, 54), P(54, 54), P(50, 64)], fill=beak)  # beak
    _eyes(d, P, 43, 57, 48, 4.4, blink)
    return img


def draw_dino(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    body, outline, spike = (120, 200, 120), (60, 140, 70), (90, 170, 100)
    # tail
    d.polygon([P(72, 120), P(96, 110), P(74, 128)], fill=body, outline=outline)
    # legs
    _capsule(d, P(40, 116), P(39, 130), int(0.12 * W), body)
    _capsule(d, P(60, 116), P(61, 130), int(0.12 * W), body)
    # body
    d.ellipse([*P(26, 58), *P(74, 126)], fill=body, outline=outline,
              width=max(1, int(0.012 * W)))
    # back spikes
    for sx in (44, 52, 60, 68):
        d.polygon([P(sx - 5, 60), P(sx + 5, 60), P(sx, 46)], fill=spike)
    # head
    d.ellipse([*P(34, 20), *P(72, 56)], fill=body, outline=outline,
              width=max(1, int(0.012 * W)))
    _eyes(d, P, 46, 60, 34, 4.4, blink)
    d.arc([*P(44, 40), *P(62, 50)], 0, 180, fill=outline,
          width=max(1, int(0.01 * W)))
    return img


def draw_bunny(box, squash, blink):
    W, H = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    P = _mapper(W, H, squash)
    fur, outline, inner, nose = (238, 238, 244), (180, 180, 196), \
        (255, 190, 200), (230, 130, 150)
    # ears
    d.ellipse([*P(36, 2), *P(48, 48)], fill=fur, outline=outline,
              width=max(1, int(0.01 * W)))
    d.ellipse([*P(52, 2), *P(64, 48)], fill=fur, outline=outline,
              width=max(1, int(0.01 * W)))
    d.ellipse([*P(39, 8), *P(45, 42)], fill=inner)
    d.ellipse([*P(55, 8), *P(61, 42)], fill=inner)
    # body
    d.ellipse([*P(24, 74), *P(76, 128)], fill=fur, outline=outline,
              width=max(1, int(0.012 * W)))
    # head
    d.ellipse([*P(30, 42), *P(70, 82)], fill=fur, outline=outline,
              width=max(1, int(0.012 * W)))
    _eyes(d, P, 42, 58, 58, 4.8, blink, colour=(70, 60, 70))
    d.polygon([P(47, 64), P(53, 64), P(50, 69)], fill=nose)
    return img


DRAWERS = {
    "robot": draw_robot, "cat": draw_cat, "ghost": draw_ghost,
    "slime": draw_slime, "duck": draw_duck, "fox": draw_fox,
    "penguin": draw_penguin, "dino": draw_dino, "bunny": draw_bunny,
}


# ============================================================================
#  Friendly things the pet says
# ============================================================================

GREETINGS = [
    "Hi there!", "You've got this!", "Looking good today.",
    "Need a hand?", "Stay hydrated!", "Deep breath in...",
    "One task at a time.", "You're doing great.", "Almost there!",
    "Remember to blink!", "Nice work so far.", "Keep it up!",
]
BREAK_LINES = [
    "Time to stretch!", "Stand up for a sec?", "Rest your eyes - look far away.",
    "Grab some water?", "Quick walk? Your back will thank you.",
    "Roll those shoulders!",
]
POMODORO_START = ["Focus time! Let's go.", "25 minutes. Heads down!"]
POMODORO_BREAK = ["Break time! Well earned.", "Pause. Breathe. Reset."]
HUNGRY_LINES = ["I'm getting hungry...", "Snack time? *tummy rumble*",
                "Feed me? Pretty please!", "Could go for a treat..."]
FED_LINES = ["Yum, thank you!", "So tasty!", "Mmm, my favourite!", "*happy munch*"]
PLAY_LINES = ["Yay, that was fun!", "Let's play again soon!", "Wheee!",
              "You're the best!"]


# ============================================================================
#  The running app (imports tkinter lazily so --selftest works headless)
# ============================================================================

def run_app(settings):
    import ctypes
    import tkinter as tk
    from PIL import ImageTk

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # ---- geometry helpers ----
    def work_area(root):
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        try:
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0,
                                                       ctypes.byref(r), 0)
            if r.right > r.left and r.bottom > r.top:
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()

    def key_matte(rgba, key, rim):
        base = Image.new("RGBA", rgba.size, rim + (255,))
        soft = Image.alpha_composite(base, rgba)
        alpha = rgba.split()[3].point(lambda a: 255 if a > 96 else 0)
        out = Image.new("RGB", rgba.size, key)
        out.paste(soft.convert("RGB"), (0, 0), alpha)
        return out

    class Companion:
        BREATH_FRAMES = 14
        BREATH_DEPTH = 0.04
        FRAME_MS = 40
        FLOAT_PX = 5

        def __init__(self):
            self.s = settings
            self.root = tk.Tk()
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.attributes("-transparentcolor", TRANSPARENT)

            self.width = max(80, min(400, int(self.s["size"])))
            self.height = int(self.width * 4 / 3)
            self._build_frames()

            self.canvas = tk.Canvas(self.root, width=self.width,
                                    height=self.height, bg=TRANSPARENT,
                                    highlightthickness=0, cursor="hand2")
            self.canvas.pack()
            self.item = self.canvas.create_image(
                0, 0, anchor="nw", image=self.photos[0])

            self.canvas.bind("<Button-1>", self.on_press)
            self.canvas.bind("<B1-Motion>", self.on_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_release)
            self.canvas.bind("<Double-Button-1>", lambda e: self.say_random())
            self.canvas.bind("<Button-3>", self.on_menu)

            self.left, self.top, self.right, self.bottom = work_area(self.root)
            self._place_initial()

            # animation state
            self.tick = 0
            self.blink_until = 0
            self.next_blink = self._frames(random.uniform(2, 5))
            self.bounce = 0.0
            self.dragging = False
            self.drag_dx = self.drag_dy = 0
            self.moved = False

            # bubble
            self.bubble = None
            self.bubble_hide_at = 0

            # schedulers (wall-clock deadlines, in monotonic seconds)
            self.next_speech = self._deadline(self.s["speech_every"]) \
                if self.s["speech"] else None
            self.next_break = self._deadline(self.s["break_every"] * 60) \
                if self.s["break_reminders"] else None
            self.pomo_state = None      # None | "focus" | "break"
            self.pomo_end = 0

            # pet-care stats: catch up decay for time since last run
            self._apply_offline_decay()
            self.next_stat = self._deadline(15)      # recompute every 15s
            self.next_hungry = self._deadline(60)    # earliest hungry nag
            self.game = None                         # open mini-game window

            self._build_menu()
            self._apply_startup(self.s["start_with_windows"], announce=False)
            self.tray = None
            self._start_tray()

            self.root.deiconify()
            self.play("hello")
            self.say(random.choice(["Hello! I'm here if you need me.",
                                    "Hi! Right-click me for options."]), 6)
            self.animate()

        # ---- frames ----
        def _build_frames(self):
            rim = (198, 200, 210)
            W, H = self.width * SS, self.height * SS
            self.frames_open, self.frames_blink = [], []

            custom = None
            if self.s["character"] == "custom" and self.s.get("custom_image"):
                custom = load_custom_image(self.s["custom_image"])

            if custom is not None:
                # a user image: breathe + float, no blink (a photo can't blink)
                for f in custom_frames(custom, self.width, self.height,
                                       self.BREATH_FRAMES, self.BREATH_DEPTH):
                    m = key_matte(f, TRANSPARENT, rim)
                    self.frames_open.append(m)
                    self.frames_blink.append(m)
            else:
                drawer = DRAWERS.get(self.s["character"], draw_robot)
                for i in range(self.BREATH_FRAMES):
                    sq = 1.0 - self.BREATH_DEPTH * (
                        1 - math.cos(2 * math.pi * i / self.BREATH_FRAMES)) / 2
                    fo = drawer((W, H), sq, 0.0).resize(
                        (self.width, self.height), Image.LANCZOS)
                    fb = drawer((W, H), sq, 1.0).resize(
                        (self.width, self.height), Image.LANCZOS)
                    self.frames_open.append(key_matte(fo, TRANSPARENT, rim))
                    self.frames_blink.append(key_matte(fb, TRANSPARENT, rim))

            from PIL import ImageTk as _Tk
            self.photos = [_Tk.PhotoImage(f) for f in self.frames_open]
            self.photos_blink = [_Tk.PhotoImage(f) for f in self.frames_blink]

        def _frames(self, seconds):
            # tick-based, for the purely visual blink timing where small drift
            # doesn't matter
            return self.tick + int(seconds * 1000 / self.FRAME_MS)

        def _deadline(self, seconds):
            # wall-clock, for anything the user would time against a real clock
            # (focus/break timers, reminders, care decay). Frame ticks run slow
            # -- Windows rounds after(40) up to ~47ms and render time adds more --
            # so counting frames made a "25-minute" focus block run ~28-30 min
            # and skipped time spent asleep.
            return time.monotonic() + seconds

        def _place_initial(self):
            x, y = self.s.get("x"), self.s.get("y")
            if x is None or y is None:
                x = self.right - self.width - 24
                y = self.top + 24
            x = max(self.left, min(self.right - self.width, int(x)))
            y = max(self.top, min(self.bottom - self.height, int(y)))
            self.base_x, self.base_y = x, y
            self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

        # ---- dragging ----
        def on_press(self, e):
            self.dragging = True
            self.moved = False
            self.drag_dx, self.drag_dy = e.x, e.y

        def on_drag(self, e):
            if not self.dragging:
                return
            self.moved = True
            nx = self.root.winfo_x() + e.x - self.drag_dx
            ny = self.root.winfo_y() + e.y - self.drag_dy
            nx = max(self.left, min(self.right - self.width, nx))
            ny = max(self.top, min(self.bottom - self.height, ny))
            self.base_x, self.base_y = nx, ny
            self.root.geometry(f"+{nx}+{ny}")

        def on_release(self, e):
            self.dragging = False
            if self.moved:
                self.s["x"], self.s["y"] = self.base_x, self.base_y
                save_settings(self.s)
            else:
                self.bounce = 1.0
                self.say_random()

        # ---- speech bubble ----
        def say_random(self):
            self.say(random.choice(GREETINGS), 4)

        def say(self, text, seconds=4, force=False):
            # `force` is for timer alerts (break / Pomodoro): turning off the
            # chatty speech bubbles shouldn't also silence the focus timer.
            if not self.s["speech"] and not force:
                return
            self._show_bubble(text)
            self.bubble_hide_at = self._frames(seconds)

        def _show_bubble(self, text):
            self._hide_bubble()
            b = tk.Toplevel(self.root)
            b.overrideredirect(True)
            b.attributes("-topmost", True)
            b.attributes("-transparentcolor", TRANSPARENT)
            b.configure(bg=TRANSPARENT)
            pad = 10
            font = ("Segoe UI", max(9, self.width // 16))
            lbl = tk.Label(b, text=text, bg="#ffffff", fg="#222222",
                           font=font, padx=pad, pady=pad - 2,
                           wraplength=self.width * 2, justify="center",
                           relief="solid", bd=1)
            lbl.pack()
            b.update_idletasks()
            bw, bh = lbl.winfo_reqwidth(), lbl.winfo_reqheight()
            px = self.root.winfo_x() + (self.width - bw) // 2
            px = max(self.left, min(self.right - bw, px))
            py = self.root.winfo_y() - bh - 6
            if py < self.top:
                py = self.root.winfo_y() + self.height + 6
            b.geometry(f"+{px}+{py}")
            self.bubble = b

        def _hide_bubble(self):
            if self.bubble is not None:
                try:
                    self.bubble.destroy()
                except Exception:
                    pass
                self.bubble = None

        def _show_builtins(self):
            """Built-in cartoon pets are listed only if you haven't hidden them,
            or you have no custom pets yet (so the app is never empty)."""
            return (self.s.get("show_builtin_pets", False)
                    or not self.s.get("custom_pets"))

        # ---- the tray / right-click menu ----
        def _build_menu(self):
            m = tk.Menu(self.root, tearoff=0)
            char = tk.Menu(m, tearoff=0)
            pets = self.s.get("custom_pets", [])
            show_builtins = self._show_builtins()
            if show_builtins:
                for key in CHARACTERS:
                    char.add_command(
                        label=("* " if key == self.s["character"] else "   ")
                        + CHARACTER_LABELS[key],
                        command=lambda k=key: self.set_character(k))
            if pets:
                if show_builtins:
                    char.add_separator()
                active = self.s.get("custom_image")
                for p in pets:
                    on = (self.s["character"] == "custom"
                          and active == p["path"])
                    char.add_command(
                        label=("* " if on else "   ") + p["name"],
                        command=lambda pa=p["path"]: self.set_custom_pet(pa))
            char.add_separator()
            char.add_command(label="   Add image(s)...",
                             command=self.choose_custom_image)
            if self.s["character"] == "custom" and self.s.get("custom_image"):
                char.add_command(
                    label="   Remove this pet",
                    command=lambda: self.remove_custom_pet(
                        self.s["custom_image"]))
            m.add_cascade(label="Choose pet", menu=char)
            m.add_command(label="Say something", command=self.say_random)
            m.add_separator()
            if self.s["care_enabled"]:
                m.add_command(label="Feed", command=self.feed)
                m.add_command(label="Play catch game", command=self.play_catch)
                m.add_command(label="How are you?", command=self.show_stats)
                m.add_separator()
            m.add_command(label=self._pomo_menu_text() + " (Pomodoro)",
                          command=self.toggle_pomodoro)
            m.add_command(label="Settings...", command=self.open_settings)
            m.add_separator()
            m.add_command(label="Hide for now",
                          command=lambda: self.root.withdraw())
            m.add_command(label="About", command=self.about)
            m.add_command(label="Quit", command=self.quit)
            self.menu = m

        def on_menu(self, e):
            try:
                self.menu.tk_popup(e.x_root, e.y_root)
            finally:
                self.menu.grab_release()

        # ---- real Windows system-tray icon (optional dependency) ----
        def _start_tray(self):
            try:
                import threading
                import pystray
            except Exception:
                return      # pystray not installed - right-click menu still works
            drawer = DRAWERS.get(self.s["character"], draw_robot)
            icon_img = drawer((64 * SS, 85 * SS), 1.0, 0.0).resize(
                (64, 64), Image.LANCZOS)

            def do(fn):
                # marshal tray-thread callbacks onto the tk main thread
                return lambda *a: self.root.after(0, fn)

            def show():
                self.root.deiconify()
                self.root.lift()

            def care_on(item):
                return bool(self.s.get("care_enabled"))

            menu = pystray.Menu(
                pystray.MenuItem("Show", do(show), default=True),
                pystray.MenuItem("Say hi", do(self.say_random)),
                pystray.MenuItem("Feed", do(self.feed), visible=care_on),
                pystray.MenuItem("Play catch game", do(self.play_catch),
                                 visible=care_on),
                pystray.MenuItem("How are you?", do(self.show_stats),
                                 visible=care_on),
                pystray.MenuItem(lambda item: self._pomo_menu_text(),
                                 do(self.toggle_pomodoro)),
                pystray.MenuItem("Settings...", do(self.open_settings)),
                pystray.MenuItem("Quit", do(self.quit)),
            )
            self.tray = pystray.Icon(APP_ID, icon_img, APP_NAME, menu)
            threading.Thread(target=self.tray.run, daemon=True).start()

        # ---- actions ----
        def set_character(self, key):
            if key == self.s["character"]:
                return
            self.s["character"] = key
            save_settings(self.s)
            self._build_frames()
            self._build_menu()
            self._update_tray_icon()
            self.say(f"I'm {CHARACTER_LABELS[key]} now!", 4)

        def _update_tray_icon(self):
            if self.tray is None:
                return
            try:
                if self.s["character"] == "custom" and self.s.get("custom_image"):
                    img = load_custom_image(self.s["custom_image"])
                    icon = img.resize((64, 64), Image.LANCZOS) if img else None
                else:
                    drawer = DRAWERS.get(self.s["character"], draw_robot)
                    icon = drawer((64 * SS, 85 * SS), 1.0, 0.0).resize(
                        (64, 64), Image.LANCZOS)
                if icon is not None:
                    self.tray.icon = icon
            except Exception:
                pass

        def _save_pet_image(self, src_path, img):
            """Save a (possibly cut-out) pet image into the app's pet folder as
            PNG, so transparency is kept; return the new path."""
            pets_dir = os.path.join(config_dir(), "custom_pets")
            os.makedirs(pets_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(src_path))[0] or "pet"
            dest = os.path.join(pets_dir, stem + ".png")
            n = 1
            while os.path.exists(dest):
                dest = os.path.join(pets_dir, f"{stem}_{n}.png")
                n += 1
            img.save(dest)
            return dest

        def choose_custom_image(self, on_done=None):
            """Pick one or more images, cut out the background, and add them.

            on_done(n_added) is called on the UI thread once the (background)
            work finishes -- the adding is async, so a caller can't just check a
            count right after this returns.
            """
            from tkinter import filedialog
            self._pick_done = on_done
            paths = filedialog.askopenfilenames(
                title="Choose image(s) for your pets",
                filetypes=[("Images", "*.png *.gif *.jpg *.jpeg *.bmp *.webp"),
                           ("All files", "*.*")])
            if not paths:
                self._pick_done = None
                return
            if self.s.get("cutout_pets", True):
                self.say("Making your pet... the first time I may take a minute "
                         "to download the cut-out model.", 8)
            else:
                self.say("Adding your pet...", 4)
            import threading
            threading.Thread(target=self._process_new_pets,
                             args=(list(paths),), daemon=True).start()

        def _process_new_pets(self, paths):
            """Worker thread: load, optionally remove the background, and save
            each image, then hand the results back to the UI thread."""
            cut = self.s.get("cutout_pets", True)
            out, bad = [], 0
            for path in paths:
                img = load_custom_image(path)
                if img is None:
                    bad += 1
                    continue
                try:
                    if cut:
                        img = remove_background(img)
                    dest = self._save_pet_image(path, img)
                    out.append((path, dest))
                except Exception:
                    bad += 1
            self.root.after(0, lambda: self._pets_added(out, bad))

        def _pets_added(self, out, bad):
            """UI thread: register the newly made pets and switch to the last."""
            from tkinter import messagebox
            last = None
            for src, dest in out:
                name = _unique_pet_name(_name_from_path(src),
                                        self.s["custom_pets"])
                self.s["custom_pets"].append({"name": name, "path": dest})
                last = dest
            if last is not None:
                self.s["custom_image"] = last
                self.s["character"] = "custom"
            save_settings(self.s)
            self._build_frames()
            self._build_menu()
            self._update_tray_icon()
            n = len(out)
            if n == 1:
                self.say("Ooh, a new look!", 4)
            elif n > 1:
                self.say(f"Added {n} new pets! Right-click to switch.", 5)
            if bad:
                messagebox.showerror(
                    APP_NAME, f"Couldn't use {bad} image(s). A clear photo of "
                    "a person or character works best.")
            cb = getattr(self, "_pick_done", None)
            self._pick_done = None
            if cb:
                try:
                    cb(len(out))
                except Exception:
                    pass

        def set_custom_pet(self, path):
            """Switch to one of the custom pets already in the gallery."""
            if (self.s["character"] == "custom"
                    and self.s.get("custom_image") == path):
                return
            self.s["custom_image"] = path
            self.s["character"] = "custom"
            save_settings(self.s)
            self._build_frames()
            self._build_menu()
            self._update_tray_icon()
            name = next((p["name"] for p in self.s["custom_pets"]
                         if p["path"] == path), None)
            self.say(f"I'm {name} now!" if name else "Ooh, a new look!", 4)

        def remove_custom_pet(self, path):
            """Remove a custom pet from the gallery (and delete our copy)."""
            self.s["custom_pets"] = [p for p in self.s["custom_pets"]
                                     if p["path"] != path]
            try:
                pets_dir = os.path.join(config_dir(), "custom_pets")
                if os.path.dirname(os.path.abspath(path)) == pets_dir:
                    os.remove(path)
            except OSError:
                pass
            if self.s.get("custom_image") == path:
                remaining = self.s["custom_pets"]
                if remaining:
                    self.s["custom_image"] = remaining[0]["path"]
                else:
                    self.s["custom_image"] = ""
                    self.s["character"] = DEFAULTS["character"]
            save_settings(self.s)
            self._build_frames()
            self._build_menu()
            self._update_tray_icon()
            self.say("Okay, I removed that one.", 3)

        def _pomo_menu_text(self):
            running = getattr(self, "pomo_state", None) is not None
            return "Stop focus timer" if running else "Start focus timer"

        def toggle_pomodoro(self):
            if self.pomo_state is None:
                self.pomo_state = "focus"
                self.pomo_end = self._deadline(self.s["pomodoro_focus"] * 60)
                self.say(random.choice(POMODORO_START), 5)
            else:
                self.pomo_state = None
                self.say("Timer stopped.", 3)
            self._build_menu()                  # flip Start <-> Stop label
            if self.tray is not None:
                try:
                    self.tray.update_menu()
                except Exception:
                    pass

        def about(self):
            from tkinter import messagebox
            messagebox.showinfo(
                APP_NAME,
                f"{APP_NAME}\n\nA friendly desktop pet with a built-in focus "
                "timer and break reminders.\n\nDrag to move, double-click to "
                "chat, right-click for the menu.")

        def open_settings(self):
            SettingsWindow(self)

        def rebuild_schedulers(self):
            self.next_speech = self._deadline(self.s["speech_every"]) \
                if self.s["speech"] else None
            self.next_break = self._deadline(self.s["break_every"] * 60) \
                if self.s["break_reminders"] else None

        def resize(self, new_size):
            self.width = max(80, min(400, int(new_size)))
            self.height = int(self.width * 4 / 3)
            self._build_frames()
            self.canvas.config(width=self.width, height=self.height)
            self._place_initial()

        def _apply_startup(self, enabled, announce=True):
            """Add/remove the startup entry. Returns True on success, False on
            failure, None when the Store build can't do it itself."""
            ok = set_run_at_startup(enabled)
            # None = packaged build: don't claim it worked, and don't flip the
            # saved flag as if it did.
            self.s["start_with_windows"] = bool(enabled and ok is True)
            save_settings(self.s)
            if announce:
                if ok is None:
                    self.say("In the Store version, turn this on under Windows "
                             "Settings > Apps > Startup.", 6)
                elif not ok:
                    self.say("Couldn't change startup setting.", 4)
                else:
                    self.say("Will start with Windows." if enabled
                             else "Won't auto-start anymore.", 4)
            return ok

        def play(self, kind):
            if self.s.get("sound"):
                play_sound(kind)

        # ---- pet care (feeding / happiness) ----
        def _apply_offline_decay(self):
            last = self.s.get("stats_time")
            now = time.time()
            if last:
                self._decay((now - last) / 60.0)
            self.s["stats_time"] = now
            save_settings(self.s)

        def _decay(self, minutes):
            minutes = max(0.0, min(minutes, 60 * 24))   # cap a long sleep
            self.s["hunger"] = min(100.0, self.s["hunger"] + minutes / 6.0)
            target = 100.0 - self.s["hunger"]           # happy when well-fed
            pull = min(1.0, minutes / 120.0)
            self.s["happiness"] += (target - self.s["happiness"]) * pull
            self.s["happiness"] = max(0.0, min(100.0, self.s["happiness"]))

        def _save_stats(self):
            self.s["stats_time"] = time.time()
            save_settings(self.s)

        def mood(self):
            h, hp = self.s["hunger"], self.s["happiness"]
            if hp > 75 and h < 40:
                return "delighted"
            if h > 75:
                return "very hungry"
            if hp < 35:
                return "a bit glum"
            return "content"

        def feed(self):
            if not self.s["care_enabled"]:
                return
            self.s["hunger"] = max(0.0, self.s["hunger"] - 35.0)
            self.s["happiness"] = min(100.0, self.s["happiness"] + 12.0)
            self._save_stats()
            self.bounce = 1.0
            self.play("feed")
            self.say(random.choice(FED_LINES), 4)

        def play_catch(self):
            if self.game is not None:
                try:
                    self.game.win.lift()
                except Exception:
                    self.game = None
                return
            self.game = MiniGame(self)

        def on_game_over(self, score):
            if self.game is None:
                return               # already processed this round
            self.game = None
            if self.s["care_enabled"]:
                self.s["happiness"] = min(100.0, self.s["happiness"]
                                          + min(25.0, score * 2.0))
                self.s["hunger"] = max(0.0, self.s["hunger"] - score * 1.0)
                self._save_stats()
            best = ""
            if score > self.s["high_score"]:
                self.s["high_score"] = score
                save_settings(self.s)
                best = " New best!"
            self.bounce = 1.0
            self.play("happy")
            self.say(random.choice(PLAY_LINES) + f" ({score} caught){best}", 6)

        def show_stats(self):
            name = CHARACTER_LABELS[self.s["character"]]
            self.say(f"{name} is feeling {self.mood()}.\n"
                     f"Hunger {int(self.s['hunger'])}/100, "
                     f"Happiness {int(self.s['happiness'])}/100.", 6)

        def quit(self):
            self._save_stats()
            save_settings(self.s)
            self._hide_bubble()
            if self.tray is not None:
                try:
                    self.tray.stop()
                except Exception:
                    pass
            try:
                self.root.destroy()
            except Exception:
                pass

        # ---- main loop ----
        def animate(self):
            self.tick += 1
            now = time.monotonic()
            frame = self.tick % self.BREATH_FRAMES

            if self.tick >= self.next_blink:
                self.blink_until = self.tick + max(1, 140 // self.FRAME_MS)
                self.next_blink = self._frames(random.uniform(2.5, 6))
            blinking = self.tick < self.blink_until
            img = (self.photos_blink if blinking else self.photos)[frame]
            self.canvas.itemconfig(self.item, image=img)

            # float + bounce
            dy = self.FLOAT_PX * math.sin(
                2 * math.pi * self.tick / (self.BREATH_FRAMES * 2))
            if self.bounce > 0.01:
                dy -= self.bounce * 18 * abs(math.sin(self.bounce * math.pi * 2))
                self.bounce = max(0.0, self.bounce - 0.08)
            if not self.dragging:
                self.root.geometry(
                    f"+{self.base_x}+{int(self.base_y + dy)}")

            # bubble lifetime + follow
            if self.bubble is not None:
                if self.tick >= self.bubble_hide_at:
                    self._hide_bubble()
                else:
                    try:
                        bw = self.bubble.winfo_width()
                        bh = self.bubble.winfo_height()
                        px = max(self.left, min(self.right - bw,
                                 self.base_x + (self.width - bw) // 2))
                        py = int(self.base_y + dy) - bh - 6
                        if py < self.top:
                            py = int(self.base_y + dy) + self.height + 6
                        self.bubble.geometry(f"+{px}+{py}")
                    except Exception:
                        pass

            # unprompted speech
            if self.next_speech is not None and now >= self.next_speech:
                if self.bubble is None and self.pomo_state is None:
                    self.say_random()
                self.next_speech = self._deadline(self.s["speech_every"])

            # break reminders
            if self.next_break is not None and now >= self.next_break:
                self.play("alert")
                self.say(random.choice(BREAK_LINES), 7, force=True)
                self.bounce = 1.0
                self.next_break = self._deadline(self.s["break_every"] * 60)

            # pomodoro
            if self.pomo_state is not None and now >= self.pomo_end:
                self.play("chime")
                if self.pomo_state == "focus":
                    self.pomo_state = "break"
                    self.pomo_end = self._deadline(self.s["pomodoro_break"] * 60)
                    self.say(random.choice(POMODORO_BREAK), 8, force=True)
                    self.bounce = 1.0
                else:
                    self.pomo_state = "focus"
                    self.pomo_end = self._deadline(self.s["pomodoro_focus"] * 60)
                    self.say(random.choice(POMODORO_START), 6, force=True)

            # pet care: decay stats, and occasionally ask to be fed
            if self.s["care_enabled"] and now >= self.next_stat:
                # decay the real elapsed time, not an assumed 15s, so sleeping or
                # a slow frame rate doesn't under-count
                self._decay(15.0 / 60.0)
                # keep the timestamp in step with the decay just applied, so
                # any save (drag, settings...) can't make the next launch
                # count this time again in _apply_offline_decay
                self.s["stats_time"] = time.time()
                self.next_stat = self._deadline(15)
                if self.s["hunger"] > 75 and now >= self.next_hungry \
                        and self.bubble is None and self.pomo_state is None:
                    self.say(random.choice(HUNGRY_LINES), 6)
                    self.next_hungry = self._deadline(180)   # don't nag

            self.root.after(self.FRAME_MS, self.animate)

        def run(self):
            self.root.mainloop()

    class SettingsWindow:
        def __init__(self, app):
            self.app = app
            self.s = app.s
            w = tk.Toplevel(app.root)
            w.title(f"{APP_NAME} - Settings")
            w.attributes("-topmost", True)
            w.resizable(False, False)
            self.w = w
            pad = {"padx": 10, "pady": 4}
            row = 0

            tk.Label(w, text="Pet:").grid(row=row, column=0, sticky="w", **pad)
            self.char_var = tk.StringVar(value=self.s["character"])
            # Built-in characters (only when shown), plus every custom pet.
            show_builtins = app._show_builtins()
            self.label_to_key = ({CHARACTER_LABELS[k]: k for k in CHARACTERS}
                                 if show_builtins else {})
            self.label_to_custom = {}
            pet_labels = []
            for p in self.s.get("custom_pets", []):
                lbl = "[mine] " + p["name"]
                self.label_to_custom[lbl] = p["path"]
                pet_labels.append(lbl)
            om = tk.OptionMenu(
                w, self.char_var,
                *(list(self.label_to_key.keys()) + pet_labels))
            # Show whichever pet is currently active.
            default_label = (CHARACTER_LABELS["robot"] if show_builtins
                             else (pet_labels[0] if pet_labels else ""))
            if self.s["character"] == "custom":
                cur = self.s.get("custom_image")
                self.char_var.set(next(
                    (l for l, pa in self.label_to_custom.items() if pa == cur),
                    default_label))
            elif show_builtins:
                self.char_var.set(CHARACTER_LABELS.get(
                    self.s["character"], default_label))
            else:
                self.char_var.set(default_label)
            om.grid(row=row, column=1, sticky="ew", **pad)
            tk.Button(w, text="Add image(s)...",
                      command=self._pick_image).grid(row=row, column=2, **pad)
            row += 1

            tk.Label(w, text="Size:").grid(row=row, column=0, sticky="w", **pad)
            self.size_var = tk.IntVar(value=self.s["size"])
            tk.Scale(w, from_=90, to=320, orient="horizontal",
                     variable=self.size_var).grid(row=row, column=1,
                                                  sticky="ew", **pad)
            row += 1

            self.speech_var = tk.BooleanVar(value=self.s["speech"])
            tk.Checkbutton(w, text="Speech bubbles",
                           variable=self.speech_var).grid(
                row=row, column=0, columnspan=2, sticky="w", **pad)
            row += 1

            self.break_var = tk.BooleanVar(value=self.s["break_reminders"])
            tk.Checkbutton(w, text="Break reminders",
                           variable=self.break_var).grid(
                row=row, column=0, columnspan=2, sticky="w", **pad)
            row += 1

            tk.Label(w, text="Break every (min):").grid(
                row=row, column=0, sticky="w", **pad)
            self.breakmin_var = tk.IntVar(value=self.s["break_every"])
            tk.Spinbox(w, from_=10, to=180, textvariable=self.breakmin_var,
                       width=6).grid(row=row, column=1, sticky="w", **pad)
            row += 1

            tk.Label(w, text="Focus length (min):").grid(
                row=row, column=0, sticky="w", **pad)
            self.focus_var = tk.IntVar(value=self.s["pomodoro_focus"])
            tk.Spinbox(w, from_=5, to=90, textvariable=self.focus_var,
                       width=6).grid(row=row, column=1, sticky="w", **pad)
            row += 1

            self.care_var = tk.BooleanVar(value=self.s["care_enabled"])
            tk.Checkbutton(w, text="Pet care (feeding, mini-game, moods)",
                           variable=self.care_var).grid(
                row=row, column=0, columnspan=2, sticky="w", **pad)
            row += 1

            self.sound_var = tk.BooleanVar(value=self.s["sound"])
            tk.Checkbutton(w, text="Sound effects",
                           variable=self.sound_var).grid(
                row=row, column=0, columnspan=2, sticky="w", **pad)
            row += 1

            self.cutout_var = tk.BooleanVar(value=self.s.get("cutout_pets", True))
            tk.Checkbutton(w, text="Cut out background when adding an image",
                           variable=self.cutout_var).grid(
                row=row, column=0, columnspan=2, sticky="w", **pad)
            row += 1

            self.builtins_var = tk.BooleanVar(
                value=self.s.get("show_builtin_pets", False))
            tk.Checkbutton(w, text="Show the built-in cartoon characters",
                           variable=self.builtins_var).grid(
                row=row, column=0, columnspan=2, sticky="w", **pad)
            row += 1

            self.startup_var = tk.BooleanVar(value=self.s["start_with_windows"])
            tk.Checkbutton(w, text="Start with Windows",
                           variable=self.startup_var).grid(
                row=row, column=0, columnspan=2, sticky="w", **pad)
            row += 1

            bar = tk.Frame(w)
            bar.grid(row=row, column=0, columnspan=2, pady=10)
            tk.Button(bar, text="Save", width=10,
                      command=self.save).pack(side="left", padx=6)
            tk.Button(bar, text="Cancel", width=10,
                      command=w.destroy).pack(side="left", padx=6)

        def _pick_image(self):
            # Adding is asynchronous (it may download the cut-out model), so we
            # reopen Settings from a callback once the pets are actually added,
            # not right after this returns.
            self.app.choose_custom_image(on_done=self._reopen_if_added)

        def _reopen_if_added(self, n_added):
            if n_added:
                try:
                    self.w.destroy()
                except Exception:
                    pass
                SettingsWindow(self.app)

        def save(self):
            from tkinter import messagebox
            app = self.app
            # Read and validate EVERYTHING before changing any setting, so a
            # typo in one box can't leave the settings half-applied.
            try:
                chosen = self.char_var.get()
                if chosen in self.label_to_key:
                    new_char, new_custom = self.label_to_key[chosen], None
                elif chosen in self.label_to_custom:
                    new_char, new_custom = "custom", self.label_to_custom[chosen]
                else:
                    new_char, new_custom = self.s["character"], None
                new_size = int(self.size_var.get())
                break_every = int(self.breakmin_var.get())
                focus = int(self.focus_var.get())
            except (tk.TclError, ValueError):
                messagebox.showerror(
                    APP_NAME, "Please enter whole numbers in the minutes boxes.",
                    parent=self.w)
                return
            if not (10 <= break_every <= 180 and 5 <= focus <= 90):
                messagebox.showerror(
                    APP_NAME, "Break reminders: 10-180 minutes.\n"
                              "Focus length: 5-90 minutes.", parent=self.w)
                return

            # all valid - apply
            self.s["speech"] = bool(self.speech_var.get())
            self.s["break_reminders"] = bool(self.break_var.get())
            self.s["break_every"] = break_every
            self.s["pomodoro_focus"] = focus
            self.s["care_enabled"] = bool(self.care_var.get())
            self.s["sound"] = bool(self.sound_var.get())
            self.s["cutout_pets"] = bool(self.cutout_var.get())
            self.s["show_builtin_pets"] = bool(self.builtins_var.get())
            if new_size != self.s["size"]:
                self.s["size"] = new_size
                app.resize(new_size)
            if new_char == "custom" and new_custom:
                app.set_custom_pet(new_custom)
            elif new_char != self.s["character"] and new_char in CHARACTERS:
                app.set_character(new_char)
            # If the built-ins were just hidden while a built-in is still the
            # active pet, switch to one of your own pets instead.
            if (not self.s["show_builtin_pets"] and self.s["custom_pets"]
                    and self.s["character"] != "custom"):
                app.set_custom_pet(self.s["custom_pets"][0]["path"])
            note = "Settings saved!"
            want_startup = bool(self.startup_var.get())
            if want_startup != self.s["start_with_windows"]:
                if not app._apply_startup(want_startup, announce=False):
                    note = "Saved - but couldn't change the startup setting."
            app.rebuild_schedulers()
            app._build_menu()
            if app.tray is not None:
                try:
                    app.tray.update_menu()      # care items show/hide
                except Exception:
                    pass
            save_settings(self.s)
            self.w.destroy()
            app.say(note, 4)

    class MiniGame:
        """Catch-the-Treats: treats fall, click them before they hit the
        ground. Catching treats feeds the pet and makes it happier."""
        W, H = 380, 300
        DURATION = 25            # seconds per round
        TREAT_R = 18

        def __init__(self, app):
            self.app = app
            self.score = 0
            self.time_left = self.DURATION
            self.treats = []     # list of [canvas_id, x, y, speed, kind]
            self.running = True

            w = tk.Toplevel(app.root)
            w.title("Catch the Treats!")
            w.resizable(False, False)
            w.attributes("-topmost", True)
            w.configure(bg="#eef3ff")
            w.protocol("WM_DELETE_WINDOW", self.close)
            self.win = w

            self.hud = tk.Label(w, text="", bg="#eef3ff", fg="#333",
                                font=("Segoe UI", 12, "bold"))
            self.hud.pack(pady=(8, 2))
            self.canvas = tk.Canvas(w, width=self.W, height=self.H,
                                    bg="#dbe7ff", highlightthickness=0)
            self.canvas.pack(padx=10, pady=(0, 10))
            tk.Label(w, text="Click the treats before they fall!",
                     bg="#eef3ff", fg="#667").pack(pady=(0, 8))
            self.canvas.bind("<Button-1>", self.on_click)

            self._centre_on_pet()
            self._update_hud()
            self.spawn_tick = 0
            self.frame = 0
            self._timer()
            self._loop()

        def _centre_on_pet(self):
            try:
                px = self.app.base_x + self.app.width // 2 - self.W // 2
                py = self.app.base_y + self.app.height // 2 - self.H // 2
                px = max(self.app.left, min(self.app.right - self.W - 20, px))
                py = max(self.app.top, min(self.app.bottom - self.H - 60, py))
                self.win.geometry(f"+{int(px)}+{int(py)}")
            except Exception:
                pass

        def _update_hud(self):
            self.hud.config(text=f"Score: {self.score}    "
                                 f"Time: {self.time_left}s    "
                                 f"Best: {self.app.s['high_score']}")

        def _timer(self):
            if not self.running:
                return
            self.time_left -= 1
            self._update_hud()
            if self.time_left <= 0:
                self.finish()
                return
            self.win.after(1000, self._timer)

        def spawn(self):
            kinds = [("#ff8a5b", 1), ("#ffd23f", 1), ("#8ac926", 1),
                     ("#e63946", -1)]   # red = bad treat, costs a point
            colour, val = random.choice(kinds)
            x = random.randint(self.TREAT_R, self.W - self.TREAT_R)
            speed = random.uniform(3.5, 7.0)
            r = self.TREAT_R
            cid = self.canvas.create_oval(x - r, -r, x + r, r, fill=colour,
                                          outline="")
            self.treats.append([cid, x, -r, speed, val])

        def on_click(self, e):
            for t in list(self.treats):
                cid, x, y, _, val = t
                if (e.x - x) ** 2 + (e.y - y) ** 2 <= (self.TREAT_R + 4) ** 2:
                    self.score = max(0, self.score + val)
                    self.canvas.delete(cid)
                    self.treats.remove(t)
                    self.app.play("catch")
                    self._update_hud()
                    break

        def _loop(self):
            if not self.running:
                return
            self.frame += 1
            if self.frame % max(6, 16 - self.score // 3) == 0:
                self.spawn()
            for t in list(self.treats):
                t[2] += t[3]
                self.canvas.move(t[0], 0, t[3])
                if t[2] - self.TREAT_R > self.H:
                    self.canvas.delete(t[0])
                    self.treats.remove(t)
            self.win.after(30, self._loop)

        def finish(self):
            if not self.running:
                return
            self.running = False
            try:
                self.canvas.create_text(
                    self.W // 2, self.H // 2, text=f"Time!\nYou caught {self.score}",
                    font=("Segoe UI", 22, "bold"), fill="#2b3a67",
                    justify="center")
                self.win.after(1400, self._safe_destroy)
            except Exception:
                self._safe_destroy()
            self.app.on_game_over(self.score)

        def close(self):
            self.running = False
            self.app.on_game_over(self.score)
            self._safe_destroy()

        def _safe_destroy(self):
            try:
                self.win.destroy()
            except Exception:
                pass

    Companion().run()


# ============================================================================
#  Start-with-Windows (registry Run key)  -  stdlib only
# ============================================================================

SOUND_SEQUENCES = {
    "feed":  [(523, 80), (392, 110)],         # soft "nom nom"
    "catch": [(880, 60)],                       # bright blip
    "happy": [(659, 80), (880, 120)],           # rising cheer
    "alert": [(440, 130), (440, 130)],          # gentle double nudge
    "chime": [(659, 90), (988, 150)],           # focus-timer chime
    "hello": [(587, 70), (784, 90)],
}


def play_sound(kind):
    """Play a short beep sequence on Windows. No-op elsewhere or on failure.

    Uses the stdlib winsound (no extra dependency). Runs on a daemon thread
    because winsound.Beep blocks for its duration.
    """
    if os.name != "nt":
        return
    seq = SOUND_SEQUENCES.get(kind)
    if not seq:
        return
    try:
        import threading
        import winsound
    except Exception:
        return

    def run():
        for freq, dur in seq:
            try:
                winsound.Beep(int(freq), int(dur))
            except Exception:
                break

    threading.Thread(target=run, daemon=True).start()


def _is_packaged_msix():
    """True when running from a Microsoft Store (MSIX) package, where HKCU\\Run
    is virtualised and never seen by Windows."""
    return os.name == "nt" and "\\WindowsApps\\" in (sys.executable or "")


def set_run_at_startup(enabled):
    """Add/remove the app from the current-user startup. Returns True on success,
    or None when packaged (the Store build can't use HKCU\\Run; Windows controls
    startup for it via Settings > Apps > Startup)."""
    if os.name != "nt":
        return False
    if _is_packaged_msix():
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
            winreg.KEY_SET_VALUE)
        if enabled:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}"'
            else:
                cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


# ============================================================================
#  Headless self-test  -  renders every character to PNGs, no display needed
# ============================================================================

def selftest(outdir=None):
    outdir = outdir or os.path.join(config_dir(), "selftest")
    os.makedirs(outdir, exist_ok=True)
    W, H = 150 * SS, 200 * SS
    results = []
    for key, drawer in DRAWERS.items():
        for blink in (0.0, 1.0):
            img = drawer((W, H), 1.0, blink).resize((150, 200), Image.LANCZOS)
            name = f"{key}{'_blink' if blink else ''}.png"
            img.save(os.path.join(outdir, name))
            results.append(name)
    # custom-image path: build breathing frames from a generated test image
    test_img = Image.new("RGBA", (120, 160), (0, 0, 0, 0))
    ImageDraw.Draw(test_img).ellipse([10, 10, 110, 150], fill=(200, 120, 255, 255))
    cframes = custom_frames(test_img, 150, 200, 14, 0.04)
    assert len(cframes) == 14 and cframes[0].size == (150, 200)
    cframes[0].save(os.path.join(outdir, "custom.png"))
    results.append("custom.png")
    # custom-pet gallery helpers
    assert _name_from_path("iron-man.png") == "Iron Man"
    assert _name_from_path("/x/THOR_wall.jpg") == "Thor Wall"
    assert _unique_pet_name("Hulk", [{"name": "Hulk"}]) == "Hulk (2)"
    assert _unique_pet_name("Hulk", [{"name": "Thor"}]) == "Hulk"
    # background-removal heuristic fallback (no network / no model needed):
    # a magenta blob on a solid white field should come back with a
    # transparent background and the subject kept.
    bg = Image.new("RGB", (80, 80), (255, 255, 255))
    ImageDraw.Draw(bg).ellipse([24, 24, 56, 56], fill=(200, 120, 255))
    cut = _heuristic_cutout(bg)
    assert cut.mode == "RGBA" and cut.size == (80, 80)
    assert cut.getpixel((0, 0))[3] == 0           # corner transparent
    assert cut.getpixel((40, 40))[3] == 255       # subject kept
    cut.save(os.path.join(outdir, "cutout_heuristic.png"))
    results.append("cutout_heuristic.png")
    # settings round-trip
    s = load_settings()
    save_settings(s)
    print(f"Rendered {len(results)} frames to {outdir}")
    print("Characters OK:", ", ".join(DRAWERS), "+ custom pet gallery")
    print("Settings file:", SETTINGS_PATH)
    return results


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    # One pet at a time: a second launch (e.g. auto-start plus a manual click)
    # would give two pets and two tray icons that overwrite each other's saved
    # settings. Bow out quietly if we're already running.
    if not suite_common.acquire_single_instance(suite_common.COMPANION_MUTEX):
        return
    settings = load_settings()
    # allow "python desktop_companion.py cat" to pick a character quickly,
    # or "python desktop_companion.py C:\path\to\image.png" for a custom pet
    for a in sys.argv[1:]:
        if a in CHARACTERS:
            settings["character"] = a
        elif os.path.isfile(a) and load_custom_image(a) is not None:
            if not any(p.get("path") == a for p in settings["custom_pets"]):
                settings["custom_pets"].append(
                    {"name": _unique_pet_name(_name_from_path(a),
                                              settings["custom_pets"]),
                     "path": a})
            settings["character"] = "custom"
            settings["custom_image"] = a
    run_app(settings)


if __name__ == "__main__":
    main()
