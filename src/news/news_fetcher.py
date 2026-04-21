"""yfinance `.news`를 사용해 종목별 최근 N시간 뉴스를 수집.

설계 주의점:
  - yfinance 뉴스 스키마는 버전에 따라 2종 존재:
    * old flat:     {'title', 'link', 'providerPublishTime'(unix), 'publisher'}
    * new nested:   {'content': {'title', 'canonicalUrl': {'url'}, 'pubDate'(ISO), 'provider': {'displayName'}}}
    → 양쪽 모두 방어적 파싱. 키 누락 시 해당 아이템만 skip.
  - 외부 호출 실패는 해당 티커만 빈 리스트로 퇴각, 전체 배치 실패 금지.
  - 향후 NewsAPI/Finnhub 교체 가능하도록 인터페이스 안정화.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import NEWS_LOOKBACK_HOURS, NEWS_MAX_PER_TICKER  # noqa: E402


@dataclass
class NewsItem:
    """단일 뉴스 아이템. published_at은 UTC."""

    ticker: str
    title: str
    url: str
    published_at: datetime
    publisher: str


_MAX_WORKERS = 10


def _parse_pub_date(value: object) -> datetime | None:
    """pubDate/providerPublishTime을 UTC datetime으로.

    - int/str 형태의 unix timestamp
    - ISO 8601 문자열 (끝에 Z 또는 +offset)
    둘 다 허용. 실패 시 None.
    """
    if value is None:
        return None
    # unix timestamp (int/float/숫자 문자열)
    try:
        ts = float(value)
        if ts > 1e12:  # ms 단위일 가능성 방어
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (TypeError, ValueError):
        pass
    # ISO 문자열
    try:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_news_item(ticker: str, raw: dict) -> NewsItem | None:
    """yfinance raw 뉴스 dict를 NewsItem으로. 스키마 2종 지원.

    실패 시(필수 필드 누락) None.
    """
    try:
        if isinstance(raw.get("content"), dict):
            # 새 nested 스키마
            c = raw["content"]
            title = c.get("title")
            url_obj = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
            url = url_obj.get("url") if isinstance(url_obj, dict) else None
            published_at = _parse_pub_date(c.get("pubDate") or c.get("displayTime"))
            provider = c.get("provider") or {}
            publisher = provider.get("displayName", "") if isinstance(provider, dict) else ""
        else:
            # 구 flat 스키마
            title = raw.get("title")
            url = raw.get("link")
            published_at = _parse_pub_date(raw.get("providerPublishTime"))
            publisher = raw.get("publisher", "") or ""

        if not title or not url or published_at is None:
            return None

        return NewsItem(
            ticker=ticker,
            title=str(title).strip(),
            url=str(url).strip(),
            published_at=published_at,
            publisher=str(publisher).strip(),
        )
    except Exception as e:
        logger.debug(f"[{ticker}] 뉴스 아이템 파싱 실패: {e}")
        return None


def fetch_news_for_ticker(
    ticker: str,
    hours: int = NEWS_LOOKBACK_HOURS,
    max_items: int = NEWS_MAX_PER_TICKER,
) -> list[NewsItem]:
    """단일 티커의 최근 N시간 뉴스 최대 max_items개 (최신순).

    Args:
        ticker: yfinance 포맷 티커.
        hours: lookback 윈도우 (시간).
        max_items: 최대 반환 개수.

    Returns:
        NewsItem 리스트. 실패·뉴스 없음 시 빈 리스트.
    """
    try:
        raw_list = yf.Ticker(ticker).news or []
    except Exception as e:
        logger.warning(f"[{ticker}] 뉴스 조회 실패: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items: list[NewsItem] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        item = _parse_news_item(ticker, raw)
        if item is None:
            continue
        if item.published_at < cutoff:
            continue
        items.append(item)

    # 최신순 정렬 후 상위 max_items
    items.sort(key=lambda x: x.published_at, reverse=True)
    return items[:max_items]


def fetch_news_batch(
    tickers: list[str],
    hours: int = NEWS_LOOKBACK_HOURS,
    max_per_ticker: int = NEWS_MAX_PER_TICKER,
) -> dict[str, list[NewsItem]]:
    """여러 티커 뉴스를 병렬 조회.

    Returns: {ticker: [NewsItem, ...]} (뉴스 없는 티커는 빈 리스트).
    """
    if not tickers:
        return {}

    # 중복 제거 (동일 티커 중복 호출 방지)
    unique = list(dict.fromkeys(tickers))
    result: dict[str, list[NewsItem]] = {t: [] for t in unique}

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_news_for_ticker, t, hours, max_per_ticker): t
            for t in unique
        }
        for fut in as_completed(future_map):
            ticker = future_map[fut]
            try:
                result[ticker] = fut.result()
            except Exception as e:
                logger.warning(f"[{ticker}] 뉴스 future 실패: {e}")

    total_articles = sum(len(v) for v in result.values())
    covered = sum(1 for v in result.values() if v)
    logger.info(
        f"뉴스 배치 완료: {covered}/{len(unique)}개 티커에서 총 {total_articles}건 수집"
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="yfinance 뉴스 수집 테스트")
    parser.add_argument(
        "tickers",
        nargs="*",
        default=["AAPL", "MSFT"],
        help="조회할 티커들 (기본: AAPL MSFT)",
    )
    parser.add_argument("--hours", type=int, default=NEWS_LOOKBACK_HOURS)
    parser.add_argument("--max", type=int, default=NEWS_MAX_PER_TICKER)
    args = parser.parse_args()

    news_map = fetch_news_batch(
        args.tickers, hours=args.hours, max_per_ticker=args.max
    )

    for ticker, items in news_map.items():
        print(f"\n=== {ticker} (n={len(items)}) ===")
        for it in items:
            age_h = (datetime.now(timezone.utc) - it.published_at).total_seconds() / 3600
            print(f"  [{age_h:>4.1f}h ago] {it.publisher}")
            print(f"    {it.title[:100]}")
            print(f"    {it.url[:100]}")
