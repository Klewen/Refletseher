from __future__ import annotations

import pytest

from screensync.device import protocol as P
from screensync.device.driver import HardwareEffect, Ms1565Driver
from screensync.device.mock import MockBackend, MOCK_INFO
from screensync.device.transport import (
    AmbiguousDevice,
    DeviceInfo,
    DeviceNotFound,
    GuardedTransport,
    matches_expected,
    select_device,
)

VERIFIED_SELECT = (bytes([0x02, 0x01, 0x01])).ljust(64, b"\x00")
VERIFIED_EFFECT = (
    bytes([0x02, 0x02, 0x01, 0x58, 0x02, 0x00, 0x00, 0x0F, 0x01, 0x00, 0, 255, 0, 0, 100, 255, 0, 0])
).ljust(64, b"\x00")


def test_select_packet_is_byte_identical_to_verified_snippet():
    assert P.build_select_zones(0x01) == VERIFIED_SELECT


def test_steady_packet_is_byte_identical_to_verified_snippet():
    assert P.build_steady((255, 0, 0)) == VERIFIED_EFFECT


@pytest.mark.parametrize("mask", [0x01, 0x02, 0x04, 0x08, 0x0F, 0x05])
def test_zone_masks_valid(mask):
    pkt = P.build_select_zones(mask)
    assert len(pkt) == 64 and pkt[2] == mask
    P.validate_packet(pkt)


@pytest.mark.parametrize("mask", [0, 0x10, 0xFF, -1, True])
def test_zone_masks_invalid(mask):
    with pytest.raises(P.ProtocolViolation):
        P.build_select_zones(mask)


def test_zone_mask_constants():
    assert P.ZONE_MASKS == (0x01, 0x02, 0x04, 0x08)
    assert P.ALL_ZONES_MASK == 0x0F
    assert P.mask_for_zones([0, 3]) == 0x09
    assert P.zones_in_mask(0x0A) == [1, 3]


@pytest.mark.parametrize("color", [(256, 0, 0), (-1, 0, 0), (0, 0), (1.5, 0, 0), "red"])
def test_rgb_bounds(color):
    with pytest.raises(P.ProtocolViolation):
        P.build_steady(color)


@pytest.mark.parametrize("pid", [0xA0, 0xB0, 0xFF, 0x03, 0x00, 0x10])
def test_forbidden_or_unknown_packet_ids_rejected(pid):
    pkt = bytes([0x02, pid]).ljust(64, b"\x00")
    with pytest.raises(P.ProtocolViolation):
        P.validate_packet(pkt)


def test_flash_save_never_reaches_transport(mock_backend):
    transport = GuardedTransport(mock_backend.open(MOCK_INFO))
    with pytest.raises(P.ProtocolViolation, match="Forbidden"):
        transport.send_feature_report(bytes([0x02, 0xA0]).ljust(64, b"\x00"))
    assert mock_backend.packets == []


def test_packet_length_validation():
    with pytest.raises(P.ProtocolViolation):
        P.validate_packet(VERIFIED_SELECT[:63])
    with pytest.raises(P.ProtocolViolation):
        P.validate_packet(VERIFIED_SELECT + b"\x00")
    with pytest.raises(P.ProtocolViolation):
        P.validate_packet(bytes([0x01]) + VERIFIED_SELECT[1:])


def test_trailing_garbage_rejected():
    bad = bytearray(VERIFIED_EFFECT)
    bad[40] = 7
    with pytest.raises(P.ProtocolViolation):
        P.validate_packet(bytes(bad))
    bad_sel = bytearray(VERIFIED_SELECT)
    bad_sel[10] = 1
    with pytest.raises(P.ProtocolViolation):
        P.validate_packet(bytes(bad_sel))


def test_constant_bytes_enforced():
    bad = bytearray(VERIFIED_EFFECT)
    bad[7] = 0x0E
    with pytest.raises(P.ProtocolViolation):
        P.validate_packet(bytes(bad))


def test_effect_keyframes_and_speed():
    eff = HardwareEffect(P.EffectType.COLOR_CYCLE, ((255, 0, 0), (0, 255, 0), (0, 0, 255)), speed_cs=500)
    sel, pkt = eff.packets()
    assert sel[2] == 0x0F
    assert pkt[2] == P.EffectType.COLOR_CYCLE
    assert pkt[3] | pkt[4] << 8 == 500
    frames = P.decode_keyframes(pkt)
    assert frames[0].time == 0 and frames[-1].time == 100
    assert frames[-1].color == frames[0].color  # loop closes
    assert len(frames) == 4


def test_too_many_keyframes_rejected():
    with pytest.raises(P.ProtocolViolation):
        P.evenly_spaced_keyframes([(i, i, i) for i in range(11)])


def test_speed_limits():
    kf = P.evenly_spaced_keyframes([(255, 0, 0), (0, 0, 255)])
    with pytest.raises(P.ProtocolViolation):
        P.build_effect(P.EffectType.BREATH, kf, speed_cs=50)  # faster than 1 s
    with pytest.raises(P.ProtocolViolation):
        P.build_effect(P.EffectType.BREATH, kf, speed_cs=7000)
    with pytest.raises(P.ProtocolViolation):
        P.build_effect(P.EffectType.STEADY, kf, speed_cs=300)


def test_describe_packet():
    assert "SELECT" in P.describe_packet(VERIFIED_SELECT)
    assert "STEADY" in P.describe_packet(VERIFIED_EFFECT)


# --------------------------------------------------------------- discovery
def _info(**kw):
    base = dict(path=b"x", vendor_id=0x1462, product_id=0x1601, usage_page=0xFF, usage=1, interface_number=0)
    base.update(kw)
    return DeviceInfo(**base)


def test_vid_pid_matching():
    assert matches_expected(_info())
    assert not matches_expected(_info(vendor_id=0x1234))
    assert not matches_expected(_info(product_id=0x1602))
    assert not matches_expected(_info(usage_page=0x01, usage=6))  # e.g. a keyboard collection


def test_select_device_none_and_ambiguous():
    with pytest.raises(DeviceNotFound):
        select_device([])
    with pytest.raises(DeviceNotFound):
        select_device([_info(vendor_id=0x046D)])
    with pytest.raises(AmbiguousDevice):
        select_device([_info(path=b"a", interface_number=1), _info(path=b"b", interface_number=2)])
    exact = select_device([_info(path=b"a", interface_number=0), _info(path=b"b", usage_page=0xFF00, interface_number=1)])
    assert exact.path == b"a"


# ------------------------------------------------------------------ driver
def test_driver_sequence_and_ack(mock_backend):
    drv = Ms1565Driver(mock_backend.open(MOCK_INFO))
    drv.set_steady(0x01, (255, 0, 0))
    assert mock_backend.packets == [VERIFIED_SELECT, VERIFIED_EFFECT]
    assert mock_backend.ack_reads == 2  # read after each write, failure ignored
    assert mock_backend.zone_colors()[0] == (255, 0, 0)


def test_driver_groups_equal_colors(mock_backend):
    drv = Ms1565Driver(mock_backend.open(MOCK_INFO))
    n = drv.apply_zone_colors([(1, 2, 3)] * 4)
    assert n == 2
    assert mock_backend.packets[0][2] == 0x0F


def test_driver_short_write_raises(mock_backend):
    from screensync.device.transport import DeviceIOError

    mock_backend.short_write = 10
    drv = Ms1565Driver(mock_backend.open(MOCK_INFO))
    with pytest.raises(DeviceIOError):
        drv.select_zones(0x01)


def test_guard_rejects_other_reads(mock_backend):
    t = GuardedTransport(mock_backend.open(MOCK_INFO))
    with pytest.raises(P.ProtocolViolation):
        t.get_feature_report(0x02, 64)


def test_mock_backend_lists_only_expected_device():
    b = MockBackend()
    assert select_device(b.enumerate()) == MOCK_INFO
