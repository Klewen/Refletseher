"""Application level tests: controller, profiles, settings, effects, automation."""

from __future__ import annotations

import datetime as dt
import json
import time

import pytest

from refletseher.automation import AutomationService, Context, in_time_range, parse_hhmm
from refletseher.capture.synthetic import SYNTHETIC_MONITOR, SyntheticBackend, vertical_bands
from refletseher.core.controller import AppController, Mode
from refletseher.core.settings import AppSettings, AutomationRule, SettingsStore
from refletseher.device import protocol as P
from refletseher.device.conflicts import ConflictReport, classify
from refletseher.device.mock import MockBackend
from refletseher.device.worker import ConnectionState
from refletseher.effects import SPECS, EffectConfig, EffectId, flash_rate, period_seconds, render, to_hardware
from refletseher.profiles.model import LightMode, Profile, ProfileError
from refletseher.profiles.presets import PRESET_IDS
from refletseher.profiles.store import ProfileStore
from refletseher.sync.engine import ScreenSyncEngine, SyncConfig

RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


def wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stores(tmp_path):
    return SettingsStore(tmp_path / "settings.json"), ProfileStore(tmp_path / "profiles.json")


@pytest.fixture
def app(stores):
    settings, profiles = stores
    backend = MockBackend()
    synth = SyntheticBackend(lambda t: vertical_bands([RED, GREEN, BLUE, WHITE]))

    def engine_factory(sink):
        return ScreenSyncEngine(sink, monitors_fn=lambda: [SYNTHETIC_MONITOR], backend_factory=lambda name: synth)

    ctrl = AppController(settings, profiles, backend_factory=lambda: backend, sync_engine_factory=engine_factory,
                         conflict_fn=lambda: ConflictReport((), ()))
    ctrl.worker.config.backoff_base_s = 0.05
    ctrl.start(apply_startup_profile=False)
    ctrl.backend = backend
    ctrl.synth = synth
    yield ctrl
    ctrl.shutdown()


# ------------------------------------------------------------ controller
def test_manual_zone_control(app):
    app.set_static(zone_colors=[RED, GREEN, BLUE, WHITE])
    assert app.worker.wait_idle()
    assert app.backend.zone_colors() == (RED, GREEN, BLUE, WHITE)
    snap = app.snapshot()
    assert snap.intended == (RED, GREEN, BLUE, WHITE)
    assert snap.device.confirmed_zone_colors == (RED, GREEN, BLUE, WHITE)


def test_brightness_and_power(app):
    app.set_static(zone_colors=[RED] * 4, zone_brightness=[100, 50, 100, 100])
    app.set_master_brightness(50)
    assert app.worker.wait_idle()
    assert app.backend.zone_colors()[0] == (128, 0, 0)
    assert app.backend.zone_colors()[1] == (64, 0, 0)
    app.set_power(False)
    assert app.worker.wait_idle()
    assert app.backend.zone_colors() == ((0, 0, 0),) * 4
    assert app.snapshot().mode == Mode.OFF
    app.set_power(True)
    assert app.worker.wait_idle()
    assert app.backend.zone_colors()[0] == (128, 0, 0)


def test_undo_previous_state(app):
    app.set_static(zone_colors=[RED] * 4)
    time.sleep(1.6)  # history coalesces rapid changes
    app.set_static(zone_colors=[BLUE] * 4)
    assert app.undo()
    assert app.worker.wait_idle()
    assert app.backend.zone_colors() == (RED,) * 4


def test_mode_switch_effect_hardware_and_software(app):
    app.start_effect(EffectConfig(EffectId.BREATHING, prefer_hardware=True))
    assert app.worker.wait_idle()
    assert app.backend.keyboard.zone_effect == [P.EffectType.BREATH] * 4
    snap = app.snapshot()
    assert snap.simulated and snap.intended_kind == "hardware_effect"
    app.start_effect(EffectConfig(EffectId.ZONE_CHASE, speed=100))
    assert wait_for(lambda: app.worker.snapshot().frames_applied > 3)
    assert app.backend.keyboard.zone_effect == [P.EffectType.STEADY] * 4
    assert not app.snapshot().simulated
    app.stop_effect()
    assert app.snapshot().mode == Mode.STATIC


def test_screen_sync_end_to_end(app):
    app.start_sync()
    assert wait_for(lambda: app.backend.zone_colors()[0][0] > 150 and app.backend.zone_colors()[2][2] > 150, 5)
    snap = app.snapshot()
    assert snap.mode == Mode.SCREEN_SYNC and snap.sync is not None and snap.sync.backend == "synthetic"
    app.stop_sync()
    assert app.snapshot().mode == Mode.STATIC


def test_screen_capture_loss_recovers(app):
    app.synth.fail_grabs = 2
    app.start_sync()
    assert wait_for(lambda: app.snapshot().sync is not None and app.snapshot().sync.state == "backoff", 3)
    assert wait_for(lambda: app.snapshot().sync.state == "running", 8)
    assert app.synth.opened >= 2


def test_device_disconnect_keeps_intended(app):
    app.set_static(zone_colors=[RED] * 4)
    assert app.worker.wait_idle()
    app.backend.unplug()
    app.set_static(zone_colors=[GREEN] * 4)
    assert wait_for(lambda: app.snapshot().device.state != ConnectionState.CONNECTED)
    snap = app.snapshot()
    assert snap.intended == (GREEN,) * 4  # what we want ...
    assert snap.device.pending  # ... is not confirmed on the device
    app.backend.replug()
    assert wait_for(lambda: app.backend.zone_colors() == (GREEN,) * 4, 5)


def test_watchdog_restarts_dead_sync_engine(app):
    app.start_sync()
    assert wait_for(lambda: app.snapshot().sync is not None and app.snapshot().sync.state == "running")
    app._engine.stop()
    assert "sync" in app.watchdog()
    assert wait_for(lambda: app._engine.running)


def test_profile_apply_and_exit_restore(app):
    app.apply_profile("preset_msi_red")
    assert app.worker.wait_idle()
    assert app.backend.zone_colors() == (RED,) * 4
    assert app.settings.last_manual_profile_id == "preset_msi_red"
    app.apply_profile("preset_adaptive")
    assert app.snapshot().mode == Mode.SCREEN_SYNC
    app.shutdown()
    assert app.backend.zone_colors() == (RED,) * 4  # restored on exit
    assert not app.worker.alive
    assert app.backend.close_count >= 1


def test_clean_shutdown_stops_threads(app):
    app.start_sync()
    assert wait_for(lambda: app._engine is not None and app._engine.running)
    engine = app._engine
    app.shutdown()
    assert not engine.running
    assert not app.worker.alive


def test_flash_command_never_sent(app):
    app.apply_profile("preset_rainbow")
    app.start_sync()
    time.sleep(0.5)
    app.set_static(zone_colors=[RED, GREEN, BLUE, WHITE])
    app.worker.wait_idle()
    assert app.backend.packets
    assert all(p[1] in (0x01, 0x02) for p in app.backend.packets)


# --------------------------------------------------------------- profiles
def test_presets_seeded(stores):
    _, profiles = stores
    ids = {p.id for p in profiles.list()}
    assert set(PRESET_IDS) <= ids
    assert len(PRESET_IDS) == 12


def test_profile_save_load_roundtrip(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    p = Profile("mine", "Benim Profilim", LightMode.STATIC)
    p.static.zone_colors = [RED, GREEN, BLUE, WHITE]
    store.put(p)
    again = ProfileStore(tmp_path / "p.json").get("mine")
    assert again is not None and again.static.zone_colors == [RED, GREEN, BLUE, WHITE]
    dup = store.duplicate("mine")
    assert dup.id != "mine" and dup.static.zone_colors == p.static.zone_colors
    assert store.delete("mine") and store.get("mine") is None


def test_invalid_profiles_rejected():
    with pytest.raises(ProfileError):
        Profile.from_dict({"name": "x", "mode": "laser"})
    with pytest.raises(ProfileError):
        Profile.from_dict({"name": "x", "static": {"zone_colors": ["#FF0000"]}})
    with pytest.raises(ProfileError):
        Profile.from_dict({"name": ""})
    with pytest.raises(ProfileError):
        Profile.from_dict({"name": "x", "id": "../../evil"})
    p = Profile.from_dict({"name": "x", "master_brightness": 900})
    assert p.master_brightness == 100


def test_corrupt_profile_file_recovers(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("{ not json", "utf-8")
    store = ProfileStore(path)
    assert store.load_errors and len(store.list()) == 12
    assert list(tmp_path.glob("profiles.corrupt-*.json"))


def test_import_export(tmp_path):
    store = ProfileStore(tmp_path / "a.json")
    out = tmp_path / "export.json"
    assert store.export(["preset_sunset", "preset_ocean"], out) == 2
    other = ProfileStore(tmp_path / "b.json")
    imported, errors = other.import_file(out)
    assert len(imported) == 2 and not errors
    assert all(not p.builtin for p in imported)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"profiles": [{"name": "ok"}, {"mode": "?"}]}), "utf-8")
    imported, errors = other.import_file(bad)
    assert len(imported) == 1 and len(errors) == 1


# --------------------------------------------------------------- settings
def test_invalid_config_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"language": "xx", "update_hz": 500, "region": [0, 0], "automation": [{"kind": "?"}]}), "utf-8")
    s = SettingsStore(path).settings
    assert s.language == "tr" and s.update_hz == 15.0 and s.region == [0.0, 0.0, 1.0, 1.0] and s.automation == []
    path.write_text("garbage", "utf-8")
    assert SettingsStore(path).settings == AppSettings()


# ---------------------------------------------------------------- effects
@pytest.mark.parametrize("eid", list(EffectId))
def test_every_effect_renders_valid_colors(eid):
    cfg = EffectConfig(eid)
    for t in (0.0, 0.37, 1.9, 7.3):
        cols = render(cfg, t)
        assert len(cols) == 4 and all(0 <= v <= 255 for c in cols for v in c)


@pytest.mark.parametrize("eid", list(EffectId))
def test_effects_are_photosensitivity_safe(eid):
    assert period_seconds(100) >= 1.0
    # fastest setting, default palette and a worst-case black/white palette
    for colors in ([], [(0, 0, 0), (255, 255, 255)] * 4 + [(0, 0, 0)]):
        cfg = EffectConfig(eid, speed=100, colors=list(colors))
        assert flash_rate(cfg) <= 3.0, (eid, colors, flash_rate(cfg))


def test_hardware_mapping():
    hw = to_hardware(EffectConfig(EffectId.WAVE, direction="rtl"))
    assert hw is not None and hw.effect == P.EffectType.COLOR_WAVE and hw.direction == P.WaveDirection.RIGHT_TO_LEFT
    assert to_hardware(EffectConfig(EffectId.ZONE_CHASE)) is None  # software only
    assert to_hardware(EffectConfig(EffectId.BREATHING, prefer_hardware=False)) is None
    for eid, spec in SPECS.items():
        hw = to_hardware(EffectConfig(eid))
        if hw is not None:
            for pkt in hw.packets():
                P.validate_packet(pkt)


# ------------------------------------------------------------- automation
def test_time_range():
    assert in_time_range(parse_hhmm("23:30"), parse_hhmm("23:00"), parse_hhmm("07:00"))
    assert in_time_range(parse_hhmm("06:59"), parse_hhmm("23:00"), parse_hhmm("07:00"))
    assert not in_time_range(parse_hhmm("12:00"), parse_hhmm("23:00"), parse_hhmm("07:00"))


def test_automation_edges_and_priority():
    rules = [
        AutomationRule("night", "schedule", "preset_night", start="22:00", end="06:00"),
        AutomationRule("game", "process", "preset_gaming", processes=["game.exe"]),
    ]
    ctx = {"v": Context(dt.datetime(2026, 1, 1, 23, 0), set())}
    applied, reverted = [], []
    svc = AutomationService(lambda: rules, lambda p, r: applied.append(p), lambda r: reverted.append(r), context_fn=lambda: ctx["v"])
    assert svc.evaluate_once() == "night" and applied == ["preset_night"]
    svc.evaluate_once()
    assert applied == ["preset_night"]  # edge triggered: no re-apply
    ctx["v"] = Context(dt.datetime(2026, 1, 1, 23, 5), {"game.exe"})
    assert svc.evaluate_once() == "game" and applied[-1] == "preset_gaming"
    ctx["v"] = Context(dt.datetime(2026, 1, 1, 12, 0), set())
    assert svc.evaluate_once() is None and reverted


def test_controller_rule_revert_respects_manual_choice(app):
    app.apply_profile("preset_deep_blue")
    app._on_rule_apply("preset_gaming", "game")
    assert app.state.profile_id == "preset_gaming"
    app._on_rule_revert("game")
    assert app.state.profile_id == "preset_deep_blue"
    app._on_rule_apply("preset_gaming", "game")
    app.apply_profile("preset_sunset")  # user overrides
    app._on_rule_revert("game")
    assert app.state.profile_id == "preset_sunset"


def test_conflict_classification():
    rep = classify(["Mystic_Light_Service.exe", "LEDKeeper2.exe", "MSI_Central_Service.exe", "chrome.exe"])
    assert rep.has_conflict and "Mystic Light Service" in rep.lighting
    assert "MSI Center Service" in rep.infrastructure
    assert not classify(["explorer.exe"]).has_conflict


def test_sync_engine_static_scene_reduces_work():
    out = []
    synth = SyntheticBackend(lambda t: vertical_bands([RED, BLUE]))
    synth.name = "gdi"  # behaves like an always-returning backend
    eng = ScreenSyncEngine(out.append, monitors_fn=lambda: [SYNTHETIC_MONITOR], backend_factory=lambda n: synth)
    eng.start(SyncConfig(analysis_fps=20))
    time.sleep(1.5)
    st = eng.snapshot()
    eng.stop()
    assert st.frames_static > 5  # identical frames skipped
    assert st.frames_analyzed <= 3
    assert len(out) < 60  # converged output is not resubmitted


# ------------------------------------------------ standby / capture fallback
class _FlakyFactory:
    """dxgi raises the given error ``fails`` times, gdi always works."""

    def __init__(self, exc_type, fails: int) -> None:
        from refletseher.capture import synthetic as S

        self.exc_type, self.fails = exc_type, fails
        self.opened: list[str] = []
        self._S = S

    def __call__(self, name: str):
        factory = self

        class _B(self._S.SyntheticBackend):
            def __init__(self) -> None:
                super().__init__(lambda t: vertical_bands([RED, BLUE]))
                self.name = name

            def open(self, monitor, region) -> None:
                if name == "dxgi" and factory.fails > 0:
                    factory.fails -= 1
                    raise factory.exc_type("simulated")
                factory.opened.append(name)
                super().open(monitor, region)

        return _B()


def test_transient_access_loss_does_not_fall_back_to_gdi():
    from refletseher.capture import CaptureAccessLost

    fac = _FlakyFactory(CaptureAccessLost, fails=1)
    eng = ScreenSyncEngine(lambda c: None, monitors_fn=lambda: [SYNTHETIC_MONITOR], backend_factory=fac)
    eng.start(SyncConfig(backend="auto"))
    try:
        assert wait_for(lambda: eng.snapshot().state == "running", 4)
        assert fac.opened == ["dxgi"]  # waited and retried DXGI instead of using GDI
    finally:
        eng.stop()


def test_fallback_backend_is_promoted_back_to_dxgi():
    from refletseher.capture import CaptureError

    fac = _FlakyFactory(CaptureError, fails=1)
    eng = ScreenSyncEngine(lambda c: None, monitors_fn=lambda: [SYNTHETIC_MONITOR], backend_factory=fac)
    eng.PROMOTE_AFTER_S = 0.3
    eng.start(SyncConfig(backend="auto"))
    try:
        assert wait_for(lambda: eng.snapshot().backend in ("winrt", "gdi"), 3)
        assert wait_for(lambda: eng.snapshot().backend == "dxgi", 3)
    finally:
        eng.stop()


def test_display_off_on_pauses_and_reasserts(app):
    app.start_sync()
    assert wait_for(lambda: app.snapshot().sync is not None and app.snapshot().sync.state == "running")
    app.on_display_off()
    assert wait_for(lambda: app.snapshot().sync.state == "paused")
    before = app.backend.open_count, len(app.backend.packets)
    app.backend.keyboard.zone_color = [(0, 0, 0)] * 4  # MCU lost its state in standby
    app.on_display_on()
    assert wait_for(lambda: app.snapshot().sync.state == "running")
    assert wait_for(lambda: len(app.backend.packets) > before[1])  # colours re-asserted
    assert wait_for(lambda: app.backend.zone_colors()[0] != (0, 0, 0))


# ------------------------------------------------------------ rename migration
def test_legacy_data_folder_is_migrated(tmp_path):
    from refletseher.paths import LEGACY_APP_NAMES, migrate_legacy_data

    old = tmp_path / LEGACY_APP_NAMES[0]
    old.mkdir()
    (old / "settings.json").write_text('{"language": "en"}', "utf-8")
    (old / "profiles.json").write_text("{}", "utf-8")
    new = tmp_path / "Refletseher"
    assert migrate_legacy_data(new, tmp_path)
    assert (new / "settings.json").read_text("utf-8") == '{"language": "en"}'
    assert (old / "settings.json").exists()  # old data is left untouched
    assert not migrate_legacy_data(new, tmp_path)  # only on first run


def test_no_migration_without_legacy_data(tmp_path):
    from refletseher.paths import migrate_legacy_data

    assert not migrate_legacy_data(tmp_path / "Refletseher", tmp_path)
    assert not (tmp_path / "Refletseher").exists()


def test_autostart_replaces_legacy_entry(monkeypatch):
    import sys as _sys
    import types

    from refletseher.core import autostart

    store = {autostart.LEGACY_VALUE_NAMES[0]: r'"C:\old\app.exe" --tray'}

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER=0, KEY_SET_VALUE=2, REG_SZ=1,
        OpenKey=lambda *a, **k: Key(),
        QueryValueEx=lambda key, name: (store[name], 1) if name in store else (_ for _ in ()).throw(FileNotFoundError(name)),
        SetValueEx=lambda key, name, res, typ, value: store.__setitem__(name, value),
        DeleteValue=lambda key, name: store.pop(name) if name in store else (_ for _ in ()).throw(FileNotFoundError(name)),
    )
    monkeypatch.setitem(_sys.modules, "winreg", fake)
    monkeypatch.setattr(_sys, "platform", "win32")
    assert autostart.migrate_legacy()
    assert autostart.VALUE_NAME in store and autostart.LEGACY_VALUE_NAMES[0] not in store
    assert not autostart.migrate_legacy()  # nothing left to migrate
