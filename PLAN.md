# PLAN.md — Phase별 체크리스트

> 각 Phase 완료 시 ☐ → ☑로 변경하고, 하단 "발견한 이슈/주의점"에 한 줄씩 추가.

---

## Phase 0 · 프로젝트 초기화 ☑
- **입력**: 없음
- **출력**: 디렉토리 구조, `CLAUDE.md`, `PLAN.md`, `requirements.txt`, `.env.example`, `.gitignore`, `config/settings.py`, 빈 `__init__.py`
- **의존성**: 없음
- **완료 기준**:
  - [x] 디렉토리 구조 생성 (config, src/{data,analysis,news,telegram_bot}, scheduler, tests, logs, data/cache)
  - [x] CLAUDE.md 작성 (목표, 스택, 아키텍처, 코딩 규칙, 데이터 흐름)
  - [x] PLAN.md 작성
  - [x] requirements.txt 작성
  - [x] .env.example 작성
  - [x] .gitignore 작성
  - [x] config/settings.py 골격 작성 (dotenv 로딩 + 상수)
  - [x] __init__.py 파일들 생성

---

## Phase 1 · S&P 500 리스트 + 시장 데이터 ☑
- **입력**: 위키피디아 S&P 500 페이지 / yfinance
- **출력**:
  - `src/data/sp500_list.py`: `get_sp500_tickers() -> list[dict]`
  - `src/data/market_data.py`: `fetch_market_data(tickers) -> pd.DataFrame`
- **의존성**: Phase 0 완료. requirements 설치.
- **완료 기준**:
  - [x] `python -m src.data.sp500_list` 실행 시 처음 5개 종목 정상 출력 (503개 확인: MMM, AOS, ABT, ABBV, ACN)
  - [x] `python -m src.data.market_data` 실행 시 시총 Top 10 정상 출력 (NVDA $4.9T, GOOGL, GOOG, AAPL, MSFT, AMZN, AVGO, META, TSLA, WMT)
  - [x] 실패 종목 스킵 로직 구현 (개별 try/except + 3회 지수 백오프)
  - [x] 캐시 fallback 구현 (24h TTL + stale 캐시 최후 수단)
  - [x] DataFrame 컬럼: ticker, name, prev_close, last_close, change_pct, market_cap, dollar_volume, turnover_ratio

---

## Phase 2 · 순위 분석 ☑
- **입력**: Phase 1의 DataFrame
- **출력**: `src/analysis/rankings.py`
  - `top_by_market_cap(df, n=10)`
  - `top_gainers_losers(df, n=10)`
  - `top_by_turnover_ratio(df, n=10)`
  - `@dataclass RankedStock`
- **의존성**: Phase 1
- **완료 기준**:
  - [x] `python -m src.analysis.rankings` 실행 시 4종 순위 모두 정상 출력 (시총·상승·하락·거래대금비율)
  - [x] `_clean()`에서 NaN + 시총/거래대금 0 제외
  - [x] `top_by_turnover_ratio`에서 MIN_MARKET_CAP=$1B 필터 적용
  - [x] rankings.py는 순수 함수 (네트워크 호출 없음, 입력은 DataFrame만)
  - [x] `_validate()` 스키마 검증

---

## Phase 3 · 뉴스 수집 ☑
- **입력**: 티커 리스트
- **출력**: `src/news/news_fetcher.py`
  - `fetch_news_for_ticker(ticker, hours=24)`
  - `fetch_news_batch(tickers, hours=24, max_per_ticker=3)`
  - `@dataclass NewsItem`
- **의존성**: Phase 0 (독립 개발 가능)
- **완료 기준**:
  - [x] `python -m src.news.news_fetcher AAPL MSFT` 실행 시 각 티커의 24h 뉴스 최대 3개 출력 (각 3건 확인)
  - [x] 스키마 2종 방어 파싱: old flat(`providerPublishTime`, `link`) + new nested(`content.canonicalUrl.url`, `content.pubDate`)
  - [x] 24시간 경계 필터링: 0.2h~3.9h 이내만 반환 확인
  - [x] ThreadPoolExecutor (max_workers=10) + 중복 티커 제거

---

## Phase 4 · 텔레그램 포매터 + 전송 ☑
- **입력**: Phase 2의 RankedStock 리스트 + Phase 3의 NewsItem 맵
- **출력**:
  - `src/telegram_bot/formatter.py`: `format_full_report(...) -> list[str]`
  - `src/telegram_bot/sender.py`: `send_messages(messages) -> None`
- **의존성**: Phase 2, Phase 3 (포맷 대상 데이터 필요)
- **완료 기준**:
  - [x] 실제 토큰으로 `python -m src.telegram_bot.sender "연결 테스트"` 실행 시 수신처(DM)에 수신 확인
  - [x] 4096자 초과 시 `_split_long_section`으로 자동 분할 (안전장치 _SAFE_LEN=3896)
  - [x] HTML 이스케이프: `<`/`>`/`&` + URL quote. 이스케이프 검증 완료 (mock에서 `<John Ternus>` → `&lt;John Ternus&gt;`, `&foo=1` → `&amp;foo=1`)
  - [x] 재시도 로직: 429(Telegram retry_after 준수), 5xx/network(지수 백오프 3회), 4xx 즉시 실패
  - [x] README에 봇 생성·채널 추가·연결 테스트·에러 진단 가이드

---

## Phase 5 · 파이프라인 통합 + 스케줄러 ☑
- **입력**: 전 단계 모든 모듈
- **출력**:
  - `src/main.py`: `run_daily_report()`
  - `scheduler/daily_run.py`: APScheduler cron
- **의존성**: Phase 1~4
- **완료 기준**:
  - [x] `python -m src.main` 수동 실행 E2E 성공: 503/503 market data, 38 unique 티커, 뉴스 90건, 9개 메시지 전송 (총 60.3s)
  - [x] APScheduler 트리거 등록 검증: `next_run_time=2026-04-22 07:00:00+09:00`, cron[hour='7', minute='0']
  - [x] 단계별 소요시간 로깅: `[1/6]`~`[6/6]` + 총 소요, `logs/YYYY-MM-DD.log`에 utf-8 저장
  - [x] 예외 발생 시 `_notify_failure()` → Telegram으로 `<pre>traceback</pre>` 전송 + 재전파
  - [x] README에 APScheduler/nohup/systemd/cron(KST/UTC) 배포 가이드

---

## Phase 6 · 운영 안정화 ☑
- **입력**: Phase 5 완성본
- **출력**: 에러 알림 강화, 휴장일 처리, 로그 로테이션, 단위 테스트, README 최종화
- **의존성**: Phase 5
- **완료 기준**:
  - [x] 네트워크/데이터 장애 시뮬 통과: market_data 0/503 → `_check_data_health` RuntimeError → HTML-escaped traceback을 `_notify_failure`로 Telegram 전송 + 재전파
  - [x] 주말/미국 공휴일 휴장 처리: `src/data/market_calendar.py` (NYSE mcal). 일요일(2026-04-19) 시뮬 결과 파이프라인 스킵 + `🏖 NYSE 휴장일 안내` 메시지만 전송
  - [x] 데이터 결측 2단계 감지: 전체 <50% 또는 메가캡 10종 중 ≥7 결측 → RuntimeError
  - [x] loguru rotation 10MB / retention 30d (Phase 5에서 선제 적용)
  - [x] tests/ 3종 통과: **43 passed in 1.83s** (test_rankings=14, test_formatter=14, test_news_fetcher=15)
  - [x] README 최종화: 개발 워크플로(pytest/모듈별 단독 실행/--force) + 운영 주의사항(휴장일·건강 검증)

---

# 발견한 이슈 / 주의점
- Phase 0: (기록 없음)
- Phase 1:
  - 위키피디아 기본 UA 차단됨 → `Mozilla/5.0` UA 헤더 필수.
  - `yf.download()`는 내부적으로 per-symbol 병렬이라 "진짜 배치"가 아님 → `Ticker.fast_info` + ThreadPoolExecutor로 통일 (OHLCV + 시총 한 번에, `.info`보다 10배+ 빠름).
  - `fast_info`는 yfinance 버전별로 dict-like 또는 attribute-access → `getattr(fi, key, None)`로 통일.
  - 503종목 / workers=15 → 약 40초 소요. 안정적으로 0개 스킵.
  - Windows 콘솔(cp949) 한글 깨짐은 데이터 이슈가 아님. 파일 내 한글은 정상 (utf-8).
  - `change_pct`는 %단위 (예: 1.23) — 포맷 시 별도 `%` 붙이지 말 것.
- Phase 2:
  - yfinance rate limit: 503개를 짧은 간격으로 반복 호출 시 `Too Many Requests` → ~180개 스킵.
    대응: `_MAX_WORKERS` 15→10, `_BASE_BACKOFF_SEC` 0.5→1.0s, `market_data.fetch_market_data(use_cache=True)` 추가 (10분 disk 캐시, 개발/디버깅용). 운영(일1회 07:00)에선 자연스럽게 expire되므로 영향 없음.
  - Windows `cp949` 콘솔 한계: 이모지·한글 깨짐은 출력 문제. 데이터는 utf-8 정상 저장. 이모지는 텔레그램 포매터에서만 사용하고 콘솔 print에는 쓰지 말 것.
  - rankings는 "순수 함수" 지향: 모든 함수가 DataFrame in / list[RankedStock] out. 테스트 시 mock DataFrame만 있으면 됨.
  - Losers 정렬: `sort_values('change_pct', ascending=True).head(n)` — losers[0]이 최대 하락.
- Phase 3:
  - yfinance `.news` 스키마 2종 공존 가능성 실제 확인. 현재(2026-04) 버전은 대부분 `content.*` nested 스키마 반환.
  - `pubDate`는 ISO 8601 (`2026-04-21T12:34:56Z`), `providerPublishTime`은 unix ts. `_parse_pub_date`가 둘 다 처리 + ms 단위(>1e12) 자동 보정.
  - yfinance 뉴스 endpoint는 crumb/cookie 획득이 필요해 rate limit 시 `YFRateLimitError` 발생 → 티커 단위 try/except로 해당 티커만 빈 리스트 퇴각.
  - 뉴스 중복 호출 방지: Phase 5에서 순위 3종에 등장한 unique 티커만 모아 `fetch_news_batch` 호출 (spec에 명시).
  - 모든 `published_at`은 UTC — KST 변환은 포매터에서 표시용으로만.
- Phase 4:
  - HTML 모드는 `<b> <i> <a> <code> <pre>` 등 한정 태그만 허용. Markdown 이스케이프 걱정 없어 훨씬 단순 → HTML 선택 정당화.
  - 길이 상한 `_SAFE_LEN = 4096 - 200`: 이모지(🟢🔴📊)는 BMP 밖 문자라 일부 Telegram 카운팅에서 2자로 셀 수 있어 여유 확보.
  - `disable_web_page_preview=True`: 뉴스 링크마다 프리뷰 카드 뜨면 메시지가 거대해짐 → 차단.
  - Windows `cp949` 콘솔 이모지 출력: main 블록에서 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`로 해결. 이모지는 텔레그램용이므로 제거 불가.
  - 비재시도성 에러 (4xx 중 429 제외): 재시도해도 성공 불가. 즉시 raise.
  - 실제 전송 검증은 .env 세팅 후 사용자가 직접 (자동화 불가).
- Phase 5:
  - E2E 타이밍 기준점: sp500_list 0.0s(캐시) / market_data 35.6s / rankings 0.0s / news 1.8s / format 0.0s / send 22.8s = 총 60s. 네트워크가 병목.
  - 9개 메시지로 분할됨 — 10 tickers × 4 sections × (종목블록 ~150자 + 뉴스 3건) ≈ 23K자 / 4K = 6+메시지 필요. 섹션 섹션이 살짝 큰 경우 `_split_long_section`이 추가 분할.
  - main.py에 `use_cache=True` 추가 — 10분 TTL이라 일 1회 운영엔 항상 expire, 수동 재실행 때만 효과.
  - loguru 파일 sink `rotation="10 MB", retention="30 days"` — Phase 6의 요구사항을 선제 적용 (큰 비용 없음).
  - `_setup_logging()`은 module-level 플래그로 멱등 — scheduler에서 매 fire마다 호출돼도 파일 sink 중복 추가 안 됨.
  - 에러 알림 HTML: `<pre>` 안에 traceback 넣을 때 `html.escape` 필수 (traceback에 `<`,`>` 자주 등장).
  - APScheduler `misfire_grace_time=3600, coalesce=True`: 프로세스가 07:00 직전에 죽고 07:30에 부활해도 놓친 실행을 1회만 회복.
- Phase 6:
  - 휴장 판정 기준 날짜: `today_in_et()` = KST 실행 시점의 미국 ET 날짜. KST 07:00 월요일 = ET 일요일 → 스킵. 주말/공휴일 자동 대응.
  - `_notify_holiday`는 best-effort: 메시지 전송 실패해도 main 흐름에 영향 없음 (캘린더 자체로는 핵심 데이터 아님).
  - 메가캡 하드코딩 리스트 `_MEGA_CAPS` 10종: 2026-04 기준 현실 시총 상위 10위. 반기/연 1회 리밸런싱 필요 — 장기 운영 시 `_check_data_health` 로직 재검토.
  - pytest 설정: `pytest.ini` + `pythonpath = .` → `from src.X.Y` import 가능. tests는 mock 기반 순수 함수 검증이라 실행 1.8초.
  - `test_news_fetcher`는 `monkeypatch.setattr(news_fetcher.yf, "Ticker", FakeTicker)` 방식으로 yfinance 의존성 격리.
  - `force=True` 인자: 디버깅·수동 재처리용 휴장 우회. 운영 스케줄러에선 기본값 False 유지.
  - `_setup_logging()` 멱등성 덕에 테스트 실행 시 logger handler 중복 추가 안 됨.

## 배포 (GitHub Actions, 2026-04-21 추가) ☑
- **경로**: `.github/workflows/daily-report.yml`
- **트리거**: cron `0 22 * * *` UTC = 07:00 KST (KST는 DST 없음 — 연중 고정) + `workflow_dispatch` (수동 실행 버튼)
- **실행 환경**: ubuntu-latest + Python 3.11 + pip cache
- **Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` (Repo Settings → Secrets → Actions)
- **핵심 디자인**:
  - `config/settings.py`의 `load_dotenv(.env)`는 `.env` 부재 시 조용히 no-op → `os.getenv`가 GH env vars에서 읽음. **코드 수정 없이** .env 경로와 env var 경로 둘 다 지원.
  - 시뮬 검증: `.env`를 일시 rename → env var 주입 → `python -m src.telegram_bot.sender` 성공 → `.env` 복원.
  - `concurrency: daily-report, cancel-in-progress: false`: 이전 run이 지연 시 중복 실행 방지.
  - `timeout-minutes: 15`: 60s 실행 대비 여유. 완전 타임아웃 시 실패 alert.
  - 실패 시 `logs/` 디렉토리를 artifact로 upload (7일 보존) — yfinance 장애 진단용.
- **운영 주의**:
  - GH Actions 60일 비활성 규칙 — 2개월 내 commit 또는 수동 run 필요.
  - GH 스케줄러는 best-effort (고부하 시 몇 분 지연 가능) — 일일 리포트엔 허용 범위.
  - yfinance는 GH Actions IP를 rate limit할 가능성 — Phase 1/2에서 구축한 재시도·지수 백오프로 대부분 해결. 심하면 scheduler 스펙을 분 단위로 분산(예: `15 22 * * *`)하거나 데이터 소스 교체.
- **Git 안전성 (pre-commit dry-run)**: `git add -n .` 결과 29파일 staged. `.env`·`logs/`·`data/cache/`·`__pycache__/` 모두 정상 제외. `.env.example`은 placeholder로 올라감 — OK.

## 관심종목 기능 (2026-04-22 추가) ☑
- **목표**: 사용자가 봇 DM에 티커 입력 → 다음 리포트부터 **📌 내 관심종목** 섹션에 등락률 + 뉴스 포함.
- **새 모듈**:
  - `src/data/watchlist.py`: `data/watchlist.json`에 `{tickers, last_update_id}` persist. repo에 커밋.
  - `src/telegram_bot/commands.py`: `fetch_updates` (getUpdates) + `process_updates` (파싱/인증) + `format_ack_message`.
- **수정 모듈**:
  - `src/telegram_bot/formatter.py`: `format_full_report(..., watchlist=None)` — 비어있으면 섹션 미추가, 있으면 5번째 섹션.
  - `src/main.py`: 단계 0.5 `_process_user_commands()`, 단계 1에서 S&P500 + watchlist extras 합쳐 fetch, 단계 3에서 `_build_watchlist_stocks()`로 RankedStock 구성, 단계 4 뉴스 대상에 합류, 단계 5 포매터에 watchlist 인자로 전달. `_check_data_health`는 S&P500 서브셋만으로 평가.
  - `.github/workflows/daily-report.yml`: `permissions: contents: write` + "Commit watchlist changes" 스텝 (`[skip ci]` 로 재트리거 방지).
- **커맨드 문법**:
  - 티커: `BE`, 복수: `NVDA MSFT AAPL` (공백/쉼표/개행), 제거: `-BE`
  - 슬래시: `/list`(조회), `/clear`(초기화), `/start`·`/help`(현재 상태 표시)
  - 정규화: 소문자 → 대문자, `BRK.B` → `BRK-B`
- **인증**: `TELEGRAM_CHANNEL_ID`와 일치하는 chat_id(숫자) 또는 `@username`만 처리. 타 유저 `/start` 안전 무시.
- **offset 관리**: Telegram getUpdates는 `offset`으로 cursor 진행. watchlist.json에 `last_update_id` 저장 → 중복 수신 방지. 미인증 메시지도 offset은 전진 (재처리 비용 제로).
- **테스트**: `tests/test_commands.py` 17 케이스 (parsing·normalize·unauth·multiline·comma·offset) — 전체 pytest **62 passed**.
- **E2E sim**: mocked getUpdates([{text:"BE"}]) + mocked market data w/ synthetic BE row → `📌 내 관심종목` 섹션에 `BE Bloom Energy +12.50%` 렌더링 확인. watchlist.json에 `{"tickers":["BE"], "last_update_id":999}` 저장 확인.
- **주의점**:
  - GH Actions 첫 실행 때 repo의 **Settings → Actions → General → Workflow permissions** 가 "Read and write permissions"여야 auto-commit 동작. 기본값은 "Read repository contents" 뿐.
  - `data/cache/` 는 gitignored이지만 `data/watchlist.json`은 커밋 대상 — 경로 분리 의도적.
  - 미인증 메시지도 offset 전진: 공개 채널에서 타인이 스팸해도 무한 루프 없음.
  - main.py의 `use_cache=True` 는 watchlist 기능 추가로 `use_cache=False`로 회귀 (새 티커 추가 시 stale 캐시 피하기 위해).
