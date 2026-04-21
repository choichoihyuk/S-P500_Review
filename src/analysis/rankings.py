"""market_data DataFrame에서 3종 순위를 계산하는 순수 함수들.

네트워크·외부 호출 없음. 입력 DataFrame은 market_data.SCHEMA를 따라야 한다.
단위 테스트가 쉽도록 side-effect 없이 설계.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import MIN_MARKET_CAP, TOP_N  # noqa: E402


@dataclass
class RankedStock:
    """순위에 등장한 종목 1개의 표현.

    rank_reason은 UI/로그에 표시할 한국어 라벨 (예: "시총 1위", "상승률 3위").
    """

    ticker: str
    name: str
    change_pct: float
    market_cap: float
    dollar_volume: float
    turnover_ratio: float
    rank_reason: str


_REQUIRED_COLS = {
    "ticker",
    "name",
    "change_pct",
    "market_cap",
    "dollar_volume",
    "turnover_ratio",
}


def _validate(df: pd.DataFrame) -> None:
    """입력 DataFrame 스키마 검증."""
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame에 누락 컬럼: {missing}")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """NaN 제거 + 시총/거래대금 0인 종목 제외 (비정상 데이터 방지)."""
    before = len(df)
    df = df.dropna(subset=["market_cap", "change_pct", "dollar_volume", "turnover_ratio"])
    df = df[(df["market_cap"] > 0) & (df["dollar_volume"] > 0)]
    dropped = before - len(df)
    if dropped:
        logger.debug(f"_clean: {dropped}개 row drop (NaN 또는 0 시총/거래대금)")
    return df


def _to_ranked(row: pd.Series, reason: str) -> RankedStock:
    return RankedStock(
        ticker=str(row["ticker"]),
        name=str(row["name"]),
        change_pct=float(row["change_pct"]),
        market_cap=float(row["market_cap"]),
        dollar_volume=float(row["dollar_volume"]),
        turnover_ratio=float(row["turnover_ratio"]),
        rank_reason=reason,
    )


def top_by_market_cap(df: pd.DataFrame, n: int = TOP_N) -> list[RankedStock]:
    """시가총액 Top n."""
    _validate(df)
    cleaned = _clean(df)
    sorted_df = cleaned.sort_values("market_cap", ascending=False).head(n)
    return [_to_ranked(r, f"시총 {i + 1}위") for i, (_, r) in enumerate(sorted_df.iterrows())]


def top_gainers_losers(
    df: pd.DataFrame, n: int = TOP_N
) -> tuple[list[RankedStock], list[RankedStock]]:
    """일일 등락률 상승 Top n, 하락 Top n을 함께 반환.

    Returns: (gainers, losers). gainers[0]은 최고 상승, losers[0]은 최대 하락.
    """
    _validate(df)
    cleaned = _clean(df)

    gainers_df = cleaned.sort_values("change_pct", ascending=False).head(n)
    losers_df = cleaned.sort_values("change_pct", ascending=True).head(n)

    gainers = [
        _to_ranked(r, f"상승률 {i + 1}위") for i, (_, r) in enumerate(gainers_df.iterrows())
    ]
    losers = [
        _to_ranked(r, f"하락률 {i + 1}위") for i, (_, r) in enumerate(losers_df.iterrows())
    ]
    return gainers, losers


def top_by_turnover_ratio(
    df: pd.DataFrame,
    n: int = TOP_N,
    min_market_cap: float = MIN_MARKET_CAP,
) -> list[RankedStock]:
    """시총 대비 거래대금 비율 Top n.

    소형주는 분모(시총)가 작아 비율이 쉽게 튐 → MIN_MARKET_CAP 이하 제외.
    """
    _validate(df)
    cleaned = _clean(df)
    filtered = cleaned[cleaned["market_cap"] >= min_market_cap]
    excluded = len(cleaned) - len(filtered)
    if excluded:
        logger.debug(
            f"turnover_ratio: 시총 ${min_market_cap / 1e9:.1f}B 미만 {excluded}개 제외"
        )
    sorted_df = filtered.sort_values("turnover_ratio", ascending=False).head(n)
    return [
        _to_ranked(r, f"거래대금비율 {i + 1}위")
        for i, (_, r) in enumerate(sorted_df.iterrows())
    ]


def _print_rank(title: str, stocks: list[RankedStock]) -> None:
    print(f"\n{title}")
    print("─" * 85)
    print(
        f"{'Rank':<5} {'Ticker':<8} {'Name':<28} {'Δ%':>7} "
        f"{'MCap($B)':>10} {'DollarVol($M)':>14} {'TurnR':>8}"
    )
    print("─" * 85)
    for i, s in enumerate(stocks):
        print(
            f"{i + 1:<5} {s.ticker:<8} {s.name[:26]:<28} "
            f"{s.change_pct:>+6.2f}% {s.market_cap / 1e9:>10,.1f} "
            f"{s.dollar_volume / 1e6:>14,.1f} {s.turnover_ratio:>8.4f}"
        )


if __name__ == "__main__":
    from src.data.market_data import fetch_market_data
    from src.data.sp500_list import get_sp500_tickers

    sp500 = get_sp500_tickers()
    name_map = {t["ticker"]: t["name"] for t in sp500}
    # use_cache=True: rate limit 걸린 반복 실행 시에도 10분 내면 바로 결과 사용.
    df = fetch_market_data(
        [t["ticker"] for t in sp500], name_map=name_map, use_cache=True
    )

    mc_top = top_by_market_cap(df)
    gainers, losers = top_gainers_losers(df)
    turnover_top = top_by_turnover_ratio(df)

    # 콘솔(cp949)에서 이모지 UnicodeEncodeError 방지 — 이모지는 텔레그램 포매터에만.
    _print_rank("[시가총액 Top 10]", mc_top)
    _print_rank("[일일 상승률 Top 10]", gainers)
    _print_rank("[일일 하락률 Top 10]", losers)
    _print_rank("[시총 대비 거래대금 비율 Top 10]", turnover_top)
