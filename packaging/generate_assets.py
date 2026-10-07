"""
Generate every store/app image asset from the mascot art.

Produces, into packaging/assets/:
  * app.ico                 - multi-size icon for the PyInstaller .exe
  * StoreLogo.png           - 50x50, Microsoft Store listing
  * Square44x44Logo.png     - taskbar / app-list icon
  * Square71x71Logo.png     - small tile
  * Square150x150Logo.png   - medium tile
  * Square310x310Logo.png   - large tile
  * Wide310x150Logo.png     - wide tile
  * SplashScreen.png        - 620x300 launch splash
  * hero.png                - 1280x720 store screenshot / marketing hero

Run:  python packaging/generate_assets.py
Everything is drawn with PIL, so there are no binary assets to keep in git.
"""

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# import the mascot drawers from the app itself
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from desktop_companion import DRAWERS, SS   # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUT, exist_ok=True)

# brand gradient (top -> bottom)
TOP = (99, 102, 241)       # indigo
BOTTOM = (56, 189, 248)    # sky


def _font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf",
                 "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def gradient(w, h, top=TOP, bottom=BOTTOM):
    base = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    return base.convert("RGBA")


def rounded_mask(size, radius_frac=0.22):
    w, h = size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=int(min(w, h) * radius_frac), fill=255)
    return m


def mascot(size, character="robot", pad_frac=0.16):
    """Mascot rendered transparent, centred in a (size,size) box."""
    drawer = DRAWERS.get(character, DRAWERS["robot"])
    W = H = size * SS
    art = drawer((W, int(H * 1.33)), 1.0, 0.0)
    # trim to content
    bbox = art.getbbox()
    if bbox:
        art = art.crop(bbox)
    inner = int(size * (1 - 2 * pad_frac))
    art.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(art, ((size - art.width) // 2,
                                 (size - art.height) // 2))
    return canvas


def icon(size, character="robot", rounded=True, bg=True):
    """Branded square icon: mascot on the gradient, rounded corners."""
    if bg:
        base = gradient(size, size)
        # subtle inner glow
        glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([size * 0.1, size * 0.05, size * 0.9, size * 0.85],
                   fill=(255, 255, 255, 40))
        base.alpha_composite(glow)
    else:
        base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base.alpha_composite(mascot(size, character))
    if rounded and bg:
        base.putalpha(rounded_mask((size, size)))
    return base


def save(img, name):
    path = os.path.join(OUT, name)
    img.save(path)
    print("  wrote", name, img.size)


def make_square_assets():
    # Store tiles usually have no rounded corners (Windows masks them itself),
    # but a gentle rounding reads well in the app list too.
    for size, name in [(50, "StoreLogo.png"), (44, "Square44x44Logo.png"),
                       (71, "Square71x71Logo.png"),
                       (150, "Square150x150Logo.png"),
                       (310, "Square310x310Logo.png")]:
        save(icon(size, rounded=True), name)


def make_wide():
    w, h = 310, 150
    base = gradient(w, h)
    base.alpha_composite(mascot(h, pad_frac=0.12), (14, 0))
    d = ImageDraw.Draw(base)
    d.text((h + 20, h // 2 - 18), "Desktop", font=_font(30),
           fill=(255, 255, 255))
    d.text((h + 20, h // 2 + 14), "Companion", font=_font(24),
           fill=(235, 240, 255))
    base.putalpha(rounded_mask((w, h), 0.08))
    save(base, "Wide310x150Logo.png")


def make_splash():
    w, h = 620, 300
    base = gradient(w, h)
    base.alpha_composite(mascot(200, pad_frac=0.05),
                         (w // 2 - 100, h // 2 - 130))
    d = ImageDraw.Draw(base)
    txt = "Desktop Companion"
    f = _font(40)
    tw = d.textbbox((0, 0), txt, font=f)[2]
    d.text(((w - tw) // 2, h - 70), txt, font=f, fill=(255, 255, 255))
    save(base, "SplashScreen.png")


def make_ico():
    # multi-resolution .ico for the executable
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [icon(s, rounded=True) for s in sizes]
    # The base image must be the largest: Pillow skips any requested size
    # bigger than the image it is saving from.
    imgs[-1].save(os.path.join(OUT, "app.ico"),
                  sizes=[(s, s) for s in sizes],
                  append_images=imgs[:-1])
    print("  wrote app.ico", sizes)


def make_hero():
    """A 1280x720 marketing image / store screenshot showing the whole cast."""
    w, h = 1280, 720
    base = gradient(w, h, (79, 70, 229), (14, 165, 233))
    d = ImageDraw.Draw(base)
    cast = list(DRAWERS)
    n = len(cast)
    cell = w // (n + 1)
    for i, c in enumerate(cast):
        m = mascot(200, c, pad_frac=0.05)
        x = cell // 2 + i * cell
        y = int(h * 0.42 + 24 * math.sin(i))
        base.alpha_composite(m, (x, y))
    title = "Meet your Desktop Companion"
    f = _font(58)
    tw = d.textbbox((0, 0), title, font=f)[2]
    d.text(((w - tw) // 2, 70), title, font=f, fill=(255, 255, 255))
    sub = "A friendly pet with a built-in focus timer and break reminders"
    fs = _font(30)
    sw = d.textbbox((0, 0), sub, font=fs)[2]
    d.text(((w - sw) // 2, 150), sub, font=fs, fill=(225, 230, 255))
    save(base.convert("RGB"), "hero.png")


def main():
    print(f"Generating assets into {OUT}")
    make_square_assets()
    make_wide()
    make_splash()
    make_ico()
    make_hero()
    print("Done.")


if __name__ == "__main__":
    main()
