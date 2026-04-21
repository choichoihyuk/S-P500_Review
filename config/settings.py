"""환경변수 로딩 + 전역 상수.

모든 모듈은 시크릿·설정을 이 파일에서 임포트한다. .env 직접 참조 금지.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 = 이 파일의 두 단계 상위
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

# ─────────────────────────────────────────────
# Secrets (.env)
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ─────────────────────────────────────────────
# Schedule
# ─────────────────────────────────────────────
TIMEZONE: str = "Asia/Seoul"
RUN_HOUR: int = 7
RUN_MINUTE: int = 0

# ─────────────────────────────────────────────
# Data / Analysis
# ─────────────────────────────────────────────
# 거래대금 비율 Top 계산 시 소형주 이상치 방지용 하한 (USD)
MIN_MARKET_CAP: float = 1_000_000_000.0  # $1B

# S&P 500 리스트 캐시 TTL (초)
SP500_CACHE_TTL_SEC: int = 24 * 60 * 60

# 순위 크기
TOP_N: int = 10

# 뉴스
NEWS_LOOKBACK_HOURS: int = 24
NEWS_MAX_PER_TICKER: int = 3

# 텔레그램 메시지 제한
TELEGRAM_MAX_MESSAGE_LEN: int = 4096

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
CACHE_DIR: Path = PROJECT_ROOT / "data" / "cache"
LOG_DIR: Path = PROJECT_ROOT / "logs"


def validate() -> None:
    """필수 환경변수가 있는지 검증. main/sender 진입 시 호출."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID:
        missing.append("TELEGRAM_CHANNEL_ID")
    if missing:
        raise RuntimeError(
            f".env에 다음 환경변수가 누락되었습니다: {', '.join(missing)}. "
            ".env.example을 복사해 .env를 만들고 값을 채워주세요."
        )


if __name__ == "__main__":
    print(f"PROJECT_ROOT  : {PROJECT_ROOT}")
    print(f"TIMEZONE      : {TIMEZONE}")
    print(f"RUN_HOUR      : {RUN_HOUR:02d}:{RUN_MINUTE:02d}")
    print(f"TOP_N         : {TOP_N}")
    print(f"MIN_MARKET_CAP: ${MIN_MARKET_CAP:,.0f}")
    print(f"TELEGRAM_TOKEN: {'(set)' if TELEGRAM_BOT_TOKEN else '(MISSING)'}")
    print(f"TELEGRAM_CHID : {TELEGRAM_CHANNEL_ID or '(MISSING)'}")
