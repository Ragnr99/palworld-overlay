"""The element type chart: a ring diagram of what beats what.

The whole chart is one 5-element loop plus a 4-link chain hanging off Fire,
which is why a ring reads better here than a 9x9 grid. Arrow = "beats" (1.5x).

Everything is drawn in the element colour with a black outline and no panel
behind it, so it stays legible over a busy game frame without blocking any of
it. Nothing may be drawn in the transparent key colour except on purpose - see
_dark, which carves its crescent out of a disc that way.

All geometry derives from the `scale` setting through Geo, so the size slider
re-lays the chart out rather than stretching a bitmap.
"""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path

import hotkeys

from .base import TRANSPARENT_KEY, Module, Toggle, outlined_text, placement

# Drop real element PNGs here as fire.png, water.png, ... and they replace the
# drawn glyphs. Transparent background, roughly 32-64px square.
ICON_DIR = Path(__file__).resolve().parent.parent / "icons"

ELEMENT_COLORS = {
    "Neutral": "#e8e4da",
    "Fire": "#ff6f2c",
    "Water": "#2fa6ff",
    "Electric": "#ffd21e",
    "Grass": "#46c85a",
    "Ice": "#6fe4ff",
    "Ground": "#c58a4e",
    "Dark": "#a95cff",
    "Dragon": "#2fd6b0",
}

RING = ["Fire", "Grass", "Ground", "Electric", "Water"]  # ...and Water -> Fire closes it
CHAIN = ["Fire", "Ice", "Dragon", "Dark", "Neutral"]     # Fire also beats Ice

#: Grey enough to sit behind the chart rather than compete with it, light enough
#: to still read against the game through the black halo.
HOTKEY_COLOR = "#9aa3ad"


class Geo:
    """Every measurement the chart needs, at one scale."""

    def __init__(self, scale: float):
        self.scale = scale
        self.r = 78 * scale             # pentagon radius
        self.glyph = 17 * scale         # half-size of a drawn element symbol
        self.outline = max(2, int(2 * scale))
        self.chain_gap_y = 60 * scale   # drop from the pentagon to the chain row
        self.chain_step_x = 68 * scale
        self.label_dy = 15 * scale      # label sits this far under its glyph
        self.pad_x = 40 * scale         # room for "ELECTRIC" to overhang
        self.pad_y = 14 * scale


# ---------------- layout ----------------

def _layout(g: Geo, sym_r: float, labels: bool):
    """{element: (x, y)}, the pentagon's centre, and the canvas size.

    All in final pixel coords.

    `sym_r` is the half-size of the largest symbol. Spacing scales off it so the
    real 48px wiki icons get the same breathing room the smaller drawn glyphs
    do, instead of colliding with each other and with the arrows.
    """
    spread = sym_r / g.glyph
    ring_r, step, gap = g.r * spread, g.chain_step_x * spread, g.chain_gap_y * spread

    pts = {}
    for i, name in enumerate(RING):
        a = math.radians(90 + i * 72)  # Fire lands at the bottom vertex
        pts[name] = (ring_r * math.cos(a), ring_r * math.sin(a))

    tail = CHAIN[1:]
    span = step * (len(tail) - 1)
    for j, name in enumerate(tail):
        pts[name] = (-span / 2 + j * step, ring_r + gap)

    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    label_room = (g.label_dy + 10 * g.scale) if labels else 0
    left = min(xs) - sym_r - g.pad_x
    top = min(ys) - sym_r - g.pad_y
    right = max(xs) + sym_r + g.pad_x
    bottom = max(ys) + sym_r + label_room + g.pad_y

    # The ring is built around the origin, so once everything shifts into
    # positive coords the origin lands on the pentagon's centre - the one big
    # empty patch in the whole drawing.
    pts = {name: (p[0] - left, p[1] - top) for name, p in pts.items()}
    return pts, (-left, -top), int(right - left), int(bottom - top)


# ---------------- element glyphs ----------------
#
# Vector stand-ins for Palworld's element icons, drawn in a -1..1 unit box and
# scaled by Geo.glyph.

def _poly(c, x, y, pts, color, g: Geo, smooth=False):
    coords = []
    for px, py in pts:
        coords += [x + px * g.glyph, y + py * g.glyph]
    c.create_polygon(coords, fill=color, outline="#000000",
                     width=g.outline, smooth=smooth, joinstyle="round")


def _stroke(c, x, y, segments, color, g: Geo, width=0.16):
    """Outlined line work (snowflake arms, leaf midrib): black underlay, colour on top."""
    w = max(2, width * g.glyph)
    for pass_color, pass_w in (("#000000", w + g.outline), (color, w)):
        for (x1, y1), (x2, y2) in segments:
            c.create_line(x + x1 * g.glyph, y + y1 * g.glyph,
                          x + x2 * g.glyph, y + y2 * g.glyph,
                          fill=pass_color, width=pass_w, capstyle="round")


def _fire(c, x, y, col, g):
    # points pushed past the unit box on purpose: smooth splines pull the
    # outline inward, so a literal -1..1 flame renders visibly smaller than the
    # hard-edged glyphs next to it
    _poly(c, x, y, [(0, -1.15), (0.66, -0.15), (0.72, 0.4), (0.36, 1.0), (0, 0.5),
                    (-0.36, 1.0), (-0.72, 0.4), (-0.66, -0.15)], col, g, smooth=True)


def _water(c, x, y, col, g):
    _poly(c, x, y, [(0, -1), (0.42, -0.15), (0.6, 0.35), (0.3, 0.9),
                    (-0.3, 0.9), (-0.6, 0.35), (-0.42, -0.15)], col, g, smooth=True)


def _electric(c, x, y, col, g):
    _poly(c, x, y, [(-0.1, -1), (0.62, -1), (0.14, -0.12), (0.6, -0.12),
                    (-0.3, 1), (-0.02, 0.08), (-0.5, 0.08)], col, g)


def _grass(c, x, y, col, g):
    _poly(c, x, y, [(0.72, -0.78), (0.6, 0.2), (-0.28, 0.82), (-0.72, 0.78),
                    (-0.5, -0.18), (0.2, -0.7)], col, g, smooth=True)
    _stroke(c, x, y, [((-0.62, 0.68), (0.55, -0.6))], col, g, width=0.11)


def _ice(c, x, y, col, g):
    segs = []
    for k in range(3):  # three arms crossing at the centre = six spokes
        dx, dy = math.cos(math.radians(k * 60)), math.sin(math.radians(k * 60))
        segs.append(((-dx, -dy), (dx, dy)))
    for k in range(6):  # a barb angled back down each spoke
        a = math.radians(k * 60)
        ex, ey = math.cos(a) * 0.62, math.sin(a) * 0.62
        for spread in (150, -150):
            b = a + math.radians(spread)
            segs.append(((ex, ey), (ex + math.cos(b) * 0.3, ey + math.sin(b) * 0.3)))
    _stroke(c, x, y, segs, col, g, width=0.15)


def _ground(c, x, y, col, g):
    _poly(c, x, y, [(-1, 0.75), (-0.42, -0.3), (-0.05, 0.2), (0.35, -0.85),
                    (1, 0.75)], col, g)


def _dark(c, x, y, col, g):
    """Crescent: a full disc with a second disc punched out in the transparent key."""
    c.create_oval(x - g.glyph, y - g.glyph, x + g.glyph, y + g.glyph,
                  fill=col, outline="#000000", width=g.outline)
    c.create_oval(x - g.glyph * 0.15, y - g.glyph * 1.05,
                  x + g.glyph * 1.75, y + g.glyph * 1.05,
                  fill=TRANSPARENT_KEY, outline=TRANSPARENT_KEY)


def _dragon(c, x, y, col, g):
    # head in profile, snout left and a swept horn top-right. Left hard-edged:
    # smoothing rounds the horn and snout off and it stops reading as a dragon.
    _poly(c, x, y, [(-1.0, 0.3), (-0.62, -0.02), (-0.22, -0.42), (0.12, -0.28),
                    (0.42, -1.0), (0.55, -0.22), (1.0, 0.08), (0.52, 0.6),
                    (-0.05, 0.82), (-0.6, 0.62)], col, g)
    r = g.glyph * 0.14
    c.create_oval(x - g.glyph * 0.3 - r, y + g.glyph * 0.05 - r,
                  x - g.glyph * 0.3 + r, y + g.glyph * 0.05 + r,
                  fill="#000000", outline="")


def _neutral(c, x, y, col, g):
    ring = (x - g.glyph * 0.92, y - g.glyph * 0.92, x + g.glyph * 0.92, y + g.glyph * 0.92)
    c.create_oval(*ring, fill="", outline="#000000",
                  width=g.outline + max(2, int(2.5 * g.scale)))
    c.create_oval(*ring, fill="", outline=col, width=max(2, int(2.5 * g.scale)))
    r = g.glyph * 0.3
    c.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="#000000", width=g.outline)


GLYPHS = {
    "Fire": _fire, "Water": _water, "Electric": _electric, "Grass": _grass,
    "Ice": _ice, "Ground": _ground, "Dark": _dark, "Dragon": _dragon,
    "Neutral": _neutral,
}

# ---------------- drawing ----------------

def _hits_a_symbol(box, centers, sym_r):
    """True if the rectangle `box` overlaps any symbol's circle.

    Exact rectangle-versus-circle: clamp the circle's centre into the box and
    measure what's left.
    """
    x0, y0, x1, y1 = box
    for px, py in centers:
        near_x = min(max(px, x0), x1)
        near_y = min(max(py, y0), y1)
        if math.hypot(px - near_x, py - near_y) < sym_r:
            return True
    return False


def _arrow(c, p, q, color, sym_r, g: Geo):
    """Arrow from node p to node q, trimmed at both ends so it clears the symbols."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    ax, ay = p[0] + ux * (sym_r + 5 * g.scale), p[1] + uy * (sym_r + 5 * g.scale)
    bx, by = q[0] - ux * (sym_r + 8 * g.scale), q[1] - uy * (sym_r + 8 * g.scale)
    shape = (11 * g.scale, 13 * g.scale, 4.5 * g.scale)
    # black underlay first, coloured arrow on top: same trick as the text
    c.create_line(ax, ay, bx, by, fill="#000000", width=max(3, 4.5 * g.scale),
                  arrow="last", arrowshape=shape, capstyle="round")
    c.create_line(ax, ay, bx, by, fill=color, width=max(1, 2 * g.scale),
                  arrow="last", arrowshape=shape, capstyle="round")


class TypeChart(Module):
    id = "typechart"
    name = "Type Chart"
    blurb = "Ring diagram of what beats what. An arrow means 1.5x damage."
    settings = placement(x=282, y=24, scale=0.75, opacity=0.92) + (
        Toggle("labels", "Element names", True,
               help="Off once you know the glyphs - it shrinks the chart a lot."),
        Toggle("hotkey", "Settings hotkey in the middle", True,
               help=f"Parks a small {hotkeys.PANEL_HOTKEY} reminder in the empty centre of "
                    f"the ring, so you never have to remember how to open this panel. "
                    f"Hides itself under about 0.45 size, where it would start "
                    f"overlapping the glyphs."),
    )

    def __init__(self):
        # Tk silently drops images that lose their last reference, and reloading
        # them on every redraw would re-read the PNGs on every drag of the size
        # slider. Keyed by scale, which is the only thing that changes them.
        self._icons: dict[float, tuple[dict, float]] = {}

    def _load_icons(self, g: Geo):
        """Real element PNGs from icons/, if the folder has any.

        Returns (images, half_size). Tk only downscales by whole factors, so an
        icon lands on the nearest integer division of the drawn-glyph size
        rather than an exact match; the layout then spaces everything off
        whatever size it got.
        """
        if g.scale in self._icons:
            return self._icons[g.scale]

        icons, half = {}, 0.0
        if ICON_DIR.is_dir():
            for name in ELEMENT_COLORS:
                path = ICON_DIR / f"{name.lower()}.png"
                if not path.is_file():
                    continue
                try:
                    img = tk.PhotoImage(file=str(path))
                except tk.TclError:
                    continue  # not a PNG Tk can read; fall back to the drawn glyph
                factor = max(1, round(img.width() / (g.glyph * 2)))
                if factor > 1:
                    img = img.subsample(factor)
                icons[name] = img
                half = max(half, img.width() / 2, img.height() / 2)

        self._icons[g.scale] = (icons, half)
        return icons, half

    def draw(self, canvas, cfg):
        g = Geo(cfg["scale"])
        labels = cfg["labels"]
        icons, icon_half = self._load_icons(g)
        sym_r = max(g.glyph, icon_half)
        pts, center, width, height = _layout(g, sym_r, labels)

        # arrows first so the symbols sit on top of where they get trimmed
        for i, name in enumerate(RING):
            _arrow(canvas, pts[name], pts[RING[(i + 1) % len(RING)]],
                   ELEMENT_COLORS[name], sym_r, g)
        for name, nxt in zip(CHAIN, CHAIN[1:]):
            _arrow(canvas, pts[name], pts[nxt], ELEMENT_COLORS[name], sym_r, g)

        if cfg["hotkey"]:
            # A point smaller and a good deal dimmer than the element names, so
            # it reads as a footnote rather than as part of the chart.
            #
            # The ring shrinks with scale but the font bottoms out at 6pt, so
            # under about 0.45 the reminder starts running into the glyphs.
            # Measure what was actually drawn and take it back out if it does -
            # at that size it was too small to read anyway, and covering the
            # chart to say how to open the settings defeats the point.
            ids = outlined_text(canvas, center[0], center[1],
                                hotkeys.PANEL_HOTKEY.upper(), HOTKEY_COLOR,
                                7.5 * g.scale, floor=6)
            if _hits_a_symbol(canvas.bbox(*ids), pts.values(), sym_r):
                for item in ids:
                    canvas.delete(item)

        for name, color in ELEMENT_COLORS.items():
            x, y = pts[name]
            if name in icons:
                canvas.create_image(x, y, image=icons[name])
            else:
                GLYPHS[name](canvas, x, y, color, g)
            if labels:
                outlined_text(canvas, x, y + sym_r + g.label_dy, name.upper(), color, 8 * g.scale)

        return width, height
