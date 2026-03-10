"""Environment diagnostics."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path

from frpdeck.domain.state import NodeBase
from frpdeck.services.runtime import command_exists


@dataclass(slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def run_doctor(instance_dir: Path | None, node: NodeBase | None = None) -> list[DoctorCheck]:
    """Return diagnostic results."""
    systemctl_available = command_exists("systemctl")
    checks = [
        DoctorCheck("platform", platform.system() == "Linux", f"detected {platform.system()}"),
        DoctorCheck(
            "systemctl",
            systemctl_available,
            "systemctl available in PATH" if systemctl_available else "systemctl not found; apply/restart/status will not work in this environment",
        ),
        DoctorCheck("external tools", True, "tar/curl not required; frpdeck uses Python stdlib for download and extraction"),
    ]
    if instance_dir is not None:
        checks.extend(
            [
                DoctorCheck("node.yaml", (instance_dir / "node.yaml").exists(), f"expected {(instance_dir / 'node.yaml').resolve()}"),
                DoctorCheck(
                    "state dir",
                    (instance_dir / "state").exists(),
                    f"expected {(instance_dir / 'state').resolve()}",
                ),
            ]
        )
    if node is not None:
        paths = node.resolved_paths(instance_dir or Path.cwd())
        checks.extend(
            [
                DoctorCheck(
                    "install_dir write",
                    _has_write_access(paths.install_dir),
                    f"target {paths.install_dir}; use sudo or adjust paths.install_dir if this fails",
                ),
                DoctorCheck(
                    "systemd_unit_dir write",
                    os.access(paths.systemd_unit_dir, os.W_OK),
                    f"target {paths.systemd_unit_dir}; use sudo or adjust paths.systemd_unit_dir if this fails",
                ),
            ]
        )
    return checks


def _has_write_access(target: Path) -> bool:
    probe = target if target.exists() else target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)
