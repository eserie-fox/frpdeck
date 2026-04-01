"""Download helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.request import Request, urlopen

from frpdeck.domain.errors import DownloadError


DownloadProgressCallback = Callable[[int, int | None], None]

_CHUNK_SIZE = 64 * 1024


def download_file(
    url: str,
    destination: Path,
    *,
    progress: DownloadProgressCallback | None = None,
) -> Path:
    """Download a URL to a local file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "frpdeck/0.1"})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as handle:
            total_bytes = _parse_content_length(response.headers.get("Content-Length"))
            downloaded_bytes = 0
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded_bytes += len(chunk)
                if progress is not None:
                    progress(downloaded_bytes, total_bytes)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise DownloadError(f"failed to download {url}: {exc}") from exc
    return destination


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        total_bytes = int(value)
    except ValueError:
        return None
    return total_bytes if total_bytes > 0 else None
