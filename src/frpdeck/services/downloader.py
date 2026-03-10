"""Download helpers."""

from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen

from frpdeck.domain.errors import DownloadError


def download_file(url: str, destination: Path) -> Path:
    """Download a URL to a local file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "frpdeck/0.1"})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as handle:
            handle.write(response.read())
    except Exception as exc:
        raise DownloadError(f"failed to download {url}: {exc}") from exc
    return destination
