"""Download Southern Power's official annual plant/unit generation file."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path

import pandas as pd
import requests

from nzk_aphiam.config.paths import PROJECT_ROOT

DATASET_URL = "https://www.data.go.kr/data/15127550/fileData.do"
DEFAULT_DOWNLOAD_URL = (
    "https://www.data.go.kr/cmm/cmm/fileDownload.do?"
    "atchFileId=FILE_000000003623726&fileDetailSn=1&insertDataPrcus=N"
)
EXPECTED_COLUMNS = ["년도", "발전원", "플랜트", "호기", "용량", "발전량"]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "kepco_subsidiaries" / "southern_power"


def download(url: str, timeout: int = 60) -> bytes:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def parse_csv(content: bytes) -> pd.DataFrame:
    from io import BytesIO

    try:
        data = pd.read_csv(BytesIO(content), encoding="utf-8-sig")
    except UnicodeDecodeError:
        data = pd.read_csv(BytesIO(content), encoding="cp949")
    if list(data.columns) != EXPECTED_COLUMNS:
        raise ValueError(f"Unexpected Southern annual columns: {list(data.columns)!r}")
    return data


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_DOWNLOAD_URL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)
    content = download(args.url, args.timeout)
    data = parse_csv(content)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "southern_power_annual_generation.csv"
    metadata_path = args.out_dir / "southern_power_annual_generation.metadata.json"
    csv_path.write_bytes(content)
    metadata_path.write_text(
        json.dumps(
            {
                "source": "data.go.kr",
                "dataset_url": DATASET_URL,
                "download_url": args.url,
                "row_count": len(data),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(data)} annual generation rows to {csv_path}")


if __name__ == "__main__":
    main()
