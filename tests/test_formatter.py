"""formatter.py 단위 테스트: 포맷 헬퍼 + HTML escape + 4096자 제한."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.analysis.rankings import RankedStock
from src.news.news_fetcher import NewsItem
from src.telegram_bot.formatter import (
    _format_change,
    _format_mcap,
    _format_stock,
    _format_turnover,
    format_full_report,
)


def _rs(
    ticker: str = "X",
    name: str = "Corp X",
    change_pct: float = 1.0,
    market_cap: float = 1e12,
    dollar_volume: float = 1e10,
    rank_reason: str = "r",
) -> RankedStock:
    turnover = dollar_volume / market_cap
    return RankedStock(
        ticker, name, change_pct, market_cap, dollar_volume, turnover, rank_reason
    )


class TestFormatHelpers:
    def test_mcap_trillion(self) -> None:
        assert _format_mcap(5e12) == "$5.00T"
        assert _format_mcap(1e12) == "$1.00T"

    def test_mcap_billion(self) -> None:
        assert _format_mcap(50e9) == "$50.0B"
        assert _format_mcap(500e9) == "$500.0B"

    def test_change_positive_green_emoji(self) -> None:
        s = _format_change(1.23)
        assert s.startswith("🟢")
        assert "+1.23%" in s

    def test_change_negative_red_emoji(self) -> None:
        s = _format_change(-2.5)
        assert s.startswith("🔴")
        assert "-2.50%" in s

    def test_change_zero_white_emoji(self) -> None:
        assert _format_change(0.0).startswith("⚪")

    def test_turnover_percent(self) -> None:
        assert _format_turnover(0.0049) == "회전율 0.49%"
        assert _format_turnover(0.0) == "회전율 0.00%"


class TestHTMLEscape:
    def test_name_escapes_ampersand_and_angle_brackets(self) -> None:
        stock = _rs(name="Foo & <Bar>")
        block = _format_stock(1, stock, [])
        assert "Foo &amp; &lt;Bar&gt;" in block
        # 원본 문자가 이스케이프되지 않은 채 등장하면 안 됨
        assert " & " not in block.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "")

    def test_news_title_escape(self) -> None:
        news = [NewsItem("X", "Acme <spoiler> & more",
                         "https://example.com?a=1&b=2",
                         datetime.now(timezone.utc), "Reuters")]
        block = _format_stock(1, _rs(), news)
        assert "&lt;spoiler&gt;" in block
        assert "a=1&amp;b=2" in block

    def test_publisher_escape(self) -> None:
        news = [NewsItem("X", "T", "https://ex.com",
                         datetime.now(timezone.utc), "Reu<ters>")]
        block = _format_stock(1, _rs(), news)
        assert "Reu&lt;ters&gt;" in block


class TestStockBlock:
    def test_no_news_fallback_text(self) -> None:
        block = _format_stock(1, _rs(), [])
        assert "24h 이내 뉴스 없음" in block

    def test_ticker_in_output(self) -> None:
        block = _format_stock(1, _rs(ticker="NVDA"), [])
        assert "NVDA" in block
        assert "<b>1. NVDA</b>" in block


class TestFullReport:
    def _big_report(self) -> tuple:
        stocks = [
            _rs(ticker=f"T{i:02d}", name=f"Company Name Number {i}",
                change_pct=0.5 * (i - 5), market_cap=(100 - i) * 1e10,
                dollar_volume=(50 - i) * 1e8, rank_reason=f"rank{i}")
            for i in range(1, 11)
        ]
        now = datetime.now(timezone.utc)
        news_map = {
            s.ticker: [
                NewsItem(s.ticker, f"Headline number {j} for ticker {s.ticker}",
                         f"https://example.com/{s.ticker}/{j}",
                         now - timedelta(hours=j), "Major Publisher Name")
                for j in range(1, 4)
            ]
            for s in stocks
        }
        return stocks, news_map

    def test_each_message_within_4096(self) -> None:
        stocks, news_map = self._big_report()
        messages = format_full_report(stocks, stocks, stocks, stocks, news_map)
        assert len(messages) >= 1
        for i, m in enumerate(messages):
            assert len(m) <= 4096, f"메시지 {i} 길이 {len(m)}자 > 4096"

    def test_header_in_first_message(self) -> None:
        stock = _rs()
        messages = format_full_report([stock], [stock], [stock], [stock], {})
        assert "S&amp;P 500" in messages[0]

    def test_returns_nonempty_list(self) -> None:
        stock = _rs()
        messages = format_full_report([stock], [stock], [stock], [stock], {})
        assert len(messages) >= 1
        assert all(isinstance(m, str) and m for m in messages)

    def test_handles_missing_news_per_ticker(self) -> None:
        stocks, news_map = self._big_report()
        # 뉴스 맵에서 절반 제거 → 에러 없이 "뉴스 없음" 표시
        partial_news = {k: v for i, (k, v) in enumerate(news_map.items()) if i % 2 == 0}
        messages = format_full_report(stocks, stocks, stocks, stocks, partial_news)
        combined = "\n".join(messages)
        assert "24h 이내 뉴스 없음" in combined
