"""Fixed things in the world, as opposed to position.py's moving one.

Right now that means the journal notes - the readable pages Palworld scatters
around and calls Journals, which everyone else calls notes or notebooks. There
are 55 on Palpagos and they never move, so unlike a player position this needs
no server, no permission and no network: it is a file that ships with the
overlay.

The file stores raw Unreal world coordinates rather than the numbers the game
prints, so the same calibration that places the player dot also places the
notes. Get the conversion wrong and everything is wrong together, which is the
only way a marker layer can be trusted - a note that is right when the player
dot is wrong would be worse than no note at all.

Stdlib only.

    py -3.10 markers.py         list what shipped, in in-game coordinates
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import position

#: Shipped with the overlay; see palworld-map's scripts/fetch_notes.py for how
#: it is regenerated from paldb's map payload.
NOTES_FILE = Path(__file__).resolve().parent / "data" / "journals.json"


@dataclass(frozen=True)
class Note:
    """One journal note, in the coordinates the in-game map shows."""

    name: str
    series: str
    x: float
    y: float

    def distance(self, x: float, y: float) -> float:
        return math.dist((self.x, self.y), (x, y))


def _load() -> tuple[tuple[str, str, float, float], ...]:
    """The raw file: (name, series, world x, world y).

    A missing or mangled file means no markers, never a traceback - the overlay
    draws over a game and a broken data file must not take the frame with it.
    """
    try:
        payload = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        rows = payload["notes"]
    except (OSError, ValueError, KeyError, TypeError):
        return ()

    out = []
    for row in rows:
        try:
            out.append((str(row["name"]), str(row.get("series", "")),
                        float(row["x"]), float(row["y"])))
        except (KeyError, TypeError, ValueError):
            continue  # one bad row shouldn't cost the other fifty-four
    return tuple(out)


_RAW = None
#: converted notes, keyed by the calibration they were converted with. The
#: panel's origin/scale sliders change that key, so dragging one reconverts
#: rather than showing stale positions, and holding one costs one small list.
_CACHE: dict[tuple[float, float, float], tuple[Note, ...]] = {}


def notes(origin_x: float = position.MAP_ORIGIN_X,
          origin_y: float = position.MAP_ORIGIN_Y,
          scale: float = position.MAP_SCALE) -> tuple[Note, ...]:
    """Every shipped note, in in-game map coordinates under this calibration."""
    global _RAW
    if _RAW is None:
        _RAW = _load()

    key = (float(origin_x), float(origin_y), float(scale))
    hit = _CACHE.get(key)
    if hit is None:
        hit = tuple(Note(name, series, *position.to_map(wx, wy, origin_x, origin_y, scale))
                    for name, series, wx, wy in _RAW)
        _CACHE[key] = hit
    return hit


def near(x: float, y: float, radius: float, limit: int = 0,
         **calibration) -> list[tuple[float, Note]]:
    """(distance, note) for everything within `radius`, nearest first.

    Fifty-five distance checks is nothing, so this is recomputed per frame
    rather than kept in some spatial index that would have to be invalidated.
    """
    found = [(n.distance(x, y), n) for n in notes(**calibration)]
    found = [pair for pair in found if pair[0] <= radius]
    found.sort(key=lambda pair: pair[0])
    return found[:limit] if limit else found


if __name__ == "__main__":
    all_notes = notes()
    print(f"{len(all_notes)} notes from {NOTES_FILE}")
    for note in sorted(all_notes, key=lambda n: (n.series, n.name)):
        print(f"  {note.x:8.0f} {note.y:8.0f}  {note.name}")
