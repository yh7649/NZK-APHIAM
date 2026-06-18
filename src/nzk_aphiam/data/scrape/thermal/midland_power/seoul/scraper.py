from __future__ import annotations

from collections.abc import Sequence

from nzk_aphiam.data.scrape.thermal.midland_power import facility_status_scraper


def main(argv: Sequence[str] | None = None) -> None:
    facility_status_scraper.main(["--facility", "seoul", *(argv or [])])


if __name__ == "__main__":
    main()
