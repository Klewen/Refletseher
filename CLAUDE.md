# CLAUDE.md — Refletseher

Windows 11 desktop app (Python 3.12 + PySide6) that drives the MSI MysticLight MS-1565 4-zone keyboard
(VID 0x1462 / PID 0x1601) for screen-synced ambient lighting and manual RGB. UI is Turkish-first.

## Commands

- Install / sync: `uv sync` (never `pip install` into system Python; deps are pinned in `uv.lock`)
- Run: `uv run refletseher` · without hardware: `uv run refletseher --simulate`
- Tests: `uv run pytest -q` (no hardware, ~20 s) · hardware opt-in: `uv run pytest tests/hardware --run-hardware`
- Benchmark: `uv run python scripts/benchmark.py [--animate] [--hardware]`
- UI screenshots: `uv run python scripts/ui_snapshots.py docs/screenshots`
- Build exe: `powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1` → `dist\Refletseher\Refletseher.exe`
- Hardware validation helpers: `uv run python scripts/hw_validate.py {snippet|probe|zones|latency|effects|color HEX}`

## Hard safety rules (do not relax)

- Only packet ids `0x01` (select zones) and `0x02` (set effect) may ever reach the device. `0xA0` (save to flash),
  `0xB0`, `0xFF` and anything unknown are forbidden. `device/protocol.py::validate_packet` + `GuardedTransport` enforce this.
- Never write firmware/EC/BIOS, never install or swap drivers (no Zadig/libusb), never stop/kill/uninstall MSI services.
- `hidapi` is imported in exactly one place: `device/transport.py::HidapiBackend`. GUI code must not touch HID or dxcam.
- All HID writes happen on the `DeviceWorker` thread (rate-limited, coalescing, duplicate suppression).
- Automated tests must never write to the physical keyboard; hardware tests are marked `@pytest.mark.hardware`.
- Captured frames stay in memory; never save or transmit them. Do not try to bypass DRM capture restrictions.
- Effects must stay photosensitivity-safe (`tests/test_app.py::test_effects_are_photosensitivity_safe`).
- Do not report simulated results as hardware results; update `docs/HARDWARE_VALIDATION.md` honestly.

## Layout

```
src/refletseher/
  device/    protocol (builders + validation), transport (HidapiBackend), mock, driver, worker, ratelimit, conflicts
  capture/   base (Region, MonitorInfo, reduce_frame), monitors (Win32/DisplayConfig/HDR), dxcam_backend, gdi_backend, synthetic
  color/     colorspace (OKLab), frame (letterbox, weights), clustering, extractors (5 modes), scene (cuts, flash guard), settings
  sync/      matching, transition, output, engine (ScreenSyncEngine thread)
  effects/   11 effects, hardware mapping, software render, runner
  profiles/  model (validation), presets (12), store (atomic JSON, import/export)
  automation/ rules + AutomationService
  core/      controller (AppController: the only API the UI uses), settings, autostart
  ui/        theme, widgets (keyboard_view, color_picker, common), pages/*, main_window
  i18n/      tr.json (primary) + en.json — every user-visible string goes through tr("key")
```

## Conventions

- New UI text: add the key to **both** `i18n/locales/tr.json` and `en.json` (tests check parity and usage).
- Timing: use `time.perf_counter` (Windows `time.monotonic` is 15.6 ms coarse); short waits use `time.sleep`.
- Colour math happens in OKLab; outputs are 8-bit sRGB values scaled linearly for brightness.
- Keep the mock (`device/mock.py`) behaviourally in sync with the real transport.
- Verified hardware facts live in `docs/HARDWARE_VALIDATION.md`; protocol details in `docs/HARDWARE_PROTOCOL.md`.
- Progress log: `docs/PROGRESS.md`.
