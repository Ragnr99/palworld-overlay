"""What an overlay module is, and what a setting is.

A module is one thing drawn on screen. It declares its settings as data; the
control panel builds its own UI from that declaration and the host gives it a
click-through window positioned by it. Adding a screen reader or a bot status
readout later means writing a class here and listing it in __init__ - neither
the panel nor the host needs to learn about it.

Settings are the contract between the two processes, so they have to survive a
hand-edited or stale settings.json. Every Setting can coerce any junk value back
into something valid, which is why nothing downstream ever range-checks.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Any, Sequence

#: This exact colour is punched out of every overlay window and becomes fully
#: transparent. Nothing may be drawn in it except on purpose - which also makes
#: it handy for carving shapes (see typechart._dark).
TRANSPARENT_KEY = "#010203"

user32 = ctypes.WinDLL("user32", use_last_error=True)

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


def screen_bounds():
    """(left, top, right, bottom) of the whole desktop, second monitors included.

    Position sliders span this rather than the primary monitor, so an overlay
    can be parked on a second screen. Left/top go negative when a monitor sits
    left of or above the primary one.
    """
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1920
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1080
    return left, top, left + width, top + height


# ---------------- settings ----------------

@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    default: Any
    #: shown under the control in the panel, for anything non-obvious
    help: str = ""

    def coerce(self, value: Any) -> Any:
        return value


@dataclass(frozen=True)
class Slider(Setting):
    lo: float = 0.0
    hi: float = 1.0
    step: float = 1.0
    unit: str = ""

    @property
    def integral(self) -> bool:
        """Whole-number setting, so the panel shows '282' and not '282.00'."""
        return float(self.step).is_integer() and float(self.lo).is_integer()

    def coerce(self, value: Any) -> float | int:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return self.default
        if v != v:  # NaN, which would poison every comparison downstream
            return self.default
        v = min(self.hi, max(self.lo, v))
        if self.step:
            v = min(self.hi, self.lo + round((v - self.lo) / self.step) * self.step)
        return int(round(v)) if self.integral else round(v, 4)


@dataclass(frozen=True)
class Toggle(Setting):
    def coerce(self, value: Any) -> bool:
        return bool(value)


@dataclass(frozen=True)
class Choice(Setting):
    options: tuple[str, ...] = ()

    def coerce(self, value: Any) -> str:
        return value if value in self.options else self.default


def placement(x: int, y: int, scale: float = 1.0, opacity: float = 0.95) -> tuple[Setting, ...]:
    """The settings every drawn module has, with its own defaults filled in.

    Each module owns its position and opacity because each gets its own layered
    window - Windows sets alpha per window, so there's no way to share one.
    """
    left, top, right, bottom = screen_bounds()
    return (
        Toggle("enabled", "Show on screen", True),
        Slider("x", "Position X", x, lo=left, hi=right, step=1, unit="px"),
        Slider("y", "Position Y", y, lo=top, hi=bottom, step=1, unit="px"),
        Slider("scale", "Size", scale, lo=0.4, hi=3.0, step=0.05,
               help="Multiplier on everything the module draws. Bump it on a 1440p or "
                    "4K display."),
        Slider("opacity", "Opacity", opacity, lo=0.1, hi=1.0, step=0.01,
               help="1.00 is solid."),
    )


# ---------------- modules ----------------

class Module:
    """One thing on screen. Subclass, declare `settings`, implement `draw`."""

    #: settings.json section name, and the panel's stable ordering key
    id: str = ""
    #: what the panel calls it
    name: str = ""
    #: one-liner under the section header
    blurb: str = ""
    #: False for settings-only sections (see modules.general) - no window is made
    draws: bool = True
    settings: Sequence[Setting] = ()

    def defaults(self) -> dict[str, Any]:
        return {s.key: s.default for s in self.settings}

    def coerce(self, values: dict[str, Any]) -> dict[str, Any]:
        """Fill in what's missing, fix what's wrong, keep what's unknown."""
        out = dict(values)
        for s in self.settings:
            out[s.key] = s.coerce(values.get(s.key, s.default))
        return out

    def draw(self, canvas, cfg: dict[str, Any]) -> tuple[int, int]:
        """Draw into `canvas` from (0, 0) and return the (width, height) used.

        Called on a fresh, empty canvas whenever anything but position or
        opacity changes, so it can be a straight redraw with no diffing.
        """
        raise NotImplementedError

    #: keys whose change the host can honour without redrawing anything
    CHEAP_KEYS = frozenset({"enabled", "x", "y", "opacity"})


# ---------------- shared drawing ----------------

_OFFSETS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))


def outlined_text(canvas, x, y, text, fill, size, floor=7):
    """Text with a black halo, so it stays legible over any game background.

    Eight offset copies underneath rather than a panel behind it: the point of
    the overlay is not to hide what it sits on.

    `floor` is the smallest point size to fall back to. Scaled sizes round down
    to nothing on a small overlay, and 7pt is about the limit for something you
    read; drop it only for text that is deliberately subordinate.
    """
    font = ("Segoe UI", max(floor, int(size)), "bold")
    ids = [canvas.create_text(x + dx, y + dy, text=text, fill="#000000", font=font)
           for dx, dy in _OFFSETS]
    ids.append(canvas.create_text(x, y, text=text, fill=fill, font=font))
    return ids
