"""Control panel for the overlay.

A normal, clickable window - the opposite of the overlay itself. Open it with
Ctrl+Alt+O (the watcher holds that hotkey, so it works with Palworld closed), or
double-click "Overlay Settings.bat".

Nothing here knows what a type chart is. The whole window is generated from the
module registry: every Module contributes a section, every Setting contributes a
row, and the control used is picked from the Setting's type. Registering a new
module gives it a full settings UI without this file changing.

Edits are written to settings.json a moment after you stop dragging, and a
running overlay picks them up on its next tick, so sliders move the real thing
while you watch. Nothing is sent back the other way: the panel is the writer and
the overlay is the reader.

    py -3.10 panel.py
"""

import ctypes
import sys
import tkinter as tk
from tkinter import ttk

from launcher import PANEL_WINDOW_TITLE
from modules import MODULES, Choice, Slider, Text, Toggle
from settings import Settings

#: Long enough that a slider drag is one write, short enough to feel live.
SAVE_DEBOUNCE_MS = 180

MUTEX_NAME = "PalworldOverlayPanel"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# ---------------- single instance ----------------

def _claim_single_instance() -> bool:
    """False if a panel is already open. The handle is deliberately leaked -
    Windows releases it when the process dies."""
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def _focus_existing() -> None:
    """Bring the already-open panel forward, so a second Ctrl+Alt+O isn't a no-op."""
    hwnd = user32.FindWindowW(None, PANEL_WINDOW_TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)


# ---------------- widgets ----------------

def _number(setting, value) -> str:
    """A slider's value as bare text, no unit - this goes in an editable box."""
    if isinstance(setting, Slider):
        return f"{int(value)}" if setting.integral else f"{value:.2f}"
    return str(value)


def _scrollable(parent):
    """Canvas-backed scrolling frame. Returns the frame to put content in."""
    canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
    bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas, padding=(12, 10))
    window = canvas.create_window((0, 0), window=inner, anchor="nw")

    canvas.configure(yscrollcommand=bar.set)
    inner.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
    # keep the content as wide as the viewport, so rows can stretch
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta // 120, "units"))

    canvas.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return inner


class Panel:
    def __init__(self):
        self.settings = Settings()
        self._save_job = None
        #: per-widget closures that pull their value back out of settings
        self._refreshers: list = []

        self.root = tk.Tk()
        self.root.title(PANEL_WINDOW_TITLE)
        self.root.geometry("560x720")
        self.root.minsize(430, 360)
        self._build()

    # ---------------- building ----------------

    def _build(self):
        header = ttk.Frame(self.root, padding=(14, 12, 14, 6))
        header.pack(fill="x")
        ttk.Label(header, text="Overlay settings",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(header, foreground="#666", wraplength=500, justify="left",
                  text="Changes apply to a running overlay within a quarter second. "
                       "Leave this window focused while you drag - the overlay stays "
                       "on screen so you can see what you're doing.").pack(anchor="w", pady=(2, 0))

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True)
        content = _scrollable(body)

        for module in MODULES:
            self._section(content, module)

        footer = ttk.Frame(self.root, padding=(14, 8))
        footer.pack(fill="x")
        self.status = ttk.Label(footer, foreground="#666", text="")
        self.status.pack(side="left")
        ttk.Button(footer, text="Close", command=self.root.destroy).pack(side="right")
        ttk.Button(footer, text="Reset all", command=self._reset_all).pack(side="right", padx=6)

    def _section(self, parent, module):
        frame = ttk.LabelFrame(parent, text=module.name, padding=(12, 8, 12, 12))
        frame.pack(fill="x", pady=(0, 12))
        frame.columnconfigure(1, weight=1)

        row = 0
        if module.blurb:
            ttk.Label(frame, text=module.blurb, foreground="#666",
                      wraplength=460, justify="left").grid(row=row, column=0, columnspan=4,
                                                           sticky="w", pady=(0, 8))
            row += 1

        for setting in module.settings:
            row = self._row(frame, module, setting, row)

        ttk.Button(frame, text=f"Reset {module.name}",
                   command=lambda m=module: self._reset(m.id)).grid(row=row, column=0, columnspan=4,
                                                                    sticky="w", pady=(8, 0))

    def _row(self, frame, module, setting, row):
        value = self.settings.get(module.id, setting.key)

        if isinstance(setting, Toggle):
            var = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(frame, text=setting.label, variable=var,
                            command=lambda: self._change(module.id, setting, var.get())
                            ).grid(row=row, column=0, columnspan=4, sticky="w", pady=2)
            self._refreshers.append(
                lambda: var.set(bool(self.settings.get(module.id, setting.key))))

        elif isinstance(setting, Choice):
            ttk.Label(frame, text=setting.label).grid(row=row, column=0, sticky="w", padx=(0, 10))
            var = tk.StringVar(value=str(value))
            box = ttk.Combobox(frame, textvariable=var, values=list(setting.options),
                               state="readonly")
            box.grid(row=row, column=1, columnspan=3, sticky="ew", pady=2)
            box.bind("<<ComboboxSelected>>",
                     lambda _: self._change(module.id, setting, var.get()))
            self._refreshers.append(
                lambda: var.set(str(self.settings.get(module.id, setting.key))))

        elif isinstance(setting, Text):
            ttk.Label(frame, text=setting.label).grid(row=row, column=0, sticky="w", padx=(0, 10))
            var = tk.StringVar(value=str(value))
            entry = ttk.Entry(frame, textvariable=var,
                              show="•" if setting.secret else "")
            entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=2)
            # Written on every keystroke. The save debounce already collapses a
            # burst of edits into one write, which is the same thing it does for
            # a slider drag, so typing a hostname is one save and not twelve.
            var.trace_add("write",
                          lambda *_, s=setting, v=var, m=module.id:
                          self._change(m, s, v.get()))
            self._refreshers.append(
                lambda: var.set(str(self.settings.get(module.id, setting.key))))

        elif isinstance(setting, Slider):
            ttk.Label(frame, text=setting.label).grid(row=row, column=0, sticky="w", padx=(0, 10))
            var = tk.DoubleVar(value=float(value))
            #: what the box shows. Kept in step with the handle, but the source
            #: of truth only while it's being typed into.
            text = tk.StringVar(value=_number(setting, value))

            def slide(raw, s=setting, v=var, m=module.id, t=text, snap=False):
                return self._slide(m, s, raw, v, t, snap)

            scale = ttk.Scale(frame, from_=setting.lo, to=setting.hi, variable=var,
                              command=slide)
            scale.grid(row=row, column=1, sticky="ew", pady=2)

            entry = ttk.Entry(frame, textvariable=text, width=7, justify="right")
            entry.grid(row=row, column=2, sticky="e", padx=(10, 0))
            if setting.unit:
                ttk.Label(frame, text=setting.unit, foreground="#888", width=2).grid(
                    row=row, column=3, sticky="w", padx=(3, 0))

            def commit(_=None, s=setting, v=var, t=text, m=module.id):
                self._commit_text(m, s, v, t)

            entry.bind("<Return>", commit)
            entry.bind("<KP_Enter>", commit)
            entry.bind("<FocusOut>", commit)
            entry.bind("<Escape>",
                       lambda _, s=setting, t=text, m=module.id:
                       t.set(_number(s, self.settings.get(m, s.key))))
            # select-all on focus, so typing a new value replaces rather than appends
            entry.bind("<FocusIn>", lambda e: e.widget.select_range(0, "end"))

            # ttk.Scale's own arrow keys move by a fraction of the range, which
            # is useless for pixel-nudging a slider spanning the whole desktop.
            def nudge(delta, s=setting, v=var):
                slide(v.get() + delta * s.step, snap=True)
                return "break"
            scale.bind("<Left>", lambda _: nudge(-1))
            scale.bind("<Right>", lambda _: nudge(+1))
            # snap the handle onto the coerced value once the drag ends
            scale.bind("<ButtonRelease-1>", lambda _, v=var: slide(v.get(), snap=True))

            def refresh(s=setting, v=var, m=module.id, t=text):
                current = self.settings.get(m, s.key)
                v.set(float(current))
                t.set(_number(s, current))
            self._refreshers.append(refresh)

        else:
            return row  # unknown Setting subclass: skip rather than crash the panel

        if setting.help:
            row += 1
            ttk.Label(frame, text=setting.help, foreground="#888", wraplength=440,
                      justify="left", font=("Segoe UI", 8)).grid(
                row=row, column=0, columnspan=4, sticky="w", pady=(0, 6))
        return row + 1

    # ---------------- changes ----------------

    def _slide(self, module_id, setting, raw, var, text, snap=False):
        """A slider moved.

        The stored value is always the coerced one, but the handle only gets
        snapped onto it on release or an arrow-key nudge - writing it back
        mid-drag fights the handle under the cursor. The write re-enters here
        once via the scale's command, which is harmless: coercing an already
        coerced value is a no-op, so it settles immediately.
        """
        stored = self.settings.set(module_id, setting.key, raw)
        text.set(_number(setting, stored))
        if snap and var.get() != stored:
            var.set(stored)
        self._touch()

    def _commit_text(self, module_id, setting, var, text):
        """Take what was typed into a slider's box, or put back what's real.

        Setting.coerce turns anything unparseable into the *default*, which is a
        nasty surprise when you fat-finger a position you spent a minute
        dialling in. So parsing happens here and a junk box just reverts to the
        live value; only a genuine number reaches coerce, which clamps it.

        The unit is stripped first, so pasting "282 px" straight back in works.
        """
        typed = text.get().strip()
        if setting.unit and typed.lower().endswith(setting.unit.lower()):
            typed = typed[:-len(setting.unit)].strip()
        try:
            parsed = float(typed)
        except ValueError:
            text.set(_number(setting, self.settings.get(module_id, setting.key)))
            return
        stored = self.settings.set(module_id, setting.key, parsed)
        var.set(stored)  # moves the handle, whose command refreshes the box
        text.set(_number(setting, stored))
        self._touch()

    def _change(self, module_id, setting, value):
        self.settings.set(module_id, setting.key, value)
        self._touch()

    def _touch(self):
        """Coalesce a drag's worth of edits into one write."""
        self.status.configure(text="Applying…")
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(SAVE_DEBOUNCE_MS, self._save)

    def _save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)  # reset saves immediately, mid-debounce
            self._save_job = None
        self.settings.save()
        self.status.configure(text="Saved")

    def _refresh_all(self):
        for refresh in self._refreshers:
            refresh()

    def _reset(self, module_id):
        self.settings.reset(module_id)
        self._refresh_all()
        self._save()

    def _reset_all(self):
        self.settings.reset()
        self._refresh_all()
        self._save()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not _claim_single_instance():
        _focus_existing()
        sys.exit(0)
    Panel().run()
