"""Device layer: MS-1565 protocol, transports, driver and the HID worker."""

from .driver import HardwareEffect, Ms1565Driver
from .protocol import EffectType, ProtocolViolation, WaveDirection, Zone
from .transport import DeviceBackend, DeviceInfo, HidapiBackend
from .worker import ConnectionState, DeviceSnapshot, DeviceWorker, WorkerConfig

__all__ = [
    "ConnectionState",
    "DeviceBackend",
    "DeviceInfo",
    "DeviceSnapshot",
    "DeviceWorker",
    "EffectType",
    "HardwareEffect",
    "HidapiBackend",
    "Ms1565Driver",
    "ProtocolViolation",
    "WaveDirection",
    "WorkerConfig",
    "Zone",
]
