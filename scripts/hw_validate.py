"""Hardware validation for the MSI MysticLight MS-1565 controller.

Only the allow-listed, non-persistent commands are used (0x01 select zones,
0x02 set effect). Nothing is ever saved to flash. Run from the project root:

    uv run python scripts/hw_validate.py snippet      # offline: packet == verified bytes
    uv run python scripts/hw_validate.py probe        # enumerate + open + close, no writes
    uv run python scripts/hw_validate.py zones        # Z1 red, Z2 green, Z3 blue, Z4 white
    uv run python scripts/hw_validate.py latency      # gentle colour ramps at 5/10/15 Hz
    uv run python scripts/hw_validate.py effects --seconds 240
    uv run python scripts/hw_validate.py color FF0000 # all zones one colour
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refletseher.device import protocol as P  # noqa: E402
from refletseher.device.driver import HardwareEffect, Ms1565Driver  # noqa: E402
from refletseher.device.transport import HidapiBackend, select_device  # noqa: E402
from refletseher.rgb import from_hex, hsv_to_rgb  # noqa: E402

VERIFIED_EFFECT_PAYLOAD = [0x01, 0x58, 0x02, 0x00, 0x00, 0x0F, 0x01, 0x00, 0, 255, 0, 0, 100, 255, 0, 0]
TEST_COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]


def verified_packet(packet_id: int, payload: list[int]) -> bytes:
    return (bytes([0x02, packet_id]) + bytes(payload)).ljust(64, b"\x00")


def cmd_snippet(_: argparse.Namespace) -> dict:
    sel_ok = P.build_select_zones(0x01) == verified_packet(0x01, [0x01])
    eff_ok = P.build_steady((255, 0, 0)) == verified_packet(0x02, VERIFIED_EFFECT_PAYLOAD)
    print(f"select packet identical to verified snippet: {sel_ok}")
    print(f"steady packet identical to verified snippet: {eff_ok}")
    return {"select_identical": sel_ok, "steady_identical": eff_ok}


def open_driver() -> tuple[Ms1565Driver, object]:
    backend = HidapiBackend()
    info = select_device(backend.enumerate())
    print(f"device: {info.label} path={info.path!r} usage_page=0x{info.usage_page:X} usage={info.usage}")
    return Ms1565Driver(backend.open(info), ack_read=True), info


def cmd_probe(_: argparse.Namespace) -> dict:
    drv, info = open_driver()
    drv.close()
    print("open/close OK (no packets written)")
    return {"device": info.label}


def cmd_zones(_: argparse.Namespace) -> dict:
    drv, _ = open_driver()
    try:
        t0 = time.perf_counter()
        for z, color in enumerate(TEST_COLORS):
            drv.set_steady(P.ZONE_MASKS[z], color)
        dt = (time.perf_counter() - t0) * 1000
    finally:
        drv.close()
    print(f"4 zones written in {dt:.1f} ms ({drv.stats.packets} packets, acks ok={drv.stats.ack_ok} failed={drv.stats.ack_failed})")
    print("Expected left->right: RED | GREEN | BLUE | WHITE")
    return {"frame_ms": dt, "packets": drv.stats.packets, "ack_ok": drv.stats.ack_ok, "ack_failed": drv.stats.ack_failed}


def cmd_latency(args: argparse.Namespace) -> dict:
    """Slow hue drift (no flashing). Every frame changes all 4 zones -> 8 packets."""
    drv, _ = open_driver()
    results = {}
    try:
        for hz in args.rates:
            frame_ms: list[float] = []
            drv.stats.latencies_ms.clear()
            period = 1.0 / hz
            n = int(hz * args.seconds)
            start = time.perf_counter()
            late = 0
            for i in range(n):
                target = start + i * period
                now = time.perf_counter()
                if target > now:
                    time.sleep(target - now)
                elif now - target > period:
                    late += 1
                base = (i / max(1, n - 1)) * 60.0 + (hz * 7)
                colors = [hsv_to_rgb(base + z * 25, 0.9, 0.8) for z in range(4)]
                t0 = time.perf_counter()
                for z in range(4):
                    drv.set_steady(P.ZONE_MASKS[z], colors[z])
                frame_ms.append((time.perf_counter() - t0) * 1000)
            elapsed = time.perf_counter() - start
            pk = list(drv.stats.latencies_ms)
            res = {
                "target_hz": hz,
                "frames": n,
                "achieved_hz": round(n / elapsed, 2),
                "frame_ms_median": round(statistics.median(frame_ms), 2),
                "frame_ms_p95": round(sorted(frame_ms)[int(0.95 * len(frame_ms)) - 1], 2),
                "frame_ms_max": round(max(frame_ms), 2),
                "packet_ms_median": round(statistics.median(pk), 3),
                "packet_ms_p95": round(sorted(pk)[int(0.95 * len(pk)) - 1], 3),
                "late_frames": late,
                "duty_cycle_pct": round(sum(frame_ms) / (elapsed * 1000) * 100, 1),
            }
            results[str(hz)] = res
            print(json.dumps(res))
        drv.apply_zone_colors([(0, 80, 255)] * 4)
    finally:
        drv.close()
    print(f"ack ok={drv.stats.ack_ok} failed={drv.stats.ack_failed}")
    return {"rates": results, "ack_ok": drv.stats.ack_ok, "ack_failed": drv.stats.ack_failed}


def cmd_effects(args: argparse.Namespace) -> dict:
    """Loops: static test colours -> breath -> colour cycle -> wave (8 s each)."""
    rainbow = [hsv_to_rgb(h, 1, 1) for h in (0, 60, 120, 180, 240, 300)]
    phases = [
        ("static", None),
        ("breath", HardwareEffect(P.EffectType.BREATH, ((255, 0, 0), (0, 0, 255)), speed_cs=300)),
        ("cycle", HardwareEffect(P.EffectType.COLOR_CYCLE, tuple(rainbow), speed_cs=600)),
        ("wave", HardwareEffect(P.EffectType.COLOR_WAVE, tuple(rainbow), speed_cs=300,
                                direction=P.WaveDirection.LEFT_TO_RIGHT)),
    ]
    drv, _ = open_driver()
    end = time.monotonic() + args.seconds
    try:
        while time.monotonic() < end:
            for name, eff in phases:
                if time.monotonic() >= end:
                    break
                print(f"[{time.strftime('%H:%M:%S')}] phase {name}", flush=True)
                if eff is None:
                    for z, c in enumerate(TEST_COLORS):
                        drv.set_steady(P.ZONE_MASKS[z], c)
                else:
                    drv.apply_effect(eff)
                time.sleep(min(8.0, max(0.0, end - time.monotonic())))
        for z, c in enumerate(TEST_COLORS):
            drv.set_steady(P.ZONE_MASKS[z], c)
    finally:
        drv.close()
    return {"done": True}


def cmd_color(args: argparse.Namespace) -> dict:
    color = from_hex(args.hex)
    drv, _ = open_driver()
    try:
        drv.set_steady(P.ALL_ZONES_MASK, color)
    finally:
        drv.close()
    return {"color": args.hex}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, help="append results to this JSON file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snippet")
    sub.add_parser("probe")
    sub.add_parser("zones")
    lat = sub.add_parser("latency")
    lat.add_argument("--rates", type=float, nargs="+", default=[5, 10, 15])
    lat.add_argument("--seconds", type=float, default=4.0)
    eff = sub.add_parser("effects")
    eff.add_argument("--seconds", type=float, default=240.0)
    col = sub.add_parser("color")
    col.add_argument("hex")
    args = ap.parse_args()
    fn = {"snippet": cmd_snippet, "probe": cmd_probe, "zones": cmd_zones, "latency": cmd_latency,
          "effects": cmd_effects, "color": cmd_color}[args.cmd]
    result = fn(args)
    if args.json:
        data = json.loads(args.json.read_text("utf-8")) if args.json.exists() else {}
        data[args.cmd] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), **result}
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, indent=2), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
