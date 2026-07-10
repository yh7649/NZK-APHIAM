"""Download CAPSS detailed emissions statistics workbooks from air.go.kr.

The CAPSS board publishes one attachment per annual inventory year, with a
special reassessment post that carries revised 2016-2019 workbooks. Discovery is
done from the official board at run time so file identifiers are not hard-coded.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import unquote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nzk_aphiam.config.paths import CAPSS_RAW_DIR

BASE_URL = "https://www.air.go.kr"
BOARD_ID = 10
MENU_ID = 32
LIST_URL = f"{BASE_URL}/article/list.do?boardId={BOARD_ID}&menuId={MENU_ID}"
EMISSION_STATISTICS_URL = LIST_URL
SECTOR_SUMMARY_URL = f"{BASE_URL}/capss/emission/sector.do?menuId=30"
SIDO_SUMMARY_URL = f"{BASE_URL}/capss/emission/sido.do?menuId=31"
POINT_SOURCE_CONTEXT_URLS = (
    f"{BASE_URL}/contents/view.do?contentsId=14&menuId=52",
    f"{BASE_URL}/contents/view.do?contentsId=15&menuId=53",
)
FIRST_YEAR = 1999

ARTICLE_PATTERN = re.compile(
    r'<a\s+href="(?P<href>[^"]*articleId=(?P<article_id>\d+)[^"]*)"\s+'
    r'title="(?P<title>[^"]*배출량[^"]*통계[^"]*)"',
    flags=re.DOTALL,
)
DOWNLOAD_PATTERN = re.compile(
    r"(?P<filename>[^<>]+?\.xlsx)\s*"
    r'<a[^>]+href="(?P<href>/file/download\.do\?fileId=(?P<file_id>\d+))"'
    r"[^>]*>\s*다운로드",
    flags=re.DOTALL,
)
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")


@dataclass(frozen=True)
class CapssAttachment:
    """One workbook attachment from the CAPSS emissions statistics board."""

    year: int
    article_id: int
    file_id: int
    title: str
    filename: str
    article_url: str
    download_url: str
    reassessment: bool


def build_session() -> requests.Session:
    """Create a retrying session with a transparent project user agent."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "NZK-APHIAM CAPSS research data collector",
            "Referer": EMISSION_STATISTICS_URL,
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


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("&quot;", '"')).strip()


def _page_url(page: int) -> str:
    return f"{LIST_URL}&currentPageNo={page}"


def _extract_years(value: str) -> list[int]:
    return [int(match.group(0)) for match in YEAR_PATTERN.finditer(value)]


def parse_board_list(html: str, page_url: str) -> list[tuple[int, str, str]]:
    """Extract article IDs, titles, and absolute URLs from a board-list page."""
    articles: list[tuple[int, str, str]] = []
    for match in ARTICLE_PATTERN.finditer(html):
        title = _clean_text(match.group("title"))
        if "대기오염물질" not in title:
            continue
        article_id = int(match.group("article_id"))
        article_url = urljoin(page_url, match.group("href").replace("&amp;", "&"))
        articles.append((article_id, title, article_url))
    return articles


def parse_article_attachments(
    html: str, article_id: int, title: str, article_url: str
) -> list[CapssAttachment]:
    """Extract detailed annual workbook attachments from one board article."""
    attachments: list[CapssAttachment] = []
    title_years = set(_extract_years(title))
    for match in DOWNLOAD_PATTERN.finditer(html):
        filename = _clean_text(match.group("filename"))
        years = _extract_years(filename) or sorted(title_years)
        if not years:
            continue
        if "시군구" not in filename or "소분류" not in filename or "연료" not in filename:
            continue
        for year in years:
            attachments.append(
                CapssAttachment(
                    year=year,
                    article_id=article_id,
                    file_id=int(match.group("file_id")),
                    title=title,
                    filename=filename,
                    article_url=article_url,
                    download_url=urljoin(BASE_URL, match.group("href").replace("&amp;", "&")),
                    reassessment="재산정" in title or "재산정" in filename,
                )
            )
    return attachments


def discover_attachments(
    session: requests.Session, pages: int = 3, timeout: int = 30
) -> list[CapssAttachment]:
    """Discover all advertised detailed CAPSS annual workbook attachments."""
    discovered: list[CapssAttachment] = []
    for page in range(1, pages + 1):
        page_url = _page_url(page)
        try:
            response = session.get(page_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(
                f"Could not load CAPSS board page {page}: {error.__class__.__name__}"
            ) from None
        for article_id, title, article_url in parse_board_list(response.text, page_url):
            try:
                article_response = session.get(article_url, timeout=timeout)
                article_response.raise_for_status()
            except requests.RequestException as error:
                raise RuntimeError(
                    f"Could not load CAPSS article {article_id}: {error.__class__.__name__}"
                ) from None
            discovered.extend(
                parse_article_attachments(article_response.text, article_id, title, article_url)
            )

    by_year: dict[int, CapssAttachment] = {}
    for attachment in discovered:
        current = by_year.get(attachment.year)
        if current is None or (attachment.reassessment and not current.reassessment):
            by_year[attachment.year] = attachment
    return [by_year[year] for year in sorted(by_year)]


def select_attachments(
    attachments: list[CapssAttachment], start_year: int | None, end_year: int | None
) -> list[CapssAttachment]:
    """Select an inclusive available year range and reject gaps."""
    available = {attachment.year: attachment for attachment in attachments}
    if not available:
        raise ValueError("No CAPSS detailed emissions workbooks were discovered.")
    start = min(available) if start_year is None else start_year
    end = max(available) if end_year is None else end_year
    if start > end:
        raise ValueError("start_year must not be after end_year.")
    missing = [year for year in range(start, end + 1) if year not in available]
    if missing:
        years = ", ".join(str(year) for year in missing)
        raise ValueError(f"CAPSS does not advertise detailed workbooks for: {years}")
    return [available[year] for year in range(start, end + 1)]


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without reading it all into memory."""
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filename_from_response(response: requests.Response, fallback: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r'filename="?([^";]+)"?', disposition, flags=re.IGNORECASE)
    if match:
        return unquote(match.group(1))
    return fallback


def download_attachment(
    session: requests.Session,
    attachment: CapssAttachment,
    output_dir: Path,
    timeout: int,
    overwrite: bool,
) -> dict[str, object]:
    """Download one CAPSS workbook atomically and return provenance fields."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"capss_emissions_statistics_{attachment.year}.xlsx"
    if destination.exists() and not overwrite:
        status = "reused"
        source_filename = attachment.filename
    else:
        partial = destination.with_suffix(destination.suffix + ".part")
        try:
            response = session.get(attachment.download_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(
                f"CAPSS download failed for {attachment.year}: {error.__class__.__name__}"
            ) from None
        partial.write_bytes(response.content)
        if not partial.read_bytes().startswith(b"PK"):
            raise RuntimeError(
                f"CAPSS response is not an XLSX workbook: {attachment.download_url}"
            )
        partial.replace(destination)
        status = "downloaded"
        source_filename = _filename_from_response(response, attachment.filename)

    return {
        **asdict(attachment),
        "file": destination.name,
        "source_filename": source_filename,
        "bytes": destination.stat().st_size,
        "sha256": file_sha256(destination),
        "status": status,
    }


def scrape(
    output_dir: Path,
    start_year: int | None,
    end_year: int | None,
    timeout: int,
    overwrite: bool,
    list_years: bool = False,
) -> list[dict[str, object]]:
    """Discover and download CAPSS detailed annual emissions workbooks."""
    session = build_session()
    available = discover_attachments(session, timeout=timeout)
    if list_years:
        for attachment in available:
            suffix = " (reassessment)" if attachment.reassessment else ""
            print(
                f"{attachment.year}{suffix}: article {attachment.article_id}, file {attachment.file_id}"
            )
        return []

    selected = select_attachments(available, start_year, end_year)
    records = [
        download_attachment(session, attachment, output_dir, timeout, overwrite)
        for attachment in selected
    ]
    metadata = {
        "dataset": "CAPSS detailed national air pollutant emissions statistics",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_page_url": EMISSION_STATISTICS_URL,
        "source_summary_pages": {
            "by_sector": SECTOR_SUMMARY_URL,
            "by_province": SIDO_SUMMARY_URL,
        },
        "point_source_location_note": (
            "The public CAPSS/SEMS pages describe the emissions-source management system, "
            "but this scraper does not find a public facility coordinate download on the "
            "CAPSS emissions statistics board. Treat point-source-resolved downscaling as "
            "requiring a separate SEMS/CAPSS access check."
        ),
        "point_source_context_urls": list(POINT_SOURCE_CONTEXT_URLS),
        "coverage": [selected[0].year, selected[-1].year],
        "records": records,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for record in records:
        print(f"{record['year']}: {record['file']} ({record['bytes']} bytes, {record['status']})")
    return records


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=CAPSS_RAW_DIR / "emissions_statistics")
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--list-years", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    scrape(
        output_dir=args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        timeout=args.timeout,
        overwrite=args.overwrite,
        list_years=args.list_years,
    )
