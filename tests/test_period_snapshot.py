import datetime as dt

import pandas as pd

from nzk_aphiam.data.scrape.common.period_snapshot import save_period_snapshots

FIXED_TODAY = dt.date(2026, 6, 30)


def _rows(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(records)


def test_first_run_writes_one_new_snapshot_per_period(tmp_path) -> None:
    rows = _rows(
        [
            {"date": "2010-01-01", "plant": "A", "value": 1},
            {"date": "2010-02-01", "plant": "A", "value": 2},
            {"date": "2011-01-01", "plant": "A", "value": 3},
        ]
    )

    summary = save_period_snapshots(
        rows,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    statuses = {period.period: period.status for period in summary.periods}
    assert statuses == {"2010": "new", "2011": "new"}
    assert summary.combined_row_count == 3
    assert (tmp_path / "source.source.2010.csv").exists()
    assert (tmp_path / "source.source.2011.csv").exists()
    assert (tmp_path / "source.csv").exists()


def test_unchanged_period_is_not_rewritten(tmp_path) -> None:
    rows = _rows([{"date": "2010-01-01", "plant": "A", "value": 1}])
    save_period_snapshots(
        rows,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )
    period_path = tmp_path / "source.source.2010.csv"
    first_mtime = period_path.stat().st_mtime_ns

    summary = save_period_snapshots(
        rows,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    assert summary.periods[0].status == "unchanged"
    assert period_path.stat().st_mtime_ns == first_mtime


def test_open_current_period_growth_is_extended_not_revised(tmp_path) -> None:
    today = dt.date(2026, 6, 30)
    rows_v1 = _rows([{"date": "2026-01-01", "plant": "A", "value": 1}])
    save_period_snapshots(
        rows_v1,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=today,
    )

    rows_v2 = _rows(
        [
            {"date": "2026-01-01", "plant": "A", "value": 1},
            {"date": "2026-06-01", "plant": "A", "value": 9},
        ]
    )
    summary = save_period_snapshots(
        rows_v2,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=today,
    )

    assert summary.periods[0].status == "extended"
    assert summary.periods[0].row_count == 2
    assert summary.revisions == []


def test_closed_period_content_change_is_flagged_as_revision(tmp_path) -> None:
    rows_v1 = _rows([{"date": "2010-01-01", "plant": "A", "value": 1}])
    save_period_snapshots(
        rows_v1,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    rows_v2 = _rows([{"date": "2010-01-01", "plant": "A", "value": 999}])
    summary = save_period_snapshots(
        rows_v2,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    assert summary.periods[0].status == "revised"
    assert summary.periods[0].removed_row_count == 1
    assert summary.periods[0].added_row_count == 1
    assert summary.revisions and summary.revisions[0].period == "2010"


def test_combined_file_reflects_full_latest_dataset_regardless_of_period_status(
    tmp_path,
) -> None:
    rows_v1 = _rows(
        [
            {"date": "2010-01-01", "plant": "A", "value": 1},
            {"date": "2011-01-01", "plant": "A", "value": 2},
        ]
    )
    save_period_snapshots(
        rows_v1,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    rows_v2 = _rows(
        [
            {"date": "2010-01-01", "plant": "A", "value": 1},
            {"date": "2011-01-01", "plant": "A", "value": 2},
            {"date": "2012-01-01", "plant": "A", "value": 3},
        ]
    )
    summary = save_period_snapshots(
        rows_v2,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    combined = pd.read_csv(summary.combined_path)
    assert len(combined) == 3
    assert sorted(combined["value"].tolist()) == [1, 2, 3]


def test_month_granularity_periods(tmp_path) -> None:
    rows = _rows(
        [
            {"date": "2024-01-15", "plant": "A", "value": 1},
            {"date": "2024-02-15", "plant": "A", "value": 2},
        ]
    )
    summary = save_period_snapshots(
        rows,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        granularity="month",
        today=FIXED_TODAY,
    )
    periods = {period.period for period in summary.periods}
    assert periods == {"202401", "202402"}


def test_unseparated_yyyymm_requires_explicit_format_to_parse_correctly(tmp_path) -> None:
    # "201201" silently misparses to year 2001 under pandas' default date
    # inference (it reads as day=20, month=12, year=2001), which would file
    # Midland Power's 2012 rows under a 2001 snapshot without raising an
    # error. An explicit date_format is what prevents that.
    rows = _rows([{"ym": "201201", "plant": "A", "value": 1}])
    summary = save_period_snapshots(
        rows,
        date_column="ym",
        date_format="%Y%m",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )
    assert [period.period for period in summary.periods] == ["2012"]


def test_whitespace_padded_numeric_strings_do_not_trigger_false_revision(tmp_path) -> None:
    # A column like "    13.84" (leading-space-padded, as Midland Power's
    # source emits) can get re-inferred as a clean float on a bare re-read
    # from disk, which would make an unchanged period look revised purely
    # from dtype drift rather than any real content change.
    rows = _rows(
        [
            {"date": "2010-01-01", "plant": "A", "uper": "    13.84"},
            {"date": "2010-02-01", "plant": "B", "uper": "21.67"},
        ]
    )
    save_period_snapshots(
        rows,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    summary = save_period_snapshots(
        rows,
        date_column="date",
        date_format="%Y-%m-%d",
        output_dir=tmp_path,
        stem="source",
        today=FIXED_TODAY,
    )

    assert summary.periods[0].status == "unchanged"
