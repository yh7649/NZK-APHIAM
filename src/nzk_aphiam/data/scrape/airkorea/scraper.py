"""Download finalized hourly, monitor-level air quality archives from AirKorea.

AirKorea publishes one ZIP archive per year. Each archive contains quarterly
XLSX workbooks with hourly observations, monitor names and codes, addresses,
and criteria-pollutant concentrations. The annual archive index is discovered
at run time so attachment identifiers are not hard-coded.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urljoin
from zipfile import BadZipFile, ZipFile, is_zipfile

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.airkorea.or.kr"
SOURCE_PAGE_URL = f"{BASE_URL}/web/last_amb_hour_data"
FIRST_YEAR = 2001

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "airkorea" / "hourly_finalized"

ARCHIVE_PATTERN = re.compile(
    r"<span>\s*(?P<year>20\d{2})년(?P<provisional>\*)?\s*</span>.*?"
    r"location\.href=[\"'](?P<url>/jfile/readDownloadFile\.do\?[^\"']+)[\"']",
    flags=re.DOTALL,
)


@dataclass(frozen=True)
class Archive:
    """One annual attachment advertised by the AirKorea archive page."""

    year: int
    url: str
    provisional: bool


def build_session() -> requests.Session:
    """Create a retrying session with a transparent project user agent."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "NZK-APHIAM AirKorea research data collector",
            "Referer": SOURCE_PAGE_URL,
        }
    )
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1,
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET"},
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def parse_archive_index(html: str) -> list[Archive]:
    """Extract annual archive links from the official download page."""
    archives = [
        Archive(
            year=int(match.group("year")),
            url=urljoin(BASE_URL, match.group("url").replace("&amp;", "&")),
            provisional=bool(match.group("provisional")),
        )
        for match in ARCHIVE_PATTERN.finditer(html)
    ]
    archives = sorted(
        {archive.year: archive for archive in archives}.values(), key=lambda x: x.year
    )
    if not archives:
        raise RuntimeError("AirKorea archive page contained no annual download links.")
    return archives


def discover_archives(session: requests.Session, timeout: int) -> list[Archive]:
    """Fetch and parse the official AirKorea annual archive index."""
    try:
        response = session.get(SOURCE_PAGE_URL, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(
            f"Could not load the AirKorea archive index: {error.__class__.__name__}"
        ) from None
    return parse_archive_index(response.text)


def select_archives(
    archives: Iterable[Archive], start_year: int | None, end_year: int | None
) -> list[Archive]:
    """Select an inclusive year range and reject unavailable requested years."""
    available = {archive.year: archive for archive in archives}
    if not available:
        raise ValueError("No AirKorea archives were supplied.")

    start = min(available) if start_year is None else start_year
    end = max(available) if end_year is None else end_year
    if start > end:
        raise ValueError("start_year must not be after end_year.")

    missing = [year for year in range(start, end + 1) if year not in available]
    if missing:
        years = ", ".join(str(year) for year in missing)
        raise ValueError(f"AirKorea does not advertise archives for requested year(s): {years}")
    return [available[year] for year in range(start, end + 1)]


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a potentially large file without loading it into memory."""
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_zip(path: Path) -> int:
    """Check that a download has a readable ZIP directory and return member count."""
    if not is_zipfile(path):
        raise RuntimeError(f"AirKorea response is not a complete ZIP archive: {path}")
    try:
        with ZipFile(path) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
    except BadZipFile:
        raise RuntimeError(f"AirKorea response is not a complete ZIP archive: {path}") from None
    if not members:
        raise RuntimeError(f"AirKorea ZIP archive contains no files: {path}")
    return len(members)


def download_archive(
    session: requests.Session,
    archive: Archive,
    destination: Path,
    timeout: int,
    overwrite: bool,
    resume: bool,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Download one archive atomically, retaining partial bytes on interruption."""
    if destination.exists() and not overwrite:
        validate_zip(destination)
        return "reused"

    partial = destination.with_suffix(destination.suffix + ".part")
    if overwrite:
        partial.unlink(missing_ok=True)

    offset = partial.stat().st_size if resume and partial.exists() else 0
    if not resume:
        partial.unlink(missing_ok=True)
        offset = 0

    headers = {"Range": f"bytes={offset}-"} if offset else {}
    try:
        response = session.get(archive.url, headers=headers, stream=True, timeout=timeout)
        response.raise_for_status()

        resumed = offset > 0 and response.status_code == 206
        mode = "ab" if resumed else "wb"
        with partial.open(mode) as file:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    file.write(chunk)
    except requests.RequestException as error:
        raise RuntimeError(
            f"AirKorea download failed for {archive.year}: {error.__class__.__name__}; "
            f"partial data retained at {partial}"
        ) from None

    validate_zip(partial)
    partial.replace(destination)
    return "resumed" if resumed else "downloaded"


def scrape(
    output_dir: Path,
    start_year: int | None,
    end_year: int | None,
    timeout: int,
    overwrite: bool,
    resume: bool = True,
    list_years: bool = False,
) -> list[dict[str, object]]:
    """Discover and download an inclusive range of annual AirKorea archives."""
    session = build_session()
    available = discover_archives(session, timeout)
    if list_years:
        for archive in available:
            suffix = " (provisional annual file)" if archive.provisional else ""
            print(f"{archive.year}{suffix}")
        return []

    selected = select_archives(available, start_year, end_year)
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, object]] = []

    for archive in selected:
        path = output_dir / f"airkorea_hourly_finalized_{archive.year}.zip"
        status = download_archive(session, archive, path, timeout, overwrite, resume)
        members = validate_zip(path)
        record: dict[str, object] = {
            **asdict(archive),
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
            "zip_member_count": members,
            "status": status,
        }
        files.append(record)
        print(f"{archive.year}: {path.name} ({record['bytes']} bytes, {status})")

    metadata = {
        "dataset": "AirKorea finalized hourly monitor-level air quality observations",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_page_url": SOURCE_PAGE_URL,
        "coverage": [selected[0].year, selected[-1].year],
        "reporting_level": "air-quality monitoring station-hour",
        "archive_format": "Annual ZIP files containing quarterly XLSX workbooks",
        "source_columns_observed": [
            "region",
            "station_name",
            "station_code",
            "measurement_datetime",
            "SO2",
            "CO",
            "O3",
            "NO2",
            "PM10",
            "PM2.5 (where available)",
            "address",
        ],
        "missing_value_note": "AirKorea documents -999 for invalid observations.",
        "finalization_note": (
            "Years marked provisional on the source page use monthly-report statistics and may "
            "change during annual finalization."
        ),
        "files": files,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download finalized hourly monitor-level air quality data from AirKorea."
    )
    parser.add_argument(
        "--start-year", type=int, help=f"First year (coverage begins in {FIRST_YEAR})."
    )
    parser.add_argument(
        "--end-year", type=int, help="Last year; defaults to the latest advertised archive."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=120, help="Per-request timeout in seconds.")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace complete existing archives."
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Discard partial downloads instead of attempting resume.",
    )
    parser.add_argument(
        "--list-years",
        action="store_true",
        help="List currently advertised years without downloading.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scrape(
        output_dir=args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        timeout=args.timeout,
        overwrite=args.overwrite,
        resume=not args.no_resume,
        list_years=args.list_years,
    )
