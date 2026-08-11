"""A north-up minimap: where you are, without opening the map.

The player is always dead centre and everything else scrolls under them, which
is what makes this cheap enough to run at 10Hz on the UI thread - draw() builds
the frame once and update() only moves things that moved.

Nothing is drawn behind the map unless you supply a map image, so by default
this is a grid, a trail and a dot floating over the game rather than a panel
covering a corner of it. Same principle as the type chart.

Where the coordinates come from is position.py's problem, not this file's. This
module only ever sees in-game map coordinates.
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

import markers
import position

from .base import TRANSPARENT_KEY, Choice, Module, Slider, Text, Toggle, outlined_text, placement

#: The minimap is this many pixels square at scale 1.0.
BASE_SIZE = 200

BORDER_COLOR = "#c9d1d9"
GRID_COLOR = "#7d8794"
PLAYER_COLOR = "#ffffff"
PLAYER_RING = "#2fa6ff"
TRAIL_COLOR = (0x2f, 0xa6, 0xff)
TEXT_COLOR = "#e8e4da"
STALE_COLOR = "#ff8f5a"
#: Journal notes: paper on the map, dimmer when pinned to the edge because it
#: is a direction rather than a place.
NOTE_COLOR = "#f6d98a"
NOTE_EDGE_COLOR = "#b39a55"
NOTE_OUTLINE = "#241d0e"

#: Grid spacings to choose from, in map units. A 1/2.5/5 progression, so the
#: labels stay round numbers at every view range.
GRID_STEPS = (10, 25, 50, 100, 250, 500, 1000, 2500)
#: Aim for at most this many grid lines per axis.
GRID_TARGET = 6


def _nice_step(span: float) -> int:
    """The largest round grid spacing that still puts a few lines on screen."""
    for step in GRID_STEPS:
        if span / step <= GRID_TARGET:
            return step
    return GRID_STEPS[-1]


def _fade(t: float) -> str:
    """Trail colour at position t along it, 0 = oldest. Fades toward black.

    Tk has no per-item alpha, so an old breadcrumb is dimmed rather than made
    transparent. Against the dark game world that reads the same way.
    """
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * (0.15 + 0.85 * t))))
                                   for c in TRAIL_COLOR)


class Minimap(Module):
    id = "minimap"
    name = "Minimap"
    blurb = ("Live position and a scrolling minimap, without opening the in-game map. "
             "Needs a dedicated server with its REST API on - see the help under "
             "'Position from'.")
    live = True
    settings = placement(x=24, y=24, scale=1.0, opacity=0.85) + (
        Choice("source", "Position from", position.SOURCE_REST,
               options=position.SOURCES,
               help="The server option needs a Palworld dedicated server started with "
                    "RESTAPIEnabled=True in PalWorldSettings.ini. A single-player world "
                    "or a co-op game hosted from the client does not publish coordinates, "
                    "so there is nothing to read and the map will sit on 'no server'. "
                    "Demo walks a fake player around so you can place and size the map "
                    "with Palworld closed."),
        Text("host", "Server address", "127.0.0.1",
             help="Where the server's REST API is. Leave as-is if it runs on this PC."),
        Slider("port", "REST port", 8212, lo=1, hi=65535, step=1,
               help="RESTAPIPort in PalWorldSettings.ini."),
        Text("password", "Admin password", "", secret=True,
             help="AdminPassword from PalWorldSettings.ini. Stored as plain text in "
                  "settings.json, the same as the server's own config file."),
        Text("player", "Player name", "",
             help="Which player to follow on a busy server. Blank follows whoever the "
                  "server lists first, which is what you want when it's just you."),
        Slider("range", "View range", 250, lo=40, hi=1500, step=10, unit="u",
               help="How far from you the edge of the map is, in the coordinates the "
                    "game shows. Smaller is more zoomed in."),
        Toggle("grid", "Grid lines", True),
        Toggle("coords", "Coordinate readout", True,
               help="Your position along the bottom edge, in the same numbers the "
                    "in-game map shows."),
        Slider("trail", "Trail length", 40, lo=0, hi=240, step=5,
               help="How many past positions to leave behind you. 0 turns the trail off. "
                    "At half a second a reading, 40 is about the last twenty seconds."),
        Toggle("notes", "Journal notes", True,
               help="Marks the 55 readable journal notes on Palpagos. Their positions "
                    "ship with the overlay, so this needs nothing from the game."),
        Slider("notes_range", "Notes within", 400, lo=50, hi=3000, step=10, unit="u",
               help="How far away a note still counts. Ones inside the map sit where "
                    "they are; ones further out but still inside this range are pinned "
                    "to the edge pointing at them, so the map tells you which way to "
                    "walk instead of only what you are standing on. The nearest one is "
                    "named under the map."),
        Toggle("notes_label", "Name the nearest note", True),
        Text("map_image", "Map image file", "",
             help="Optional PNG to scroll under the marker - drop one next to the overlay "
                  "and put its filename here. Without it you get the grid alone, which "
                  "still tells you where you are and covers none of the game."),
        Slider("image_span", "Map image covers", 800, lo=100, hi=3000, step=10, unit="u",
               help="Half the width of the area your image covers, in map coordinates, "
                    "measured from 0,0 at its centre. Only matters with an image set."),
        Toggle("image_flip", "Flip image north/south", False,
               help="If your map image comes out upside down, turn this on."),
        Slider("world_origin", "Coordinate origin E/W", position.MAP_ORIGIN_X,
               lo=-400000, hi=400000, step=1,
               help="Advanced. Converts the server's raw world coordinates into the "
                    "numbers the game shows you, and places the note markers with them. "
                    "The two axes have different origins - that is not a typo. Only "
                    "touch these three if the readout disagrees with the in-game map."),
        Slider("world_origin_y", "Coordinate origin N/S", position.MAP_ORIGIN_Y,
               lo=-400000, hi=400000, step=1, help="Advanced. See above."),
        Slider("world_scale", "Coordinate scale", position.MAP_SCALE,
               lo=50, hi=2000, step=0.01, help="Advanced. See above."),
    )

    def __init__(self):
        self._tracker = position.Tracker()
        self._trail: list[tuple[float, float]] = []
        #: canvas item ids, rebuilt by every draw()
        self._grid: list[int] = []
        self._dots: list[int] = []
        self._notes: list[int] = []
        self._readout: list[int] = []
        self._status: list[int] = []
        self._note_label: list[int] = []
        self._label_font = None
        self._image_item: int | None = None
        #: (path, mtime) -> source PhotoImage, so the file is read once
        self._source_image: tuple[tuple, tk.PhotoImage] | None = None
        #: the scrolled crop shown on screen, reused frame to frame
        self._view_image: tk.PhotoImage | None = None
        self._units_per_px = 1.0
        self._box = BASE_SIZE

    # ---------------- geometry ----------------

    def _size(self, cfg) -> int:
        return max(60, int(BASE_SIZE * cfg["scale"]))

    # ---------------- map image ----------------

    def _load_image(self, cfg, canvas) -> tk.PhotoImage | None:
        """The user's map PNG, cached until the file or its mtime changes."""
        name = str(cfg.get("map_image", "")).strip()
        if not name:
            self._source_image = None
            return None

        path = Path(name)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError:
            self._source_image = None
            return None

        if self._source_image and self._source_image[0] == key:
            return self._source_image[1]
        try:
            image = tk.PhotoImage(master=canvas, file=str(path))
        except tk.TclError:
            self._source_image = None  # not a PNG Tk can read
            return None
        self._source_image = (key, image)
        return image

    def _view_scale(self, source: tk.PhotoImage | None, cfg) -> tuple[float, int, int, int]:
        """(map units per screen pixel, source pixels to crop, zoom, subsample).

        Tk can only scale an image by whole factors, so with an image the zoom
        is quantised and the real units-per-pixel is derived from the factor
        actually used rather than the one asked for. Grid and trail are placed
        with that same number, so they stay registered with the image even when
        the requested range wasn't exactly achievable.
        """
        box = self._box
        exact = (2 * float(cfg["range"])) / box
        if source is None:
            return exact, 0, 1, 1

        span = max(1.0, float(cfg["image_span"]))
        px_per_unit = source.width() / (2 * span)
        wanted = max(1.0, 2 * float(cfg["range"]) * px_per_unit)  # source px across
        if wanted >= box:
            factor = max(1, round(wanted / box))
            crop, zoom, subsample = box * factor, 1, factor
        else:
            factor = max(1, round(box / wanted))
            crop, zoom, subsample = max(1, box // factor), factor, 1
        return (crop / px_per_unit) / box, crop, zoom, subsample

    def _scroll_image(self, source: tk.PhotoImage, cfg, x: float, y: float) -> None:
        """Copy the square of `source` around (x, y) into the on-screen crop."""
        span = max(1.0, float(cfg["image_span"]))
        px_per_unit = source.width() / (2 * span)
        _, crop, zoom, subsample = self._view_scale(source, cfg)

        # player position in source pixels, with north at the top
        cx = (x + span) * px_per_unit
        cy = (span - y) * px_per_unit if cfg["image_flip"] else (y + span) * px_per_unit
        x0, y0 = int(round(cx - crop / 2)), int(round(cy - crop / 2))

        # Tk clamps a -from rectangle to the image, which would silently slide
        # the content sideways at the edges of the world. Clamp it here instead
        # and shift the destination by as much as was trimmed, so the map stops
        # at the edge rather than following you.
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1 = min(source.width(), x0 + crop)
        cy1 = min(source.height(), y0 + crop)

        view = self._view_image
        if view is None:
            return
        view.blank()
        if cx1 <= cx0 or cy1 <= cy0:
            return  # entirely off the image
        view.tk.call(view, "copy", source,
                     "-from", cx0, cy0, cx1, cy1,
                     "-to", ((cx0 - x0) * zoom) // subsample, ((cy0 - y0) * zoom) // subsample,
                     "-zoom", zoom, zoom, "-subsample", subsample, subsample)

    # ---------------- drawing ----------------

    def draw(self, canvas, cfg):
        box = self._box = self._size(cfg)
        scale = cfg["scale"]
        self._grid.clear()
        self._dots.clear()
        self._notes.clear()
        self._readout = []
        self._status = []
        self._note_label = []
        self._label_font = None
        self._image_item = None

        source = self._load_image(cfg, canvas)
        self._units_per_px = self._view_scale(source, cfg)[0]
        if source is not None:
            self._view_image = tk.PhotoImage(master=canvas, width=box, height=box)
            self._image_item = canvas.create_image(0, 0, anchor="nw", image=self._view_image)
        else:
            self._view_image = None

        # Grid lines are at fixed world coordinates, so they scroll with the
        # map. Enough of them are made here to cover the box at any offset and
        # update() just slides them; creating and deleting lines every frame
        # would be the expensive way to do the same thing.
        if cfg["grid"]:
            step_px = _nice_step(box * self._units_per_px) / self._units_per_px
            count = int(box / max(1.0, step_px)) + 2
            width = max(1, int(scale))
            for _ in range(count * 2):
                self._grid.append(
                    canvas.create_line(0, 0, 0, 0, fill=GRID_COLOR, width=width, state="hidden"))

        trail = int(cfg["trail"])
        for i in range(trail):
            t = (i + 1) / trail
            self._dots.append(canvas.create_oval(0, 0, 0, 0, outline="",
                                                 fill=_fade(t), state="hidden"))

        # One polygon per shipped note, made here and moved by update() for the
        # same reason as the grid. Created before the frame and the player so
        # both stay on top of them.
        if cfg["notes"]:
            for _ in markers.notes(**position.calibration(cfg)):
                self._notes.append(
                    canvas.create_polygon(0, 0, 0, 0, 0, 0, 0, 0, fill=NOTE_COLOR,
                                          outline=NOTE_OUTLINE, width=max(1, int(scale)),
                                          state="hidden"))

        self._frame(canvas, box, scale)
        self._marker(canvas, box, scale)

        # Text sizes bottom out at outlined_text's floor, so below about 0.6
        # scale the labels stop shrinking with the box. Hold them far enough off
        # each edge for the floor size rather than the requested one, or they
        # get clipped by the canvas and cut in half by the border.
        if cfg["coords"]:
            self._readout = outlined_text(canvas, box / 2, box - max(10, 11 * scale),
                                          "", TEXT_COLOR, 9 * scale)
        self._status = outlined_text(canvas, box / 2, box / 2 + max(20, 22 * scale),
                                     "", STALE_COLOR, 8.5 * scale)

        # The nearest note's name goes in a strip *under* the map rather than
        # on it: names run to nearly thirty characters, and anything that long
        # inside the box is either clipped by the canvas or sitting on top of
        # the ground you are trying to read.
        if cfg["notes"] and cfg["notes_label"]:
            strip = max(13, int(14 * scale))
            # mirrors what outlined_text will build, so _fit measures the font
            # that actually gets drawn rather than one that looks like it
            self._label_font = tkfont.Font(root=canvas, family="Segoe UI",
                                           size=max(7, int(8 * scale)), weight="bold")
            self._note_label = outlined_text(canvas, box / 2, box + strip / 2,
                                             "", NOTE_COLOR, 8 * scale)
            return box, box + strip
        return box, box

    def _frame(self, canvas, box, scale) -> None:
        """Border and the north tick, so the thing reads as a map and not a smudge."""
        inset = max(1, int(scale))
        canvas.create_rectangle(inset, inset, box - inset, box - inset,
                                outline="#000000", width=max(3, int(3.5 * scale)))
        canvas.create_rectangle(inset, inset, box - inset, box - inset,
                                outline=BORDER_COLOR, width=max(1, int(1.5 * scale)))
        outlined_text(canvas, box / 2, max(9, 10 * scale), "N", BORDER_COLOR, 8.5 * scale)

    def _marker(self, canvas, box, scale) -> None:
        """The player, pinned to the centre.

        A ringed dot rather than an arrow: the server reports where you are and
        not which way you are facing, and an arrow would be claiming a heading
        that nothing here actually knows.
        """
        cx = cy = box / 2
        r = max(3.0, 3.6 * scale)
        canvas.create_oval(cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2,
                           outline="#000000", width=max(2, int(2 * scale)))
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           fill=PLAYER_COLOR, outline=PLAYER_RING, width=max(1, int(1.5 * scale)))

    # ---------------- live update ----------------

    def update(self, canvas, cfg) -> None:
        self._tracker.configure(cfg)
        fix = self._tracker.latest()

        if fix is None:
            self._hide_all(canvas)
            self._say(canvas, self._status, self._tracker.status())
            self._say(canvas, self._readout, "")
            self._say(canvas, self._note_label, "")
            return

        if fix.stale():
            self._say(canvas, self._status, f"{self._tracker.status()} · {fix.age():.0f}s ago")
        else:
            self._say(canvas, self._status, "")

        self._push_trail(fix)
        if self._image_item is not None and self._source_image is not None:
            self._scroll_image(self._source_image[1], cfg, fix.x, fix.y)
        self._place_grid(canvas, cfg, fix)
        self._place_trail(canvas, cfg, fix)
        self._place_notes(canvas, cfg, fix)

        self._say(canvas, self._readout, f"{fix.x:.0f}, {fix.y:.0f}")

    def _say(self, canvas, items, text) -> None:
        """Set every copy of one piece of text - the halo as well as the face.

        outlined_text returns eight black copies and the coloured one; writing
        to the last alone leaves the halo blank, which is exactly the case
        where the text is over a bright sky and needs it.
        """
        for item in items:
            canvas.itemconfigure(item, text=text)

    def _hide_all(self, canvas) -> None:
        for item in self._grid + self._dots + self._notes:
            canvas.itemconfigure(item, state="hidden")

    #: history kept regardless of the current trail setting, so turning the
    #: trail up shows where you have been rather than starting from empty
    TRAIL_HISTORY = 240

    def _push_trail(self, fix) -> None:
        # update() runs faster than positions arrive, so the same fix comes
        # round several times; only a real move earns a breadcrumb.
        if not self._trail or math.dist(self._trail[-1], (fix.x, fix.y)) > 0.5:
            self._trail.append((fix.x, fix.y))
        if len(self._trail) > self.TRAIL_HISTORY:
            del self._trail[:-self.TRAIL_HISTORY]

    def _to_screen(self, fix, x, y) -> tuple[float, float]:
        """Map coordinates -> canvas pixels, with the player at the centre."""
        half = self._box / 2
        return (half + (x - fix.x) / self._units_per_px,
                half + (y - fix.y) / self._units_per_px)

    def _place_grid(self, canvas, cfg, fix) -> None:
        if not self._grid:
            return
        box = self._box
        half_units = (box / 2) * self._units_per_px
        step = _nice_step(2 * half_units)
        pairs = len(self._grid) // 2

        for axis in (0, 1):
            # the last gridline at or before the left/top edge; the lines drawn
            # are the `pairs` that follow it, which is enough to span the box
            low = (fix.x if axis == 0 else fix.y) - half_units
            first = math.floor(low / step) * step
            for i in range(pairs):
                item = self._grid[axis * pairs + i]
                value = first + (i + 1) * step
                if axis == 0:
                    px, _ = self._to_screen(fix, value, fix.y)
                    coords = (px, 0, px, box)
                else:
                    _, py = self._to_screen(fix, fix.x, value)
                    coords = (0, py, box, py)
                edge = coords[0] if axis == 0 else coords[1]
                if 0 <= edge <= box:
                    canvas.coords(item, *coords)
                    canvas.itemconfigure(item, state="normal")
                else:
                    canvas.itemconfigure(item, state="hidden")

    def _place_notes(self, canvas, cfg, fix) -> None:
        """Journal notes: where they are, or which way they are.

        A note further away than the map can show is pinned to the edge in the
        direction of it rather than dropped. On a 250-unit map that is nearly
        all of them, and a marker layer that only lights up once you are already
        standing on the thing would be decoration.
        """
        if not self._notes:
            return

        box = self._box
        half = box / 2
        size = max(2.5, 3.4 * cfg["scale"])
        # keep a pinned marker clear of the border, which is drawn over it
        margin = max(2.0, 3.0 * cfg["scale"]) + size

        found = markers.near(fix.x, fix.y, float(cfg["notes_range"]),
                             limit=len(self._notes), **position.calibration(cfg))

        for item, (distance, note) in zip(self._notes, found):
            px, py = self._to_screen(fix, note.x, note.y)
            dx, dy = px - half, py - half
            reach = max(abs(dx), abs(dy))
            pinned = reach > half - margin
            if pinned:
                # slide it back along the same bearing until it sits on the edge
                scale_back = (half - margin) / reach if reach else 0.0
                px, py = half + dx * scale_back, half + dy * scale_back
            edge = size * (0.8 if pinned else 1.0)
            canvas.coords(item, px, py - edge, px + edge, py, px, py + edge, px - edge, py)
            canvas.itemconfigure(item, state="normal",
                                 fill=NOTE_EDGE_COLOR if pinned else NOTE_COLOR)

        for item in self._notes[len(found):]:
            canvas.itemconfigure(item, state="hidden")

        if self._note_label:
            if found:
                distance, note = found[0]
                self._say(canvas, self._note_label,
                          self._fit(f"{note.name} · {distance:.0f}u", box))
            else:
                self._say(canvas, self._note_label, "")

    def _fit(self, text: str, width: float) -> str:
        """Trim `text` to the width of the map, since that is all there is.

        Measured rather than counted: the names run from 'Auri's Diary - 1' to
        'Castaway's Journal - Day 12-1' and the font is proportional, so a
        character budget would either clip the long ones or waste the strip.
        """
        font = self._label_font
        if font is None:
            return text
        limit = max(20.0, width - 6)
        if font.measure(text) <= limit:
            return text
        ellipsis = "…"
        trimmed = text
        while trimmed and font.measure(trimmed + ellipsis) > limit:
            trimmed = trimmed[:-1]
        return (trimmed.rstrip() + ellipsis) if trimmed else ""

    def _place_trail(self, canvas, cfg, fix) -> None:
        if not self._dots:
            return
        recent = self._trail[-len(self._dots):]
        radius = max(1.0, 1.6 * cfg["scale"])
        # newest dots line up with the brightest colours, which were assigned at
        # the end of the pool in draw()
        offset = len(self._dots) - len(recent)
        for i, item in enumerate(self._dots):
            if i < offset:
                canvas.itemconfigure(item, state="hidden")
                continue
            x, y = recent[i - offset]
            px, py = self._to_screen(fix, x, y)
            if 0 <= px <= self._box and 0 <= py <= self._box:
                canvas.coords(item, px - radius, py - radius, px + radius, py + radius)
                canvas.itemconfigure(item, state="normal")
            else:
                canvas.itemconfigure(item, state="hidden")
