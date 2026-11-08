"""Application entry point.

    uv run refletseher            # normal start
    uv run refletseher --tray     # start hidden in the system tray
    uv run refletseher --simulate # no HID access, simulated keyboard
"""

from __future__ import annotations

import os

# Must happen before NumPy/OpenCV are imported: our matrices are tiny, and a
# 24-thread OpenBLAS pool commits ~30 MB per thread for nothing.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import getpass  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402

from . import __version__
from .logging_setup import setup_logging
from .paths import profiles_file, settings_file

log = logging.getLogger("refletseher")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="refletseher", description="Refletseher")
    ap.add_argument("--tray", action="store_true", help="start minimised to the system tray")
    ap.add_argument("--simulate", action="store_true", help="do not access the HID device (simulated keyboard)")
    ap.add_argument("--debug", action="store_true", help="verbose logging incl. HID packet trace")
    ap.add_argument("--profile", metavar="ID", help="apply this profile id after start (e.g. preset_cinematic)")
    ap.add_argument("--quit", action="store_true", help="ask a running instance to shut down cleanly")
    ap.add_argument("--version", action="version", version=f"Refletseher {__version__}")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    from .core.settings import SettingsStore

    settings = SettingsStore(settings_file())
    setup_logging(debug=args.debug or settings.settings.debug_logging)
    log.info("Refletseher %s starting (python %s)", __version__, sys.version.split()[0])

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Refletseher")
    app.setOrganizationName("Refletseher")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    # ---- single instance: two instances must never drive the HID device
    server_name = f"Refletseher-{getpass.getuser()}"
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(300):
        sock.write(b"quit" if args.quit else b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        log.info("Another instance is running - sent %s", "quit" if args.quit else "show")
        return 0
    if args.quit:
        log.info("--quit: no running instance")
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    from .core import autostart

    if getattr(sys, "frozen", False):
        # v1.0.x was "ScreenSync RGB": move its start-with-Windows entry over
        autostart.migrate_legacy()

    from .i18n import set_language
    from .profiles.store import ProfileStore
    from .ui.theme import apply_theme

    set_language(settings.settings.language)
    apply_theme(app, settings.settings.theme)
    profiles = ProfileStore(profiles_file())
    for err in profiles.load_errors:
        log.warning(err)

    import cv2

    cv2.setNumThreads(1)  # 160x90 frames: thread pools only add wake-ups

    from .core.controller import AppController
    from .device.mock import MockBackend

    backend_factory = None
    if args.simulate:
        shared = MockBackend()
        backend_factory = lambda: shared  # noqa: E731
        log.info("Simulation mode: HID access disabled for this session")
    controller = AppController(settings, profiles, backend_factory=backend_factory, simulated=args.simulate)
    controller.start(apply_startup_profile=not args.profile)
    if args.profile and not controller.apply_profile(args.profile, source="cli"):
        log.warning("--profile %s: no such profile", args.profile)

    from .ui.main_window import MainWindow

    window = MainWindow(controller)

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(300)
        msg = bytes(conn.readAll()).strip()
        conn.disconnectFromServer()
        if msg == b"quit":
            log.info("Quit requested by another process")
            window.quit_app()
        else:
            window.bring_to_front()

    server.newConnection.connect(_on_new_connection)
    app.aboutToQuit.connect(window.shutdown)
    if not (args.tray or settings.settings.start_minimized):
        window.show()
    code = app.exec()
    window.shutdown()
    server.close()
    log.info("Refletseher exited with code %s", code)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
