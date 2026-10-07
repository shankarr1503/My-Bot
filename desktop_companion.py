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
    "character": "robot",        # robot | cat | ghost | slime | duck
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
    if data["character"] not in CHARACTERS:
        data["character"] = DEFAULTS["character"]
    return data


def save_settings(data):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
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

            # schedulers (in ticks)
            self.next_speech = self._frames(self.s["speech_every"]) \
                if self.s["speech"] else None
            self.next_break = self._frames(self.s["break_every"] * 60) \
                if self.s["break_reminders"] else None
            self.pomo_state = None      # None | "focus" | "break"
            self.pomo_end = 0

            # pet-care stats: catch up decay for time since last run
            self._apply_offline_decay()
            self.next_stat = self._frames(15)        # recompute every 15s
            self.next_hungry = self._frames(60)      # earliest hungry nag
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
            drawer = DRAWERS.get(self.s["character"], draw_robot)
            rim = (198, 200, 210)
            W, H = self.width * SS, self.height * SS
            self.frames_open, self.frames_blink = [], []
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
            return self.tick + int(seconds * 1000 / self.FRAME_MS)

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

        def say(self, text, seconds=4):
            if not self.s["speech"]:
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

        # ---- the tray / right-click menu ----
        def _build_menu(self):
            m = tk.Menu(self.root, tearoff=0)
            char = tk.Menu(m, tearoff=0)
            for key in CHARACTERS:
                char.add_command(
                    label=("* " if key == self.s["character"] else "   ")
                    + CHARACTER_LABELS[key],
                    command=lambda k=key: self.set_character(k))
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
            if self.tray is not None:
                drawer = DRAWERS.get(key, draw_robot)
                try:
                    self.tray.icon = drawer((64 * SS, 85 * SS), 1.0, 0.0).resize(
                        (64, 64), Image.LANCZOS)
                except Exception:
                    pass
            self.say(f"I'm {CHARACTER_LABELS[key]} now!", 4)

        def _pomo_menu_text(self):
            running = getattr(self, "pomo_state", None) is not None
            return "Stop focus timer" if running else "Start focus timer"

        def toggle_pomodoro(self):
            if self.pomo_state is None:
                self.pomo_state = "focus"
                self.pomo_end = self._frames(self.s["pomodoro_focus"] * 60)
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
            self.next_speech = self._frames(self.s["speech_every"]) \
                if self.s["speech"] else None
            self.next_break = self._frames(self.s["break_every"] * 60) \
                if self.s["break_reminders"] else None

        def resize(self, new_size):
            self.width = max(80, min(400, int(new_size)))
            self.height = int(self.width * 4 / 3)
            self._build_frames()
            self.canvas.config(width=self.width, height=self.height)
            self._place_initial()

        def _apply_startup(self, enabled, announce=True):
            """Add/remove the startup entry. Returns True on success."""
            ok = set_run_at_startup(enabled)
            self.s["start_with_windows"] = bool(enabled and ok)
            save_settings(self.s)
            if announce:
                if not ok:
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
            if self.next_speech is not None and self.tick >= self.next_speech:
                if self.bubble is None and self.pomo_state is None:
                    self.say_random()
                self.next_speech = self._frames(self.s["speech_every"])

            # break reminders
            if self.next_break is not None and self.tick >= self.next_break:
                self.play("alert")
                self.say(random.choice(BREAK_LINES), 7)
                self.bounce = 1.0
                self.next_break = self._frames(self.s["break_every"] * 60)

            # pomodoro
            if self.pomo_state is not None and self.tick >= self.pomo_end:
                self.play("chime")
                if self.pomo_state == "focus":
                    self.pomo_state = "break"
                    self.pomo_end = self._frames(self.s["pomodoro_break"] * 60)
                    self.say(random.choice(POMODORO_BREAK), 8)
                    self.bounce = 1.0
                else:
                    self.pomo_state = "focus"
                    self.pomo_end = self._frames(self.s["pomodoro_focus"] * 60)
                    self.say(random.choice(POMODORO_START), 6)

            # pet care: decay stats, and occasionally ask to be fed
            if self.s["care_enabled"] and self.tick >= self.next_stat:
                self._decay(15.0 / 60.0)
                # keep the timestamp in step with the decay just applied, so
                # any save (drag, settings...) can't make the next launch
                # count this time again in _apply_offline_decay
                self.s["stats_time"] = time.time()
                self.next_stat = self._frames(15)
                if self.s["hunger"] > 75 and self.tick >= self.next_hungry \
                        and self.bubble is None and self.pomo_state is None:
                    self.say(random.choice(HUNGRY_LINES), 6)
                    self.next_hungry = self._frames(180)   # don't nag

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
            om = tk.OptionMenu(w, self.char_var,
                               *[CHARACTER_LABELS[k] for k in CHARACTERS])
            # map label<->key
            self.label_to_key = {CHARACTER_LABELS[k]: k for k in CHARACTERS}
            self.char_var.set(CHARACTER_LABELS[self.s["character"]])
            om.grid(row=row, column=1, sticky="ew", **pad)
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

        def save(self):
            from tkinter import messagebox
            app = self.app
            # Read and validate EVERYTHING before changing any setting, so a
            # typo in one box can't leave the settings half-applied.
            try:
                new_char = self.label_to_key[self.char_var.get()]
                new_size = int(self.size_var.get())
                break_every = int(self.breakmin_var.get())
                focus = int(self.focus_var.get())
            except (tk.TclError, ValueError, KeyError):
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
            if new_size != self.s["size"]:
                self.s["size"] = new_size
                app.resize(new_size)
            if new_char != self.s["character"]:
                app.set_character(new_char)
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


def set_run_at_startup(enabled):
    """Add/remove the app from the current-user startup. Returns True on success."""
    if os.name != "nt":
        return False
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
    # settings round-trip
    s = load_settings()
    save_settings(s)
    print(f"Rendered {len(results)} frames to {outdir}")
    print("Characters OK:", ", ".join(DRAWERS))
    print("Settings file:", SETTINGS_PATH)
    return results


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    settings = load_settings()
    # allow "python desktop_companion.py cat" to pick a character quickly
    for a in sys.argv[1:]:
        if a in CHARACTERS:
            settings["character"] = a
    run_app(settings)


if __name__ == "__main__":
    main()
