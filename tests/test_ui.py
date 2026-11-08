"""GUI smoke tests (offscreen Qt) and localisation consistency."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from refletseher.i18n import LOCALES_DIR, load_locale, set_language, tr

SRC = Path(__file__).resolve().parents[1] / "src" / "refletseher"


# ------------------------------------------------------------------ i18n
def test_locales_have_identical_keys():
    trk, en = load_locale("tr"), load_locale("en")
    assert set(trk) == set(en), set(trk) ^ set(en)


def test_locale_files_are_valid_json_without_duplicates():
    for path in LOCALES_DIR.glob("*.json"):
        seen: set[str] = set()

        def hook(pairs):
            for k, _ in pairs:
                assert k not in seen or k == "", f"duplicate key {k} in {path.name}"
                seen.add(k)
            return dict(pairs)

        json.loads(path.read_text("utf-8"), object_pairs_hook=hook)


def test_all_literal_keys_exist():
    keys = set(load_locale("tr"))
    used: set[str] = set()
    for py in SRC.rglob("*.py"):
        text = py.read_text("utf-8")
        used |= {k for k in re.findall(r"""\btr\(\s*["']([a-z_][a-z0-9_.]+)["']""", text) if not k.endswith(".")}
    nav = {f"nav.{k}" for k in ("dashboard", "sync", "studio", "effects", "profiles", "hardware", "settings")}
    missing = sorted((used | nav) - keys)
    assert not missing, missing


def test_dynamic_key_families_exist():
    from refletseher.color.settings import SpatialWeighting, SyncMode
    from refletseher.effects import EffectId

    keys = set(load_locale("tr"))
    need = set()
    need |= {f"effect.{e.value}" for e in EffectId} | {f"effect.{e.value}.desc" for e in EffectId}
    need |= {f"algo.{m.value}" for m in SyncMode} | {f"algo.{m.value}.desc" for m in SyncMode if m != SyncMode.ADAPTIVE}
    need |= {"algo.adaptive.desc", "algo.dark", "algo.monochrome", "algo.multicolor"}
    need |= {f"weighting.{w.value}" for w in SpatialWeighting}
    need |= {f"backend.{b}" for b in ("auto", "dxgi", "winrt", "gdi")}
    need |= {f"perf.{p}" for p in ("eco", "balanced", "responsive")} | {f"perf.{p}.desc" for p in ("eco", "balanced", "responsive")}
    need |= {f"capture_error.{c}" for c in ("unavailable", "access_lost", "monitor_gone", "capture_error", "monitors", "crash")}
    need |= {f"preset.{p}" for p in ("cinematic", "gaming", "deep_blue", "msi_red", "cyberpunk", "ocean", "sunset", "rainbow", "night", "white", "adaptive", "custom")}
    assert not sorted(need - keys), sorted(need - keys)


def test_translation_fallback_and_format():
    set_language("tr")
    assert tr("zone.n", n=3) == "Bölge 3"
    assert tr("does.not.exist") == "does.not.exist"
    set_language("en")
    assert tr("zone.n", n=3) == "Zone 3"
    set_language("tr")


# --------------------------------------------------------------------- GUI
@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("REFLETSEHER_HOME", str(tmp_path))
    from refletseher.capture.synthetic import SYNTHETIC_MONITOR, SyntheticBackend, moving_scene
    from refletseher.core.controller import AppController
    from refletseher.core.settings import SettingsStore
    from refletseher.device.conflicts import ConflictReport
    from refletseher.device.mock import MockBackend
    from refletseher.profiles.store import ProfileStore
    from refletseher.sync.engine import ScreenSyncEngine
    from refletseher.ui.main_window import MainWindow
    from refletseher.ui.theme import apply_theme
    from PySide6.QtWidgets import QApplication

    apply_theme(QApplication.instance(), "dark")
    backend = MockBackend()
    synth = SyntheticBackend(moving_scene)
    ctrl = AppController(
        SettingsStore(tmp_path / "s.json"),
        ProfileStore(tmp_path / "p.json"),
        backend_factory=lambda: backend,
        sync_engine_factory=lambda sink: ScreenSyncEngine(sink, monitors_fn=lambda: [SYNTHETIC_MONITOR], backend_factory=lambda n: synth),
        conflict_fn=lambda: ConflictReport(("Mystic Light Service",), ()),
        simulated=True,
    )
    ctrl.start(apply_startup_profile=False)
    win = MainWindow(ctrl)
    qtbot.addWidget(win)
    win.show()
    win.backend = backend
    yield win
    win.shutdown()


@pytest.mark.gui
def test_all_pages_render_and_update(window, qtbot):
    for key in window.pages:
        window.show_page(key)
        qtbot.wait(80)
        assert window.stack.currentWidget() is window.pages[key]


@pytest.mark.gui
def test_gui_never_blocks_during_sync(window, qtbot):
    from PySide6.QtWidgets import QApplication

    window.controller.start_sync()
    window.show_page("sync")
    worst = 0.0
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        t0 = time.perf_counter()
        QApplication.processEvents()
        worst = max(worst, time.perf_counter() - t0)
        time.sleep(0.005)
    assert worst < 0.25, f"event loop stalled for {worst * 1000:.0f} ms"
    assert window.controller.snapshot().sync.frames_analyzed > 3


@pytest.mark.gui
def test_studio_zone_click_changes_device(window, qtbot):
    page = window.pages["studio"]
    window.show_page("studio")
    page.select_zone(2)
    page.picker.set_color((1, 2, 3), emit=True)
    assert window.controller.worker.wait_idle()
    assert window.backend.zone_colors()[2] == (1, 2, 3)
    assert window.controller.state.static.zone_colors[0] != (1, 2, 3)


@pytest.mark.gui
def test_close_to_tray_and_quit(window, qtbot):
    from PySide6.QtWidgets import QSystemTrayIcon

    window.close()
    assert not window.isVisible()
    if QSystemTrayIcon.isSystemTrayAvailable():
        # close_to_tray defaults to True -> hidden, lighting keeps running
        assert window.controller.worker.alive
        window.quit_app()
    # without a tray (e.g. offscreen CI) closing must quit cleanly
    assert not window.controller.worker.alive


@pytest.mark.gui
def test_modern_standby_display_state_events(window):
    import ctypes

    from refletseher.ui.main_window import GUID_CONSOLE_DISPLAY_STATE, POWERBROADCAST_SETTING

    calls = []
    window.controller.on_display_off = lambda: calls.append("off")
    window.controller.on_display_on = lambda: calls.append("on")

    def send(state: int) -> None:
        buf = ctypes.create_string_buffer(ctypes.sizeof(POWERBROADCAST_SETTING) + 4)
        s = POWERBROADCAST_SETTING.from_buffer(buf)
        s.PowerSetting = GUID_CONSOLE_DISPLAY_STATE
        s.DataLength = 4
        ctypes.c_uint32.from_buffer(buf, POWERBROADCAST_SETTING.Data.offset).value = state
        window._on_power_setting(ctypes.addressof(buf))

    window._display_state = None
    send(1)  # initial notification after registering: ignored
    send(2)  # dimmed: ignored
    send(0)
    send(0)  # repeated: ignored
    send(1)
    assert calls == ["off", "on"]
