"""Download KMA surface and upper-air observations as immutable annual snapshots.

The KMA type-01 APIs return whitespace-delimited text. This collector preserves
their documented source fields without imputing missing values. ASOS timestamps
are KST; radiosonde, stability, and Wind Profiler timestamps are UTC.

KMA requires both an API Hub key and a separate usage activation for each API.
Put the key in ``KMA_API_HUB_KEY`` in the project ``.env`` file.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import datetime as dt
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Iterable

from dotenv import load_dotenv
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nzk_aphiam.config.paths import PROJECT_ROOT, WEATHER_RAW_DIR
from nzk_aphiam.data.scrape.weather.kma.schemas import (
    ASOS_COLUMNS,
    PROFILER_COLUMNS,
    PROFILER_STATION_COLUMNS,
    RADIOSONDE_COLUMNS,
    STABILITY_COLUMNS,
    STATION_COLUMNS,
)

API_KEY_ENV = "KMA_API_HUB_KEY"
BASE_URL = "https://apihub.kma.go.kr/api/typ01/url"
SOURCE_PAGE_URLS = {
    "surface": "https://apihub.kma.go.kr/apiList.do?seqApi=2&seqApiSub=238",
    "radiosonde": "https://apihub.kma.go.kr/apiList.do?seqApi=4&seqApiSub=254",
    "stability": "https://apihub.kma.go.kr/apiList.do?seqApi=4&seqApiSub=254",
    "profiler": "https://apihub.kma.go.kr/apiList.do?seqApi=4&seqApiSub=255",
    "stations": "https://apihub.kma.go.kr/apiList.do?seqApi=4&seqApiSub=319",
}
ENDPOINTS = {
    "surface": f"{BASE_URL}/kma_sfctm3.php",
    "radiosonde": f"{BASE_URL}/upp_temp.php",
    "stability": f"{BASE_URL}/upp_idx.php",
    "profiler": f"{BASE_URL}/kma_wpf.php",
    "stations": f"{BASE_URL}/stn_inf.php",
    "profiler_stations": f"{BASE_URL}/stn_wpf.php",
}
DATASET_COLUMNS = {
    "surface": ASOS_COLUMNS,
    "radiosonde": RADIOSONDE_COLUMNS,
    "stability": STABILITY_COLUMNS,
    "profiler": PROFILER_COLUMNS,
}
CORE_DATASETS = ("stations", "surface", "radiosonde", "stability")


class KmaApiError(RuntimeError):
    """A credential, authorization, transport, or schema failure from KMA."""


@dataclass(frozen=True)
class SnapshotRecord:
    dataset: str
    year: int
    path: str
    rows: int
    bytes: int
    sha256: str
    status: str
    requests: int


def get_api_key() -> str:
    """Load the KMA key without ever including its value in an error."""
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv(API_KEY_ENV, "").strip()
    if not key:
        raise ValueError(
            f"{API_KEY_ENV} is missing. Add it to .env, but do not commit or print the key."
        )
    return key


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "NZK-APHIAM KMA research data collector"})
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


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except (ValueError, requests.JSONDecodeError):
        return f"HTTP {response.status_code}"
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    message = result.get("message") or result.get("resultMsg")
    return f"HTTP {response.status_code}: {message}" if message else f"HTTP {response.status_code}"


def request_text(
    session: requests.Session,
    endpoint: str,
    params: dict[str, str],
    api_key: str,
    timeout: int,
) -> str:
    """Request one text response while preventing credentials from entering errors."""
    safe_params = {**params, "authKey": api_key}
    try:
        response = session.get(endpoint, params=safe_params, timeout=timeout)
    except requests.RequestException as error:
        raise KmaApiError(f"KMA request failed: {error.__class__.__name__}") from None
    if response.status_code != 200:
        raise KmaApiError(_error_message(response))
    text = response.text
    if text.lstrip().startswith("{"):
        try:
            payload = response.json()
        except (ValueError, requests.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and "result" in payload:
            raise KmaApiError(_error_message(response))
    return text


def parse_text_response(text: str, columns: list[str]) -> pd.DataFrame:
    """Parse KMA's whitespace text format using its documented field order."""
    rows: list[list[str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        values = line.split()
        if len(values) != len(columns):
            raise KmaApiError(
                f"KMA schema mismatch: expected {len(columns)} fields but received "
                f"{len(values)}. Response was not saved."
            )
        rows.append(values)
    return pd.DataFrame(rows, columns=columns, dtype="string")


def _date_chunks(year: int, days: int = 31) -> Iterable[tuple[dt.date, dt.date]]:
    cursor = dt.date(year, 1, 1)
    year_end = dt.date(year, 12, 31)
    while cursor <= year_end:
        end = min(cursor + dt.timedelta(days=days - 1), year_end)
        yield cursor, end
        cursor = end + dt.timedelta(days=1)


def estimate_requests(dataset: str, start_year: int, end_year: int, profiler_hours: int) -> int:
    years = end_year - start_year + 1
    if dataset == "surface" or dataset == "stability":
        return sum(1 for year in range(start_year, end_year + 1) for _ in _date_chunks(year))
    if dataset == "radiosonde":
        return (
            sum(
                (dt.date(year, 12, 31) - dt.date(year, 1, 1)).days + 1
                for year in range(start_year, end_year + 1)
            )
            * 2
        )
    if dataset == "profiler":
        return sum(
            (dt.date(year, 12, 31) - dt.date(year, 1, 1)).days + 1
            for year in range(start_year, end_year + 1)
        ) * (24 // profiler_hours)
    if dataset == "stations":
        return years * 3
    if dataset == "core":
        return sum(
            estimate_requests(item, start_year, end_year, profiler_hours) for item in CORE_DATASETS
        )
    raise ValueError(f"Unknown KMA dataset: {dataset}")


def _fetch_surface_year(client: "KmaClient", year: int) -> tuple[pd.DataFrame, int]:
    frames = []
    requests_used = 0
    for start, end in _date_chunks(year):
        text = client.get(
            ENDPOINTS["surface"],
            {
                "tm1": start.strftime("%Y%m%d0000"),
                "tm2": end.strftime("%Y%m%d2300"),
                "stn": "0",
                "help": "0",
            },
        )
        frames.append(parse_text_response(text, ASOS_COLUMNS))
        requests_used += 1
    return pd.concat(frames, ignore_index=True), requests_used


def _fetch_radiosonde_year(client: "KmaClient", year: int) -> tuple[pd.DataFrame, int]:
    frames = []
    requests_used = 0
    day = dt.date(year, 1, 1)
    while day.year == year:
        for hour in (0, 12):
            text = client.get(
                ENDPOINTS["radiosonde"],
                {"tm": f"{day:%Y%m%d}{hour:02d}00", "stn": "0", "pa": "0", "help": "0"},
            )
            frame = parse_text_response(text, RADIOSONDE_COLUMNS)
            if not frame.empty:
                frames.append(frame)
            requests_used += 1
        day += dt.timedelta(days=1)
    return _concat_or_empty(frames, RADIOSONDE_COLUMNS), requests_used


def _fetch_stability_year(client: "KmaClient", year: int) -> tuple[pd.DataFrame, int]:
    frames = []
    requests_used = 0
    for start, end in _date_chunks(year):
        text = client.get(
            ENDPOINTS["stability"],
            {
                "tm1": start.strftime("%Y%m%d00"),
                "tm2": end.strftime("%Y%m%d23"),
                "stn": "0",
                "help": "0",
            },
        )
        frame = parse_text_response(text, STABILITY_COLUMNS)
        if not frame.empty:
            frames.append(frame)
        requests_used += 1
    return _concat_or_empty(frames, STABILITY_COLUMNS), requests_used


def _fetch_profiler_year(
    client: "KmaClient", year: int, interval_hours: int
) -> tuple[pd.DataFrame, int]:
    frames = []
    requests_used = 0
    day = dt.date(year, 1, 1)
    while day.year == year:
        for hour in range(0, 24, interval_hours):
            text = client.get(
                ENDPOINTS["profiler"],
                {
                    "tm": f"{day:%Y%m%d}{hour:02d}00",
                    "stn": "0",
                    "mode": "L",
                    "help": "0",
                },
            )
            frame = parse_text_response(text, PROFILER_COLUMNS)
            if not frame.empty:
                frames.append(frame)
            requests_used += 1
        day += dt.timedelta(days=1)
    return _concat_or_empty(frames, PROFILER_COLUMNS), requests_used


def _fetch_station_year(client: "KmaClient", year: int) -> tuple[pd.DataFrame, int]:
    frames = []
    kst_time = f"{year}07010000"
    for station_type in ("SFC", "UPP"):
        text = client.get(
            ENDPOINTS["stations"],
            {"inf": station_type, "tm": kst_time, "stn": "0", "help": "0"},
        )
        frame = parse_text_response(text, STATION_COLUMNS)
        frame.insert(0, "STATION_TYPE", station_type)
        frames.append(frame)
    text = client.get(
        ENDPOINTS["profiler_stations"],
        {"tm": f"{year}07010000", "stn": "0", "raw": "1", "help": "0"},
    )
    profiler = parse_text_response(text, PROFILER_STATION_COLUMNS)
    for column in STATION_COLUMNS:
        if column not in profiler:
            profiler[column] = pd.NA
    profiler = profiler.rename(columns={"TM_ST": "OBS_START", "TM_ED": "OBS_END"})
    profiler.insert(0, "STATION_TYPE", "WPF")
    ordered = ["STATION_TYPE", *STATION_COLUMNS, "OBS_START", "OBS_END"]
    for frame in frames:
        frame["OBS_START"] = pd.NA
        frame["OBS_END"] = pd.NA
    combined = pd.concat([*frames, profiler], ignore_index=True)[ordered]
    combined.insert(0, "SNAPSHOT_YEAR", str(year))
    return combined, 3


def _concat_or_empty(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


class KmaClient:
    def __init__(self, api_key: str, timeout: int, delay_seconds: float) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.session = build_session()

    def get(self, endpoint: str, params: dict[str, str]) -> str:
        text = request_text(self.session, endpoint, params, self.api_key, self.timeout)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return text


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_snapshot(frame: pd.DataFrame, path: Path, overwrite: bool) -> str:
    """Write atomically; never replace a prior snapshot unless explicitly requested."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return "reused"
    partial = path.with_suffix(path.suffix + ".part")
    frame.to_csv(partial, index=False, encoding="utf-8-sig")
    if path.exists() and _file_sha256(path) == _file_sha256(partial):
        partial.unlink()
        return "unchanged"
    status = "revised" if path.exists() else "new"
    partial.replace(path)
    return status


def _read_existing_record(dataset: str, year: int, path: Path) -> SnapshotRecord:
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype="string")
    return SnapshotRecord(
        dataset, year, str(path), len(frame), path.stat().st_size, _file_sha256(path), "reused", 0
    )


def scrape_dataset_year(
    client: KmaClient,
    dataset: str,
    year: int,
    output_dir: Path,
    overwrite: bool,
    profiler_interval_hours: int,
) -> SnapshotRecord:
    path = output_dir / dataset / f"{dataset}.source.{year}.csv"
    if path.exists() and not overwrite:
        return _read_existing_record(dataset, year, path)
    if dataset == "surface":
        frame, requests_used = _fetch_surface_year(client, year)
    elif dataset == "radiosonde":
        frame, requests_used = _fetch_radiosonde_year(client, year)
    elif dataset == "stability":
        frame, requests_used = _fetch_stability_year(client, year)
    elif dataset == "profiler":
        frame, requests_used = _fetch_profiler_year(client, year, profiler_interval_hours)
    elif dataset == "stations":
        frame, requests_used = _fetch_station_year(client, year)
    else:
        raise ValueError(f"Unknown KMA dataset: {dataset}")
    status = save_snapshot(frame, path, overwrite)
    return SnapshotRecord(
        dataset,
        year,
        str(path),
        len(frame),
        path.stat().st_size,
        _file_sha256(path),
        status,
        requests_used,
    )


def write_metadata(output_dir: Path, records: list[SnapshotRecord]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "metadata.json"
    existing: dict = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    indexed = {
        (item["dataset"], int(item["year"])): item for item in existing.get("snapshots", [])
    }
    for record in records:
        indexed[(record.dataset, record.year)] = asdict(record)
    metadata = {
        "dataset": "KMA surface and upper-air meteorological observations",
        "retrieved_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "credential_env": API_KEY_ENV,
        "timestamp_conventions": {
            "surface": "KST (Asia/Seoul)",
            "radiosonde": "UTC",
            "stability": "UTC",
            "profiler": "UTC",
        },
        "source_pages": SOURCE_PAGE_URLS,
        "missing_values": "Provider sentinel values are preserved in raw snapshots.",
        "snapshots": [indexed[key] for key in sorted(indexed)],
    }
    partial = path.with_suffix(".json.part")
    partial.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(path)


def scrape(
    dataset: str,
    start_year: int,
    end_year: int,
    output_dir: Path,
    timeout: int,
    delay_seconds: float,
    overwrite: bool,
    max_requests: int,
    profiler_interval_hours: int,
) -> list[SnapshotRecord]:
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")
    if profiler_interval_hours not in {1, 2, 3, 4, 6, 8, 12, 24}:
        raise ValueError("profiler_interval_hours must divide 24.")
    datasets = CORE_DATASETS if dataset == "core" else (dataset,)
    planned = sum(
        estimate_requests(item, year, year, profiler_interval_hours)
        for item in datasets
        for year in range(start_year, end_year + 1)
        if overwrite or not (output_dir / item / f"{item}.source.{year}.csv").exists()
    )
    if planned > max_requests:
        raise ValueError(
            f"Planned KMA pull requires approximately {planned:,} requests, exceeding "
            f"--max-requests={max_requests:,}. Narrow the year range or explicitly raise the cap."
        )
    client = KmaClient(get_api_key() if planned else "", timeout, delay_seconds)
    records = []
    for item in datasets:
        for year in range(start_year, end_year + 1):
            record = scrape_dataset_year(
                client, item, year, output_dir, overwrite, profiler_interval_hours
            )
            records.append(record)
            print(
                f"{item} {year}: {record.rows:,} rows, {record.status}, "
                f"{record.requests:,} request(s)"
            )
            write_metadata(output_dir, records)
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download KMA meteorology as immutable annual source snapshots."
    )
    parser.add_argument(
        "dataset", choices=("core", "surface", "radiosonde", "stability", "profiler", "stations")
    )
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--output-dir", type=Path, default=WEATHER_RAW_DIR)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--delay-seconds", type=float, default=0.05)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-requests", type=int, default=20_000)
    parser.add_argument(
        "--profiler-interval-hours",
        type=int,
        default=1,
        help="Profiler sampling interval; hourly by default. Run profiler in small year batches.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scrape(
        dataset=args.dataset,
        start_year=args.start_year,
        end_year=args.end_year,
        output_dir=args.output_dir,
        timeout=args.timeout,
        delay_seconds=args.delay_seconds,
        overwrite=args.overwrite,
        max_requests=args.max_requests,
        profiler_interval_hours=args.profiler_interval_hours,
    )
