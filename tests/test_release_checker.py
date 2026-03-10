import io
import json
import tarfile
from pathlib import Path

from frpdeck.domain.enums import Role
from frpdeck.domain.install import BinaryConfig
from frpdeck.domain.state import ClientNodeConfig
from frpdeck.domain.systemd import ServiceConfig
from frpdeck.domain.client_config import AuthConfig, ClientCommonConfig
from frpdeck.services.installer import _version_from_archive_name
from frpdeck.services.release_checker import get_release
from frpdeck.services.scaffold import scaffold_instance


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> io.BytesIO:
        return self._buffer

    def __exit__(self, exc_type, exc, tb) -> None:
        self._buffer.close()


def test_get_release_uses_pinned_tag_endpoint(monkeypatch) -> None:
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout=20):
        seen_urls.append(request.full_url)
        return _FakeResponse(
            {
                "tag_name": "v0.65.0",
                "assets": [
                    {
                        "name": "frp_0.65.0_linux_amd64.tar.gz",
                        "browser_download_url": "https://example.invalid/frp_0.65.0_linux_amd64.tar.gz",
                    }
                ],
            }
        )

    monkeypatch.setattr("frpdeck.services.release_checker.urlopen", fake_urlopen)

    release = get_release(BinaryConfig(version="v0.65.0"))

    assert seen_urls == ["https://api.github.com/repos/fatedier/frp/releases/tags/v0.65.0"]
    assert release.version == "0.65.0"


def test_archive_version_extraction_variants() -> None:
    assert _version_from_archive_name("frp_0.65.0_linux_amd64.tar.gz") == "0.65.0"
    assert _version_from_archive_name("frp_0.65.0_linux_arm64.tar.gz") == "0.65.0"
    assert _version_from_archive_name("frp_v0.65.0_linux_amd64.tar.gz") == "0.65.0"
    assert _version_from_archive_name("not-frp.tar.gz") == "unknown"


def test_scaffold_uses_runtime_log_paths(tmp_path: Path) -> None:
    instance_dir = scaffold_instance(tmp_path, Role.CLIENT, "demo-client")
    content = (instance_dir / "node.yaml").read_text(encoding="utf-8")

    assert "runtime/logs/frpc.log" in content