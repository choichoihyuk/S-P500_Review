"""RankedStock + NewsItem → 텔레그램 HTML 메시지 포맷.

설계 주의점:
  - Telegram HTML parse_mode: `<b> <i> <a href> <code> <pre>` 등만 허용.
    특수문자 `<`, `>`, `&`는 html.escape로 처리.
  - 메시지 1건 최대 4096자 (text entity 기준) → 섹션 단위 분할.
  - 날짜·시각은 Asia/Seoul로 표시 (집계 자체는 미국 장 마감 기준이지만 수신자가 한국).
"""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import TELEGRAM_MAX_MESSAGE_LEN, TIMEZONE  # noqa: E402
from src.analysis.rankings import RankedStock  # noqa: E402
from src.news.news_fetcher import NewsItem  # noqa: E402

# 길이 여유분 — 실제 제한 4096보다 약간 적게 잡아 분할 시 안전
_SAFE_LEN = TELEGRAM_MAX_MESSAGE_LEN - 200


def _format_mcap(mc: float) -> str:
    """시가총액 자동 단위 (T / B)."""
    if mc >= 1e12:
        return f"${mc / 1e12:.2f}T"
    return f"${mc / 1e9:,.1f}B"


def _format_change(pct: float) -> str:
    """등락률 컬러 이모지 + 부호."""
    if pct > 0:
        emoji = "🟢"
        sign = "+"
    elif pct < 0:
        emoji = "🔴"
        sign = ""
    else:
        emoji = "⚪"
        sign = ""
    return f"{emoji} {sign}{pct:.2f}%"


def _format_turnover(ratio: float) -> str:
    """거래대금/시총 비율을 % 포맷 (0.0049 → 0.49%)."""
    return f"회전율 {ratio * 100:.2f}%"


def _format_header(now_kst: datetime | None = None) -> str:
    if now_kst is None:
        now_kst = datetime.now(ZoneInfo(TIMEZONE))
    date_str = now_kst.strftime("%Y-%m-%d %H:%M KST")
    return f"<b>📊 S&amp;P 500 데일리 리포트</b>\n<i>{date_str}</i>"


def _format_stock(idx: int, stock: RankedStock, news: list[NewsItem]) -> str:
    """종목 1개를 여러 줄 HTML 블록으로."""
    lines: list[str] = []
    ticker_esc = html.escape(stock.ticker)
    name_esc = html.escape(stock.name)
    lines.append(f"<b>{idx}. {ticker_esc}</b> {name_esc}")

    metrics = [
        _format_change(stock.change_pct),
        f"시총 {_format_mcap(stock.market_cap)}",
        _format_turnover(stock.turnover_ratio),
    ]
    lines.append(" | ".join(metrics))

    if not news:
        lines.append("• 24h 이내 뉴스 없음")
    else:
        for n in news:
            # href 값 내부 따옴표·< > 방어
            url_esc = html.escape(n.url, quote=True)
            title_esc = html.escape(n.title)
            pub_esc = f" — {html.escape(n.publisher)}" if n.publisher else ""
            lines.append(f'• <a href="{url_esc}">{title_esc}</a>{pub_esc}')

    return "\n".join(lines)


def format_section(
    title: str,
    items: list[RankedStock],
    news_map: dict[str, list[NewsItem]],
) -> str:
    """제목 헤더 + 종목 블록들을 하나의 섹션 문자열로."""
    title_esc = html.escape(title)
    parts = [f"<b>━━━ {title_esc} ━━━</b>", ""]
    for i, stock in enumerate(items, start=1):
        parts.append(_format_stock(i, stock, news_map.get(stock.ticker, [])))
        parts.append("")
    return "\n".join(parts).rstrip()


def _split_long_section(section: str, max_len: int) -> list[str]:
    """한 섹션이 max_len 초과 시 빈 줄 기준으로 분할 (드문 안전장치)."""
    if len(section) <= max_len:
        return [section]

    blocks = section.split("\n\n")
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for block in blocks:
        block_len = len(block) + 2  # '\n\n' overhead
        if buf and buf_len + block_len > max_len:
            chunks.append("\n\n".join(buf))
            buf = [block]
            buf_len = block_len
        else:
            buf.append(block)
            buf_len += block_len
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def format_full_report(
    market_cap_top: list[RankedStock],
    gainers: list[RankedStock],
    losers: list[RankedStock],
    turnover_top: list[RankedStock],
    news_map: dict[str, list[NewsItem]],
    now_kst: datetime | None = None,
) -> list[str]:
    """전체 리포트를 텔레그램 메시지 리스트로 반환.

    헤더 + 4섹션을 렌더링하고, 섹션 단위로 메시지를 분할.
    헤더는 첫 섹션과 합칠 수 있으면 합침 (메시지 개수 절약).
    """
    header = _format_header(now_kst)

    sections_raw = [
        ("시가총액 Top 10", market_cap_top),
        ("일일 상승률 Top 10", gainers),
        ("일일 하락률 Top 10", losers),
        ("시총 대비 거래대금 비율 Top 10", turnover_top),
    ]
    sections = [format_section(t, items, news_map) for t, items in sections_raw]

    messages: list[str] = []
    combined_first = f"{header}\n\n{sections[0]}"
    if len(combined_first) <= _SAFE_LEN:
        messages.append(combined_first)
        messages.extend(sections[1:])
    else:
        messages.append(header)
        messages.extend(sections)

    # 섹션이 단독으로 초과할 경우 추가 분할
    final: list[str] = []
    for msg in messages:
        final.extend(_split_long_section(msg, TELEGRAM_MAX_MESSAGE_LEN))
    return final


def _mock_data() -> tuple[
    list[RankedStock], list[RankedStock], list[RankedStock], list[RankedStock],
    dict[str, list[NewsItem]],
]:
    """standalone 실행용 mock 데이터. 이스케이프·포맷 검증 목적."""
    from datetime import timedelta, timezone

    now = datetime.now(timezone.utc)

    def rs(t, n, pct, mc, dv, rr):
        tr = dv / mc if mc else 0.0
        return RankedStock(t, n, pct, mc, dv, tr, rr)

    mc_top = [
        rs("NVDA", "Nvidia", 0.53, 4.91e12, 24e9, "시총 1위"),
        rs("AAPL", "Apple Inc.", 0.91, 4.01e12, 10e9, "시총 2위"),
        rs("MSFT", "Microsoft", -1.02, 3.11e12, 11.5e9, "시총 3위"),
    ]
    gainers = [
        rs("TTD", "Trade Desk (The)", 6.46, 11.4e9, 501.9e6, "상승률 1위"),
        rs("SWK", "Stanley Black & Decker", 5.70, 11.7e9, 264.7e6, "상승률 2위"),
    ]
    losers = [
        rs("NRG", "NRG Energy", -7.54, 33.4e9, 601.8e6, "하락률 1위"),
        rs("DGX", "Quest Diagnostics", -6.33, 21.7e9, 385.2e6, "하락률 2위"),
    ]
    turnover = [
        rs("SNDK", "Sandisk", -0.08, 134.8e9, 10276.5e6, "거래대금비율 1위"),
        rs("NCLH", "Norwegian Cruise Line <test>&Co", -4.21, 9.2e9, 584.1e6, "거래대금비율 2위"),
    ]

    news_map = {
        "NVDA": [
            NewsItem("NVDA", "NVIDIA reports record Q1 revenue, beats estimates",
                     "https://example.com/nvda-q1?ref=test&foo=1",
                     now - timedelta(hours=2), "Reuters"),
            NewsItem("NVDA", "AI chip demand pushes Nvidia past $5T valuation",
                     "https://example.com/nvda-5t", now - timedelta(hours=6), "Bloomberg"),
        ],
        "AAPL": [
            NewsItem("AAPL", "Tim Cook names successor <John Ternus> as he steps down",
                     "https://example.com/aapl-ceo",
                     now - timedelta(minutes=15), "Euronews"),
        ],
        # MSFT, TTD, ... 는 뉴스 없음 — "24h 이내 뉴스 없음" 케이스 검증
    }
    return mc_top, gainers, losers, turnover, news_map


if __name__ == "__main__":
    # Windows cp949 콘솔에서 이모지 print 시 UnicodeEncodeError 방지.
    # 텔레그램 전송용 이모지는 그대로 두되, 표준 출력만 utf-8로 교체.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    mc, g, l, t, nm = _mock_data()
    messages = format_full_report(mc, g, l, t, nm)

    total_len = sum(len(m) for m in messages)
    print(f"\n총 {len(messages)}개 메시지, 합계 {total_len}자")
    for i, msg in enumerate(messages, 1):
        print(f"\n{'=' * 20} MSG {i}/{len(messages)} (len={len(msg)}) {'=' * 20}")
        print(msg)
        print()
