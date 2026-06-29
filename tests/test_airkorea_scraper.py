from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from nzk_aphiam.data.scrape.airkorea import scraper

INDEX_HTML = """
<td><span>2024년</span><button onclick='location.href="/jfile/readDownloadFile.do?fileId=x&fileSeq=24"'>다운로드</button></td>
<td><span>2025년*</span><button onclick='location.href="/jfile/readDownloadFile.do?fileId=x&amp;fileSeq=25"'>다운로드</button></td>
"""


def zip_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("quarter.xlsx", b"workbook")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.headers: dict[str, str] | None = None

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.headers = kwargs.get("headers")  # type: ignore[assignment]
        return self.response


def test_parse_archive_index_extracts_year_urls_and_provisional_marker() -> None:
    archives = scraper.parse_archive_index(INDEX_HTML)

    assert [archive.year for archive in archives] == [2024, 2025]
    assert archives[0].url.endswith("fileId=x&fileSeq=24")
    assert archives[1].provisional is True


def test_select_archives_is_inclusive_and_rejects_gaps() -> None:
    archives = scraper.parse_archive_index(INDEX_HTML)

    assert [item.year for item in scraper.select_archives(archives, 2024, 2025)] == [2024, 2025]
    with pytest.raises(ValueError, match="2023"):
        scraper.select_archives(archives, 2023, 2025)


def test_download_archive_writes_valid_zip_atomically(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(zip_bytes()))
    archive = scraper.Archive(2024, "https://example.test/2024.zip", False)
    destination = tmp_path / "2024.zip"

    status = scraper.download_archive(session, archive, destination, 10, False, True, chunk_size=7)  # type: ignore[arg-type]

    assert status == "downloaded"
    assert scraper.validate_zip(destination) == 1
    assert not destination.with_suffix(".zip.part").exists()


def test_download_archive_resumes_when_server_honors_range(tmp_path: Path) -> None:
    payload = zip_bytes()
    split = len(payload) // 2
    destination = tmp_path / "2024.zip"
    destination.with_suffix(".zip.part").write_bytes(payload[:split])
    session = FakeSession(FakeResponse(payload[split:], status_code=206))
    archive = scraper.Archive(2024, "https://example.test/2024.zip", False)

    status = scraper.download_archive(session, archive, destination, 10, False, True)  # type: ignore[arg-type]

    assert status == "resumed"
    assert session.headers == {"Range": f"bytes={split}-"}
    assert destination.read_bytes() == payload


def test_download_archive_restarts_if_server_ignores_range(tmp_path: Path) -> None:
    payload = zip_bytes()
    destination = tmp_path / "2024.zip"
    destination.with_suffix(".zip.part").write_bytes(b"stale partial")
    session = FakeSession(FakeResponse(payload, status_code=200))
    archive = scraper.Archive(2024, "https://example.test/2024.zip", False)

    status = scraper.download_archive(session, archive, destination, 10, False, True)  # type: ignore[arg-type]

    assert status == "downloaded"
    assert destination.read_bytes() == payload


def test_existing_invalid_archive_is_not_silently_reused(tmp_path: Path) -> None:
    destination = tmp_path / "2024.zip"
    destination.write_bytes(b"not a zip")
    archive = scraper.Archive(2024, "https://example.test/2024.zip", False)

    with pytest.raises(RuntimeError, match="not a complete ZIP"):
        scraper.download_archive(
            FakeSession(FakeResponse(b"")), archive, destination, 10, False, True
        )  # type: ignore[arg-type]
