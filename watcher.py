"""Starts the overlay when Palworld starts.

The other half of the pairing lives in overlay.py: it quits on its own once the
game's process is gone (EXIT_WITH_GAME), so this only ever has to handle the
launch side. One overlay per game session - if you quit it by hand with
Ctrl+Alt+Shift+P mid-session, it stays quit until you next start Palworld.

Idles as a bare Python process with no tkinter loaded, waking every few seconds
to walk the process table.

    pyw -3.10 watcher.py
Or double-click "Overlay Watcher.bat".
"""

import ctypes
import subprocess
import sys
import time
from pathlib import Path

import gamestate

POLL_SECONDS = 5
GAME_EXE = "palworld"

HERE = Path(__file__).resolve().parent
OVERLAY = HERE / "overlay.py"
CREATE_NO_WINDOW = 0x08000000
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


def _launch():
    # sys.executable is pythonw.exe when this was started with pyw, so the child
    # inherits the same no-console behaviour
    subprocess.Popen([sys.executable, str(OVERLAY)], cwd=str(HERE),
                     creationflags=CREATE_NO_WINDOW, close_fds=True)


def main():
    launched_this_session = False
    while True:
        if gamestate.game_running(GAME_EXE):
            if not launched_this_session:
                _launch()
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
