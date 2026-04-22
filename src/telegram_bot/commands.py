"""Telegram 인커밍 메시지 처리 — getUpdates 기반 커맨드 파싱.

지원 커맨드 (봇 DM에서 입력):
  - `BE`           : BE를 관심종목에 추가
  - `NVDA MSFT`    : 공백/개행 구분으로 여러 개 한 번에
  - `-BE`          : BE를 관심종목에서 제거
  - `/list`        : 현재 관심종목 조회
  - `/clear`       : 전부 제거

보안: `authorized_chat_id`와 일치하는 chat에서 온 메시지만 처리. 봇이 다른
사용자에게도 열려 있으면 `/start`가 다수에서 와도 안전하게 무시.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import TELEGRAM_BOT_TOKEN  # noqa: E402

_GET_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"

# 티커 정규식: 1~6자 영문/숫자, 내부에 . 또는 - 허용 (BRK.B, BF-B 등)
_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,5}$")


@dataclass
class CommandOutcome:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    cleared: bool = False
    list_requested: bool = False
    ignored: list[str] = field(default_factory=list)   # 인식 못 한 텍스트

    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.cleared)

    def has_feedback(self) -> bool:
        """사용자에게 돌려줄 피드백이 있는지."""
        return self.has_changes() or self.list_requested or bool(self.ignored)


def _normalize(raw: str) -> str:
    """사용자 입력 → yfinance 포맷 (BRK.B → BRK-B, 대문자)."""
    return raw.strip().upper().replace(".", "-")


def fetch_updates(last_update_id: int, timeout_sec: int = 15) -> list[dict]:
    """getUpdates — last+1 부터 새 메시지 반환. 실패 시 빈 리스트."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN 없음 — getUpdates 스킵")
        return []
    url = _GET_UPDATES_URL.format(token=TELEGRAM_BOT_TOKEN)
    params = {"offset": last_update_id + 1, "timeout": 0}
    try:
        resp = requests.get(url, params=params, timeout=timeout_sec)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"getUpdates 실패: {e}")
        return []

    if not data.get("ok"):
        logger.warning(f"getUpdates 응답 not ok: {data}")
        return []
    return data.get("result", [])


def process_updates(
    updates: list[dict],
    current_tickers: list[str],
    authorized_chat_id: str,
) -> tuple[list[str], int, CommandOutcome]:
    """Telegram update 리스트를 처리해 tickers/offset/결과 요약 반환.

    Args:
        updates: getUpdates.result 배열.
        current_tickers: 기존 관심종목.
        authorized_chat_id: 이 chat의 메시지만 처리 (타인 봇 악용 방지).

    Returns:
        (new_tickers, max_update_id, outcome)
    """
    tickers: set[str] = set(current_tickers)
    outcome = CommandOutcome()
    max_uid = 0
    auth = str(authorized_chat_id)

    for upd in updates:
        uid = int(upd.get("update_id", 0))
        if uid > max_uid:
            max_uid = uid

        msg = upd.get("message") or upd.get("channel_post") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        chat_username = chat.get("username", "") or ""
        text = (msg.get("text") or "").strip()

        # 인증: 숫자 id 일치 또는 @username 일치 (어느 쪽이든)
        is_authorized = (
            chat_id == auth
            or (auth.startswith("@") and f"@{chat_username}" == auth)
        )
        if not is_authorized:
            logger.debug(f"미인증 chat({chat_id}/@{chat_username}) 메시지 무시")
            continue

        if not text:
            continue

        for token in text.replace(",", " ").split():
            token = token.strip()
            if not token:
                continue
            low = token.lower()

            if low in ("/list", "/watchlist", "/status"):
                outcome.list_requested = True
                continue
            if low in ("/clear", "/reset"):
                if tickers:
                    outcome.removed.extend(sorted(tickers))
                    tickers.clear()
                    outcome.cleared = True
                continue
            if low in ("/start", "/help"):
                outcome.list_requested = True
                continue

            remove = token.startswith("-")
            symbol_raw = token.lstrip("-")
            symbol = _normalize(symbol_raw)

            if not _TICKER_RE.match(symbol):
                outcome.ignored.append(token)
                continue

            if remove:
                if symbol in tickers:
                    tickers.discard(symbol)
                    outcome.removed.append(symbol)
                else:
                    outcome.ignored.append(f"-{symbol}(없음)")
            else:
                if symbol in tickers:
                    outcome.ignored.append(f"{symbol}(이미 있음)")
                else:
                    tickers.add(symbol)
                    outcome.added.append(symbol)

    return sorted(tickers), max_uid, outcome


def format_ack_message(outcome: CommandOutcome, final_tickers: list[str]) -> str:
    """사용자에게 보낼 커맨드 결과 요약 HTML 메시지."""
    lines: list[str] = []
    if outcome.added:
        lines.append(f"✅ 추가: <code>{' '.join(outcome.added)}</code>")
    if outcome.removed and not outcome.cleared:
        lines.append(f"🗑 제거: <code>{' '.join(outcome.removed)}</code>")
    if outcome.cleared:
        lines.append("🧹 관심종목 전체 초기화")
    if outcome.ignored:
        short = outcome.ignored[:5]
        more = f" +{len(outcome.ignored) - 5}개" if len(outcome.ignored) > 5 else ""
        lines.append(f"❓ 무시: <code>{' '.join(short)}</code>{more}")
    if outcome.list_requested or outcome.has_changes():
        if final_tickers:
            lines.append(
                f"📌 현재 관심종목({len(final_tickers)}): <code>{' '.join(final_tickers)}</code>"
            )
        else:
            lines.append("📌 관심종목 없음")
    return "\n".join(lines) if lines else "(변경 없음)"


if __name__ == "__main__":
    # 현재 봇에 쌓인 메시지 확인용 (offset 0부터)
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    updates = fetch_updates(args.offset - 1)  # fetch_updates는 +1 하므로 -1 보정
    print(f"받은 update: {len(updates)}개")
    for u in updates:
        uid = u.get("update_id")
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        text = msg.get("text", "")
        print(f"  uid={uid} chat={chat.get('id')} text={text!r}")
