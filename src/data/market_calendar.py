"""NYSE 개장일 체크. 휴장(주말·미국 공휴일)에는 리포트 스킵.

파이프라인은 07:00 KST(= UTC 22:00 = ET 전날 17~18시) 실행이므로, "오늘 ET"
= "전일 KST" 에 해당하는 세션이 개장일이었는지를 확인한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
from loguru import logger

_NYSE = mcal.get_calendar("NYSE")
_US_TZ = ZoneInfo("America/New_York")


def today_in_et() -> date:
    """현재 시각을 미국 동부(ET) 기준 날짜로 반환."""
    return datetime.now(_US_TZ).date()


def is_nyse_open_on(target: date) -> bool:
    """주어진 ET 날짜에 NYSE 정규 세션이 있었는지 여부."""
    schedule = _NYSE.schedule(
        start_date=target.isoformat(),
        end_date=target.isoformat(),
    )
    return not schedule.empty


def get_previous_market_day(reference: date | None = None) -> date:
    """reference로부터 직전 개장일. reference가 개장일이면 reference 자체를 반환.

    최근 10일 내에서 검색 — 연속 휴장(추수감사절 등)도 충분히 커버.
    """
    if reference is None:
        reference = today_in_et()
    schedule = _NYSE.schedule(
        start_date=(reference - timedelta(days=10)).isoformat(),
        end_date=reference.isoformat(),
    )
    if schedule.empty:
        raise RuntimeError(f"최근 10일 내 개장일 없음: reference={reference}")
    return schedule.index[-1].date()


if __name__ == "__main__":
    today = today_in_et()
    print(f"오늘(ET): {today}")
    print(f"NYSE 개장 여부: {is_nyse_open_on(today)}")
    print(f"직전 개장일: {get_previous_market_day(today)}")

    # 테스트 케이스: 주말·공휴일
    test_dates = [
        date(2026, 1, 1),   # 신정 (휴장)
        date(2026, 1, 19),  # MLK Day 월요일 (휴장)
        date(2026, 4, 3),   # Good Friday (휴장)
        date(2026, 4, 4),   # 토요일 (휴장)
        date(2026, 4, 6),   # 월요일 (개장)
        date(2026, 7, 3),   # 독립기념일 대체 (휴장)
    ]
    print("\n[샘플 날짜 검증]")
    for d in test_dates:
        print(f"  {d} ({d.strftime('%A')}): open={is_nyse_open_on(d)}")
