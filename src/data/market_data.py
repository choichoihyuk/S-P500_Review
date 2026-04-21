"""yfinance로 S&P 500 종목의 주가·시총·거래대금 데이터를 DataFrame으로 반환.

반환 컬럼 스키마 (SCHEMA):
  - ticker         : str   — yfinance 포맷 (BRK-B)
  - name           : str   — 회사명 (name_map에서 제공, 없으면 ticker)
  - prev_close     : float — 전일 종가
  - last_close     : float — 최신 종가
  - change_pct     : float — (last - prev) / prev * 100
  - market_cap     : float — 시가총액 (USD)
  - dollar_volume  : float — 거래대금 = last_close * volume
  - turnover_ratio : float — dollar_volume / market_cap (0~1 범위 드물게 초과)

설계 선택 (왜 yf.download가 아니라 Ticker.fast_info를?):
  yfinance 0.2.x에서 `yf.download()`는 Yahoo의 historical chart API를
  per-symbol로 호출한다 (진짜 배치 아님 — 내부에서 병렬화만). market_cap은
  어차피 별도 endpoint가 필요하므로, `Ticker.fast_info`만 ThreadPoolExecutor로
  병렬화하면 OHLCV + 시총을 한 번의 per-ticker 호출로 모두 커버해 단순해진다.
  `fast_info`는 `.info`보다 10배+ 빠르고 (필요한 필드만 포함된 가벼운 dict),
  rate limit도 상대적으로 관대.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import CACHE_DIR, MIN_MARKET_CAP  # noqa: E402

SCHEMA: list[str] = [
    "ticker",
    "name",
    "prev_close",
    "last_close",
    "change_pct",
    "market_cap",
    "dollar_volume",
    "turnover_ratio",
]

# Yahoo rate limit 회피 + 디버깅 편의용 단기 캐시.
# 운영(매일 07:00) 실행에서는 의미 없음 — 24시간 텀이라 항상 expire.
_DEV_CACHE_PATH = CACHE_DIR / "market_data.pkl"
_DEV_CACHE_TTL_SEC = 10 * 60

_MAX_WORKERS = 10  # 15 → 10: Yahoo rate limit 완화
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SEC = 1.0  # 0.5 → 1.0: rate limit 회복 시간 확보


def _safe_float(val: object) -> float | None:
    """None/NaN/0/문자열 등 방어. 실패 시 None."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check
        return None
    return f


def _fetch_one(ticker: str, name: str) -> dict | None:
    """단일 종목의 fast_info를 조회. 지수 백오프 재시도 최대 3회.

    반환: SCHEMA에 맞는 dict, 또는 실패 시 None.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            fi = yf.Ticker(ticker).fast_info

            # fast_info는 버전에 따라 dict-like 또는 attribute-access.
            # getattr + 기본값으로 둘 다 안전하게 처리.
            last_close = _safe_float(getattr(fi, "last_price", None))
            prev_close = _safe_float(getattr(fi, "previous_close", None))
            volume = _safe_float(getattr(fi, "last_volume", None))
            market_cap = _safe_float(getattr(fi, "market_cap", None))

            if last_close is None or prev_close is None or prev_close == 0:
                logger.debug(f"[{ticker}] 가격 데이터 누락 — skip")
                return None

            volume = volume or 0.0
            market_cap = market_cap or 0.0
            change_pct = (last_close - prev_close) / prev_close * 100.0
            dollar_volume = last_close * volume
            turnover_ratio = dollar_volume / market_cap if market_cap > 0 else 0.0

            return {
                "ticker": ticker,
                "name": name or ticker,
                "prev_close": prev_close,
                "last_close": last_close,
                "change_pct": change_pct,
                "market_cap": market_cap,
                "dollar_volume": dollar_volume,
                "turnover_ratio": turnover_ratio,
            }
        except Exception as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BASE_BACKOFF_SEC * (2**attempt))

    logger.warning(f"[{ticker}] fast_info 조회 실패 ({_MAX_ATTEMPTS}회 재시도): {last_exc}")
    return None


def fetch_market_data(
    tickers: list[str],
    name_map: dict[str, str] | None = None,
    use_cache: bool = False,
) -> pd.DataFrame:
    """S&P 500 종목들의 시장 데이터를 DataFrame으로 반환.

    Args:
        tickers: yfinance 포맷 티커 리스트.
        name_map: {ticker: name} 매핑. 없으면 ticker를 name으로 사용.
        use_cache: True면 10분 내 disk 캐시가 있으면 재사용 (개발/디버깅용).
            운영(일 1회 07:00)에서는 False 유지 — 24h 텀이라 캐시 항상 expire.

    Returns:
        SCHEMA 컬럼을 가진 DataFrame. 실패한 종목은 제외. 시가총액 내림차순 정렬.
    """
    name_map = name_map or {}

    if use_cache and _DEV_CACHE_PATH.exists():
        age = time.time() - _DEV_CACHE_PATH.stat().st_mtime
        if age < _DEV_CACHE_TTL_SEC:
            df = pd.read_pickle(_DEV_CACHE_PATH)
            logger.info(
                f"market data dev 캐시 사용 (age={age:.0f}s, n={len(df)})"
            )
            return df

    started = time.monotonic()
    logger.info(f"market data 조회 시작 ({len(tickers)}개 종목, workers={_MAX_WORKERS})")

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        future_to_ticker = {
            executor.submit(_fetch_one, t, name_map.get(t, t)): t for t in tickers
        }
        for fut in as_completed(future_to_ticker):
            result = fut.result()
            if result is not None:
                rows.append(result)

    elapsed = time.monotonic() - started
    skipped = len(tickers) - len(rows)
    logger.info(
        f"market data 조회 완료: {len(rows)}개 성공, {skipped}개 스킵, {elapsed:.1f}s"
    )

    if not rows:
        return pd.DataFrame(columns=SCHEMA)

    df = pd.DataFrame(rows, columns=SCHEMA)
    df = df.sort_values("market_cap", ascending=False).reset_index(drop=True)

    # use_cache=True면 성공 결과 저장 (다음 반복 실행 시 rate limit 회피).
    if use_cache:
        _DEV_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(_DEV_CACHE_PATH)
        logger.debug(f"market data dev 캐시 저장: {_DEV_CACHE_PATH}")

    return df


if __name__ == "__main__":
    # 같은 패키지의 sp500_list 임포트 — 이름/섹터 매핑 구성
    from src.data.sp500_list import get_sp500_tickers

    sp500 = get_sp500_tickers()
    tickers = [t["ticker"] for t in sp500]
    name_map = {t["ticker"]: t["name"] for t in sp500}

    df = fetch_market_data(tickers, name_map=name_map)

    print(f"\n총 {len(df)}개 종목 데이터 수집 (원본 {len(tickers)}개 중)")
    print("\n시가총액 Top 10:")
    print("─" * 90)
    print(
        f"{'Rank':<5} {'Ticker':<8} {'Name':<28} {'Last':>10} {'Δ%':>7} "
        f"{'MCap($B)':>10} {'TurnoverR':>10}"
    )
    print("─" * 90)
    for i, row in df.head(10).iterrows():
        print(
            f"{i + 1:<5} {row['ticker']:<8} {row['name'][:26]:<28} "
            f"{row['last_close']:>10,.2f} {row['change_pct']:>+6.2f}% "
            f"{row['market_cap'] / 1e9:>10,.1f} {row['turnover_ratio']:>10.4f}"
        )
    print("─" * 90)
    print(f"MIN_MARKET_CAP 필터(${MIN_MARKET_CAP / 1e9:.0f}B) 이하: "
          f"{(df['market_cap'] < MIN_MARKET_CAP).sum()}개")
