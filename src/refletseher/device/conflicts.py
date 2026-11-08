"""Detect software that may drive the same MysticLight controller.

Read-only: we only *list* processes. We never stop, kill or modify MSI
services; the user gets instructions instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Lower-case process names (without .exe). "lighting" processes are the ones
# that actively drive Mystic Light; the others are MSI Center infrastructure.
LIGHTING_PROCESSES = {
    "mystic_light_service": "Mystic Light Service",
    "ledkeeper2": "LEDKeeper2 (Mystic Light)",
    "ledkeeper": "LEDKeeper (Mystic Light)",
    "mysticlight": "Mystic Light",
    "mysticlight3": "Mystic Light 3",
}
INFRA_PROCESSES = {
    "msi.centralserver": "MSI Center",
    "msi center": "MSI Center",
    "msi_central_service": "MSI Center Service",
    "msi.terminalserver": "MSI Terminal Server",
    "dragon center": "Dragon Center",
    "msi_companion_service": "MSI Companion Service",
}


@dataclass(frozen=True)
class ConflictReport:
    lighting: tuple[str, ...]
    infrastructure: tuple[str, ...]
    checked: bool = True

    @property
    def has_conflict(self) -> bool:
        return bool(self.lighting)

    @property
    def summary(self) -> str:
        if not self.checked:
            return "unknown"
        if self.lighting:
            return ", ".join(self.lighting)
        return ""


def _normalise(name: str) -> str:
    name = name.lower()
    return name[:-4] if name.endswith(".exe") else name


def classify(process_names: list[str]) -> ConflictReport:
    lighting: set[str] = set()
    infra: set[str] = set()
    for raw in process_names:
        n = _normalise(raw)
        if n in LIGHTING_PROCESSES:
            lighting.add(LIGHTING_PROCESSES[n])
        elif n in INFRA_PROCESSES:
            infra.add(INFRA_PROCESSES[n])
    return ConflictReport(tuple(sorted(lighting)), tuple(sorted(infra)))


def detect_conflicts() -> ConflictReport:
    try:
        import psutil  # noqa: PLC0415

        names = []
        for p in psutil.process_iter(["name"]):
            try:
                names.append(p.info.get("name") or "")
            except Exception:  # pragma: no cover
                continue
        return classify(names)
    except Exception:  # pragma: no cover - psutil missing or denied
        log.debug("process scan failed", exc_info=True)
        return ConflictReport((), (), checked=False)
