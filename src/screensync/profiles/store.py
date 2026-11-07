"""JSON profile storage with atomic writes, import/export and recovery."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Iterable

from .model import SCHEMA_VERSION, Profile, ProfileError, new_id
from .presets import builtin_presets

log = logging.getLogger(__name__)


def atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._profiles: dict[str, Profile] = {}
        self.load_errors: list[str] = []
        self.load()

    # ---------------------------------------------------------- persistence
    def load(self) -> None:
        with self._lock:
            self.load_errors = []
            self._profiles = {}
            if not self.path.exists():
                self._seed()
                return
            try:
                data = json.loads(self.path.read_text("utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
                    raise ValueError("unexpected structure")
            except (OSError, ValueError) as exc:
                backup = self.path.with_name(f"{self.path.stem}.corrupt-{int(time.time())}.json")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                msg = f"profiles file unreadable ({exc}); backed up to {backup.name}"
                log.error(msg)
                self.load_errors.append(msg)
                self._seed()
                return
            for i, raw in enumerate(data["profiles"]):
                try:
                    p = Profile.from_dict(raw)
                except ProfileError as exc:
                    self.load_errors.append(f"profile #{i + 1} skipped: {exc}")
                    log.warning("Invalid profile #%d skipped: %s", i + 1, exc)
                    continue
                self._profiles[p.id] = p
            if not self._profiles:
                self._seed()

    def _seed(self) -> None:
        for p in builtin_presets():
            self._profiles[p.id] = p
        self.save()

    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.path, {"version": SCHEMA_VERSION, "profiles": [p.to_dict() for p in self._profiles.values()]})

    # ------------------------------------------------------------------ CRUD
    def list(self) -> list[Profile]:
        with self._lock:
            return list(self._profiles.values())

    def get(self, pid: str | None) -> Profile | None:
        if pid is None:
            return None
        with self._lock:
            return self._profiles.get(pid)

    def put(self, profile: Profile) -> Profile:
        Profile.from_dict(profile.to_dict())  # validate
        with self._lock:
            profile.modified = time.time()
            self._profiles[profile.id] = profile
            self.save()
            return profile

    def delete(self, pid: str) -> bool:
        with self._lock:
            if self._profiles.pop(pid, None) is None:
                return False
            self.save()
            return True

    def duplicate(self, pid: str, name: str | None = None) -> Profile:
        with self._lock:
            src = self._profiles.get(pid)
            if src is None:
                raise KeyError(pid)
            copy = src.copy(id=new_id(), name=(name or f"{src.name} (2)")[:60], builtin=False)
            return self.put(copy)

    def unique_name(self, base: str) -> str:
        names = {p.name for p in self.list()}
        if base not in names:
            return base
        i = 2
        while f"{base} ({i})" in names:
            i += 1
        return f"{base} ({i})"

    def restore_presets(self) -> int:
        added = 0
        with self._lock:
            for p in builtin_presets():
                if p.id not in self._profiles:
                    self._profiles[p.id] = p
                    added += 1
            self.save()
        return added

    # --------------------------------------------------------- import/export
    def export(self, pids: Iterable[str], path: Path) -> int:
        with self._lock:
            items = [self._profiles[i].to_dict() for i in pids if i in self._profiles]
        atomic_write_json(Path(path), {"app": "ScreenSyncRGB", "version": SCHEMA_VERSION, "profiles": items})
        return len(items)

    def import_file(self, path: Path) -> tuple[list[Profile], list[str]]:
        errors: list[str] = []
        try:
            data = json.loads(Path(path).read_text("utf-8"))
        except (OSError, ValueError) as exc:
            return [], [f"file could not be read: {exc}"]
        raw = data.get("profiles") if isinstance(data, dict) and "profiles" in data else [data]
        if not isinstance(raw, list):
            return [], ["no profiles found"]
        imported: list[Profile] = []
        for i, item in enumerate(raw):
            try:
                p = Profile.from_dict(item)
            except ProfileError as exc:
                errors.append(f"#{i + 1}: {exc}")
                continue
            # never overwrite silently: imported profiles get fresh ids
            p.id = new_id()
            p.builtin = False
            p.name = self.unique_name(p.name)
            self.put(p)
            imported.append(p)
        return imported, errors
