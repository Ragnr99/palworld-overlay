"""Starting one of the other scripts as a detached process.

Lives on its own so the watcher can spawn the panel without importing it, and
therefore without pulling tkinter into a process whose whole job is to idle
cheaply. Stdlib, no tkinter, nothing at import time.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000

#: The panel's window title, which doubles as its identity: a second launch
#: finds the open one by this and focuses it instead of opening another, and the
#: overlay checks it so focusing the panel doesn't count as leaving the game.
PANEL_WINDOW_TITLE = "Palworld Overlay Settings"


def spawn(script: str) -> None:
    """Launch `script` from this folder with the interpreter we're running under.

    sys.executable is pythonw.exe when started with pyw, so the child inherits
    the same no-console behaviour; CREATE_NO_WINDOW covers the case where it
    isn't, so a console python never flashes a black box over the game.
    """
    subprocess.Popen(
        [sys.executable, str(HERE / script)],
        cwd=str(HERE),
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )
