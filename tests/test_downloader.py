from pathlib import Path

import pytest

from frpdeck.domain.errors import DownloadError
from frpdeck.services.downloader import download_file


class _FakeResponse:
    def __init__(self, chunks: list[bytes], *, content_length: str | None = None, failure_at: int | None = None) -> None:
        self._chunks = chunks
        self._index = 0
        self._failure_at = failure_at
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if self._failure_at is not None and self._index == self._failure_at:
            raise OSError("network lost")
        if self._index >= len(self._chunks):
            return b""
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


def test_download_file_reports_progress_with_content_length(monkeypatch, tmp_path: Path) -> None:
    progress_calls: list[tuple[int, int | None]] = []

    monkeypatch.setattr(
        "frpdeck.services.downloader.urlopen",
        lambda request, timeout=60: _FakeResponse([b"abc", b"def", b"ghi"], content_length="9"),
    )

    destination = download_file(
        "https://example.invalid/frp.tar.gz",
        tmp_path / "frp.tar.gz",
        progress=lambda downloaded, total: progress_calls.append((downloaded, total)),
    )

    assert destination.read_bytes() == b"abcdefghi"
    assert progress_calls == [(3, 9), (6, 9), (9, 9)]


def test_download_file_reports_progress_without_content_length(monkeypatch, tmp_path: Path) -> None:
    progress_calls: list[tuple[int, int | None]] = []

    monkeypatch.setattr(
        "frpdeck.services.downloader.urlopen",
        lambda request, timeout=60: _FakeResponse([b"ab", b"cd"]),
    )

    destination = download_file(
        "https://example.invalid/frp.tar.gz",
        tmp_path / "frp.tar.gz",
        progress=lambda downloaded, total: progress_calls.append((downloaded, total)),
    )

    assert destination.read_bytes() == b"abcd"
    assert progress_calls == [(2, None), (4, None)]


def test_download_file_raises_download_error_and_cleans_partial_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "frpdeck.services.downloader.urlopen",
        lambda request, timeout=60: _FakeResponse([b"abc", b"def"], failure_at=1),
    )

    destination = tmp_path / "frp.tar.gz"

    with pytest.raises(DownloadError, match="failed to download https://example.invalid/frp.tar.gz"):
        download_file("https://example.invalid/frp.tar.gz", destination)

    assert not destination.exists()
