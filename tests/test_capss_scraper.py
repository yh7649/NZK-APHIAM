from __future__ import annotations

from nzk_aphiam.data.scrape.capss import scraper


LIST_HTML = """
<a href="view.do?boardId=10&articleId=580&menuId=32" title="2023년 대기오염물질 배출량 통계">
  <span>2023년 대기오염물질 배출량 통계</span>
</a>
<a href="view.do?boardId=10&articleId=295&menuId=32" title="과거연도('16~'19) 대기오염물질 재산정 배출량 통계">
  <span>과거연도 재산정</span>
</a>
"""

ARTICLE_HTML = """
<li>2023년 대기오염물질 배출량 통계(시군구별 배출원소분류별 연료별).xlsx
  <a class="brdIcon_down" href="/file/download.do?fileId=887">다운로드</a>
</li>
<li>2023년 대기오염물질 배출량 통계(시도별).xlsx
  <a class="brdIcon_down" href="/file/download.do?fileId=888">다운로드</a>
</li>
"""

REASSESSMENT_HTML = """
<li>2019년 대기오염물질 배출량 통계(시군구별 배출원소분류별 연료별).xlsx
  <a class="brdIcon_down" href="/file/download.do?fileId=2959">다운로드</a>
</li>
"""


def test_parse_board_list_extracts_capss_article_urls() -> None:
    articles = scraper.parse_board_list(LIST_HTML, "https://www.air.go.kr/article/list.do")

    assert articles[0][0] == 580
    assert articles[0][1] == "2023년 대기오염물질 배출량 통계"
    assert articles[0][2].startswith("https://www.air.go.kr/article/view.do")
    assert articles[1][0] == 295


def test_parse_article_attachments_keeps_detailed_workbook_only() -> None:
    attachments = scraper.parse_article_attachments(
        ARTICLE_HTML,
        article_id=580,
        title="2023년 대기오염물질 배출량 통계",
        article_url="https://www.air.go.kr/article/view.do?articleId=580",
    )

    assert len(attachments) == 1
    assert attachments[0].year == 2023
    assert attachments[0].file_id == 887
    assert attachments[0].download_url == "https://www.air.go.kr/file/download.do?fileId=887"


def test_parse_article_attachments_marks_reassessment_files() -> None:
    attachments = scraper.parse_article_attachments(
        REASSESSMENT_HTML,
        article_id=295,
        title="과거연도('16~'19) 대기오염물질 재산정 배출량 통계",
        article_url="https://www.air.go.kr/article/view.do?articleId=295",
    )

    assert attachments[0].year == 2019
    assert attachments[0].reassessment is True


def test_select_attachments_rejects_missing_years() -> None:
    attachments = scraper.parse_article_attachments(
        ARTICLE_HTML,
        article_id=580,
        title="2023년 대기오염물질 배출량 통계",
        article_url="https://www.air.go.kr/article/view.do?articleId=580",
    )

    try:
        scraper.select_attachments(attachments, 2022, 2023)
    except ValueError as error:
        assert "2022" in str(error)
    else:
        raise AssertionError("Expected missing year to raise ValueError")
