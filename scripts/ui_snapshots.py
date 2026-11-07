"""Render every page of the main window to PNG (simulated device + synthetic screen).

    uv run python scripts/ui_snapshots.py [out_dir] [--light]
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SCREENSYNC_HOME", tempfile.mkdtemp(prefix="screensync-snap-"))


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "docs/screenshots")
    light = "--light" in sys.argv
    # --hardware: real MS-1565 (allow-listed commands only) so status badges
    # truthfully read "sent"; the screen-sync preview still uses a synthetic
    # scene so nothing from the user's real screen ends up in a screenshot.
    hardware = "--hardware" in sys.argv
    out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication

    from screensync.capture.synthetic import SYNTHETIC_MONITOR, SyntheticBackend, moving_scene
    from screensync.core.controller import AppController
    from screensync.core.settings import SettingsStore
    from screensync.device.conflicts import classify
    from screensync.device.mock import MockBackend
    from screensync.i18n import set_language
    from screensync.paths import profiles_file, settings_file
    from screensync.profiles.store import ProfileStore
    from screensync.sync.engine import ScreenSyncEngine
    from screensync.ui.main_window import MainWindow
    from screensync.ui.theme import apply_theme

    app = QApplication(sys.argv[:1])
    settings = SettingsStore(settings_file())
    set_language(os.environ.get("SCREENSYNC_LANG", "tr"))
    apply_theme(app, "light" if light else "dark")
    backend = MockBackend()
    synth = SyntheticBackend(moving_scene)
    ctrl = AppController(
        settings,
        ProfileStore(profiles_file()),
        backend_factory=None if hardware else (lambda: backend),
        sync_engine_factory=lambda sink: ScreenSyncEngine(sink, monitors_fn=lambda: [SYNTHETIC_MONITOR], backend_factory=lambda n: synth),
        conflict_fn=(lambda: classify([])) if hardware else (lambda: classify(["Mystic_Light_Service.exe", "MSI_Central_Service.exe"])),
        simulated=not hardware,
    )
    ctrl.start(apply_startup_profile=False)
    win = MainWindow(ctrl)
    win.resize(1440, 920)
    win.show()

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    ctrl.set_static(zone_colors=[(255, 0, 60), (170, 0, 255), (0, 170, 255), (0, 230, 160)])
    pump(0.5)
    shots = [("dashboard", None), ("studio", None), ("effects", None), ("profiles", None), ("hardware", None), ("settings", None)]
    for key, _ in shots:
        win.show_page(key)
        if key == "studio":
            win.pages["studio"].select_zone(0)
        pump(0.6)
        win.grab().save(str(out / f"{key}{'-light' if light else ''}.png"))
    ctrl.start_sync()
    win.show_page("sync")
    pump(2.5)
    win.grab().save(str(out / f"sync{'-light' if light else ''}.png"))
    win.show_page("dashboard")
    pump(0.6)
    win.grab().save(str(out / f"dashboard-sync{'-light' if light else ''}.png"))
    win.quit_app()
    print("saved to", out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
