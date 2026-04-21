"""현재 S&P 500 구성종목 리스트를 위키피디아에서 스크래핑.

- 성공 시 `data/cache/sp500_list.json`에 저장하고 24시간 내에는 캐시 사용.
- 스크래핑 실패 시 오래된 캐시라도 fallback.
- yfinance 티커 포맷으로 정규화 (BRK.B → BRK-B).
"""
from __future__ import annotations

import json
import sys
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import CACHE_DIR, SP500_CACHE_TTL_SEC  # noqa: E402

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CACHE_FILE = CACHE_DIR / "sp500_list.json"

# 위키피디아는 기본 UA 거부. 일반 UA 필수.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sp500-bot/1.0)"}


def _normalize_ticker(symbol: str) -> str:
    """위키 표기(BRK.B) → yfinance 포맷(BRK-B)."""
    return symbol.strip().replace(".", "-")


def _fetch_from_wiki() -> list[dict]:
    """위키피디아 constituents 테이블을 파싱해 종목 리스트 반환."""
    resp = requests.get(WIKI_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()

    # pd.read_html은 lxml/bs4 기반 — 구조 변경에 꽤 견고.
    # 첫 번째 테이블이 "Symbol, Security, GICS Sector, ..." 구조.
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]

    required = {"Symbol", "Security", "GICS Sector"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"Wikipedia 테이블 스키마 변경 감지, 누락 컬럼: {missing}")

    rows: list[dict] = []
    for _, row in df.iterrows():
        ticker = _normalize_ticker(str(row["Symbol"]))
        name = str(row["Security"]).strip()
        sector = str(row["GICS Sector"]).strip()
        if not ticker or ticker.lower() == "nan":
            continue
        rows.append({"ticker": ticker, "name": name, "sector": sector})
    return rows


def _load_cache() -> list[dict] | None:
    """캐시 파일을 로드. 없거나 파싱 실패 시 None."""
    if not CACHE_FILE.exists():
        return None
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"캐시 파싱 실패: {e}")
        return None


def _save_cache(data: list[dict]) -> None:
    """캐시 저장. 디렉토리 없으면 생성."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_sp500_tickers(force_refresh: bool = False) -> list[dict]:
    """S&P 500 종목 리스트 반환: [{ticker, name, sector}, ...]

    Args:
        force_refresh: True면 캐시 무시하고 위키피디아에서 재조회.

    Raises:
        RuntimeError: 조회 실패 + 캐시도 없을 때.
    """
    # 캐시 TTL 내면 그대로 사용
    if not force_refresh and CACHE_FILE.exists():
        age_sec = time.time() - CACHE_FILE.stat().st_mtime
        if age_sec < SP500_CACHE_TTL_SEC:
            cached = _load_cache()
            if cached:
                logger.debug(f"캐시 사용 (age={age_sec / 3600:.1f}h, n={len(cached)})")
                return cached

    try:
        data = _fetch_from_wiki()
        _save_cache(data)
        logger.info(f"위키피디아에서 {len(data)}개 종목 조회 완료")
        return data
    except Exception as e:
        logger.error(f"위키피디아 조회 실패: {e}")
        # TTL 지났더라도 stale 캐시 fallback — 장애 시 마지막 수단
        cached = _load_cache()
        if cached:
            age_h = (time.time() - CACHE_FILE.stat().st_mtime) / 3600
            logger.warning(f"stale 캐시 fallback (age={age_h:.1f}h, n={len(cached)})")
            return cached
        raise RuntimeError("S&P 500 리스트 조회 실패 + 사용 가능한 캐시 없음") from e


if __name__ == "__main__":
    tickers = get_sp500_tickers()
    print(f"\n총 {len(tickers)}개 종목\n")
    print("─" * 60)
    print(f"{'Ticker':<8} {'Name':<32} Sector")
    print("─" * 60)
    for t in tickers[:5]:
        print(f"{t['ticker']:<8} {t['name'][:30]:<32} {t['sector']}")
    print("─" * 60)
    print(f"(처음 5개만 표시)\n캐시 위치: {CACHE_FILE}")
