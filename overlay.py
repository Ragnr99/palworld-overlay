"""Palworld overlay host.

Click-through, always-on-top windows pinned over the game. No window frames, no
background panels - just the modules' own artwork floating over whatever is
behind them. The mouse passes straight through: you can never click one, drag
it, focus it, or alt-tab to it.

    Ctrl+Alt+P          show / hide
    Ctrl+Alt+O          open the settings panel
    Ctrl+Alt+Shift+P    quit

This file owns windows, Win32 plumbing and the tick loop, and nothing else. What
is actually drawn comes from modules/, one layered window each - Windows sets
opacity per window, so per-module opacity needs per-module windows anyway, and
it means a future screen-reader HUD can sit somewhere else on screen with its
own size and transparency for free.

Settings are read from settings.json and re-read whenever its mtime moves, which
is how the panel's sliders reach a running overlay. That costs one stat() per
tick and keeps the two processes from having to know anything else about each
other.

Stdlib only (tkinter + ctypes), no pip installs. Palworld must run in
*borderless windowed* - nothing can draw over exclusive fullscreen.

    py -3.10 overlay.py
Or double-click "Palworld Overlay.bat".
"""

import ctypes
import tkinter as tk
from ctypes import wintypes

import gamestate
import hotkeys
import launcher
from modules import DRAWN, Module
from modules.base import TRANSPARENT_KEY, outlined_text
from settings import Settings

GAME_EXE = "palworld"    # matched against the focused window's executable path

TICK_MS = 250            # toggle responsiveness, and how fast panel edits land
LIVE_TICK_MS = 100       # how often modules that move on their own get redrawn
TOPMOST_EVERY_MS = 2000  # re-assert always-on-top this often (games steal Z-order)
GAME_CHECK_EVERY_MS = 2000

HINT_COLOR = "#cfd4dc"
# The panel key is also parked permanently in the middle of the type chart; this
# is the only place the other two are ever advertised, which is the whole reason
# the launch hint still exists.
HINT_TEXT = (f"{hotkeys.TOGGLE_HOTKEY}  toggle      {hotkeys.PANEL_HOTKEY}  settings"
             f"      {hotkeys.QUIT_HOTKEY}  quit")

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

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wintypes.BOOL


def _hwnd(window) -> int:
    """The real top-level HWND behind a Tk window."""
    wid = window.winfo_id()
    if user32.GetWindowLongW(wid, GWL_STYLE) & WS_CHILD:
        wid = user32.GetParent(wid)
    return wid


def make_click_through(window) -> None:
    hwnd = _hwnd(window)
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                          ex | WS_EX_LAYERED | WS_EX_TRANSPARENT
                          | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)


def raise_topmost(window) -> None:
    user32.SetWindowPos(_hwnd(window), HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


# ---------------- windows ----------------

class ModuleWindow:
    """One module's click-through window, kept in step with its settings."""

    def __init__(self, root, module: Module):
        self.module = module
        self.cfg: dict = {}
        self.size = (1, 1)
        self.shown = False

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.configure(bg=TRANSPARENT_KEY)
        # order matters: -transparentcolor / -alpha make the window layered for
        # us, then the click-through bits go on top of what Tk set.
        self.win.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.win.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self.canvas.pack()

    def apply(self, cfg: dict) -> None:
        """Take new settings, doing the least work they call for."""
        first = not self.cfg
        changed = set(cfg) if first else {k for k, v in cfg.items() if self.cfg.get(k) != v}
        if not changed:
            return
        self.cfg = dict(cfg)

        if changed - Module.CHEAP_KEYS:
            self._redraw()
            self._place()
        elif changed & {"x", "y"}:
            self._place()
        if "opacity" in changed:
            self.win.attributes("-alpha", cfg["opacity"])

    def update_live(self) -> None:
        """Let a live module move its own artwork. Never called before a draw."""
        if self.cfg and self.shown:
            self.module.update(self.canvas, self.cfg)

    def _redraw(self) -> None:
        self.canvas.delete("all")
        width, height = self.module.draw(self.canvas, self.cfg)
        self.size = (max(1, int(width)), max(1, int(height)))
        self.canvas.configure(width=self.size[0], height=self.size[1])

    def _place(self) -> None:
        width, height = self.size
        self.win.geometry(f"{width}x{height}+{int(self.cfg['x'])}+{int(self.cfg['y'])}")

    def set_shown(self, shown: bool) -> None:
        if shown == self.shown:
            return
        self.shown = shown
        if shown:
            self.win.deiconify()
            self.win.update_idletasks()
            make_click_through(self.win)  # Windows drops ex-styles across a hide/show
            raise_topmost(self.win)
        else:
            self.win.withdraw()


class HintWindow:
    """The launch reminder, on the bottom edge so it never covers a module."""

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=TRANSPARENT_KEY)
        self.win.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.win.attributes("-alpha", 0.9)
        self.win.attributes("-topmost", True)

        width, height = 520, 26
        canvas = tk.Canvas(self.win, width=width, height=height,
                           bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        canvas.pack()
        outlined_text(canvas, width / 2, height / 2, HINT_TEXT, HINT_COLOR, 9)

        x = (root.winfo_screenwidth() - width) // 2
        y = root.winfo_screenheight() - height - 90
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.win.update_idletasks()
        make_click_through(self.win)
        raise_topmost(self.win)

    def close(self) -> None:
        self.win.destroy()


# ---------------- app ----------------

class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # the host itself is never seen; modules get Toplevels

        self.settings = Settings()
        self.windows = {m.id: ModuleWindow(self.root, m) for m in DRAWN}
        #: the ones that change on their own and so need more than the settings tick
        self.live = [w for w in self.windows.values() if w.module.live]

        self.alive = True
        self.enabled = True   # what Ctrl+Alt+P controls
        self._toggle_req = False
        self._quit_req = False
        self._panel_req = False
        self._saw_game = False
        self._ticks = 0

        # Auto-hide stays off until the launch hint clears, so the overlay is
        # visible on the desktop for long enough to read its own hotkeys.
        hint_seconds = self.settings.get("overlay", "hint_seconds")
        self._grace = bool(hint_seconds)
        self._hint = HintWindow(self.root) if hint_seconds else None
        if self._hint:
            self.root.after(int(hint_seconds * 1000), self._end_hint)

        self._apply_settings()
        self._sync_visibility()

        # Ctrl+Alt+O is usually already held by the watcher, and losing the race
        # for it is fine - either process opens the same panel.
        hotkeys.listen_in_background({
            "toggle": (hotkeys.CTRL_ALT, hotkeys.vk("P"), self._req_toggle),
            "quit": (hotkeys.CTRL_ALT_SHIFT, hotkeys.vk("P"), self._req_quit),
            "panel": (hotkeys.CTRL_ALT, hotkeys.vk("O"), self._req_panel),
        })
        self.root.after(TICK_MS, self._tick)
        if self.live:
            self.root.after(LIVE_TICK_MS, self._live_tick)

    # the hotkey thread only ever sets these flags; tkinter is driven from _tick
    def _req_toggle(self):
        self._toggle_req = True

    def _req_quit(self):
        self._quit_req = True

    def _req_panel(self):
        self._panel_req = True

    def _end_hint(self):
        if self._hint:
            self._hint.close()
            self._hint = None
        self._grace = False

    def _apply_settings(self) -> None:
        for module_id, window in self.windows.items():
            window.apply(self.settings.section(module_id))

    def _wants_visible(self) -> bool:
        """The manual toggle gates everything; only_in_game narrows it further."""
        if not self.enabled:
            return False
        if self._grace or not self.settings.get("overlay", "only_in_game"):
            return True
        # The settings panel counts as being in the game: focusing it takes
        # focus off Palworld, and hiding the overlay you're mid-way through
        # positioning would make the sliders useless.
        return (gamestate.in_gameplay(GAME_EXE)
                or gamestate.foreground_title() == launcher.PANEL_WINDOW_TITLE)

    def _sync_visibility(self) -> None:
        want = self._wants_visible()
        for module_id, window in self.windows.items():
            window.set_shown(want and bool(self.settings.get(module_id, "enabled")))

    def _outlived_game(self) -> bool:
        """True once Palworld has been seen running and is now gone."""
        if not self.settings.get("overlay", "exit_with_game"):
            return False
        if gamestate.game_running(GAME_EXE):
            self._saw_game = True
            return False
        return self._saw_game

    def _shutdown(self):
        """Stop the loops before tearing Tk down, so nothing ticks a dead window."""
        self.alive = False
        self.root.destroy()

    def _live_tick(self):
        """Move what moves. Separate from _tick because a minimap at 250ms
        stutters, and re-reading settings.json at 10Hz to fix that would be
        four times the disk work for the sake of one module."""
        if not self.alive:
            return
        for window in self.live:
            window.update_live()
        self.root.after(LIVE_TICK_MS, self._live_tick)

    def _tick(self):
        if self._quit_req:
            self._shutdown()
            return
        if self._toggle_req:
            self._toggle_req = False
            self.enabled = not self.enabled
        if self._panel_req:
            self._panel_req = False
            launcher.spawn("panel.py")

        # One stat() per tick is what lets the panel's sliders reach us live.
        if self.settings.reload_if_changed():
            self._apply_settings()
        self._sync_visibility()

        self._ticks += 1
        if self._ticks % max(1, TOPMOST_EVERY_MS // TICK_MS) == 0:
            for window in self.windows.values():
                if window.shown:
                    raise_topmost(window.win)
        # walking the process table is heavier than the rest of the tick, so it
        # runs on its own slower cadence
        if self._ticks % max(1, GAME_CHECK_EVERY_MS // TICK_MS) == 0 and self._outlived_game():
            self._shutdown()
            return

        self.root.after(TICK_MS, self._tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Overlay().run()
