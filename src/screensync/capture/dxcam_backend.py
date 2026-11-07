"""DXGI Desktop Duplication / Windows Graphics Capture through ``dxcam``.

* ``dxgi``  - Desktop Duplication API: lowest overhead, only delivers a
  frame when the screen changed (free idle optimisation), no cursor.
* ``winrt`` - Windows.Graphics.Capture: robust with some fullscreen apps.

dxcam's built-in recovery retries forever with sleeps (e.g. while the lock
screen is shown). We replace it per camera instance with an exception so
that *our* engine performs bounded, interruptible backoff instead.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .base import CaptureAccessLost, CaptureError, CapturedFrame, CaptureUnavailable, MonitorGone, MonitorInfo, Region, reduce_frame

log = logging.getLogger(__name__)


def _raise_access_lost(*_a: Any, **_k: Any) -> None:
    raise CaptureAccessLost("Desktop duplication access lost (lock screen, UAC, mode switch or exclusive fullscreen)")


class DxcamBackend:
    def __init__(self, kind: str = "dxgi") -> None:
        if kind not in ("dxgi", "winrt"):
            raise ValueError(kind)
        self.kind = kind
        self.name = kind
        self._cam: Any = None
        self._size = (0, 0)
        try:
            import dxcam  # noqa: F401,PLC0415
            from dxcam.dxcam import DXCamera, Device, Output  # noqa: PLC0415
            from dxcam.util.io import enum_dxgi_adapters  # noqa: PLC0415
        except Exception as exc:  # pragma: no cover - env specific
            raise CaptureUnavailable(f"dxcam not available: {exc}") from exc
        if kind == "winrt":
            try:
                import winrt.windows.graphics.capture  # noqa: F401,PLC0415
            except Exception as exc:
                raise CaptureUnavailable("Windows Graphics Capture modules are not installed") from exc
        self._DXCamera, self._Device, self._Output, self._enum = DXCamera, Device, Output, enum_dxgi_adapters

    def _find_output(self, monitor: MonitorInfo) -> tuple[Any, Any]:
        for p_adapter in self._enum():
            device = self._Device(p_adapter)
            for p_output in device.enum_outputs():
                out = self._Output(p_output)
                if out.devicename == monitor.id:
                    return device, out
        raise MonitorGone(f"No DXGI output for {monitor.id}")

    def open(self, monitor: MonitorInfo, region: Region) -> None:
        self.close()
        try:
            device, output = self._find_output(monitor)
            w, h = output.resolution
            pixel_region = None if region.is_full else region.to_pixels(w, h)
            cam = self._DXCamera(
                output=output,
                device=device,
                region=pixel_region,
                output_color="BGRA",
                max_buffer_len=2,
                backend=self.kind,
                processor_backend="numpy",
            )
        except CaptureError:
            raise
        except Exception as exc:
            msg = str(exc)
            if "0x887A0026" in msg.upper() or "ACCESS" in msg.upper():
                raise CaptureAccessLost(msg) from exc
            raise CaptureError(f"{self.kind} capture could not start: {exc}") from exc
        cam._recover_output = _raise_access_lost  # bounded recovery (see module doc)
        self._cam = cam
        self._size = (pixel_region[2] - pixel_region[0], pixel_region[3] - pixel_region[1]) if pixel_region else (w, h)
        time.sleep(0.05)

    def grab(self) -> CapturedFrame | None:
        cam = self._cam
        if cam is None:
            raise CaptureError("capture not open")
        try:
            frame = cam.grab(copy=False)
        except CaptureError:
            raise
        except Exception as exc:
            raise CaptureAccessLost(f"{self.kind} grab failed: {exc}") from exc
        if frame is None:
            return None
        small = reduce_frame(frame, channels_bgr=True)
        return CapturedFrame(small, self._size, time.perf_counter())

    def close(self) -> None:
        cam, self._cam = self._cam, None
        if cam is not None:
            try:
                cam.release()
            except Exception:  # pragma: no cover
                log.debug("dxcam release failed", exc_info=True)
