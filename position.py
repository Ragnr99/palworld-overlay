"""Where the player is, read from outside the game.

Same rule as gamestate.py: no hooks, no injection, no reading another process's
memory. That leaves exactly one supported live source, and it is worth being
blunt about which:

    rest  - Palworld's dedicated-server REST API. The server publishes every
            connected player's coordinates over HTTP, which is about as clean a
            source as exists. Needs a *dedicated server* (PalServer) with
            RESTAPIEnabled=True; a co-op world hosted from the game client does
            not have it.
    demo  - a simulated walk. Not the game. It exists so the minimap can be
            positioned, sized and sanity-checked with Palworld closed, and so a
            broken server config is obviously broken rather than just empty.

Single-player has no live source here. The save file only lands on autosave and
is a compressed GVAS blob; the only thing that would give live coordinates in a
solo world is reading the game's memory, which this project does not do. Run a
dedicated server (even locally, just for yourself) and the rest source works.

Polling happens on a daemon thread because a dead server means a socket timeout,
and the overlay's tick loop is also its UI thread - a two-second stall there
would freeze every module on screen, not just this one.

Stdlib only.

    py -3.10 position.py        connection test against settings.json
"""

from __future__ import annotations

import base64
import json
import math
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

#: Unreal world units -> the coordinates Palworld shows you on its own map.
#: The axes swap: in-game X comes from world Y. These are the community-standard
#: constants and they match the numbers the game prints, but they are exposed as
#: settings too - see the minimap module's calibration help.
MAP_ORIGIN = 157000.0
MAP_SCALE = 459.42

#: The source names the settings panel offers. Defined here rather than in the
#: module so the string that picks a source and the code that builds it can't
#: drift apart.
SOURCE_REST = "Dedicated server (REST)"
SOURCE_DEMO = "Demo (no game)"
SOURCES = (SOURCE_REST, SOURCE_DEMO)

#: Roughly the playable extent of the base map in in-game coordinates. Only used
#: to keep the demo walk somewhere plausible and to clamp the grid labels.
MAP_MIN, MAP_MAX = -800, 800

REQUEST_TIMEOUT = 2.0
POLL_SECONDS = 0.5
#: A fix older than this is stale enough to stop drawing as if it were live.
STALE_AFTER = 5.0


def to_map(world_x: float, world_y: float,
           origin: float = MAP_ORIGIN, scale: float = MAP_SCALE) -> tuple[float, float]:
    """Unreal world coordinates -> in-game map coordinates."""
    scale = scale or MAP_SCALE
    return ((world_y - origin) / scale, (world_x - origin) / scale)


def to_world(map_x: float, map_y: float,
             origin: float = MAP_ORIGIN, scale: float = MAP_SCALE) -> tuple[float, float]:
    """The inverse, kept next to it so the pair can't drift apart."""
    return (map_y * scale + origin, map_x * scale + origin)


@dataclass(frozen=True)
class Fix:
    """One position reading, in in-game map coordinates."""

    x: float
    y: float
    #: wall-clock time.monotonic() of the reading
    at: float
    name: str = ""

    def age(self) -> float:
        return time.monotonic() - self.at

    def stale(self) -> bool:
        return self.age() > STALE_AFTER


# ---------------- sources ----------------

class Source:
    """Something that can be asked for a Fix. Never raises; reports via status."""

    #: short human-readable state, shown on the minimap when there's no fix
    status = ""

    def poll(self) -> Fix | None:
        raise NotImplementedError


class DemoSource(Source):
    """A plausible wander, so the minimap can be set up with the game closed.

    Deliberately looks like walking rather than teleporting: it holds a heading
    and turns gradually, so the trail curves the way a real one does and a
    stuck-camera bug in the drawing code is obvious.
    """

    SPEED = 26.0  # map units per second, about a brisk run

    def __init__(self):
        self.status = "demo"
        self._x, self._y = 120.0, -180.0
        self._heading = random.uniform(0, math.tau)
        self._last = time.monotonic()

    def poll(self) -> Fix:
        now = time.monotonic()
        dt = min(0.5, now - self._last)  # a long stall shouldn't teleport it
        self._last = now

        self._heading += random.uniform(-0.6, 0.6) * dt
        self._x += math.cos(self._heading) * self.SPEED * dt
        self._y += math.sin(self._heading) * self.SPEED * dt

        # bounce off the edges of the playable area rather than wandering off
        for attr, value in (("_x", self._x), ("_y", self._y)):
            if not MAP_MIN < value < MAP_MAX:
                setattr(self, attr, max(MAP_MIN, min(MAP_MAX, value)))
                self._heading += math.pi / 2

        return Fix(self._x, self._y, now, "Demo")


class RestSource(Source):
    """Polls a dedicated server's /v1/api/players.

    The server answers with every connected player, so `player` picks one by
    name; empty takes whoever is listed first, which is the right behaviour for
    the overwhelmingly common case of a server with one person on it.
    """

    def __init__(self, host: str, port: int, password: str, player: str = "",
                 username: str = "admin",
                 origin: float = MAP_ORIGIN, scale: float = MAP_SCALE):
        self.url = f"http://{host.strip() or '127.0.0.1'}:{int(port)}/v1/api/players"
        self.player = player.strip().casefold()
        self.origin, self.scale = origin, scale
        self.status = "connecting"
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}",
                         "Accept": "application/json"}

    def poll(self) -> Fix | None:
        request = urllib.request.Request(self.url, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            # 401 is by far the likeliest misconfiguration, and "check the
            # password" is more use on screen than "HTTP 401".
            self.status = "bad password" if exc.code in (401, 403) else f"http {exc.code}"
            return None
        except urllib.error.URLError:
            self.status = "no server"
            return None
        except (ValueError, OSError):
            self.status = "bad reply"
            return None

        players = payload.get("players") if isinstance(payload, dict) else None
        if not players:
            self.status = "nobody online"
            return None

        chosen = None
        if self.player:
            chosen = next((p for p in players
                           if str(p.get("name", "")).casefold() == self.player), None)
            if chosen is None:
                self.status = "player not on server"
                return None
        else:
            chosen = players[0]

        try:
            world_x = float(chosen["location_x"])
            world_y = float(chosen["location_y"])
        except (KeyError, TypeError, ValueError):
            self.status = "no coordinates"
            return None

        self.status = "ok"
        x, y = to_map(world_x, world_y, self.origin, self.scale)
        return Fix(x, y, time.monotonic(), str(chosen.get("name", "")))


def _number(cfg: dict, key: str, fallback: float) -> float:
    try:
        return float(cfg.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def make_source(cfg: dict) -> Source:
    """Build the source a settings section asks for."""
    if cfg.get("source") == SOURCE_DEMO:
        return DemoSource()
    return RestSource(host=str(cfg.get("host", "127.0.0.1")),
                      port=int(_number(cfg, "port", 8212)) or 8212,
                      password=str(cfg.get("password", "")),
                      player=str(cfg.get("player", "")),
                      origin=_number(cfg, "world_origin", MAP_ORIGIN),
                      scale=_number(cfg, "world_scale", MAP_SCALE) or MAP_SCALE)


# ---------------- tracker ----------------

def _source_key(cfg: dict) -> tuple:
    """What a source is built from. A change here means rebuild it."""
    return tuple(str(cfg.get(k, "")) for k in
                 ("source", "host", "port", "password", "player",
                  "world_origin", "world_scale"))


class Tracker:
    """Owns the polling thread and hands out the newest Fix.

    One thread for the life of the overlay. Reconfiguring from the settings
    panel swaps the source under it rather than starting another, so dragging
    the port slider can't leave a pile of threads behind.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._source: Source | None = None
        self._key: tuple | None = None
        self._fix: Fix | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def configure(self, cfg: dict) -> None:
        """Point at whatever the settings now describe, starting up if needed."""
        key = _source_key(cfg)
        with self._lock:
            if key != self._key:
                self._key = key
                self._source = make_source(cfg)
                self._fix = None  # the old source's position isn't this one's
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="position",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> Fix | None:
        with self._lock:
            return self._fix

    def status(self) -> str:
        with self._lock:
            return self._source.status if self._source else "off"

    def _run(self) -> None:
        while not self._stop.wait(0):
            with self._lock:
                source = self._source
            if source is not None:
                try:
                    fix = source.poll()
                except Exception:  # a source bug must not kill the thread
                    fix = None
                    source.status = "source error"
                if fix is not None:
                    with self._lock:
                        # discard if the source was swapped mid-poll
                        if source is self._source:
                            self._fix = fix
            if self._stop.wait(POLL_SECONDS):
                return


if __name__ == "__main__":
    from settings import Settings

    section = Settings().section("minimap")
    source = make_source(section)
    print(f"source  = {type(source).__name__}")
    print(f"target  = {getattr(source, 'url', 'n/a')}")
    fix = source.poll()
    print(f"status  = {source.status}")
    if fix:
        print(f"player  = {fix.name or '(unnamed)'}")
        print(f"map x/y = {fix.x:.0f}, {fix.y:.0f}")
    else:
        print("no fix")
