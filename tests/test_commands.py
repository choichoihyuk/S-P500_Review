"""commands.py 파싱·인증 단위 테스트. getUpdates 자체는 E2E 영역이라 제외."""
from __future__ import annotations

from src.telegram_bot.commands import (
    CommandOutcome,
    format_ack_message,
    process_updates,
)


def _mk_update(uid: int, chat_id: int, text: str) -> dict:
    return {
        "update_id": uid,
        "message": {
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


class TestProcessUpdates:
    def test_add_single_ticker(self) -> None:
        upds = [_mk_update(1, 42, "BE")]
        new, uid, out = process_updates(upds, [], authorized_chat_id="42")
        assert new == ["BE"]
        assert uid == 1
        assert out.added == ["BE"]

    def test_add_multiple_space_separated(self) -> None:
        upds = [_mk_update(1, 42, "NVDA MSFT AAPL")]
        new, _, out = process_updates(upds, [], authorized_chat_id="42")
        assert set(new) == {"NVDA", "MSFT", "AAPL"}
        assert set(out.added) == {"NVDA", "MSFT", "AAPL"}

    def test_normalize_dot_to_dash(self) -> None:
        upds = [_mk_update(1, 42, "BRK.B")]
        new, _, _ = process_updates(upds, [], authorized_chat_id="42")
        assert new == ["BRK-B"]

    def test_normalize_lowercase_to_upper(self) -> None:
        upds = [_mk_update(1, 42, "be nvda")]
        new, _, _ = process_updates(upds, [], authorized_chat_id="42")
        assert set(new) == {"BE", "NVDA"}

    def test_remove_ticker(self) -> None:
        upds = [_mk_update(1, 42, "-BE")]
        new, _, out = process_updates(upds, ["BE", "NVDA"], authorized_chat_id="42")
        assert new == ["NVDA"]
        assert out.removed == ["BE"]

    def test_remove_nonexistent_ignored(self) -> None:
        upds = [_mk_update(1, 42, "-XYZ")]
        new, _, out = process_updates(upds, ["BE"], authorized_chat_id="42")
        assert new == ["BE"]
        assert any("없음" in x for x in out.ignored)

    def test_duplicate_add_ignored(self) -> None:
        upds = [_mk_update(1, 42, "BE")]
        new, _, out = process_updates(upds, ["BE"], authorized_chat_id="42")
        assert new == ["BE"]
        assert out.added == []
        assert any("이미 있음" in x for x in out.ignored)

    def test_clear_command(self) -> None:
        upds = [_mk_update(1, 42, "/clear")]
        new, _, out = process_updates(upds, ["BE", "NVDA"], authorized_chat_id="42")
        assert new == []
        assert out.cleared is True
        assert set(out.removed) == {"BE", "NVDA"}

    def test_list_command(self) -> None:
        upds = [_mk_update(1, 42, "/list")]
        new, _, out = process_updates(upds, ["BE"], authorized_chat_id="42")
        assert new == ["BE"]
        assert out.list_requested is True
        assert out.added == []

    def test_unauthorized_chat_ignored(self) -> None:
        upds = [_mk_update(1, 999, "BE")]  # chat_id=999 != authorized=42
        new, uid, out = process_updates(upds, [], authorized_chat_id="42")
        assert new == []
        # update_id는 여전히 전진 (다시 수신 안 하려면)
        assert uid == 1
        assert out.added == []

    def test_invalid_text_ignored(self) -> None:
        # 공백/숫자 조합이지만 정규식에 맞지 않는 무작위 문자열
        upds = [_mk_update(1, 42, "hello! @#$%")]
        new, _, out = process_updates(upds, [], authorized_chat_id="42")
        assert new == []
        # ignored에 일부 토큰 잡힘 (! @#$% 등은 정규식 미매칭)
        assert len(out.ignored) > 0

    def test_offset_advances_even_on_ignored(self) -> None:
        upds = [_mk_update(100, 42, "BE"), _mk_update(105, 42, "-BE")]
        _, uid, _ = process_updates(upds, [], authorized_chat_id="42")
        assert uid == 105

    def test_mixed_add_remove_in_one_message(self) -> None:
        upds = [_mk_update(1, 42, "NVDA -BE MSFT")]
        new, _, out = process_updates(upds, ["BE"], authorized_chat_id="42")
        assert set(new) == {"NVDA", "MSFT"}
        assert set(out.added) == {"NVDA", "MSFT"}
        assert out.removed == ["BE"]

    def test_multiline_message(self) -> None:
        upds = [_mk_update(1, 42, "BE\nNVDA\n/list")]
        new, _, out = process_updates(upds, [], authorized_chat_id="42")
        assert set(new) == {"BE", "NVDA"}
        assert out.list_requested is True

    def test_comma_separated(self) -> None:
        upds = [_mk_update(1, 42, "BE, NVDA, MSFT")]
        new, _, _ = process_updates(upds, [], authorized_chat_id="42")
        assert set(new) == {"BE", "NVDA", "MSFT"}


class TestFormatAckMessage:
    def test_added_rendered(self) -> None:
        out = CommandOutcome(added=["BE", "NVDA"])
        msg = format_ack_message(out, ["BE", "NVDA"])
        assert "BE NVDA" in msg
        assert "추가" in msg

    def test_removed_rendered(self) -> None:
        out = CommandOutcome(removed=["BE"])
        msg = format_ack_message(out, [])
        assert "제거" in msg
        assert "BE" in msg

    def test_cleared_rendered(self) -> None:
        out = CommandOutcome(cleared=True, removed=["BE", "NVDA"])
        msg = format_ack_message(out, [])
        assert "초기화" in msg

    def test_empty_outcome_fallback(self) -> None:
        out = CommandOutcome()
        assert format_ack_message(out, []) == "(변경 없음)"
