"""Palworld type-chart overlay.

A click-through, always-on-top diagram of the element chart pinned near the top
of the screen. No window frame, no background panel - just element glyphs and
arrows floating over whatever is behind them. The mouse passes straight through:
you can never click it, drag it, focus it, or alt-tab to it.

    Ctrl+Alt+P          show / hide
    Ctrl+Alt+Shift+P    quit

Stdlib only (tkinter + ctypes), no pip installs. Palworld must run in
*borderless windowed* - nothing can draw over exclusive fullscreen.

    py -3.10 overlay.py
Or double-click "Palworld Overlay.bat".
"""

import ctypes
import math
import threading
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

import gamestate

# ---------------- settings ----------------

POS = (282, 24)         # overlay's top-left corner on screen, in pixels.
                        # Tucked just right of the party EXP bars, which end
                        # around x=274 on a 1920x1080 client area.
OFFSET_WIDTHS = 0       # extra shift right, in multiples of its own width
SCALE = 0.75            # bump to 1.25 / 1.5 on a 1440p or 4K display
OPACITY = 0.92          # 1.0 = solid, lower = more see-through
START_HIDDEN = False    # True to launch hidden and wait for the hotkey
HINT_SECONDS = 6        # how long the hotkey reminder shows on launch

# Show the chart only during actual gameplay: hidden while any Palworld UI is
# open, and while the game isn't the focused window. Set False to have it always
# up (useful on the desktop, where there's no game to read the state from).
AUTO_HIDE = True
GAME_EXE = "palworld"   # matched against the focused window's executable path

# Quit once Palworld's process is gone, so the overlay never outlives the game.
# Only arms after the game has actually been seen, so launching this by hand
# with Palworld closed leaves it running instead of exiting instantly.
EXIT_WITH_GAME = True
GAME_CHECK_EVERY_MS = 2000

TICK_MS = 250           # toggle responsiveness
TOPMOST_EVERY_MS = 2000  # re-assert always-on-top this often (games steal Z-order)

# This exact color is punched out of the window and becomes fully transparent.
# Nothing drawn may use it - which also makes it handy for carving shapes (see Dark).
TRANSPARENT_KEY = "#010203"

# Drop real element PNGs here as fire.png, water.png, ... and they replace the
# drawn glyphs. Transparent background, roughly 32-64px square.
ICON_DIR = Path(__file__).parent / "icons"

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

# The whole chart is one 5-element loop plus a 4-link chain hanging off Fire,
# which is why a ring reads better here than a 9x9 grid. Arrow = "beats" (1.5x).
RING = ["Fire", "Grass", "Ground", "Electric", "Water"]  # ...and Water -> Fire closes it
CHAIN = ["Fire", "Ice", "Dragon", "Dark", "Neutral"]     # Fire also beats Ice

# ---------------- geometry ----------------

R = 78 * SCALE            # pentagon radius
NODE = 13 * SCALE         # clearance radius arrows stop short of
GLYPH = 17 * SCALE        # half-size of an element symbol
OUTLINE = max(2, int(2 * SCALE))
CHAIN_GAP_Y = 60 * SCALE  # drop from the pentagon down to the chain row
CHAIN_STEP_X = 68 * SCALE
LABEL_DY = 15 * SCALE     # label sits this far under its glyph
PAD_X = 40 * SCALE        # room for the widest label ("ELECTRIC") to overhang
PAD_Y = 14 * SCALE
HINT_BAND = 20 * SCALE    # reserved strip at the bottom for the launch hint


def _layout(sym_r):
    """Return {element: (x, y)} plus the canvas size, all in final pixel coords.

    `sym_r` is the half-size of the largest symbol. Spacing scales off it so the
    real 48px wiki icons get the same breathing room the smaller drawn glyphs
    do, instead of colliding with each other and with the arrows.
    """
    spread = sym_r / GLYPH
    ring_r, step, gap = R * spread, CHAIN_STEP_X * spread, CHAIN_GAP_Y * spread

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
    left = min(xs) - sym_r - PAD_X
    top = min(ys) - sym_r - PAD_Y
    right = max(xs) + sym_r + PAD_X
    bottom = max(ys) + sym_r + LABEL_DY + 10 * SCALE + PAD_Y

    pts = {name: (p[0] - left, p[1] - top) for name, p in pts.items()}
    return pts, int(right - left), int(bottom - top + HINT_BAND)


# ---------------- element glyphs ----------------
#
# Vector stand-ins for Palworld's element icons, drawn in a -1..1 unit box and
# scaled by GLYPH. Each is filled in the element color with a black outline, the
# same legibility trick the labels and arrows use - no disc behind them, so they
# stay minimal over a busy game frame.

def _poly(canvas, x, y, pts, color, smooth=False):
    coords = []
    for px, py in pts:
        coords += [x + px * GLYPH, y + py * GLYPH]
    canvas.create_polygon(coords, fill=color, outline="#000000",
                          width=OUTLINE, smooth=smooth, joinstyle="round")


def _stroke(canvas, x, y, segments, color, width=0.16):
    """Outlined line work (snowflake arms, leaf midrib): black underlay, color on top."""
    w = max(2, width * GLYPH)
    for pass_color, pass_w in (("#000000", w + OUTLINE), (color, w)):
        for (x1, y1), (x2, y2) in segments:
            canvas.create_line(x + x1 * GLYPH, y + y1 * GLYPH,
                               x + x2 * GLYPH, y + y2 * GLYPH,
                               fill=pass_color, width=pass_w, capstyle="round")


def _fire(c, x, y, col):
    # points pushed past the unit box on purpose: smooth splines pull the
    # outline inward, so a literal -1..1 flame renders visibly smaller than the
    # hard-edged glyphs next to it
    _poly(c, x, y, [(0, -1.15), (0.66, -0.15), (0.72, 0.4), (0.36, 1.0), (0, 0.5),
                    (-0.36, 1.0), (-0.72, 0.4), (-0.66, -0.15)], col, smooth=True)


def _water(c, x, y, col):
    _poly(c, x, y, [(0, -1), (0.42, -0.15), (0.6, 0.35), (0.3, 0.9),
                    (-0.3, 0.9), (-0.6, 0.35), (-0.42, -0.15)], col, smooth=True)


def _electric(c, x, y, col):
    _poly(c, x, y, [(-0.1, -1), (0.62, -1), (0.14, -0.12), (0.6, -0.12),
                    (-0.3, 1), (-0.02, 0.08), (-0.5, 0.08)], col)


def _grass(c, x, y, col):
    _poly(c, x, y, [(0.72, -0.78), (0.6, 0.2), (-0.28, 0.82), (-0.72, 0.78),
                    (-0.5, -0.18), (0.2, -0.7)], col, smooth=True)
    _stroke(c, x, y, [((-0.62, 0.68), (0.55, -0.6))], col, width=0.11)


def _ice(c, x, y, col):
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
    _stroke(c, x, y, segs, col, width=0.15)


def _ground(c, x, y, col):
    _poly(c, x, y, [(-1, 0.75), (-0.42, -0.3), (-0.05, 0.2), (0.35, -0.85),
                    (1, 0.75)], col)


def _dark(c, x, y, col):
    """Crescent: a full disc with a second disc punched out in the transparent key."""
    c.create_oval(x - GLYPH, y - GLYPH, x + GLYPH, y + GLYPH,
                  fill=col, outline="#000000", width=OUTLINE)
    c.create_oval(x - GLYPH * 0.15, y - GLYPH * 1.05,
                  x + GLYPH * 1.75, y + GLYPH * 1.05,
                  fill=TRANSPARENT_KEY, outline=TRANSPARENT_KEY)


def _dragon(c, x, y, col):
    # head in profile, snout left and a swept horn top-right. Left hard-edged:
    # smoothing rounds the horn and snout off and it stops reading as a dragon.
    _poly(c, x, y, [(-1.0, 0.3), (-0.62, -0.02), (-0.22, -0.42), (0.12, -0.28),
                    (0.42, -1.0), (0.55, -0.22), (1.0, 0.08), (0.52, 0.6),
                    (-0.05, 0.82), (-0.6, 0.62)], col)
    r = GLYPH * 0.14
    c.create_oval(x - GLYPH * 0.3 - r, y + GLYPH * 0.05 - r,
                  x - GLYPH * 0.3 + r, y + GLYPH * 0.05 + r,
                  fill="#000000", outline="")


def _neutral(c, x, y, col):
    c.create_oval(x - GLYPH * 0.92, y - GLYPH * 0.92, x + GLYPH * 0.92, y + GLYPH * 0.92,
                  fill="", outline="#000000", width=OUTLINE + max(2, int(2.5 * SCALE)))
    c.create_oval(x - GLYPH * 0.92, y - GLYPH * 0.92, x + GLYPH * 0.92, y + GLYPH * 0.92,
                  fill="", outline=col, width=max(2, int(2.5 * SCALE)))
    r = GLYPH * 0.3
    c.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="#000000", width=OUTLINE)


GLYPHS = {
    "Fire": _fire, "Water": _water, "Electric": _electric, "Grass": _grass,
    "Ice": _ice, "Ground": _ground, "Dark": _dark, "Dragon": _dragon,
    "Neutral": _neutral,
}

# ---------------- drawing ----------------

_OFFSETS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))


def _text(canvas, x, y, text, fill, size):
    """Text with a black outline so it stays legible over any game background."""
    font = ("Segoe UI", max(7, int(size)), "bold")
    ids = [canvas.create_text(x + dx, y + dy, text=text, fill="#000000", font=font)
           for dx, dy in _OFFSETS]
    ids.append(canvas.create_text(x, y, text=text, fill=fill, font=font))
    return ids


def _arrow(canvas, p, q, color, sym_r):
    """Arrow from node p to node q, trimmed at both ends so it clears the symbols."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    ax, ay = p[0] + ux * (sym_r + 5 * SCALE), p[1] + uy * (sym_r + 5 * SCALE)
    bx, by = q[0] - ux * (sym_r + 8 * SCALE), q[1] - uy * (sym_r + 8 * SCALE)
    shape = (11 * SCALE, 13 * SCALE, 4.5 * SCALE)
    # black underlay first, colored arrow on top: same legibility trick as the text
    canvas.create_line(ax, ay, bx, by, fill="#000000", width=max(3, 4.5 * SCALE),
                       arrow="last", arrowshape=shape, capstyle="round")
    canvas.create_line(ax, ay, bx, by, fill=color, width=max(1, 2 * SCALE),
                       arrow="last", arrowshape=shape, capstyle="round")


def draw_chart(canvas, pts, icons, sym_r):
    # arrows first so the symbols sit on top of where they get trimmed
    for i, name in enumerate(RING):
        nxt = RING[(i + 1) % len(RING)]
        _arrow(canvas, pts[name], pts[nxt], ELEMENT_COLORS[name], sym_r)
    for name, nxt in zip(CHAIN, CHAIN[1:]):
        _arrow(canvas, pts[name], pts[nxt], ELEMENT_COLORS[name], sym_r)

    for name, color in ELEMENT_COLORS.items():
        x, y = pts[name]
        if name in icons:
            canvas.create_image(x, y, image=icons[name])
        else:
            GLYPHS[name](canvas, x, y, color)
        _text(canvas, x, y + sym_r + LABEL_DY, name.upper(), color, 8 * SCALE)


def load_icons():
    """Real element PNGs from icons/, if the folder has any. Needs a live Tk root.

    Returns (images, half_size). Tk only downscales by whole factors, so an icon
    lands on the nearest integer division of the drawn-glyph size rather than an
    exact match; the layout then spaces everything off whatever size it got.
    """
    icons, half = {}, 0
    if not ICON_DIR.is_dir():
        return icons, half
    for name in ELEMENT_COLORS:
        path = ICON_DIR / f"{name.lower()}.png"
        if not path.is_file():
            continue
        try:
            img = tk.PhotoImage(file=str(path))
        except tk.TclError:
            continue  # not a PNG Tk can read; fall back to the drawn glyph
        factor = max(1, round(img.width() / (GLYPH * 2)))
        if factor > 1:
            img = img.subsample(factor)
        icons[name] = img
        half = max(half, img.width() / 2, img.height() / 2)
    return icons, half


# ---------------- win32 plumbing ----------------

user32 = ctypes.WinDLL("user32", use_last_error=True)

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD = 0x40000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020   # the bit that makes clicks pass through
WS_EX_TOOLWINDOW = 0x00000080    # keep it out of alt-tab and the taskbar
WS_EX_NOACTIVATE = 0x08000000    # never steal focus from the game
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
HWND_TOPMOST = wintypes.HWND(-1)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
VK_P = 0x50
WM_HOTKEY = 0x0312
ID_TOGGLE, ID_QUIT = 1, 2

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wintypes.BOOL


def _hotkey_loop(on_toggle, on_quit):
    """Own message loop on its own thread - RegisterHotKey delivers WM_HOTKEY here.

    Event-driven, so it costs nothing while idle (no key polling).
    """
    if not user32.RegisterHotKey(None, ID_TOGGLE, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_P):
        return  # something else owns Ctrl+Alt+P; the overlay still runs, just not toggleable
    user32.RegisterHotKey(None, ID_QUIT,
                          MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK_P)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            (on_quit if msg.wParam == ID_QUIT else on_toggle)()


# ---------------- app ----------------

class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # stay hidden until the styles are on, so nothing flashes

        # icons need a live Tk root, and the layout needs to know how big they
        # came out, so both happen before any geometry is decided.
        # kept on self: Tk silently drops images that lose their last reference
        self.icons, icon_half = load_icons()
        self.sym_r = max(GLYPH, icon_half)
        pts, width, height = _layout(self.sym_r)
        x = POS[0] + width * OFFSET_WIDTHS

        self.root.title("Palworld Type Chart")
        self.root.overrideredirect(True)
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.geometry(f"{width}x{height}+{x}+{POS[1]}")
        # order matters: -transparentcolor / -alpha make the window layered for us,
        # then we add the click-through bits on top of what Tk set.
        self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.root.attributes("-alpha", OPACITY)
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.root, width=width, height=height,
                                bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        draw_chart(self.canvas, pts, self.icons, self.sym_r)

        self.enabled = not START_HIDDEN   # what the Ctrl+Alt+P toggle controls
        self.shown = False                # what the window is actually doing
        self._grace = bool(HINT_SECONDS)  # auto-hide waits until the hint clears
        self._toggle_req = False
        self._quit_req = False
        self._saw_game = False
        self._ticks = 0

        # map it once so the ex-styles land on a real HWND, then settle on the
        # state we actually want
        self.root.deiconify()
        self.root.update_idletasks()
        self._apply_styles()
        self.shown = True
        if not self._wants_visible():
            self._set_shown(False)

        if HINT_SECONDS:
            hint = _text(self.canvas, width / 2, height - HINT_BAND / 2,
                         "Ctrl+Alt+P  toggle      Ctrl+Alt+Shift+P  quit",
                         "#cfd4dc", 7.5 * SCALE)
            self.root.after(HINT_SECONDS * 1000, lambda: self._end_hint(hint))

        threading.Thread(target=_hotkey_loop, args=(self._req_toggle, self._req_quit),
                         daemon=True).start()
        self.root.after(TICK_MS, self._tick)

    # hotkey thread touches only these two flags; tkinter is driven from _tick
    def _req_toggle(self):
        self._toggle_req = True

    def _req_quit(self):
        self._quit_req = True

    def _hwnd(self):
        wid = self.root.winfo_id()
        if user32.GetWindowLongW(wid, GWL_STYLE) & WS_CHILD:
            wid = user32.GetParent(wid)
        return wid

    def _apply_styles(self):
        hwnd = self._hwnd()
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              ex | WS_EX_LAYERED | WS_EX_TRANSPARENT
                              | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

    def _raise(self):
        user32.SetWindowPos(self._hwnd(), HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _end_hint(self, items):
        for item in items:
            self.canvas.delete(item)
        self._grace = False  # auto-hide takes over once the launch hint clears

    def _wants_visible(self):
        """The manual toggle gates everything; auto-hide only narrows it further."""
        if not self.enabled:
            return False
        if not AUTO_HIDE or self._grace:
            return True
        return gamestate.in_gameplay(GAME_EXE)

    def _set_shown(self, shown):
        self.shown = shown
        if shown:
            self.root.deiconify()
            self.root.update_idletasks()
            self._apply_styles()  # Windows drops ex-styles across a hide/show
            self._raise()
        else:
            self.root.withdraw()

    def _outlived_game(self):
        """True once Palworld has been seen running and is now gone."""
        if not EXIT_WITH_GAME:
            return False
        if gamestate.game_running(GAME_EXE):
            self._saw_game = True
            return False
        return self._saw_game

    def _tick(self):
        if self._quit_req:
            self.root.destroy()
            return
        if self._toggle_req:
            self._toggle_req = False
            self.enabled = not self.enabled
        want = self._wants_visible()
        if want != self.shown:
            self._set_shown(want)

        self._ticks += 1
        if self.shown and self._ticks % max(1, TOPMOST_EVERY_MS // TICK_MS) == 0:
            self._raise()
        # walking the process table is heavier than the rest of the tick, so it
        # runs on its own slower cadence
        if self._ticks % max(1, GAME_CHECK_EVERY_MS // TICK_MS) == 0:
            if self._outlived_game():
                self.root.destroy()
                return
        self.root.after(TICK_MS, self._tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Overlay().run()
