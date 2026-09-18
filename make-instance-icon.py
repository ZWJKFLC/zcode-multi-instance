#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a badge icon (png + ico) for a ZCode instance.

Electron nativeImage cannot load .ico for window/taskbar icons, so the
patch reads ZCODE_INSTANCE_ICON which MUST be a .png. An .ico is also
generated for use as the desktop shortcut icon.

Usage:
  python make-instance-icon.py <output-prefix> <color>            # e.g. orange
  python make-instance-icon.py <output-prefix> <r> <g> <b>        # e.g. 255 140 0

Requires Pillow:  pip install pillow
"""
import sys

from PIL import Image, ImageDraw

BASE = 256          # canvas size
BADGE_R = 0.19      # badge radius relative to canvas


def main():
    args = sys.argv[1:]
    if len(args) not in (2, 4):
        sys.exit(__doc__)
    prefix = args[0]
    if len(args) == 2:
        colors = {"orange": (255, 140, 0), "green": (30, 180, 90),
                  "blue": (0, 120, 215), "purple": (140, 80, 220),
                  "red": (220, 50, 50)}
        if args[1] not in colors:
            sys.exit("unknown color name, choose from: " + ", ".join(colors))
        rgb = colors[args[1]]
    else:
        rgb = tuple(int(x) for x in args[1:4])

    # start from the official icon if present next to the script, else plain badge
    try:
        import os
        base_path = os.path.join(os.environ["LOCALAPPDATA"],
                                 "Programs", "ZCode", "resources", "icon_windows.png")
        img = Image.open(base_path).convert("RGBA").resize((BASE, BASE))
    except Exception:
        img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))

    d = ImageDraw.Draw(img)
    cx, cy, r = int(BASE * (1 - BADGE_R - 0.05)), int(BASE * (1 - BADGE_R - 0.05)), int(BASE * BADGE_R)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgb + (255,))
    ring = max(4, BASE // 48)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 255), width=ring)

    png = prefix + ".png"
    ico = prefix + ".ico"
    img.save(png)
    img.save(ico, sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
    print("wrote", png, "and", ico)


if __name__ == "__main__":
    main()
