"""Human-readable CLI download progress helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


_NO_TOTAL_PROGRESS_STEP = 1024 * 1024


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ["B", "KiB", "MiB", "GiB"]:
        if size < 1024.0 or unit == "GiB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size_bytes} B"


@dataclass(slots=True)
class CliDownloadProgressReporter:
    """Emit simple download progress messages for CLI commands."""

    echo: Callable[[str], None]
    _last_percent_bucket: int = -1
    _last_size_bucket: int = -1

    def start(self, asset_name: str) -> None:
        self._last_percent_bucket = -1
        self._last_size_bucket = -1
        self.echo(f"Downloading {asset_name}...")

    def update(self, downloaded_bytes: int, total_bytes: int | None) -> None:
        if total_bytes is not None and total_bytes > 0:
            bucket = min(10, downloaded_bytes * 10 // total_bytes)
            if bucket <= 0 or bucket == self._last_percent_bucket:
                return
            self._last_percent_bucket = bucket
            self.echo(
                "Download progress: "
                f"{bucket * 10}% ({_format_size(downloaded_bytes)} / {_format_size(total_bytes)})"
            )
            return

        bucket = downloaded_bytes // _NO_TOTAL_PROGRESS_STEP
        if bucket <= 0 or bucket == self._last_size_bucket:
            return
        self._last_size_bucket = bucket
        self.echo(f"Downloaded {_format_size(downloaded_bytes)}...")

    def finish(self, asset_name: str) -> None:
        self.echo(f"OK: Downloaded {asset_name}.")
