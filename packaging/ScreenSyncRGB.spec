# PyInstaller spec for ScreenSync RGB (Windows, one-folder, windowed).
#
#   uv run pyinstaller packaging/ScreenSyncRGB.spec --noconfirm --clean
#
# One-folder (not one-file): starts faster and does not unpack into %TEMP%
# on every launch, which also avoids a common antivirus heuristic. UPX is
# disabled for the same reason. Nothing is obfuscated.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

hidden = []
hidden += collect_submodules("dxcam")
hidden += collect_submodules("winrt")
hidden += collect_submodules("screensync")
hidden += ["hid", "comtypes", "comtypes.client", "psutil", "mss", "mss.windows"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[(str(SRC / "screensync" / "i18n" / "locales"), "screensync/i18n/locales")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "IPython", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
# Not needed at runtime: OpenCV's FFmpeg video I/O (we only resize frames) and
# Qt's software OpenGL fallback (the UI uses QtWidgets raster painting).
_DROP = ("opencv_videoio_ffmpeg", "opengl32sw")
a.binaries = [b for b in a.binaries if not any(d in b[0].lower() for d in _DROP)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScreenSyncRGB",
    icon=str(ROOT / "packaging" / "icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    upx=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ScreenSyncRGB")
