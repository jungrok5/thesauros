# Thesauros

> 마태복음 6:20 — "보물을 하늘에 쌓아 두라(θησαυρός)."

추세추종 매매 룰 기반 자동 스캐너 + 매매 결정 보조 도구.
매일 16시 (KST) 자동 스캔 → 텔레그램 + 웹 푸시 알림.

라이브: https://thesauros2026.vercel.app/

---

## 무엇을 하는가

| 페이지 | 내용 |
|---|---|
| `/dashboard` | 거시 5축 다이얼 (통화·금리·경기·물가·시장 심리) + 시장 레짐 + 34개 거시 지표 |
| `/recommendations` | 일일 스캔 결과 — STRONG_BUY / BUY / AVOID 등 액션 + 신호 강도 + 이유 |
| `/themes` / `/themes/[id]` | 테마별 종목 + 변동률 히트맵 + 멤버 신호 |
| `/stocks` | 검색 (영문 티커 / 6자리 KR 코드 / 한글 종목명) |
| `/stocks/[ticker]` | 차트(MA + 패턴 + 4등분선) · 실시간 시세 · 외국인/기관 매매 · 뉴스 · 공시 · 재무 · 팩터 |
| `/watchlist` | 관심·보유 종목 + 목표가/손절가 인라인 편집 |
| `/closing-trade` | 종가매매 모드 — 보유 종목 10MA 신호등 + 매매 일지 |
| `/settings/alerts` | 텔레그램 연동 + PWA 푸시 + 알림 종류 토글 |
| `/admin/access` | 관리자 — 새 사용자 승인/반려 |

자동매매는 의도적으로 미구현. KIS API 는 데이터 읽기 전용.

---

## 아키텍처

```
┌──── 외부 API ────┐         ┌──── 우리 인프라 ────┐
│ FRED · yfinance  │         │ Vercel (Next.js 16) │
│ DART · KIS       │         │ Supabase Postgres   │
│ pykrx · FDR      │   ───►  │ GitHub Actions cron │
│ Naver · Wikipedia│         │ Telegram webhook    │
│ Google · Telegram│         │  (= Vercel route)   │
└──────────────────┘         └─────────────────────┘
```

데이터 흐름:

```
외부 API ──[cron]──► Supabase 테이블 ──► Next.js 페이지/API ──► 브라우저
                          │
                          └──► telegram_worker ──► Telegram / 웹푸시
```

cron 이 외부에서 데이터를 끌어와 Supabase 에 적재. 사이트는 Supabase 만 읽음
(서버 컴포넌트가 직접 조회). 사용자 액션 시점에 외부 API 를 부르는 건 KIS 실시간
시세 + 차트 on-demand 계산 정도.

### 컴포넌트

| 위치 | 내용 |
|---|---|
| `web-next/` | Next.js 16 App Router · Auth.js v5 · Tailwind v4 · Playwright E2E |
| `app/db/` | Supabase 통신 모듈 (cron 진입점들) |
| `app/book/` | 차트 패턴 · 추세 · 4등분선 · 거래량 분류 등 룰 엔진 |
| `app/data/` | KIS · KRX · DART · Universe (S&P 500/KOSPI/KOSDAQ) |
| `app/macro/` | FRED 거시 지표 fetcher |
| `migrations/*.sql` | Supabase 스키마 — `python -m app.db.migrate up` 으로 적용 |
| `scripts/` | 일회성 운영 헬퍼 (시크릿 업로드, 텔레그램 webhook 등록 등) |

### 외부 API ↔ cron ↔ 테이블

| 외부 | 무엇 | Python 모듈 | Supabase 테이블 | cron |
|---|---|---|---|---|
| FRED | 거시 지표 | `app/macro/fetch.py` | `macro_series`, `macro_state` | daily-scan |
| yfinance | 미국 주가 (S&P 500) + VIX/S&P/환율 | `app/db/ingest_bars_daily.py`, `app/macro/fetch.py` | `bars_daily`, `macro_series` | daily-scan |
| FDR (FinanceDataReader) | KR 주가 (KOSPI/KOSDAQ) | `app/db/ingest_bars_daily.py` | `bars_daily` | daily-scan |
| pykrx / FDR | KR 종목 마스터 (신규/폐지) | `app/db/seed_tickers.py` | `tickers` | weekly-tickers-refresh |
| Wikipedia · Nasdaq Trader | 종목 마스터 (S&P 500, NASDAQ/NYSE) | `app/db/seed_tickers.py`, `app/data/universe.py` | `tickers` | weekly-tickers-refresh |
| DART OpenAPI | KR 펀더멘털 + 공시 | `app/data/ingest_dart.py`, `app/db/ingest_news.py` | `fundamentals`, `financials_eval`, `factors_eval`, `disclosures` | weekly-fundamentals |
| Naver Finance | KR 뉴스 + 테마 + 섹터 | `app/db/ingest_news.py`, `ingest_themes.py`, `ingest_kr_sector.py` | `news`, `themes`, `theme_daily`, `theme_members` | daily-scan |
| KIS OpenAPI | 외국인/기관 매매 + 실시간 시세 | `app/db/ingest_investor_flow.py`, `app/data/kis.py` | `investor_flow` | daily-scan |
| Google OAuth | 로그인 | NextAuth | `users` | 사용자 로그인 시 |
| Telegram Bot API | 알림 발송 + 메시지 수신 | `app/db/telegram_worker.py`, `/api/telegram/webhook` | `alerts`, `users.telegram_chat_id` | cron + webhook |
| Browser Push | PWA 푸시 | `app/db/webpush.py` | `push_subscriptions` | cron |

### Cron workflows

| 워크플로 | 주기 (KST) | 단계 |
|---|---|---|
| `daily-scan.yml` | 평일 16:00 | ingest_bars_daily → scan_daily → publish_macro → ingest_themes → ingest_investor_flow |
| `weekly-tickers-refresh.yml` | 일요일 10:00 | seed_tickers (신규/폐지 마킹) |
| `weekly-fundamentals.yml` | 토요일 11:00 | ingest_dart → eval_financials |
| `keepalive.yml` | 매일 10:30 | Supabase ping (무료 플랜 1주 inactivity pause 방지) |
| `ci.yml` | PR | typecheck + lint + smoke + Playwright |

### Next.js API 경로 (모두 Supabase 또는 외부 직접)

| 경로 | 권한 | 데이터 |
|---|---|---|
| `/api/auth/[...nextauth]` | public | Google OAuth |
| `/api/access-request` | 로그인 | `users`, `access_requests` |
| `/api/admin/access-requests` | admin | `users`, `access_requests` |
| `/api/alert-preferences` | 로그인 | `alert_preferences` |
| `/api/chart` | 로그인 | `bars_daily` (on-demand MA + 패턴 계산) |
| `/api/quote/[ticker]` | 로그인 | `bars_daily` + KIS 실시간 |
| `/api/search` | 로그인 | `tickers` (pg_trgm) |
| `/api/push/subscribe` | 로그인 | `push_subscriptions` |
| `/api/telegram/link-token` | 로그인 | `telegram_link_tokens`, `users` |
| `/api/telegram/webhook` | webhook secret | Telegram → `users` |
| `/api/trade-log` | 로그인 | `trade_log` |
| `/api/watchlist` | 로그인 | `watchlist` |
| `/api/e2e-test/issue-session` | dev only (E2E_TEST_TOKEN) | `users` (테스트 유저 발급) |

### 페이지별 데이터 source / 캐싱

| 페이지 | source | 캐싱 |
|---|---|---|
| `/dashboard` | `macro_state` | `revalidate=60` |
| `/recommendations` | `scan_results` + `tickers` | `revalidate=60` |
| `/themes`, `/themes/[id]` | `themes`, `theme_daily`, `theme_members`, `scan_results` | `revalidate=60` |
| `/stocks` | 정적 검색 | 정적 |
| `/stocks/[ticker]` | `analyze_results` + `watchlist` + 클라 fetch (`/api/chart`, `/api/quote`) | `force-dynamic` (per-user) |
| `/watchlist`, `/closing-trade`, `/settings/alerts`, `/admin/access`, `/pending` | per-user Supabase | `force-dynamic` |

### 데이터 신선도

| 데이터 | 갱신 | 최악 stale |
|---|---|---|
| macro / scan / 차트 / 분석 / 뉴스 / 공시 / 외국인매매 | daily-scan | 1일 |
| 재무 / 팩터 평가 | weekly-fundamentals | 7일. UI 가 14일 초과 시 노란 경고 표시 |
| 종목 마스터 (신규/폐지) | weekly-tickers-refresh | 7일 |

---

## 로컬 개발

```cmd
:: 첫 설치
install.bat
cd web-next && npm install && cd ..

:: 마이그레이션 적용
python -m app.db.migrate up

:: 개발 서버
run-frontend.bat              :: Next.js (:3000)

:: cron 수동 실행 (GitHub Actions 동등)
run-cron-daily.bat
```

### 환경변수

**`web-next/.env.local`**

| 변수 | 용도 |
|---|---|
| `AUTH_SECRET` | NextAuth JWT (`openssl rand -base64 32`) |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Google OAuth 클라이언트 |
| `ADMIN_EMAILS` | 콤마구분. 매칭되면 자동 admin + approved |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase 클라이언트 |
| `SUPABASE_SERVICE_KEY` | 서버 전용 service_role |
| `TELEGRAM_BOT_TOKEN` | BotFather 봇 토큰 |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram → 우리 webhook 검증 (`openssl rand -hex 32`) |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | 웹 푸시 (옵션) |

**`.env`** (Python cron / 로컬)

| 변수 | 용도 |
|---|---|
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_DB_PASSWORD` | Supabase 연결 |
| `FRED_API_KEY` | FRED 거시 지표 |
| `DART_API_KEY` | KR 공시/펀더멘털 |
| `KIS_APP_KEY` / `KIS_APP_SECRET` / `KIS_ACCOUNT_NO` / `KIS_ACCOUNT_PROD_CODE` | KIS API |
| `KIS_ENV` | `real` 또는 `vts` (모의투자) |
| `SEC_USER_AGENT` | SEC EDGAR 요청 헤더 (US 펀더멘털 백업) |
| `TELEGRAM_BOT_TOKEN` | 알림 발송용 |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_CONTACT_EMAIL` | 웹 푸시 발송 |

VAPID 키 생성: `python -m app.db.vapid_keys` (일회성, 재발급 시 기존 구독자 끊김)

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

Python smoke:
```cmd
python -m pytest app/db/tests
```

---

## 배포

### 1. Supabase

1. supabase.com → New project (Region: **ap-northeast-2, Seoul**)
2. DB password 보관 → `SUPABASE_DB_PASSWORD`
3. Settings → API 에서:
   - Project URL → `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`
   - anon public → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - service_role → `SUPABASE_SERVICE_KEY` (서버 전용)
4. 로컬에서 `python -m app.db.migrate up` 으로 스키마 적용
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
2. **Root Directory = `web-next`** (필수, 기본값 잘못됨)
3. Framework: Next.js (자동 감지). Build/Install 은 `web-next/vercel.json` 가 지정
4. Settings → Environment Variables 에 위 `.env.local` 변수 모두 등록
5. Push 하면 자동 빌드 → 5분 내 URL 발급

### 4. GitHub Actions cron

Repository → Settings → Secrets and variables → Actions 에 다음 등록 (또는
`python -m scripts.upload_gh_secrets` 로 일괄 업로드):

`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_PASSWORD`,
`FRED_API_KEY`, `DART_API_KEY`,
`KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ACCOUNT_PROD_CODE`,
`SEC_USER_AGENT`, `TELEGRAM_BOT_TOKEN`,
`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`.

Actions 탭에서 `daily-scan` 을 한 번 수동 실행해 정상 동작 확인.

### 5. Telegram webhook

```cmd
python -m scripts.setup_telegram_webhook https://<your-vercel-domain>
```

또는 직접:
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<your-vercel-domain>/api/telegram/webhook",
    "secret_token": "<TELEGRAM_WEBHOOK_SECRET>",
    "allowed_updates": ["message"]
  }'
```

### 6. 첫 사용

1. `https://<your-vercel-domain>` 접속 → Google 로그인
2. `ADMIN_EMAILS` 매칭 이메일이면 `/dashboard` 로 바로 진입. 아니면 `/pending`
   에서 사용 요청 제출 → 관리자가 `/admin/access` 에서 승인
3. `/settings/alerts` → 토큰 발급 → 텔레그램에서 `/link <토큰>` → 알림 연동
4. `/settings/alerts` → "푸시 알림 켜기" 로 PWA 푸시 구독

---

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| Vercel `next: command not found` | Root Directory 가 `web-next` 가 아님 |
| Google `redirect_uri_mismatch` | Google Cloud Console redirect URI 에 prod 도메인 추가 |
| `/api/auth/...` 500 | `AUTH_SECRET` 미설정 |
| Dashboard "거시 데이터 없음" | `publish_macro` cron 미실행 → Actions 수동 트리거 |
| `/stocks/[ticker]` "분석 데이터 없음" | 해당 종목 미스캔 → `python -m app.db.scan_daily --tickers <T> --years 2` |
| 텔레그램 `/link` 무반응 | webhook 미등록/secret 불일치 → `curl .../getWebhookInfo` 로 확인 |
| 푸시 켜기 실패 ("VAPID 키 미설정") | `NEXT_PUBLIC_VAPID_PUBLIC_KEY` 미설정 |
| Supabase 갑자기 read-only | 무료 500MB 한도 초과. `bars_daily` 보존 줄이기 (`--years 2`) 또는 임시 Pro 업그레이드 |

---

## 비용

| 항목 | 한도 | 비고 |
|---|---|---|
| Vercel Hobby | 무제한 (개인 비상업) | — |
| Supabase Free | DB 500MB · Auth 50K MAU | bars_daily 2년 + KR 전체 + S&P 500 ≈ 230MB |
| GitHub Actions | Public repo 무제한 / Private 2,000분/월 | daily-scan ≈ 60-70분/회 |
| Telegram / Google OAuth | 무료 | — |

전부 무료 한도 안. 데이터 보존을 늘리거나 universe 를 확장하면 Supabase 가 첫 병목.

---

## 면책

학습/연구 도구입니다. 실거래 결과를 보장하지 않습니다.
모든 매매 판단과 손익은 본인 책임입니다.
