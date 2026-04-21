# S&P 500 Daily Telegram Bot

매일 07:00 KST에 S&P 500 상위 종목 시황과 뉴스를 텔레그램 채널로 자동 전송.

## 리포트 구성
1. **시가총액 Top 10**: 주가 등락률 + 24h 뉴스
2. **일일 등락률 Top 10 / Bottom 10**: 상승·하락 상위
3. **시총 대비 거래대금 비율 Top 10**: 회전율 상위

## 빠른 시작

### 1) 가상환경 + 패키지 설치
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2) 환경변수 설정
```bash
cp .env.example .env
# .env 파일을 열어 TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID 입력
```

### 3) 텔레그램 봇 생성
- [@BotFather](https://t.me/BotFather)에 `/newbot` → 이름·유저네임 지정 → 토큰 발급
- 채널을 만들고 봇을 **관리자(Admin)** 로 추가 (메시지 전송 권한 필수)
- 채널 ID 확인: 봇이 채널에 한 번 메시지 보낸 뒤
  `https://api.telegram.org/bot<TOKEN>/getUpdates` 에서 `chat.id` 찾기
  (공개 채널은 `@channelname` 그대로 사용 가능)

### 4) 연결 테스트 (텔레그램 전송 확인)
```bash
# 간단한 메시지 1건 전송 — 채널에 메시지가 도착해야 함
python -m src.telegram_bot.sender "연결 테스트"

# 포매터만 확인 (네트워크 전송 없이 콘솔 출력)
python -m src.telegram_bot.formatter
```
전송이 실패한다면 다음을 확인:
- `.env`의 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`가 정확한가?
- 봇이 채널의 **관리자(Admin)** 로 추가되어 있고 "메시지 전송" 권한이 있는가?
- 비공개 채널이라면 채널 ID가 `-100`으로 시작하는 숫자 형식인가?
- `HTTP 401` → 토큰 오류. `HTTP 400 "chat not found"` → 채널 ID 오류.

### 5) 실행
```bash
# 수동 1회 실행 (지금 바로 한 번 보내기)
python -m src.main

# 스케줄러 상시 구동 (매일 07:00 KST)
python -m scheduler.daily_run
```

## 배포 옵션

### ⭐ A) GitHub Actions (권장 — 무료·인프라 불필요)

공개 저장소 기준 무료, 매일 스케줄 실행, 시크릿 안전 격리. 서버 관리 0.

**1) 사전 체크 — `.env`가 git에 올라가지 않는지 확인**

```bash
# 프로젝트 루트에서
cat .gitignore | grep -E '^\.env$'     # → .env 가 나와야 함
git status --ignored 2>/dev/null | grep '.env'   # git init 이후면 Ignored: .env 확인
```

**2) git init + 첫 커밋**

```bash
cd sp500_telegram_bot
git init
git add .                              # .gitignore가 .env/logs/cache 자동 제외
git status                             # 여기에 .env 절대 없어야 함 — 있으면 멈추고 .gitignore 확인
git commit -m "Initial commit: S&P 500 daily Telegram bot"
git branch -M main
```

**3) GitHub 저장소 생성 후 push**

GitHub에서 Public 저장소 생성 (예: `sp500-daily-telegram`) 후:

```bash
git remote add origin https://github.com/<YOUR_USERNAME>/<REPO>.git
git push -u origin main
```

**4) Secrets 등록 (필수)**

저장소 페이지 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather에서 발급받은 토큰 (예: `1234567890:ABC...`) |
| `TELEGRAM_CHANNEL_ID` | 채널 ID (`@channelname` 또는 `-100...` 또는 숫자 user_id) |

**5) 수동 1회 실행으로 검증**

**Actions** 탭 → 왼쪽 **Daily S&P 500 Report** → **Run workflow** → `main` 브랜치 선택 → 버튼 클릭.

1~2분 내에 텔레그램으로 리포트가 도착하면 성공. 실패 시 해당 run의 **logs-<run_id>** artifact에서 로그 확인.

**6) 자동 실행**

등록된 workflow는 **매일 UTC 22:00 = KST 07:00**에 자동 실행됩니다. cron 스펙은 `.github/workflows/daily-report.yml`에서 수정 가능.

**주의**:
- **60일 비활성 규칙**: 커밋·수동 실행이 60일간 없으면 GitHub이 스케줄을 자동 비활성화합니다. 2개월에 한 번 이상 수동 실행하거나 작은 커밋으로 유지.
- **스케줄 지연**: GitHub 부하에 따라 몇 분 늦을 수 있음 (일상 리포트엔 문제 없음).
- **로그 보존**: 성공 로그는 GitHub에 자동 기록되고, 실패 시 7일간 artifact로 다운로드 가능.

### B) APScheduler 상시 구동 (VPS/홈서버)
위의 `python -m scheduler.daily_run`을 백그라운드로 띄우기.

**nohup (Linux/macOS)**:
```bash
nohup python -m scheduler.daily_run >> logs/scheduler.log 2>&1 &
```

**systemd (Linux 권장)** — `/etc/systemd/system/sp500-bot.service`:
```ini
[Unit]
Description=S&P 500 Daily Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/sp500_telegram_bot
Environment="PATH=/path/to/sp500_telegram_bot/venv/bin"
ExecStart=/path/to/sp500_telegram_bot/venv/bin/python -m scheduler.daily_run
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sp500-bot
sudo journalctl -u sp500-bot -f    # 로그 확인
```

### C) OS cron (프로세스 상시 구동 불필요)
APScheduler 대신 cron으로 `src.main`을 직접 호출. 상시 구동 리소스 불필요.

**서버 TZ가 KST인 경우** — `crontab -e`에 추가:
```cron
0 7 * * * cd /path/to/sp500_telegram_bot && /path/to/venv/bin/python -m src.main >> logs/cron.log 2>&1
```

**서버 TZ가 UTC인 경우** (KST 07:00 = UTC 22:00 전날):
```cron
0 22 * * * cd /path/to/sp500_telegram_bot && /path/to/venv/bin/python -m src.main >> logs/cron.log 2>&1
```


## 개발 워크플로

### 단위 테스트
```bash
# 전체 테스트 (pytest.ini에 rootdir/testpaths 설정됨)
python -m pytest

# 특정 파일만
python -m pytest tests/test_rankings.py -v
```

### 모듈별 단독 실행 (디버깅)
각 모듈은 `if __name__ == "__main__":` 섹션이 있어 단독 실행 가능:
```bash
python -m src.data.sp500_list            # S&P 500 리스트 상위 5개
python -m src.data.market_data           # 시총 Top 10 (네트워크 필요, ~40s)
python -m src.data.market_calendar       # NYSE 개장일 체크
python -m src.analysis.rankings          # 4종 순위 (market_data 결과 재사용)
python -m src.news.news_fetcher AAPL MSFT  # 뉴스 조회
python -m src.telegram_bot.formatter     # mock 데이터 포맷 출력
python -m src.telegram_bot.sender "테스트"  # Telegram 직접 전송
```

### 강제 실행 (휴장일 무시)
```bash
python -m src.main --force
```

### 로그
- 파일: `logs/YYYY-MM-DD.log` (utf-8, rotation 10MB, retention 30일)
- 콘솔: stdout/stderr (utf-8 재설정 — Windows cp949 환경에서도 이모지 출력 가능)

## 운영 주의사항

### 휴장일 처리
매일 07:00 KST 실행 시점의 **ET(미국 동부) 날짜**가 NYSE 개장일이 아니면 자동 스킵:
- 주말 (월/일 KST 실행 = ET 일/토 → 스킵)
- 미국 공휴일 (신정·MLK·Good Friday·독립기념일 등)

휴장 시에는 `🏖 NYSE 휴장일 안내` 메시지 1건만 전송되고 리포트 파이프라인은 건너뜁니다.

### 데이터 건강 검증
`run_daily_report()`는 2단계로 yfinance 장애를 감지:
1. 전체 성공률 50% 미만 → `RuntimeError`
2. 메가캡 10종(AAPL/MSFT/NVDA/GOOGL/AMZN/META/TSLA/BRK-B/JPM/LLY) 중 7개 이상 결측 → `RuntimeError`

실패 시 `❌ S&P 500 리포트 실패` 메시지와 traceback이 Telegram으로 전송되고 예외가 재전파됩니다.

## 프로젝트 구조
[CLAUDE.md](CLAUDE.md) 참조.

## 개발 로드맵
[PLAN.md](PLAN.md) 참조.
