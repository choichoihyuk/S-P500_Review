"""APScheduler BlockingScheduler — 매일 RUN_HOUR:RUN_MINUTE (KST)에 실행.

대안: OS cron (README 참조). 이 스크립트는 상시 구동 프로세스가 가능한 환경에서
systemd/nohup/pm2 등으로 띄우는 용도.
"""
from __future__ import annotations

import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import RUN_HOUR, RUN_MINUTE, TIMEZONE  # noqa: E402
from src.main import run_daily_report  # noqa: E402


def main() -> None:
    """스케줄러 시작 (blocking). Ctrl+C로 종료."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        run_daily_report,
        trigger=CronTrigger(hour=RUN_HOUR, minute=RUN_MINUTE, timezone=TIMEZONE),
        name="sp500_daily_report",
        # 프로세스가 죽었다가 07:00~08:00 사이에 되살아나면 놓친 실행도 처리
        misfire_grace_time=3600,
        coalesce=True,  # 중복된 미스된 실행은 1회로 합침
    )
    logger.info(
        f"스케줄러 시작: 매일 {RUN_HOUR:02d}:{RUN_MINUTE:02d} {TIMEZONE} "
        f"(misfire_grace=1h, coalesce=True)"
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료 (KeyboardInterrupt)")


if __name__ == "__main__":
    main()
