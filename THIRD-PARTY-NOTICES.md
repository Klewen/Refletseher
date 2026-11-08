# Third-party notices

Refletseher itself is licensed under the [MIT License](LICENSE). The Windows release (`Refletseher-win64.zip`)
bundles the following third-party components. Each component remains under its own license.

| Component | Version | License | Project |
|---|---|---|---|
| Python runtime | 3.12 | PSF-2.0 | https://www.python.org |
| Qt for Python (PySide6-Essentials, Shiboken6) and Qt 6 libraries | 6.12 | LGPL-3.0 (used under LGPLv3) | https://www.qt.io/qt-for-python |
| NumPy (incl. OpenBLAS) | 2.5 | BSD-3-Clause (and compatible permissive licenses) | https://numpy.org |
| OpenCV (opencv-python-headless) | 5.0 | Apache-2.0 | https://opencv.org |
| hidapi / cython-hidapi | 0.15 | BSD-style (used under the BSD option of its triple license) | https://github.com/trezor/cython-hidapi |
| DXcam | 0.3 | MIT | https://github.com/ra1nty/DXcam |
| python-mss | 10.2 | MIT | https://github.com/BoboTiG/python-mss |
| psutil | 7.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| comtypes | 1.4 | MIT | https://github.com/enthought/comtypes |
| PyWinRT (winrt-runtime and Windows.* projections) | 4.x | MIT | https://github.com/pywinrt/pywinrt |
| PyInstaller bootloader | 6.22 | GPL-2.0-or-later with bootloader exception | https://pyinstaller.org |

## LGPL (Qt / PySide6)

Qt and PySide6 are used under the GNU Lesser General Public License v3. In the release they ship as separate, unmodified dynamic
libraries in the `_internal` folder (`Qt6*.dll`, `PySide6`, `shiboken6`), so you can replace them with compatible builds of your own.
Their source code is available from https://download.qt.io and https://code.qt.io/cgit/pyside/pyside-setup.git. The full LGPL-3.0
text is at https://www.gnu.org/licenses/lgpl-3.0.html.

## PyInstaller

The PyInstaller bootloader is distributed under the GPL with an exception that explicitly allows bundling and distributing
applications built with it under any license.

## Trademarks

MSI, Mystic Light and Katana are trademarks of Micro-Star International Co., Ltd. Refletseher is not affiliated with MSI.
