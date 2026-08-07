"""Starts the overlay when Palworld starts, and opens the settings panel on demand.

Two jobs, both cheap:

    poll        launch overlay.py once per game session
    Ctrl+Alt+O  open panel.py

The overlay quits on its own once the game's process is gone (the general
"Close with Palworld" setting), so this only ever handles the launch side. One
overlay per game session - if you quit it by hand with Ctrl+Alt+Shift+P
mid-session, it stays quit until you next start Palworld.

This is the process that's always resident, which is why it owns the panel
hotkey: the panel then opens whether or not Palworld is running. The overlay
asks for the same hotkey as a fallback for when the watcher isn't up, and
whichever registers first wins.

Idles as a bare Python process with no tkinter loaded, waking every few seconds
to walk the process table. Both panel and overlay are spawned as separate
processes, so neither drags a UI toolkit in here.

    pyw -3.10 watcher.py
Or double-click "Overlay Watcher.bat".
"""

import ctypes
import sys
import time

import gamestate
import hotkeys
import launcher

POLL_SECONDS = 5
GAME_EXE = "palworld"

MUTEX_NAME = "PalworldOverlayWatcher"
ERROR_ALREADY_EXISTS = 183


def _claim_single_instance():
    """False if another watcher already holds the mutex.

    Matters once this autostarts at logon: double-clicking the .bat would
    otherwise leave two watchers racing to spawn two overlays. The handle is
    deliberately leaked - Windows releases it when the process dies.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def main():
    # panel.py holds its own mutex and just focuses the open window on a repeat
    # press, so this can stay a dumb spawn.
    hotkeys.listen_in_background({
        "panel": (hotkeys.CTRL_ALT, hotkeys.vk("O"), lambda: launcher.spawn("panel.py")),
    })

    launched_this_session = False
    while True:
        if gamestate.game_running(GAME_EXE):
            if not launched_this_session:
                launcher.spawn("overlay.py")
                launched_this_session = True
        else:
            launched_this_session = False  # re-arm for the next time the game opens
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if not _claim_single_instance():
        sys.exit(0)  # another watcher is already on duty
    try:
        main()
    except KeyboardInterrupt:
        pass
