"""rankings.py 순수 함수 단위 테스트. mock DataFrame만 사용, 네트워크 없음."""
from __future__ import annotations

import pandas as pd
import pytest

from src.analysis.rankings import (
    RankedStock,
    top_by_market_cap,
    top_by_turnover_ratio,
    top_gainers_losers,
)


def _row(
    ticker: str,
    name: str,
    change_pct: float,
    market_cap: float,
    dollar_volume: float,
) -> dict:
    turnover = dollar_volume / market_cap if market_cap else 0.0
    return {
        "ticker": ticker,
        "name": name,
        "prev_close": 100.0,
        "last_close": 100.0 * (1 + change_pct / 100),
        "change_pct": change_pct,
        "market_cap": market_cap,
        "dollar_volume": dollar_volume,
        "turnover_ratio": turnover,
    }


@pytest.fixture
def sample_df() -> pd.DataFrame:
    rows = [
        _row("MEGA", "Mega Corp", 1.0, 3e12, 3e10),
        _row("BIG", "Big Co", 2.0, 1e12, 2e10),
        _row("MID", "Mid Co", -0.5, 5e11, 1e10),
        _row("SMALL", "Small Co", 8.0, 2e11, 8e9),
        _row("DROP", "Drop Inc", -5.0, 3e11, 5e9),
        # 소형주 — 시총 $0.5B (< MIN_MARKET_CAP $1B)
        _row("TINY", "Tiny Inc", 15.0, 5e8, 1e9),
        # NaN / 0 케이스 (filter 대상)
        _row("NAN", "Nan Inc", float("nan"), 1e10, 1e8),
        _row("ZERO", "Zero Cap", 1.0, 0.0, 0.0),
    ]
    return pd.DataFrame(rows)


class TestTopByMarketCap:
    def test_descending_order(self, sample_df: pd.DataFrame) -> None:
        result = top_by_market_cap(sample_df, n=3)
        assert [r.ticker for r in result] == ["MEGA", "BIG", "MID"]

    def test_returns_ranked_stock_instances(self, sample_df: pd.DataFrame) -> None:
        result = top_by_market_cap(sample_df, n=2)
        assert all(isinstance(r, RankedStock) for r in result)

    def test_rank_reason(self, sample_df: pd.DataFrame) -> None:
        result = top_by_market_cap(sample_df, n=3)
        assert result[0].rank_reason == "시총 1위"
        assert result[2].rank_reason == "시총 3위"

    def test_excludes_nan_and_zero(self, sample_df: pd.DataFrame) -> None:
        result = top_by_market_cap(sample_df, n=100)
        tickers = [r.ticker for r in result]
        assert "NAN" not in tickers
        assert "ZERO" not in tickers


class TestTopGainersLosers:
    def test_gainers_descending(self, sample_df: pd.DataFrame) -> None:
        gainers, _ = top_gainers_losers(sample_df, n=3)
        # TINY(+15)가 최고, BIG(+2), MEGA(+1) 순
        assert gainers[0].ticker == "TINY"
        assert gainers[0].change_pct >= gainers[1].change_pct >= gainers[2].change_pct

    def test_losers_most_negative_first(self, sample_df: pd.DataFrame) -> None:
        _, losers = top_gainers_losers(sample_df, n=3)
        assert losers[0].ticker == "DROP"
        # ascending: -5 < -0.5 < ...
        assert losers[0].change_pct <= losers[1].change_pct

    def test_rank_reason_labels(self, sample_df: pd.DataFrame) -> None:
        gainers, losers = top_gainers_losers(sample_df, n=1)
        assert "상승률" in gainers[0].rank_reason
        assert "하락률" in losers[0].rank_reason


class TestTopByTurnoverRatio:
    def test_excludes_below_min_market_cap(self, sample_df: pd.DataFrame) -> None:
        # TINY는 회전율 가장 높지만 시총 $0.5B < $1B → 제외돼야
        result = top_by_turnover_ratio(sample_df, n=10, min_market_cap=1e9)
        assert "TINY" not in [r.ticker for r in result]

    def test_descending_turnover_ratio(self, sample_df: pd.DataFrame) -> None:
        result = top_by_turnover_ratio(sample_df, n=3, min_market_cap=1e9)
        for a, b in zip(result, result[1:]):
            assert a.turnover_ratio >= b.turnover_ratio

    def test_rank_reason(self, sample_df: pd.DataFrame) -> None:
        result = top_by_turnover_ratio(sample_df, n=1, min_market_cap=1e9)
        assert "거래대금비율" in result[0].rank_reason


class TestValidationAndEdgeCases:
    def test_missing_columns_raises(self) -> None:
        df = pd.DataFrame([{"ticker": "X"}])
        with pytest.raises(ValueError, match="누락 컬럼"):
            top_by_market_cap(df)

    def test_empty_df_returns_empty_list(self) -> None:
        schema_cols = [
            "ticker", "name", "prev_close", "last_close", "change_pct",
            "market_cap", "dollar_volume", "turnover_ratio",
        ]
        empty = pd.DataFrame(columns=schema_cols)
        assert top_by_market_cap(empty) == []
        g, l = top_gainers_losers(empty)
        assert g == [] and l == []
        assert top_by_turnover_ratio(empty) == []

    def test_n_larger_than_data(self, sample_df: pd.DataFrame) -> None:
        # NAN, ZERO 제외하면 6개. n=100 요청해도 6개만 반환.
        result = top_by_market_cap(sample_df, n=100)
        assert 1 <= len(result) <= 6
