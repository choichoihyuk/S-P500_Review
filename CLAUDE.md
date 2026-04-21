# S&P 500 Daily Telegram Bot

## 프로젝트 목표
매일 07:00 KST에 S&P 500 상위 종목(시총 Top10 / 등락률 Top10·Bottom10 / 시총 대비 거래대금 비율 Top10)의 시황과 24시간 내 뉴스를 텔레그램 채널로 자동 전송하는 Python 봇.

## 기술 스택
- **Python**: 3.11+
- **데이터**: `yfinance` (주가·시총·거래량·뉴스), `pandas` (가공·순위)
- **스크래핑**: `requests` + `beautifulsoup4` (위키피디아 S&P 500 리스트)
- **텔레그램**: 순수 `requests`로 Bot API 호출 (경량)
- **스케줄러**: `APScheduler` (또는 OS cron)
- **설정**: `python-dotenv`
- **로깅**: `loguru`
- **테스트**: `pytest`
- **(옵션) 휴장일**: `pandas_market_calendars`

## 아키텍처

```
  ┌─────────────────┐     ┌───────────────────┐
  │ sp500_list.py   │────▶│ market_data.py    │
  │ (종목 리스트)    │     │ (주가·시총·거래대금) │
  └─────────────────┘     └─────────┬─────────┘
                                    │ DataFrame
                                    ▼
                          ┌───────────────────┐
                          │ rankings.py       │
                          │ (3종 Top10)        │
                          └─────────┬─────────┘
                                    │ list[RankedStock]
                                    ▼
                          ┌───────────────────┐
                          │ news_fetcher.py   │
                          │ (24h 뉴스)         │
                          └─────────┬─────────┘
                                    ▼
                          ┌───────────────────┐
                          │ formatter.py      │
                          │ (HTML 메시지)       │
                          └─────────┬─────────┘
                                    ▼
                          ┌───────────────────┐
                          │ sender.py         │
                          │ (Telegram API)     │
                          └───────────────────┘

  오케스트레이션: src/main.py
  스케줄 트리거 : scheduler/daily_run.py (07:00 KST)
```

## 디렉토리 구조
```
sp500_telegram_bot/
├── CLAUDE.md                  # (이 파일) 영구 컨텍스트
├── PLAN.md                    # 단계별 체크리스트
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── config/
│   └── settings.py            # 환경변수·상수 로딩
├── src/
│   ├── data/
│   │   ├── sp500_list.py
│   │   └── market_data.py
│   ├── analysis/
│   │   └── rankings.py
│   ├── news/
│   │   └── news_fetcher.py
│   ├── telegram_bot/
│   │   ├── sender.py
│   │   └── formatter.py
│   └── main.py
├── scheduler/
│   └── daily_run.py
├── tests/
├── logs/
└── data/cache/                # 종목 리스트 캐시
```

## 코딩 규칙
1. **각 모듈은 단독 실행 가능**: 모든 `.py` 파일에 `if __name__ == "__main__":` 섹션 두고, 그 모듈만으로 기능 검증 가능해야 함. 디버깅 시 해당 파일만 컨텍스트에 올려도 OK.
2. **타입힌트 필수**: 함수 시그니처에 파라미터·반환 타입 명시. `list[dict]`, `pd.DataFrame`, `dict[str, list[NewsItem]]` 같은 정확한 타입.
3. **함수 docstring**: 한 줄 요약 + 필요 시 파라미터 설명. 과도하게 길게 쓰지 말 것.
4. **에러 처리**: `try/except` + `loguru.logger.error()` 로깅. 배치 작업에서 개별 실패가 전체를 망가뜨리지 않도록 개별 예외 잡고 스킵.
5. **시크릿은 `.env`**: 토큰·API 키 하드코딩 금지. 반드시 `config/settings.py` 경유.
6. **주석은 WHY만**: WHAT은 코드가 말한다. 왜 이 선택을 했는지, 어떤 제약이 있는지만 기록.
7. **Pandas DataFrame 일관성**: 모듈 간 전달은 명시적인 컬럼 스키마를 따른다 (market_data.py 상단에 SCHEMA 상수).

## 데이터 흐름 (핵심 규약)
- `sp500_list.get_sp500_tickers() -> list[dict]` (ticker, name, sector)
- `market_data.fetch_market_data(tickers) -> pd.DataFrame` (ticker, name, prev_close, last_close, change_pct, market_cap, dollar_volume, turnover_ratio)
- `rankings.*() -> list[RankedStock]` (dataclass)
- `news_fetcher.fetch_news_batch(tickers) -> dict[str, list[NewsItem]]`
- `formatter.format_full_report(...) -> list[str]` (4096자 제한 고려해 분할)
- `sender.send_messages(messages) -> None`

## 주의사항
- **yfinance rate limit**: 503개 종목 배치 조회 시 주의. 실패 시 지수 백오프 재시도.
- **yfinance 뉴스 스키마 변동 가능성**: 방어적 파싱 필수 (키 누락 허용).
- **텔레그램 메시지 4096자 제한**: 섹션 단위로 분할.
- **HTML 이스케이프**: 뉴스 제목에 `<`, `>`, `&` 포함 가능 → `html.escape()`.
- **타임존**: 모든 집계는 미국 동부 기준(장 마감 기준), 발송 시각만 KST로 표기.
