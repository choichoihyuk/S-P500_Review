"""Telegram Bot API `sendMessage` 경량 래퍼.

설계 주의점:
  - python-telegram-bot 라이브러리 대신 순수 requests — 동기 1회성 전송에 충분.
  - parse_mode=HTML, disable_web_page_preview=True (뉴스 링크 중복 프리뷰 방지).
  - 재시도 정책:
      * 200: 성공
      * 429 (rate limit): Telegram이 주는 `parameters.retry_after`만큼 대기 후 재시도
      * 5xx: 지수 백오프 3회
      * 4xx (429 제외): 즉시 raise — 재시도해도 성공 불가 (잘못된 HTML, invalid chat_id 등)
      * 네트워크 예외: 지수 백오프 3회
  - 메시지 간 0.5s sleep — 연속 전송 시 Telegram 글로벌 rate limit(~30msg/s) 방어.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import (  # noqa: E402
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    validate,
)

_API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_ATTEMPTS = 3
_INTER_MSG_DELAY_SEC = 0.5
_REQUEST_TIMEOUT_SEC = 30


def _send_once(
    text: str,
    token: str,
    chat_id: str,
) -> tuple[bool, str | None, int | None]:
    """1회 전송 시도. 반환: (성공여부, 에러메시지, retry_after초).

    retry_after가 있으면 호출자가 해당 시간만큼 대기 후 재시도.
    """
    url = _API_URL_TEMPLATE.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SEC)
    except requests.RequestException as e:
        return False, f"network: {e}", None

    if resp.status_code == 200:
        return True, None, None

    # Rate limit: Telegram이 권장 대기 시간을 돌려줌
    if resp.status_code == 429:
        retry_after = 1
        try:
            retry_after = int(
                resp.json().get("parameters", {}).get("retry_after", 1)
            )
        except (ValueError, requests.exceptions.JSONDecodeError):
            pass
        return False, f"rate_limit(retry_after={retry_after}s)", retry_after

    body_snippet = resp.text[:300].replace("\n", " ")
    return False, f"HTTP {resp.status_code}: {body_snippet}", None


def send_message(
    text: str,
    token: str | None = None,
    chat_id: str | None = None,
) -> None:
    """메시지 1건을 전송. 재시도 정책 포함. 실패 시 RuntimeError.

    token/chat_id 생략 시 config/settings.py에서 로드 (.env 경유).
    """
    token = token or TELEGRAM_BOT_TOKEN
    chat_id = chat_id or TELEGRAM_CHANNEL_ID

    last_err: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        ok, err, retry_after = _send_once(text, token, chat_id)
        if ok:
            return
        last_err = err

        if retry_after is not None:
            # 429: Telegram이 준 retry_after 사용
            logger.warning(f"Telegram {err} — 대기 후 재시도 {attempt}/{_MAX_ATTEMPTS}")
            time.sleep(retry_after + 1)
            continue

        # 비재시도성 HTTP 4xx는 여기서 바로 실패 처리 (5xx / network는 백오프)
        if err and err.startswith("HTTP 4"):
            break

        if attempt < _MAX_ATTEMPTS:
            delay = 2.0 ** (attempt - 1)
            logger.warning(
                f"Telegram 전송 실패 ({err}) — {delay}s 후 재시도 {attempt}/{_MAX_ATTEMPTS}"
            )
            time.sleep(delay)

    raise RuntimeError(f"Telegram 전송 최종 실패: {last_err}")


def send_messages(messages: list[str]) -> None:
    """여러 메시지를 순차 전송. 메시지 간 0.5s 간격."""
    validate()  # 토큰·채널 ID 누락 시 여기서 즉시 raise
    if not messages:
        logger.info("전송할 메시지가 없음")
        return

    for i, msg in enumerate(messages):
        send_message(msg)
        if i < len(messages) - 1:
            time.sleep(_INTER_MSG_DELAY_SEC)
    logger.info(f"Telegram 전송 완료: {len(messages)}개 메시지")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # 인자로 넘긴 텍스트를 1건 전송. 없으면 기본 테스트 메시지.
    text = " ".join(sys.argv[1:]) or (
        "<b>✅ sender standalone 테스트</b>\n"
        "<i>Telegram Bot API 연결 확인용 메시지입니다.</i>"
    )
    logger.info(f"전송 대상 길이: {len(text)}자")
    send_messages([text])
