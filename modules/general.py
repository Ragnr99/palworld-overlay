"""Settings that belong to the overlay as a whole rather than to one module.

Declared as a Module with draws = False so the control panel renders it the same
way it renders everything else, and the host knows not to give it a window.
"""

from .base import Module, Slider, Toggle


class General(Module):
    id = "overlay"
    name = "General"
    blurb = "Applies to every overlay module."
    draws = False
    settings = (
        Toggle("only_in_game", "Only while playing", True,
               help="Hide whenever Palworld isn't focused, or any of its menus is open. "
                    "Turn off to keep the overlay up on the desktop."),
        Toggle("exit_with_game", "Close with Palworld", True,
               help="Quit once the game's process is gone. Only arms after the game has "
                    "actually been seen, so launching by hand still works."),
        Slider("hint_seconds", "Hotkey reminder", 6, lo=0, hi=30, step=1, unit="s",
               help="How long the hotkey list shows at launch. 0 hides it."),
    )
