"""GitHub release metadata lookup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from frpdeck.domain.errors import DownloadError, ReleaseNotFoundError
from frpdeck.domain.install import BinaryConfig
from frpdeck.domain.versioning import normalize_version


GITHUB_LATEST_URL = "https://api.github.com/repos/fatedier/frp/releases/latest"
GITHUB_TAG_URL_TEMPLATE = "https://api.github.com/repos/fatedier/frp/releases/tags/v{version}"

ARCH_ALIASES: dict[str, str] = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


@dataclass(slots=True)
class ReleaseInfo:
    version: str
    asset_name: str
    asset_url: str


def get_release(binary: BinaryConfig) -> ReleaseInfo:
    """Resolve the target release for a binary, honoring pinned versions."""
    if binary.version:
        return get_release_by_version(binary, binary.version)
    return get_latest_release(binary)


def get_latest_release(binary: BinaryConfig) -> ReleaseInfo:
    """Resolve the latest GitHub release asset for the requested platform."""
    payload = _fetch_release_payload(GITHUB_LATEST_URL)
    return _release_from_payload(payload, binary)


def get_release_by_version(binary: BinaryConfig, version: str) -> ReleaseInfo:
    """Resolve a pinned release by tag version."""
    normalized = normalize_version(version)
    if not normalized:
        raise ReleaseNotFoundError("binary.version is empty after normalization")
    payload = _fetch_release_payload(GITHUB_TAG_URL_TEMPLATE.format(version=normalized))
    return _release_from_payload(payload, binary, requested_version=normalized)


def _fetch_release_payload(url: str) -> dict[str, object]:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "frpdeck/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise DownloadError(f"GitHub release lookup failed for {url}: HTTP {exc.code}") from exc
    except Exception as exc:
        raise DownloadError(f"failed to query GitHub releases API: {exc}") from exc
    if not isinstance(payload, dict):
        raise DownloadError(f"unexpected release payload from GitHub for {url}")
    return payload


def _release_from_payload(payload: dict[str, object], binary: BinaryConfig, requested_version: str | None = None) -> ReleaseInfo:
    asset_suffix = f"_{binary.os}_{ARCH_ALIASES.get(binary.arch, binary.arch)}.tar.gz"
    version = str(payload.get("tag_name", "")).lstrip("v")
    if not version and requested_version:
        version = requested_version
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise ReleaseNotFoundError("release payload did not contain an asset list")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name", "")
        if name.endswith(asset_suffix):
            return ReleaseInfo(
                version=normalize_version(version) or version,
                asset_name=name,
                asset_url=asset.get("browser_download_url", ""),
            )
    detail = f"version {requested_version}" if requested_version else "latest release"
    raise ReleaseNotFoundError(f"no release asset found for {detail} and suffix {asset_suffix}")
