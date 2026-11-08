"""HID transport abstraction.

``HidapiBackend`` is the only place in the code base that imports ``hid``.
``MockBackend`` (see ``mock.py``) implements the same protocol for tests.
The GUI never talks to either directly; it goes through ``DeviceWorker``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from . import protocol as P

log = logging.getLogger(__name__)


class DeviceError(Exception):
    """Base class for recoverable device problems."""

    code = "device_error"


class DeviceNotFound(DeviceError):
    code = "not_found"


class AmbiguousDevice(DeviceError):
    code = "ambiguous"


class AccessDenied(DeviceError):
    code = "access_denied"


class DeviceIOError(DeviceError):
    code = "io_error"


class BackendUnavailable(DeviceError):
    code = "backend_unavailable"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    path: bytes
    vendor_id: int
    product_id: int
    product: str = ""
    manufacturer: str = ""
    serial: str = ""
    release: int = 0
    usage_page: int = 0
    usage: int = 0
    interface_number: int = -1

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.product}".strip() or "MS-1565"


@runtime_checkable
class HidTransport(Protocol):
    def send_feature_report(self, data: bytes) -> int: ...

    def get_feature_report(self, report_id: int, length: int) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class DeviceBackend(Protocol):
    name: str

    def enumerate(self) -> list[DeviceInfo]: ...

    def open(self, info: DeviceInfo) -> HidTransport: ...


def matches_expected(info: DeviceInfo) -> bool:
    """Strict identity check for the MS-1565 controller."""
    if info.vendor_id != P.VENDOR_ID or info.product_id != P.PRODUCT_ID:
        return False
    # Usage page is reported as 0xFF on the user's machine; accept the
    # canonical vendor page 0xFF00 too. Reject other collections.
    if info.usage_page not in (0, P.EXPECTED_USAGE_PAGE, 0xFF00):
        return False
    if info.usage not in (0, P.EXPECTED_USAGE):
        return False
    return True


def select_device(candidates: list[DeviceInfo]) -> DeviceInfo:
    matches = [c for c in candidates if matches_expected(c)]
    if not matches:
        raise DeviceNotFound("MSI MysticLight MS-1565 (1462:1601) was not found")
    if len(matches) > 1:
        # Prefer the exact verified collection if several are exposed.
        exact = [
            m
            for m in matches
            if m.usage_page == P.EXPECTED_USAGE_PAGE
            and m.usage == P.EXPECTED_USAGE
            and m.interface_number == P.EXPECTED_INTERFACE
        ]
        if len(exact) == 1:
            return exact[0]
        raise AmbiguousDevice(f"Expected 1 matching HID device, found {len(matches)}")
    return matches[0]


class GuardedTransport:
    """Validates every outgoing packet against the protocol allow-list."""

    def __init__(self, inner: HidTransport, trace: bool = False) -> None:
        self._inner = inner
        self._trace = trace
        self.closed = False

    def send_feature_report(self, data: bytes) -> int:
        P.validate_packet(data)  # raises ProtocolViolation, never reaches hid
        if self._trace:
            log.debug("HID >> %s | %s", P.describe_packet(data), data[:24].hex(" "))
        return self._inner.send_feature_report(bytes(data))

    def get_feature_report(self, report_id: int, length: int) -> bytes:
        if report_id != P.REPORT_ID_ACK or length != P.PACKET_SIZE:
            raise P.ProtocolViolation("Only feature report 0x01 / 64 bytes may be read")
        return self._inner.get_feature_report(report_id, length)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._inner.close()


class _HidapiTransport:
    def __init__(self, dev: Any) -> None:
        self._dev = dev

    def send_feature_report(self, data: bytes) -> int:
        try:
            return int(self._dev.send_feature_report(data))
        except (OSError, ValueError) as exc:
            raise DeviceIOError(f"send_feature_report failed: {exc}") from exc

    def get_feature_report(self, report_id: int, length: int) -> bytes:
        try:
            return bytes(self._dev.get_feature_report(report_id, length))
        except (OSError, ValueError) as exc:
            raise DeviceIOError(f"get_feature_report failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:  # pragma: no cover - best effort
            log.debug("hid close failed", exc_info=True)


class HidapiBackend:
    """Real Windows HID access via cython-hidapi (``pip/uv: hidapi``)."""

    name = "hidapi"

    def __init__(self) -> None:
        try:
            import hid  # noqa: PLC0415  (only import site of hidapi)
        except ImportError as exc:  # pragma: no cover - depends on env
            raise BackendUnavailable("hidapi is not installed") from exc
        self._hid = hid

    def enumerate(self) -> list[DeviceInfo]:
        out: list[DeviceInfo] = []
        try:
            raw = self._hid.enumerate(P.VENDOR_ID, P.PRODUCT_ID)
        except Exception as exc:  # pragma: no cover
            raise DeviceIOError(f"HID enumeration failed: {exc}") from exc
        for d in raw:
            out.append(
                DeviceInfo(
                    path=d.get("path", b""),
                    vendor_id=int(d.get("vendor_id", 0)),
                    product_id=int(d.get("product_id", 0)),
                    product=d.get("product_string") or "",
                    manufacturer=d.get("manufacturer_string") or "",
                    serial=d.get("serial_number") or "",
                    release=int(d.get("release_number", 0) or 0),
                    usage_page=int(d.get("usage_page", 0) or 0),
                    usage=int(d.get("usage", 0) or 0),
                    interface_number=int(d.get("interface_number", -1)),
                )
            )
        return out

    def open(self, info: DeviceInfo) -> HidTransport:
        if not matches_expected(info):
            raise DeviceNotFound("Refusing to open a device that is not the MS-1565")
        dev = self._hid.device()
        try:
            dev.open_path(info.path)
        except OSError as exc:
            msg = str(exc).lower()
            if "access" in msg or "denied" in msg:
                raise AccessDenied(f"Access to the HID device was denied: {exc}") from exc
            raise DeviceIOError(f"Could not open HID device: {exc}") from exc
        return _HidapiTransport(dev)
