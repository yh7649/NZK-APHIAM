"""Archive the web evidence used by the plant location/date crosswalk.

The crosswalk records human-readable source URLs. This module downloads an
immutable copy of every unique URL, including full OpenStreetMap way geometry,
and writes a checksum manifest suitable for content-addressed DVC storage.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_EVIDENCE_PATH = (
    PROJECT_ROOT
    / "docs"
    / "references"
    / "crosswalk"
    / "plant_location_dates_official_evidence.csv"
)
DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "data" / "raw" / "references" / "plant_location_dates"
URL_COLUMNS = (
    "operator_source_url",
    "coordinate_source_url",
    "opening_date_source_url",
)
USER_AGENT = "NZK-APHIAM research archive/1.0 (source preservation)"
OSM_WAY_PATTERN = re.compile(r"^https://www\.openstreetmap\.org/way/(\d+)$")


def _fetch_url(source_url: str) -> str:
    """Return a machine-readable endpoint when the cited URL identifies an OSM way."""
    match = OSM_WAY_PATTERN.match(source_url)
    if match:
        return f"https://api.openstreetmap.org/api/0.6/way/{match.group(1)}/full.json"
    return source_url


def _extension(content_type: str, fetch_url: str) -> str:
    content_type = content_type.lower()
    if "json" in content_type:
        return ".json"
    if "pdf" in content_type or urlparse(fetch_url).path.lower().endswith(".pdf"):
        return ".pdf"
    if "html" in content_type:
        return ".html"
    return ".bin"


def _source_inventory(evidence: pd.DataFrame) -> dict[str, dict[str, set[str]]]:
    inventory: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"plants": set(), "roles": set()}
    )
    for row in evidence.itertuples(index=False):
        plant = f"{row.subsidiary_company} / {row.plant_name}"
        for column in URL_COLUMNS:
            value = getattr(row, column)
            if pd.isna(value) or not str(value).strip():
                continue
            url = str(value).strip()
            inventory[url]["plants"].add(plant)
            inventory[url]["roles"].add(column.removesuffix("_url"))
    return dict(inventory)


def _download(url: str) -> tuple[bytes, dict[str, object]]:
    """Download one response body with curl's retry and public-site TLS support."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        output_path = Path(temporary_directory) / "response"
        result = subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--http1.0",
                "--silent",
                "--show-error",
                "--retry",
                "3",
                "--retry-all-errors",
                "--connect-timeout",
                "30",
                "--max-time",
                "120",
                "--user-agent",
                USER_AGENT,
                "--output",
                str(output_path),
                "--write-out",
                "%{json}",
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output_path.read_bytes(), json.loads(result.stdout)


def archive_sources(
    *,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    snapshot_date: date,
    overwrite: bool = False,
) -> Path:
    """Download all cited sources and return the immutable snapshot directory."""
    evidence = pd.read_csv(evidence_path, encoding="utf-8-sig")
    missing_columns = set(URL_COLUMNS) - set(evidence.columns)
    if missing_columns:
        raise ValueError(f"Evidence file is missing URL columns: {sorted(missing_columns)}")

    snapshot_dir = archive_root / f"source.{snapshot_date.isoformat()}"
    staging_dir = archive_root / f".source.{snapshot_date.isoformat()}.tmp"
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Snapshot already exists: {snapshot_dir}. Use --overwrite only to repair "
            "the same dated snapshot deliberately."
        )
    if overwrite and snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=False)

    manifest_rows: list[dict[str, object]] = []

    for source_url, context in sorted(_source_inventory(evidence).items()):
        fetch_url = _fetch_url(source_url)
        payload, transfer = _download(fetch_url)
        content_type = str(transfer.get("content_type", ""))
        url_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
        filename = f"source_{url_hash}{_extension(content_type, fetch_url)}"
        output_path = staging_dir / filename
        output_path.write_bytes(payload)
        retrieved_at = datetime.now(UTC).isoformat()
        manifest_rows.append(
            {
                "source_url": source_url,
                "fetch_url": fetch_url,
                "final_url": transfer.get("url_effective", fetch_url),
                "source_roles": ";".join(sorted(context["roles"])),
                "plants": ";".join(sorted(context["plants"])),
                "local_file": filename,
                "content_type": content_type,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "retrieved_at_utc": retrieved_at,
                "http_status": transfer.get("http_code", ""),
            }
        )

    manifest_path = staging_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)

    metadata = {
        "snapshot_date": snapshot_date.isoformat(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "evidence_file": str(evidence_path.relative_to(PROJECT_ROOT)),
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "source_count": len(manifest_rows),
        "archive_format": "verbatim HTTP response bodies plus checksum manifest",
        "license_note": (
            "Archived for research provenance. Reuse remains subject to each source's "
            "terms; OpenStreetMap data is available under ODbL."
        ),
    }
    (staging_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    staging_dir.rename(snapshot_dir)
    return snapshot_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Snapshot date in YYYY-MM-DD form (default: today).",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    output = archive_sources(snapshot_date=args.snapshot_date, overwrite=args.overwrite)
    print(f"Archived plant location/date evidence to {output}")


if __name__ == "__main__":
    main()
