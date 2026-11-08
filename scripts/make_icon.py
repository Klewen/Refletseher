"""Render the application icon to packaging/icon.ico (+ PNG preview).

    uv run python scripts/make_icon.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    from screensync.ui.icon import render_icon

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    render_icon(size).save(buf, "PNG")
    buf.close()
    return bytes(data)


def write_ico(path: Path) -> None:
    images = [(s, png_bytes(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    path.write_bytes(header + entries + blobs)


def main() -> int:
    _app = QGuiApplication(sys.argv[:1])
    out = Path(__file__).resolve().parents[1] / "packaging"
    out.mkdir(exist_ok=True)
    write_ico(out / "icon.ico")
    (out / "icon.png").write_bytes(png_bytes(256))
    docs = out.parent / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "logo.png").write_bytes(png_bytes(512))
    print("wrote", out / "icon.ico", "and", docs / "logo.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
