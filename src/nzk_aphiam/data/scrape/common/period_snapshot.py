"""Write growing raw sources as immutable per-period snapshots.

A scraper that overwrites one cumulative file every run forces a
content-addressed storage tool (e.g. DVC) to re-store the entire historic
record whenever even one new row is appended, since the whole file's hash
changes. Splitting the same data into one immutable file per period (here,
per calendar year) avoids that: a period whose content has not changed since
the last run produces no new file and no new storage, while a period that
has genuinely gained or changed rows produces exactly one new snapshot for
that period alone.

This module decides, per period, whether a fresh pull is new, unchanged, an
expected extension of the still-open current period, or an unexpected
revision to a period that should have been settled. It also writes a
combined file in the same shape callers already produce today, so existing
cleaners and Makefile targets do not need to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import hashlib
from pathlib import Path

import pandas as pd

DEFAULT_CURRENT_PERIOD_GRACE_DAYS = 45


@dataclass(frozen=True)
class PeriodSnapshotResult:
    """Outcome for one period's snapshot file after a scrape attempt."""

    period: str
    status: str  # "new", "unchanged", "extended", or "revised"
    path: Path
    row_count: int
    added_row_count: int = 0
    removed_row_count: int = 0
    sample_removed_rows: list[dict] = field(default_factory=list)
    sample_added_rows: list[dict] = field(default_factory=list)

    def to_metadata_dict(self) -> dict:
        return {
            "period": self.period,
            "status": self.status,
            "path": str(self.path),
            "row_count": self.row_count,
            "added_row_count": self.added_row_count,
            "removed_row_count": self.removed_row_count,
            "sample_removed_rows": self.sample_removed_rows,
            "sample_added_rows": self.sample_added_rows,
        }


@dataclass(frozen=True)
class SnapshotSummary:
    """Full result of one save_period_snapshots() call."""

    combined_path: Path
    combined_row_count: int
    periods: list[PeriodSnapshotResult]

    @property
    def revisions(self) -> list[PeriodSnapshotResult]:
        return [period for period in self.periods if period.status == "revised"]

    def to_metadata_dict(self) -> dict:
        return {
            "combined_path": str(self.combined_path),
            "combined_row_count": self.combined_row_count,
            "periods": [period.to_metadata_dict() for period in self.periods],
        }


def _period_key(value: object, granularity: str, date_format: str | None) -> str:
    timestamp = pd.to_datetime(value, format=date_format) if date_format else pd.Timestamp(value)
    if granularity == "year":
        return f"{timestamp.year:04d}"
    if granularity == "month":
        return f"{timestamp.year:04d}{timestamp.month:02d}"
    raise ValueError(f"Unsupported period granularity: {granularity!r}")


def _period_end_date(period: str, granularity: str) -> dt.date:
    if granularity == "year":
        return dt.date(int(period), 12, 31)
    if granularity == "month":
        year, month = int(period[:4]), int(period[4:6])
        next_month = dt.date(year + (month == 12), (month % 12) + 1, 1)
        return next_month - dt.timedelta(days=1)
    raise ValueError(f"Unsupported period granularity: {granularity!r}")


def _content_hash(frame: pd.DataFrame) -> str:
    canonical = frame.astype(str).sort_values(list(frame.columns), kind="stable")
    payload = canonical.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _row_set_diff(
    old: pd.DataFrame, new: pd.DataFrame, sample_size: int = 5
) -> tuple[int, int, list[dict], list[dict]]:
    old_records = old.astype(str).to_dict("records")
    new_records = new.astype(str).to_dict("records")
    old_keys = {tuple(sorted(row.items())) for row in old_records}
    new_keys = {tuple(sorted(row.items())) for row in new_records}

    removed_keys = old_keys - new_keys
    added_keys = new_keys - old_keys

    removed_rows = [dict(key) for key in list(removed_keys)[:sample_size]]
    added_rows = [dict(key) for key in list(added_keys)[:sample_size]]

    return len(removed_keys), len(added_keys), removed_rows, added_rows


def save_period_snapshots(
    rows: pd.DataFrame,
    *,
    date_column: str,
    date_format: str,
    output_dir: Path,
    stem: str,
    granularity: str = "year",
    current_period_grace_days: int = DEFAULT_CURRENT_PERIOD_GRACE_DAYS,
    today: dt.date | None = None,
) -> SnapshotSummary:
    """Split a freshly fetched dataset into per-period snapshots plus a combined file.

    rows: the full dataset from this scrape attempt (every call is expected
        to re-fetch the full available history; this function decides what
        is actually new relative to what is already on disk).
    date_column: column in `rows` used to assign each row to a period.
    date_format: an explicit strptime format (e.g. "%Y-%m-%d", "%Y%m") for
        `date_column`. Required rather than inferred: an ambiguous source
        format like "201201" silently misparses under pandas' default date
        inference (it reads as 2001-12-20, not 2012-01), which would file
        rows under the wrong period without raising an error. Being explicit
        here trades a little caller verbosity for ruling that bug out.
    output_dir: directory for `{stem}.source.{period}.csv` files and the
        combined `{stem}.csv`, which keeps the same row shape callers
        produced before this helper existed.
    granularity: "year" (default) or "month".
    current_period_grace_days: a period ending within this many days of
        `today` is treated as still open. A content change there is reported
        as "extended" (new data still arriving as expected), not "revised".
    today: override for the current date; defaults to the real today and
        only exists for deterministic tests.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    today = today or dt.date.today()

    working = rows.copy()
    working["_period"] = working[date_column].map(
        lambda value: _period_key(value, granularity, date_format)
    )

    results: list[PeriodSnapshotResult] = []

    for period, period_rows in working.groupby("_period", sort=True):
        period_rows = period_rows.drop(columns="_period").reset_index(drop=True)
        period_path = output_dir / f"{stem}.source.{period}.csv"

        if not period_path.exists():
            period_rows.to_csv(period_path, index=False, encoding="utf-8-sig")
            results.append(PeriodSnapshotResult(period, "new", period_path, len(period_rows)))
            continue

        # dtype=str forces every column to load as the exact literal text in
        # the file. Without it, pandas infers per-column types fresh on each
        # re-read, and a column like Midland's whitespace-padded "uper"
        # ("    13.84") can silently come back as a clean float (13.84) --
        # making an unchanged period look like a false revision, since the
        # padded-vs-stripped strings would no longer hash equal.
        existing = pd.read_csv(period_path, encoding="utf-8-sig", low_memory=False, dtype=str)

        if _content_hash(existing) == _content_hash(period_rows):
            results.append(
                PeriodSnapshotResult(period, "unchanged", period_path, len(period_rows))
            )
            continue

        removed_count, added_count, removed_sample, added_sample = _row_set_diff(
            existing, period_rows
        )
        period_end = _period_end_date(period, granularity)
        is_open_period = (today - period_end).days <= current_period_grace_days
        status = "extended" if is_open_period else "revised"

        period_rows.to_csv(period_path, index=False, encoding="utf-8-sig")
        results.append(
            PeriodSnapshotResult(
                period,
                status,
                period_path,
                len(period_rows),
                added_row_count=added_count,
                removed_row_count=removed_count,
                sample_removed_rows=removed_sample,
                sample_added_rows=added_sample,
            )
        )

    combined = working.drop(columns="_period").sort_values(date_column, kind="stable")
    combined_path = output_dir / f"{stem}.csv"
    combined.to_csv(combined_path, index=False, encoding="utf-8-sig")

    summary = SnapshotSummary(
        combined_path=combined_path,
        combined_row_count=len(combined),
        periods=results,
    )

    revisions = summary.revisions
    if revisions:
        print(
            f"WARNING: {len(revisions)} period(s) changed outside the still-open "
            "window -- this looks like a source revision to historic data, not "
            "just new rows. Review before trusting downstream analysis built on "
            "the prior values:"
        )
        for revision in revisions:
            print(
                f"  - period {revision.period}: {revision.removed_row_count} row(s) "
                f"removed/changed, {revision.added_row_count} row(s) added/changed "
                f"({revision.path})"
            )
            for sample in revision.sample_removed_rows[:2]:
                print(f"      old: {sample}")
            for sample in revision.sample_added_rows[:2]:
                print(f"      new: {sample}")

    return summary
