"""Persisted settings, and the whole contract between the panel and the overlay.

The two run as separate processes. The panel writes settings.json; the overlay
stats it on its normal tick and reloads when the mtime moves. Nothing else
passes between them, which is why the panel works with the game closed and a
panel crash can't take the overlay down.

Defaults live on the modules, not here, so a new module's settings appear with
sane values without this file learning about it. Values are coerced through the
Setting declarations on the way in, so a hand-edited or half-upgraded file can
never hand the overlay a scale of "banana" or an opacity of 40.

Unknown sections and keys are kept and written back untouched: running an older
build for an afternoon shouldn't throw away the settings of a module it doesn't
have yet.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from modules import BY_ID, MODULES

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"


class Settings:
    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self.values: dict[str, dict[str, Any]] = {}
        self._stamp: tuple[int, int] | None = None
        self.load()

    # ---------------- disk ----------------

    def _read_stamp(self) -> tuple[int, int] | None:
        """(mtime, size) of the file, or None if it isn't there.

        Size joins mtime because a same-millisecond rewrite is plausible when
        the panel saves twice in a row on a fast drag.
        """
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def changed(self) -> bool:
        """True if the file moved under us since the last load or save."""
        return self._read_stamp() != self._stamp

    def load(self) -> None:
        raw: dict[str, Any] = {}
        stamp = self._read_stamp()
        try:
            with self.path.open(encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, ValueError):
            pass  # missing or corrupt: fall through to pure defaults

        merged = {k: dict(v) for k, v in raw.items() if isinstance(v, dict)}
        for module in MODULES:
            merged[module.id] = module.coerce(merged.get(module.id, {}))
        self.values = merged
        self._stamp = stamp

    def reload_if_changed(self) -> bool:
        if not self.changed():
            return False
        self.load()
        return True

    def save(self) -> None:
        """Write via a temp file so a half-written JSON is never observable.

        Restamps afterwards, so whichever process just saved doesn't then see
        its own write as an external change and reload itself.
        """
        tmp = self.path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self.values, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)
        except OSError:
            tmp.unlink(missing_ok=True)
            return
        self._stamp = self._read_stamp()

    # ---------------- access ----------------

    def section(self, module_id: str) -> dict[str, Any]:
        return self.values.setdefault(module_id, {})

    def get(self, module_id: str, key: str) -> Any:
        return self.section(module_id).get(key)

    def set(self, module_id: str, key: str, value: Any) -> Any:
        """Set one value, coerced through its Setting. Returns what was stored."""
        module = BY_ID.get(module_id)
        if module is not None:
            for setting in module.settings:
                if setting.key == key:
                    value = setting.coerce(value)
                    break
        self.section(module_id)[key] = value
        return value

    def reset(self, module_id: str | None = None) -> None:
        """Back to defaults, for one module or all of them."""
        targets = MODULES if module_id is None else [BY_ID[module_id]]
        for module in targets:
            self.section(module.id).update(module.defaults())
