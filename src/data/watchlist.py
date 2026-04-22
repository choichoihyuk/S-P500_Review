"""사용자 관심종목 + Telegram getUpdates offset 영구 상태.

`data/watchlist.json`은 repo에 커밋되는 상태 파일. GH Actions 각 run에서:
  1. 파일 로드
  2. getUpdates로 새 메시지 수집 → tickers 갱신 + last_update_id 전진
  3. 파일 저장
  4. 워크플로 마지막 스텝이 변경분을 자동 커밋·푸시

비고:
  - `data/cache/` 는 .gitignore 제외지만 `data/watchlist.json` 은 커밋 대상.
  - `last_update_id`는 Telegram API의 update_id 누적 offset (한 번 읽은 메시지는 재수신 안 되도록).
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import PROJECT_ROOT  # noqa: E402

WATCHLIST_PATH: Path = PROJECT_ROOT / "data" / "watchlist.json"


@dataclass
class WatchlistState:
    tickers: list[str] = field(default_factory=list)       # normalized uppercase
    last_update_id: int = 0                                # Telegram getUpdates offset


def load() -> WatchlistState:
    """watchlist.json 로드. 파일 없으면 빈 상태 반환."""
    if not WATCHLIST_PATH.exists():
        return WatchlistState()
    try:
        raw = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
        return WatchlistState(
            tickers=list(raw.get("tickers", [])),
            last_update_id=int(raw.get("last_update_id", 0)),
        )
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"watchlist.json 파싱 실패 — 빈 상태로 시작: {e}")
        return WatchlistState()


def save(state: WatchlistState) -> None:
    """state를 파일에 저장. 디렉토리 없으면 생성."""
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    WATCHLIST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.debug(f"watchlist 저장: {len(state.tickers)}종목, offset={state.last_update_id}")


if __name__ == "__main__":
    s = load()
    print(f"현재 watchlist: {s.tickers}")
    print(f"last_update_id: {s.last_update_id}")
    print(f"파일 위치: {WATCHLIST_PATH}")
