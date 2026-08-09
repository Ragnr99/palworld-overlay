"""The module registry.

MODULES is the single list both processes read: the host makes a window for each
drawing module, the panel builds a settings section for each one in this order,
and settings.json gets a section per id. Adding something new to the overlay is
a class in this package plus a line here - neither overlay.py nor panel.py has
to change.
"""

from .base import Choice, Module, Setting, Slider, Text, Toggle, placement, screen_bounds
from .general import General
from .minimap import Minimap
from .typechart import TypeChart

#: Panel section order. General first because it's the one you reach for.
MODULES: tuple[Module, ...] = (
    General(),
    TypeChart(),
    Minimap(),
)

#: Just the ones that get a window on screen.
DRAWN: tuple[Module, ...] = tuple(m for m in MODULES if m.draws)

BY_ID: dict[str, Module] = {m.id: m for m in MODULES}

__all__ = [
    "MODULES", "DRAWN", "BY_ID",
    "Module", "Setting", "Slider", "Toggle", "Choice", "Text", "placement", "screen_bounds",
]
