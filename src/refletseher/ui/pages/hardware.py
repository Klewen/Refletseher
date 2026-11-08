"""Hardware status: connection, HID statistics, conflicts, safety summary."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout

from ...core.controller import AppSnapshot
from ...device import protocol as P
from ...device.worker import ConnectionState
from ...i18n import tr
from ...rgb import to_hex
from ..base import Page, UiContext, device_status, fmt_age, mode_text
from ..widgets.common import Card, ColorChip, StatusPill, button, label


class HardwarePage(Page):
    key = "hardware"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx, tr("hardware.title"), tr("hardware.subtitle"))
        self.actions.addWidget(button(tr("hardware.rescan_conflicts"), on_click=self._rescan))
        self.actions.addWidget(button(tr("hardware.resend"), on_click=self.controller.worker.invalidate))
        self.actions.addWidget(button(tr("hardware.reconnect"), primary=True, on_click=self.controller.reconnect))

        top = QHBoxLayout()
        top.setSpacing(16)
        status = Card(tr("hardware.status"))
        self.pill = StatusPill()
        status.header.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(8)
        self.rows: dict[str, object] = {}
        keys = ["detected", "access", "connection", "mode", "backend", "device", "last_success", "errors", "last_error",
                "packets", "frames", "duplicates", "coalesced", "rate", "write_ms", "frame_ms", "acks", "update_hz"]
        for i, k in enumerate(keys):
            g.addWidget(label(tr(f"hardware.{k}"), secondary=True), i, 0)
            v = label("—")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setWordWrap(True)
            g.addWidget(v, i, 1)
            self.rows[k] = v
        g.setColumnStretch(1, 1)
        status.add_layout(g)
        top.addWidget(status, 3)

        side = Card(tr("hardware.colors"), tr("hardware.colors_hint"))
        cg = QGridLayout()
        cg.setSpacing(8)
        cg.addWidget(label(tr("hardware.intended"), caption=True), 1, 0)
        cg.addWidget(label(tr("hardware.confirmed"), caption=True), 3, 0)
        self.intended = [ColorChip(None, 30) for _ in range(4)]
        self.confirmed = [ColorChip(None, 30) for _ in range(4)]
        self.intended_hex = [label("—", caption=True) for _ in range(4)]
        self.confirmed_hex = [label("—", caption=True) for _ in range(4)]
        for i in range(4):
            cg.addWidget(label(tr("zone.n", n=i + 1), caption=True), 0, i + 1, Qt.AlignmentFlag.AlignHCenter)
            cg.addWidget(self.intended[i], 1, i + 1)
            cg.addWidget(self.intended_hex[i], 2, i + 1, Qt.AlignmentFlag.AlignHCenter)
            cg.addWidget(self.confirmed[i], 3, i + 1)
            cg.addWidget(self.confirmed_hex[i], 4, i + 1, Qt.AlignmentFlag.AlignHCenter)
        side.add_layout(cg)
        side.add(label(tr("hardware.no_readback"), caption=True, wrap=True))

        conflict = Card(tr("hardware.conflict"))
        self.conflict_pill = StatusPill()
        conflict.header.addWidget(self.conflict_pill, 0, Qt.AlignmentFlag.AlignTop)
        self.conflict_text = label("", wrap=True)
        conflict.add(self.conflict_text)
        conflict.add(label(tr("hardware.conflict_steps"), caption=True, wrap=True))

        col = Card(tr("hardware.safety"))
        allowed = ", ".join(f"0x{p:02X}" for p in sorted(P.ALLOWED_PACKET_IDS))
        forbidden = ", ".join(f"0x{p:02X}" for p in sorted(P.FORBIDDEN_PACKET_IDS))
        col.add(label(tr("hardware.safety_text", allowed=allowed, forbidden=forbidden), wrap=True, secondary=True))
        verified = ", ".join(e.name.lower() for e in sorted(P.HARDWARE_VERIFIED_EFFECTS))
        col.add(label(tr("hardware.verified_effects", effects=verified), caption=True, wrap=True))

        top.addWidget(side, 2)
        self.content.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        bottom.addWidget(conflict, 1)
        bottom.addWidget(col, 1)
        self.content.addLayout(bottom)
        self.content.addStretch(1)

    def _rescan(self) -> None:
        self.controller.refresh_conflicts()

    def update_snapshot(self, snap: AppSnapshot) -> None:
        d = snap.device
        text, level = device_status(d, snap.simulation_backend)
        self.pill.set_status(text, level)
        yes, no = tr("common.yes"), tr("common.no")
        found = d.device is not None and d.state != ConnectionState.NOT_FOUND
        r = self.rows
        r["detected"].setText(yes if found else no)
        access = {ConnectionState.ACCESS_DENIED: tr("hardware.access_denied")}.get(d.state, tr("hardware.access_ok") if d.connected else "—")
        r["access"].setText(access)
        r["connection"].setText(text + (f" · {tr('hardware.retry_in', s=f'{d.retry_in_s:.0f}')}" if d.retry_in_s > 0 else ""))
        r["mode"].setText(mode_text(snap))
        r["backend"].setText(tr("hardware.backend_sim") if snap.simulation_backend else "hidapi (Windows HID)")
        r["device"].setText(f"{d.device.label} · VID 0x{d.device.vendor_id:04X} PID 0x{d.device.product_id:04X} · "
                            f"UsagePage 0x{d.device.usage_page:X} Usage {d.device.usage}" if d.device else "—")
        r["last_success"].setText(fmt_age(d.last_written_at))
        r["errors"].setText(f"{d.error_count} ({tr('hardware.consecutive', n=d.consecutive_errors)})")
        r["last_error"].setText(d.last_error or "—")
        r["packets"].setText(f"{d.packets_sent}  ·  {d.packets_per_sec:.1f}/s")
        r["frames"].setText(str(d.frames_applied))
        r["duplicates"].setText(str(d.duplicates_skipped))
        r["coalesced"].setText(str(d.frames_coalesced))
        r["rate"].setText(f"{d.updates_per_sec:.1f} /s")
        r["write_ms"].setText(f"{d.write_latency_ms:.2f} ms")
        r["frame_ms"].setText(f"{d.frame_latency_ms:.1f} ms")
        r["acks"].setText(tr("hardware.ack_failures", n=d.ack_failures))
        r["update_hz"].setText(f"{d.update_hz:.0f} Hz")
        intended = snap.intended or (None,) * 4
        for i in range(4):
            self.intended[i].set_color(intended[i])
            self.intended_hex[i].setText(to_hex(intended[i]) if intended[i] else "—")
            c = d.confirmed_zone_colors[i]
            self.confirmed[i].set_color(c)
            self.confirmed_hex[i].setText(to_hex(c) if c else ("HW-FX" if d.confirmed_effect else "—"))
        rep = snap.conflict
        if not rep.checked:
            self.conflict_pill.set_status(tr("hardware.conflict_unknown"), "muted")
            self.conflict_text.setText("")
        elif rep.has_conflict:
            self.conflict_pill.set_status(tr("hardware.conflict_found"), "warning")
            self.conflict_text.setText(tr("hardware.conflict_list", apps=", ".join(rep.lighting + rep.infrastructure)))
        else:
            self.conflict_pill.set_status(tr("hardware.conflict_none"), "success")
            infra = ", ".join(rep.infrastructure)
            self.conflict_text.setText(tr("hardware.conflict_infra", apps=infra) if infra else tr("hardware.conflict_clear"))
