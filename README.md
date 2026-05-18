# Thesauros

> 마태복음 6:20 — "보물을 하늘에 쌓아 두라(θησαυρός)."

추세추종 매매 룰 기반 자동 스캐너 + 매매 결정 보조 도구.
KOSPI / KOSDAQ 전 종목을 매일 16시 (KST) 자동 분석 → 텔레그램 + 웹 푸시.

라이브: https://thesauros2026.vercel.app/ · 라이센스: [MIT](LICENSE)

자동매매는 의도적으로 미구현. KIS / DART / Naver / FDR API 는 모두 데이터 읽기 전용.

---

## 페이지

| URL | 내용 |
|---|---|
| `/dashboard` | 실시간 시세 띠 (KOSPI · KOSDAQ · S&P · NASDAQ · VIX · 환율 · 美10Y · WTI · Gold · BTC, 1분 갱신) · 거시 5축 다이얼 · 글로벌 속보 (Investing.com + 연합뉴스) · 시장 레짐 · 월간/분기 거시 지표 (CPI · PPI · M2 등) |
| `/recommendations` | 일일 스캔 결과 — STRONG_BUY / BUY / AVOID 액션 + 신호 강도 + 사람이 읽을 수 있는 이유. 시장·신호 유형·정렬·Top N 필터 |
| `/themes`, `/themes/[id]` | Naver 테마별 종목 + 변동률 히트맵 + 멤버 신호 |
| `/stocks` | 검색 (영문 티커 / 6자리 KR 코드 / **한글 종목명 자동 매칭** via Naver) |
| `/stocks/[ticker]` | 차트 (이평선 + 4등분선 + 패턴 오버레이) · 최종 종가 · 외국인/기관 매매 동향 · 실시간 뉴스 (네이버 종목 뉴스 탭) · DART 공시 · 재무 · 팩터 (강환국 / 그레이엄 / 마법공식 / 버핏 게이트) · 매매 플랜 |
| `/watchlist` | 관심 (observing) · 보유 (holding) 분리. 진입가 / 목표가 / 목표% / 손절가 / 손절% 인라인 편집. 90일 미접속 시 generated data 자동 만료 (관심종목 자체는 보존) |
| `/closing-trade` | 종가매매 모드 — 보유 종목 10MA 신호등 + 매매 일지. 책 원칙대로 주봉/월봉 마감 D-day (금요일 / 월말 15:30 KST) |
| `/settings/alerts` | 텔레그램 연동 · PWA 푸시 · 알림 종류 토글 (enter / pyramid / warn / exit / 240MA / 4등분선) |
| `/admin/access` | 관리자 — 새 사용자 승인/반려. `decide_access_request` RPC 로 원자성 보장 |

UI 전반에 **HelpTip** 용어집 (쌍바닥 / 돌반지 / Cup with Handle / 외국인 매매 / 강환국 가치 등) 마우스 오버 / 탭 시 설명 + 외부 위키 링크.

---

## 아키텍처

```
┌──── 외부 API ────┐         ┌──── 우리 인프라 ──────┐
│ FRED · Yahoo     │         │ Vercel (Next.js 16)  │
│ FDR · DART       │   ───►  │ Supabase Postgres     │
│ Naver · Wikipedia│         │ GitHub Actions cron   │
│ Google · Telegram│         │ Telegram webhook       │
└──────────────────┘         │   (= Vercel route)    │
                             └───────────────────────┘
```

**Server-only DB.** Cron 이 외부에서 데이터를 끌어와 Supabase 에 적재. 사이트는 Supabase 만 읽음
(서버 컴포넌트가 직접 조회). 두 종류의 실시간 fetch 는 클라이언트가 직접 호출:

- `/api/quotes/realtime` (Yahoo v8 chart, 60s ISR) — 대시보드 시세 띠
- `/api/news/global` (Investing.com + 연합뉴스 RSS, 5m ISR) — 글로벌 속보
- `/api/news/[ticker]` (네이버 증권 종목 뉴스, 5m ISR) — 종목 페이지 뉴스 탭
- `/api/chart` — bars 가 DB 에 없는 US 종목은 Yahoo 라이브 fetch (1d ISR)

### 컴포넌트

| 위치 | 내용 |
|---|---|
| `web-next/` | Next.js 16 App Router · Auth.js v5 · Tailwind v4 · lightweight-charts · Playwright E2E |
| `app/db/` | Supabase 통신 모듈 (cron 진입점들 + 데이터 품질 테스트) |
| `app/book/` | 차트 패턴 · 추세 · 4등분선 · 거래량 분류 룰 엔진 (KR 종가매매 컨텍스트) |
| `app/data/` | DART / Universe (KOSPI/KOSDAQ + S&P 500) / KIS 헬퍼 |
| `app/macro/` | FRED 거시 지표 fetcher |
| `migrations/*.sql` | Supabase 스키마 — `python -m app.db.migrate up` |
| `scripts/` | 일회성 운영 헬퍼 (시크릿 업로드, 텔레그램 webhook 등록, DB 정리) |

### 외부 API ↔ cron ↔ 테이블

| 외부 | 무엇 | Python 모듈 / Next.js route | Supabase 테이블 | cron / 트리거 |
|---|---|---|---|---|
| **FDR** | KR OHLCV (KOSPI/KOSDAQ) | `app/db/ingest_bars_daily.py` | `bars_daily` | daily-scan |
| **yfinance v8** | US OHLCV (watchlist 만), VIX/S&P/^IXIC 등 | `app/db/ingest_bars_daily.py`, `app/macro/fetch.py`, `/api/chart` US fallback, `/api/quotes/realtime` | `bars_daily`, `macro_series` | daily-scan + realtime |
| **FRED** | 거시 지표 (M2, CPI, PPI, 금리 등) | `app/macro/fetch.py` | `macro_series`, `macro_state` | daily-scan |
| **pykrx / FDR** | KR 종목 마스터 | `app/db/seed_tickers.py` | `tickers` | weekly-tickers-refresh |
| **Wikipedia · Nasdaq Trader** | US 종목 마스터 (S&P 500 등) | `app/db/seed_tickers.py`, `app/data/universe.py` | `tickers` | weekly-tickers-refresh |
| **DART OpenAPI** | KR 펀더멘털 + 공시 | `app/data/ingest_dart.py`, `app/db/ingest_news.py` | `fundamentals`, `financials_eval`, `factors_eval`, `disclosures` | weekly-fundamentals + daily-scan |
| **Naver Finance** (종목 뉴스 탭) | 종목별 뉴스 — 실시간 | `/api/news/[ticker]` | (실시간, 저장 X) | 사용자 페이지뷰 |
| **Naver Finance** (frgn.naver) | 외국인 / 기관 매매 동향 | `app/db/ingest_investor_flow.py` | `investor_flow` | daily-scan |
| **Naver Finance** (테마) | KR 테마 + 멤버 | `app/db/ingest_themes.py` | `themes`, `theme_daily`, `theme_members` | daily-scan |
| **Naver Finance** (통합 검색) | 한글 브랜드명 → ticker | `/api/search` 폴백, `lib/naver-search.ts` | (실시간) | 사용자 검색 |
| **Investing.com 한국어 RSS + 연합뉴스 경제 RSS** | 글로벌 + 국내 시장 속보 | `/api/news/global` | (실시간) | 대시보드 |
| **Google OAuth** | 로그인 | NextAuth | `users` | 로그인 시 |
| **Telegram Bot API** | 알림 발송 (outbound) + `/link`·`/start` 수신 (inbound webhook) | `app/db/telegram_worker.py`, `/api/telegram/webhook` | `alerts`, `users.telegram_chat_id` | cron + webhook |
| **Browser Push** | PWA 푸시 | `app/db/webpush.py` | `push_subscriptions` | cron |

### Cron workflows

| 워크플로 | 주기 (KST) | 단계 |
|---|---|---|
| `daily-scan.yml` | 평일 16:00 | ingest_bars_daily → scan_daily → publish_macro → ingest_themes → ingest_investor_flow → ingest_news (DART) → **retention** → **data-quality assertions** |
| `weekly-tickers-refresh.yml` | 일요일 10:00 | seed_tickers (신규 INSERT / 폐지 is_active=false) |
| `weekly-fundamentals.yml` | 토요일 11:00 | ingest_dart → eval_financials |
| `keepalive.yml` | 매일 10:30 | Supabase ping (무료 플랜 1주 inactivity pause 방지) |
| `ci.yml` | PR / push | typecheck + lint + Python smoke + data-quality + Playwright E2E |

US 종목은 cron 의 default universe 에 **없음**. 사용자가 watchlist 에 등록한 US 종목만 union 으로 자동 포함 → 풀 17 패턴 분석. watchlist 미등록 US 검색은 `/api/chart` 가 Yahoo 라이브 fetch (1일 캐시) — 차트 + 이평선만, 17 패턴 분석은 안 함.

### Next.js API 경로

| 경로 | 권한 | 데이터 |
|---|---|---|
| `/api/auth/[...nextauth]` | public | Google OAuth |
| `/api/access-request` | 로그인 | `users`, `access_requests` |
| `/api/admin/access-requests` | admin | `decide_access_request` RPC (트랜잭션) |
| `/api/alert-preferences` | 로그인 | `alert_preferences` |
| `/api/chart` | 로그인 | `bars_daily` + Yahoo 라이브 폴백 (US) |
| `/api/quote/[ticker]` | 로그인 | `bars_daily` 최종 종가 (라이브 X — 종가매매 원칙) |
| `/api/quotes/realtime` | 로그인 | Yahoo Finance v8 chart (11 심볼, 60s 캐시) |
| `/api/news/[ticker]` | 로그인 | 네이버 증권 종목 뉴스 (5m 캐시, KR 한정) |
| `/api/news/global` | 로그인 | Investing.com + 연합뉴스 RSS 머지 (5m 캐시) |
| `/api/search` | 로그인 | `tickers` (pg_trgm) + Naver 통합 검색 폴백 |
| `/api/push/subscribe` | 로그인 | `push_subscriptions` |
| `/api/telegram/link-token` | 로그인 | `telegram_link_tokens`, `users` |
| `/api/telegram/webhook` | webhook secret (≥32 chars) | Telegram → `users` |
| `/api/trade-log` | 로그인 | `trade_log` |
| `/api/watchlist` | 로그인 | `watchlist` (FK 보호 — Naver 미매칭 ticker 거부) |
| `/api/e2e-test/issue-session` | dev only (E2E_TEST_TOKEN ≥16 + IS_PROD 가드) | 테스트 유저 발급 (1h 자동 GC) |

### 데이터 신선도

| 데이터 | 갱신 | 최악 stale |
|---|---|---|
| OHLCV / scan / 분석 / macro / 테마 / 외국인매매 / 공시 | daily-scan | 1일 |
| 실시간 시세 띠 (Yahoo) · 글로벌 속보 · 종목별 뉴스 | 실시간 fetch (분~5분 캐시) | 5분 |
| 재무 / 팩터 평가 | weekly-fundamentals | 7일 (UI 가 14일 초과시 노란 경고) |
| 종목 마스터 (신규/폐지) | weekly-tickers-refresh | 7일 |

### 데이터 retention (자동)

매 daily-scan 마지막 단계로 `app/db/retention.py` 실행:

| 테이블 | 보존 |
|---|---|
| `bars_daily` | 2년 + (KR universe ∪ holding ∪ 최근 90일 접속한 watchlist) |
| `investor_flow` | 90일 |
| `disclosures` | 1년 |
| `alerts` | 90일 |
| `theme_daily` | 180일 |
| `scan_results` | 비활성 30일 후 |
| `analyze_results` | 위 engagement set 과 동일 |
| `users` | `@e2e.test` 1일 (E2E 테스트 흔적 자동 정리) |

→ DB 사이즈 **~487 MB 안정 (Free 500MB 한도 안)**. watchlist 자체는 user 소유라 절대 삭제 X.

---

## 로컬 개발

```cmd
:: 첫 설치
install.bat
cd web-next && npm install && cd ..

:: 마이그레이션 적용
python -m app.db.migrate up

:: 개발 서버 (Next.js :3000)
run-frontend.bat

:: cron 수동 실행 (GitHub Actions 동등)
run-cron-daily.bat
```

### 환경변수

**`web-next/.env.local`** (Vercel 도 같은 키)

| 변수 | 용도 |
|---|---|
| `AUTH_SECRET` | NextAuth JWT (`openssl rand -base64 32`) |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Google OAuth 클라이언트 |
| `ADMIN_EMAILS` | 콤마구분. 첫 로그인 시 자동 admin + approved |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase 클라이언트 |
| `SUPABASE_SERVICE_KEY` | 서버 전용 service_role |
| `TELEGRAM_BOT_TOKEN` | BotFather 봇 토큰 |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram → 우리 webhook 검증 (`openssl rand -hex 32`, **≥32 chars**) |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | PWA 푸시 (옵션) |
| `E2E_TEST_TOKEN` | dev 전용 — Playwright session 발급. **Vercel prod 에 등록 X** |

**`.env`** (Python cron / 로컬 GH Actions 실행)

| 변수 | 용도 |
|---|---|
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_DB_PASSWORD` | Supabase 연결 |
| `FRED_API_KEY` | FRED 거시 지표 |
| `DART_API_KEY` | DART 공시 + 펀더멘털 |
| `TELEGRAM_BOT_TOKEN` | 알림 발송용 |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_CONTACT_EMAIL` | 웹 푸시 발송 |

VAPID 키 생성: `python -m app.db.vapid_keys` (일회성. 재발급 시 기존 구독자 끊김).

> KIS API 환경변수 (`KIS_APP_KEY` 등) 는 현재 production 데이터 흐름에서 사용 안 됨. KIS 모의/실투자 모드의 외국인/기관 매매동향 응답이 불안정해서 Naver 스크래이프로 교체.

---

## 테스트

```cmd
cd web-next
:: 타입체크 + 린트
npx tsc --noEmit
npm run lint

:: E2E (Next.js 서버가 :3000 에 떠 있어야 함)
E2E_TEST_TOKEN=playwright-dev-only npx playwright test
```

Python:
```cmd
:: 스모크 (스키마 + scan 로직)
python -m pytest app/db/tests/test_smoke.py app/db/tests/test_scan.py

:: 데이터 품질 (freshness + coverage + 500MB 가드)
python -m pytest app/db/tests/test_data_quality.py
```

CI 가 PR / push 마다 위 모두 실행. daily-scan cron 도 마지막 단계로 `test_data_quality.py` 호출 → 데이터 적재 사일런트 실패를 즉시 GH Actions 워크플로 빨강으로 잡음.

---

## 배포

### 1. Supabase

1. supabase.com → New project (Region: **ap-northeast-2, Seoul**)
2. DB password 보관 → `SUPABASE_DB_PASSWORD`
3. Settings → API:
   - Project URL → `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`
   - anon public → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - service_role → `SUPABASE_SERVICE_KEY` (서버 전용)
4. 로컬에서 `python -m app.db.migrate up` 으로 스키마 적용 (현재 마이그레이션 1-19)
5. (선택) 초기 데이터: `python -m app.db.seed_tickers --markets kospi kosdaq us`

### 2. Google OAuth

1. console.cloud.google.com → 프로젝트 → APIs & Services → Credentials
2. OAuth client ID (Web application) 생성
3. Authorized redirect URIs:
   - `http://localhost:3000/api/auth/callback/google`
   - `https://<your-vercel-domain>/api/auth/callback/google`
4. Client ID / Secret → `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`

### 3. Vercel

1. vercel.com → New Project → GitHub repo 연결
2. **Root Directory = `web-next`** (필수)
3. Framework: Next.js (자동 감지). Build / Install 은 `web-next/vercel.json` 가 지정
4. Settings → Environment Variables 에 위 `.env.local` 키 모두 등록
5. Push 하면 자동 빌드 → 5분 내 URL 발급

### 4. GitHub Actions cron

Repository → Settings → Secrets and variables → Actions 에 시크릿 등록.
`python -m scripts.upload_gh_secrets` 로 `.env` 의 키를 일괄 업로드 가능.

필요 시크릿: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_PASSWORD`,
`FRED_API_KEY`, `DART_API_KEY`, `TELEGRAM_BOT_TOKEN`, `VAPID_PUBLIC_KEY`,
`VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`.

Actions 탭에서 `daily-scan` 을 한 번 수동 실행해 정상 동작 확인.

### 5. Telegram webhook

```cmd
python -m scripts.setup_telegram_webhook https://<your-vercel-domain>
```

`TELEGRAM_WEBHOOK_SECRET` 는 **최소 32자** (route 가 부족 시 500 반환).

### 6. 첫 사용

1. `https://<your-vercel-domain>` 접속 → Google 로그인
2. `ADMIN_EMAILS` 매칭 이메일이면 `/dashboard` 로 바로. 아니면 `/pending` 에서 사용 요청 제출 → 관리자가 `/admin/access` 에서 승인
3. `/settings/alerts` → 토큰 발급 → 텔레그램에서 `/link <토큰>` → 알림 연동
4. `/settings/alerts` → "푸시 알림 켜기" 로 PWA 푸시 구독

---

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| Vercel `next: command not found` | Root Directory 가 `web-next` 가 아님 |
| Google `redirect_uri_mismatch` | Google Cloud Console redirect URI 에 prod 도메인 추가 |
| `/api/auth/...` 500 | `AUTH_SECRET` 미설정 |
| `/api/telegram/webhook` 500 ("misconfigured") | `TELEGRAM_WEBHOOK_SECRET` 가 32자 미만 |
| Dashboard "거시 데이터 없음" | publish_macro cron 미실행 → Actions 수동 트리거 |
| `/stocks/[ticker]` "분석 데이터 없음" | 해당 종목 미스캔 → watchlist 에 추가하면 다음 cron 부터 자동 분석 |
| 텔레그램 `/link` 무반응 | webhook 미등록/secret 불일치 → `curl .../getWebhookInfo` 로 확인 |
| 푸시 켜기 실패 ("VAPID 키 미설정") | `NEXT_PUBLIC_VAPID_PUBLIC_KEY` 미설정 |
| Supabase 갑자기 read-only | 무료 500MB 한도 초과. `python -m app.db.retention --dry-run` 으로 정리 가능량 확인 후 실행 |

---

## 비용

| 항목 | 한도 | 현재 |
|---|---|---|
| Vercel Hobby | 무제한 (개인 비상업) | OK |
| Supabase Free | DB 500MB · Auth 50K MAU | **~487 MB** (retention 적용 후 안정) |
| GitHub Actions | Public repo 무제한 / Private 2,000분/월 | daily-scan ≈ 60분/회, public 권장 |
| Naver / Yahoo / FDR / FRED / DART / Investing.com | 무료 (rate-friendly) | OK |
| Telegram / Google OAuth | 무료 | OK |

---

## 면책

학습/연구 도구입니다. 실거래 결과를 보장하지 않습니다.
모든 매매 판단과 손익은 본인 책임입니다.
