"""전체 일일 리포트 파이프라인. `run_daily_report()`가 엔드-투-엔드 실행.

흐름:
  1. S&P 500 리스트 (sp500_list)
  2. 시장 데이터 (market_data)
  3. 3종 순위 (rankings)
  4. 순위에 등장한 unique 티커만 뽑아 뉴스 조회 (중복 호출 방지)
  5. HTML 메시지 포맷 (formatter)
  6. Telegram 전송 (sender)

각 단계 시작/종료/소요시간을 loguru로 기록. 파일 로그는 `logs/YYYY-MM-DD.log`.
실패 시 traceback 요약을 Telegram으로 알린 뒤 예외 재전파.
"""
from __future__ import annotations

import html
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import LOG_DIR, LOG_LEVEL, TELEGRAM_CHANNEL_ID, TIMEZONE  # noqa: E402
from src.analysis.rankings import (  # noqa: E402
    RankedStock,
    top_by_market_cap,
    top_by_turnover_ratio,
    top_gainers_losers,
)
from src.data import watchlist as watchlist_state  # noqa: E402
from src.data.market_calendar import (  # noqa: E402
    get_previous_market_day,
    is_nyse_open_on,
    today_in_et,
)
from src.data.market_data import fetch_market_data  # noqa: E402
from src.data.sp500_list import get_sp500_tickers  # noqa: E402
from src.news.news_fetcher import fetch_news_batch  # noqa: E402
from src.telegram_bot.commands import (  # noqa: E402
    fetch_updates,
    format_ack_message,
    process_updates,
)
from src.telegram_bot.formatter import format_full_report  # noqa: E402
from src.telegram_bot.sender import send_message, send_messages  # noqa: E402

# market data 장애 감지 임계: 성공률 이 비율 미만이면 중단 + 알림
_MIN_SUCCESS_RATIO = 0.5

# 메가캡 10종 — 이 중 7개 이상 결측이면 yfinance 장애 확정 판정
_MEGA_CAPS: frozenset[str] = frozenset(
    {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B", "JPM", "LLY"}
)
_MEGA_CAP_MISSING_THRESHOLD = 7

_logging_configured = False


def _setup_logging() -> None:
    """stdout/stderr utf-8 재설정 + 일자별 파일 로그 sink 추가 (중복 방지).

    재호출 시 파일 sink 재추가를 막기 위해 module-level 플래그로 1회 가드.
    """
    global _logging_configured
    if _logging_configured:
        return

    # Windows cp949 콘솔에서 이모지·한글 인코딩 에러 방지.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"{today}.log"

    logger.add(
        log_path,
        level=LOG_LEVEL,
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
        enqueue=False,
    )
    _logging_configured = True


def _build_watchlist_stocks(df, watchlist_tickers: list[str]) -> list[RankedStock]:
    """관심종목용 RankedStock 리스트를 df에서 추출.

    - 순위가 아니므로 등락률 내림차순 정렬 (상승 위, 하락 아래).
    - df에 없는 티커(fetch 실패)는 스킵.
    """
    if not watchlist_tickers:
        return []
    sub = df[df["ticker"].isin(watchlist_tickers)].copy()
    if sub.empty:
        return []
    sub = sub.sort_values("change_pct", ascending=False)
    stocks: list[RankedStock] = []
    for _, row in sub.iterrows():
        stocks.append(
            RankedStock(
                ticker=str(row["ticker"]),
                name=str(row["name"]),
                change_pct=float(row["change_pct"]),
                market_cap=float(row["market_cap"]),
                dollar_volume=float(row["dollar_volume"]),
                turnover_ratio=float(row["turnover_ratio"]),
                rank_reason="관심종목",
            )
        )
    return stocks


def _process_user_commands() -> list[str]:
    """getUpdates 풀링 → watchlist 갱신·파일 저장. ack 메시지는 best-effort 전송.

    Returns:
        최신 watchlist 티커 리스트 (비어있을 수 있음). pipeline은 이 리스트를 사용.
    """
    state = watchlist_state.load()
    try:
        updates = fetch_updates(state.last_update_id)
    except Exception as e:
        logger.warning(f"getUpdates 실패 — 기존 watchlist만 사용: {e}")
        return list(state.tickers)

    new_tickers, max_uid, outcome = process_updates(
        updates, state.tickers, authorized_chat_id=TELEGRAM_CHANNEL_ID
    )
    changed = (new_tickers != state.tickers) or (max_uid > state.last_update_id)

    state.tickers = new_tickers
    if max_uid > state.last_update_id:
        state.last_update_id = max_uid

    if changed:
        watchlist_state.save(state)
        logger.info(
            f"[0.5/6] watchlist: {len(new_tickers)}종목 "
            f"(+{len(outcome.added)}/-{len(outcome.removed)}), offset={max_uid}"
        )
    else:
        logger.info("[0.5/6] watchlist: 변경 없음")

    # 유저 피드백 — 전송 실패해도 파이프라인은 계속
    if outcome.has_feedback():
        try:
            ack = (
                "<b>🤖 관심종목 업데이트</b>\n"
                + format_ack_message(outcome, new_tickers)
            )
            send_message(ack)
        except Exception as e:
            logger.warning(f"ack 메시지 전송 실패(무시): {e}")

    return new_tickers


def _check_data_health(df, total_tickers: int) -> None:
    """데이터 건강 검증. 임계 미달 시 RuntimeError로 중단.

    (1) 전체 성공률 50% 미만 → 네트워크/서비스 전면 장애
    (2) 메가캡 10종 중 7개 이상 결측 → yfinance 핵심 데이터 장애
    """
    success = len(df)
    if success < total_tickers * _MIN_SUCCESS_RATIO:
        raise RuntimeError(
            f"market data 성공률 {success}/{total_tickers} "
            f"< {_MIN_SUCCESS_RATIO:.0%} — yfinance 전면 장애 의심"
        )

    fetched_tickers: set[str] = set(df["ticker"].tolist())
    missing = _MEGA_CAPS - fetched_tickers
    if len(missing) >= _MEGA_CAP_MISSING_THRESHOLD:
        raise RuntimeError(
            f"메가캡 {len(missing)}/{len(_MEGA_CAPS)} 결측 → yfinance 핵심 데이터 장애: {sorted(missing)}"
        )
    if missing:
        logger.warning(f"메가캡 일부 누락({len(missing)}개): {sorted(missing)}")


def _notify_holiday(today_et: date, now_kst: datetime) -> None:
    """휴장 안내 메시지. best-effort (실패해도 main 흐름엔 영향 없음)."""
    prev_session = get_previous_market_day(today_et - timedelta(days=1))
    msg = (
        "<b>🏖 NYSE 휴장일 안내</b>\n"
        f"<i>{now_kst.strftime('%Y-%m-%d %H:%M KST')}</i>\n\n"
        f"오늘({today_et})은 미국 증시 휴장일입니다.\n"
        f"마지막 개장일: {prev_session} — 다음 개장일 리포트를 기다려 주세요."
    )
    try:
        send_message(msg)
    except Exception as e:
        logger.warning(f"휴장 안내 전송 실패(무시 가능): {e}")


def _notify_failure(now_kst: datetime, exc: BaseException) -> None:
    """실패 요약을 Telegram으로 전송. 이것 자체가 실패해도 main 예외만 raise."""
    tb = traceback.format_exc()
    err_msg = (
        "<b>❌ S&amp;P 500 리포트 실패</b>\n"
        f"<i>{now_kst.strftime('%Y-%m-%d %H:%M KST')}</i>\n\n"
        f"<code>{html.escape(f'{type(exc).__name__}: {exc}')}</code>\n\n"
        f"<pre>{html.escape(tb[-1500:])}</pre>"
    )
    try:
        send_message(err_msg)
        logger.info("에러 알림 Telegram 전송 완료")
    except Exception as notify_err:
        logger.error(f"에러 알림 전송도 실패: {notify_err}")


def run_daily_report(*, force: bool = False) -> None:
    """Daily report 파이프라인 1회 실행.

    Args:
        force: True면 휴장일 체크를 스킵하고 무조건 실행 (디버깅·수동 재처리용).
    """
    _setup_logging()

    now_kst = datetime.now(ZoneInfo(TIMEZONE))
    started_at = time.monotonic()
    logger.info(
        f"=== Daily report 시작 ({now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}) ==="
    )

    # 0. 휴장일 가드 — 07:00 KST 시점의 ET 날짜가 개장일이 아니면 리포트 스킵
    today_et = today_in_et()
    is_open = is_nyse_open_on(today_et)

    # 0.5. 유저 커맨드 처리 (getUpdates) — 휴장일에도 가능, 다음 개장일 리포트에 반영됨
    watchlist_tickers = _process_user_commands()

    if not force and not is_open:
        logger.info(f"NYSE 휴장({today_et}) — 리포트 스킵")
        _notify_holiday(today_et, now_kst)
        return

    try:
        # 1. S&P 500 리스트
        t0 = time.monotonic()
        sp500 = get_sp500_tickers()
        name_map = {t["ticker"]: t["name"] for t in sp500}
        sp500_set = {t["ticker"] for t in sp500}
        # watchlist에서 S&P 500 밖의 종목만 추가 fetch 대상
        extra_watch = [t for t in watchlist_tickers if t not in sp500_set]
        tickers = [t["ticker"] for t in sp500] + extra_watch
        logger.info(
            f"[1/6] S&P 500 {len(sp500)}개 + watchlist 추가 {len(extra_watch)}개 "
            f"= {len(tickers)}개 종목, {time.monotonic() - t0:.1f}s"
        )

        # 2. 시장 데이터
        # use_cache=True: 10분 TTL. 일 1회 07:00 운영에선 항상 expire되어 영향 없고,
        # 수동 재실행 시 yfinance rate limit 회피.
        t0 = time.monotonic()
        df = fetch_market_data(tickers, name_map=name_map, use_cache=False)
        logger.info(
            f"[2/6] market data: {len(df)}/{len(tickers)}, "
            f"{time.monotonic() - t0:.1f}s"
        )
        # 건강 체크는 S&P 500 대상만 (extra_watch는 소수라 노이즈)
        _check_data_health(df[df["ticker"].isin(sp500_set)], total_tickers=len(sp500))

        # 3. 순위 3종 — 순위는 S&P 500만 대상
        t0 = time.monotonic()
        sp500_df = df[df["ticker"].isin(sp500_set)]
        mc_top = top_by_market_cap(sp500_df)
        gainers, losers = top_gainers_losers(sp500_df)
        turnover_top = top_by_turnover_ratio(sp500_df)

        # 관심종목 RankedStock — df에서 해당 티커만 추출
        watchlist_stocks = _build_watchlist_stocks(df, watchlist_tickers)
        logger.info(
            f"[3/6] 순위 3종 + watchlist {len(watchlist_stocks)}종목, "
            f"{time.monotonic() - t0:.1f}s"
        )

        # 4. 뉴스 — 순위에 등장한 unique 티커 ∪ watchlist
        t0 = time.monotonic()
        unique_tickers: set[str] = set()
        for lst in (mc_top, gainers, losers, turnover_top, watchlist_stocks):
            for s in lst:
                unique_tickers.add(s.ticker)
        news_map = fetch_news_batch(sorted(unique_tickers))
        total_news = sum(len(v) for v in news_map.values())
        logger.info(
            f"[4/6] 뉴스: {len(unique_tickers)}개 티커 → {total_news}건, "
            f"{time.monotonic() - t0:.1f}s"
        )

        # 5. 메시지 포맷
        t0 = time.monotonic()
        messages = format_full_report(
            mc_top, gainers, losers, turnover_top, news_map,
            now_kst=now_kst, watchlist=watchlist_stocks,
        )
        logger.info(
            f"[5/6] 메시지 {len(messages)}건 포맷 "
            f"({sum(len(m) for m in messages)}자), {time.monotonic() - t0:.1f}s"
        )

        # 6. Telegram 전송
        t0 = time.monotonic()
        send_messages(messages)
        logger.info(f"[6/6] Telegram 전송 완료, {time.monotonic() - t0:.1f}s")

        elapsed = time.monotonic() - started_at
        logger.info(f"=== Daily report 성공, 총 {elapsed:.1f}s ===")

    except Exception as e:
        elapsed = time.monotonic() - started_at
        logger.error(f"=== Daily report 실패 (after {elapsed:.1f}s): {e} ===")
        _notify_failure(now_kst, e)
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="S&P 500 Daily Telegram Report")
    parser.add_argument(
        "--force",
        action="store_true",
        help="휴장일 체크를 무시하고 강제 실행 (디버깅용)",
    )
    args = parser.parse_args()
    run_daily_report(force=args.force)
