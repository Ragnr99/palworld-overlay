"""Reading Palworld's state from outside the game, with no hooks or injection.

Two questions matter to the overlay:

    game_running()  - is Palworld alive at all?      (when to start / stop)
    in_gameplay()   - is Palworld focused, no UI up?  (when to show / hide)

Both are answered from plain Win32 calls. The menu detector leans on the fact
that Palworld hides the mouse cursor during gameplay and shows it the moment any
UI opens (inventory, Pal box, map, build, pause), so cursor visibility is the
whole signal.

Stdlib only, and cheap enough to poll a few times a second.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GAME_EXE = "palworld"  # substring match, case-insensitive

CURSOR_SHOWING = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x0002
MAX_PATH = 260
INVALID_HANDLE = ctypes.c_void_p(-1).value


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", ctypes.c_void_p), ("ptScreenPos", _POINT)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * MAX_PATH)]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def cursor_visible():
    """True when Windows is showing a cursor, i.e. Palworld has a UI open."""
    info = _CURSORINFO()
    info.cbSize = ctypes.sizeof(_CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(info)):
        return True  # can't tell, so assume a UI is up and stay out of the way
    return bool(info.flags & CURSOR_SHOWING)


def foreground_exe():
    """Full path of the focused window's executable, lowercased ('' if unknown).

    Matched on the path rather than the window title: Palworld's title is
    literally "Pal  ", which a browser tab on the wiki would also match.
    """
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(512)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def foreground_title():
    """Title bar text of the focused window ('' if there isn't one).

    Only used to recognise the overlay's own settings panel. Focusing the panel
    takes focus off the game, which would otherwise auto-hide the very overlay
    you opened the panel to adjust.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def game_running(exe_match=GAME_EXE):
    """True if any process's image name matches. Unknown counts as running.

    Failing 'open' matters here: this decides when the overlay kills itself, and
    a false negative would close it mid-session.
    """
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, INVALID_HANDLE):
        return True
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        found = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while found:
            if exe_match in entry.szExeFile.lower():
                return True
            found = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snap)


def in_gameplay(exe_match=GAME_EXE):
    """True when Palworld is the focused window and no UI is open."""
    return exe_match in foreground_exe() and not cursor_visible()


if __name__ == "__main__":
    print(f"game_running = {game_running()}")
    print(f"in_gameplay  = {in_gameplay()}")
    print(f"cursor shown = {cursor_visible()}")
    print(f"foreground   = {foreground_exe()}")
