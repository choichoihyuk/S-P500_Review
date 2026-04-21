"""news_fetcher.py 단위 테스트: pubDate 파싱 + 스키마 2종 + 24h 경계 필터."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.news import news_fetcher
from src.news.news_fetcher import _parse_news_item, _parse_pub_date


class TestParsePubDate:
    def test_unix_seconds_int(self) -> None:
        # 2023-11-14 22:13:20 UTC
        dt = _parse_pub_date(1700000000)
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2023

    def test_unix_milliseconds(self) -> None:
        dt = _parse_pub_date(1700000000000)
        assert dt is not None
        # ms → s 자동 변환으로 같은 연도
        assert dt.year == 2023

    def test_iso_z_suffix(self) -> None:
        dt = _parse_pub_date("2024-06-15T10:30:00Z")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert (dt.year, dt.month, dt.day) == (2024, 6, 15)

    def test_iso_with_offset_normalized_to_utc(self) -> None:
        # +09:00 → UTC 01:30
        dt = _parse_pub_date("2024-06-15T10:30:00+09:00")
        assert dt is not None
        assert dt.utcoffset() == timedelta(0)
        assert dt.hour == 1 and dt.minute == 30

    def test_iso_without_tz_assumed_utc(self) -> None:
        dt = _parse_pub_date("2024-06-15T10:30:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_invalid_inputs_return_none(self) -> None:
        assert _parse_pub_date("not a date") is None
        assert _parse_pub_date(None) is None
        # dict는 숫자로도 ISO로도 파싱 실패
        assert _parse_pub_date({}) is None


class TestParseNewsItem:
    def test_new_nested_schema(self) -> None:
        raw = {
            "content": {
                "title": "Hello World",
                "canonicalUrl": {"url": "https://example.com/hello"},
                "pubDate": "2024-06-15T10:30:00Z",
                "provider": {"displayName": "Reuters"},
            }
        }
        item = _parse_news_item("AAPL", raw)
        assert item is not None
        assert item.title == "Hello World"
        assert item.url == "https://example.com/hello"
        assert item.publisher == "Reuters"
        assert item.ticker == "AAPL"

    def test_old_flat_schema(self) -> None:
        raw = {
            "title": "Old News",
            "link": "https://example.com/old",
            "providerPublishTime": 1700000000,
            "publisher": "Bloomberg",
        }
        item = _parse_news_item("MSFT", raw)
        assert item is not None
        assert item.title == "Old News"
        assert item.url == "https://example.com/old"
        assert item.publisher == "Bloomberg"

    def test_new_schema_clickthrough_fallback(self) -> None:
        # canonicalUrl 없고 clickThroughUrl만 있는 경우
        raw = {
            "content": {
                "title": "Click",
                "clickThroughUrl": {"url": "https://ex.com/c"},
                "pubDate": "2024-06-15T10:30:00Z",
            }
        }
        item = _parse_news_item("X", raw)
        assert item is not None
        assert item.url == "https://ex.com/c"

    def test_missing_title_returns_none(self) -> None:
        raw = {"content": {"canonicalUrl": {"url": "https://x"},
                           "pubDate": "2024-06-15T00:00:00Z"}}
        assert _parse_news_item("X", raw) is None

    def test_missing_url_returns_none(self) -> None:
        raw = {"content": {"title": "T", "pubDate": "2024-06-15T00:00:00Z"}}
        assert _parse_news_item("X", raw) is None

    def test_missing_pub_date_returns_none(self) -> None:
        raw = {"content": {"title": "T", "canonicalUrl": {"url": "https://x"}}}
        assert _parse_news_item("X", raw) is None


class TestFetchNewsFilter:
    """yf.Ticker를 monkeypatch로 대체해 24h 경계를 검증."""

    def test_24h_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = datetime.now(timezone.utc)

        def _iso(dt: datetime) -> str:
            return dt.isoformat().replace("+00:00", "Z")

        raw_news = [
            # in window: 1h ago
            {"content": {"title": "Recent", "canonicalUrl": {"url": "u1"},
                         "pubDate": _iso(now - timedelta(hours=1)),
                         "provider": {"displayName": "P"}}},
            # boundary: 23h50m ago — IN (< 24h)
            {"content": {"title": "EdgeIn", "canonicalUrl": {"url": "u2"},
                         "pubDate": _iso(now - timedelta(hours=23, minutes=50)),
                         "provider": {"displayName": "P"}}},
            # past 24h — OUT
            {"content": {"title": "Stale", "canonicalUrl": {"url": "u3"},
                         "pubDate": _iso(now - timedelta(hours=25)),
                         "provider": {"displayName": "P"}}},
        ]

        class FakeTicker:
            def __init__(self, symbol: str) -> None:
                self.news = raw_news

        monkeypatch.setattr(news_fetcher.yf, "Ticker", FakeTicker)

        items = news_fetcher.fetch_news_for_ticker("TEST", hours=24, max_items=10)
        titles = [i.title for i in items]
        assert "Recent" in titles
        assert "EdgeIn" in titles
        assert "Stale" not in titles

    def test_max_items_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = datetime.now(timezone.utc)

        raw_news = [
            {"content": {"title": f"H{i}", "canonicalUrl": {"url": f"u{i}"},
                         "pubDate": (now - timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                         "provider": {"displayName": "P"}}}
            for i in range(10)
        ]

        class FakeTicker:
            def __init__(self, symbol: str) -> None:
                self.news = raw_news

        monkeypatch.setattr(news_fetcher.yf, "Ticker", FakeTicker)

        items = news_fetcher.fetch_news_for_ticker("TEST", hours=24, max_items=3)
        assert len(items) == 3
        # 최신순: H0(가장 최근)이 첫 번째
        assert items[0].title == "H0"

    def test_raises_in_inner_call_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """단일 티커 조회 실패 시 빈 리스트 반환 (예외 전파 안 함)."""

        class BrokenTicker:
            def __init__(self, symbol: str) -> None:
                raise RuntimeError("simulated yfinance failure")

        monkeypatch.setattr(news_fetcher.yf, "Ticker", BrokenTicker)

        items = news_fetcher.fetch_news_for_ticker("X", hours=24, max_items=3)
        assert items == []
