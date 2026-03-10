"""Backup helpers for upgrade and apply workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil


def backup_file_if_exists(source: Path, backup_dir: Path) -> Path | None:
    """Copy a file into the backup directory if it exists."""
    if not source.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target = backup_dir / f"{source.name}.{timestamp}.bak"
    shutil.copy2(source, target)
    return target
