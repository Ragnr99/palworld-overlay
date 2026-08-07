"""System-wide hotkeys, with no window to hang them off.

RegisterHotKey with a NULL hwnd delivers WM_HOTKEY to the *thread* that
registered it, so a listener owns a message loop on its own thread and calls
back from there. It's event-driven, so idling costs nothing - no key polling.

A binding that fails to register is skipped rather than fatal. That's load
bearing: the watcher and the overlay both ask for Ctrl+Alt+O so the panel opens
whether or not the watcher is running, and exactly one of them gets it.

Callbacks arrive on the listener thread. Anything touching tkinter has to set a
flag and let the owning process's tick loop act on it.

ctypes only, deliberately - the watcher uses this and must not load tkinter.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

CTRL_ALT = MOD_CONTROL | MOD_ALT
CTRL_ALT_SHIFT = MOD_CONTROL | MOD_ALT | MOD_SHIFT

# Printable labels for what overlay.py registers. They live next to the modifier
# constants so the reminder drawn on the chart can't drift from the key that
# actually opens the panel - a stale reminder is worse than none.
TOGGLE_HOTKEY = "Ctrl+Alt+P"
PANEL_HOTKEY = "Ctrl+Alt+O"
QUIT_HOTKEY = "Ctrl+Alt+Shift+P"

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wintypes.BOOL


def vk(char: str) -> int:
    """Virtual-key code for a letter or digit. 'P' -> 0x50."""
    return ord(char.upper())


Binding = tuple[int, int, Callable[[], None]]


def listen(bindings: dict[str, Binding]) -> None:
    """Register and pump, forever. Blocks; see listen_in_background."""
    live: dict[int, Callable[[], None]] = {}
    for hotkey_id, (mods, key, callback) in enumerate(bindings.values(), start=1):
        if user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, key):
            live[hotkey_id] = callback
    if not live:
        return  # everything was already taken; the caller still works, just not by key

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY and msg.wParam in live:
            live[msg.wParam]()


def listen_in_background(bindings: dict[str, Binding]) -> threading.Thread:
    thread = threading.Thread(target=listen, args=(bindings,), daemon=True)
    thread.start()
    return thread
