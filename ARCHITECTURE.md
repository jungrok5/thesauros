# Architecture

> 데이터 / API / cron 의 관계를 한 화면에. 코드를 만질 때 어디서 무엇이 일어나는지 빨리 찾기 위한 지도.

```
┌──────────────── 외부 ────────────────┐    ┌────── 우리 인프라 ──────┐
│  Google OAuth   FRED   DART OpenAPI  │    │  Vercel (Next.js)       │
│  yfinance       KIS    pykrx  Naver  │    │  Supabase Postgres      │
│  Wikipedia      Nasdaq Trader        │    │  GitHub Actions cron    │
│  Telegram Bot API                    │    │  Telegram Webhook (= Vercel) │
└──────────────────────────────────────┘    └─────────────────────────┘
```

**FastAPI 서버 없음 / DuckDB 없음 / 24/7 봇 워커 없음.** 모두 cron으로 흐름 발동, 사이트는 Supabase 직접 조회.

---

## 1. 데이터 흐름 (high level)

```
외부 API ──[GitHub Actions cron]──► Supabase 테이블 ──► Next.js 페이지/API ──► 브라우저
                                       │
                                       └──► telegram_worker (cron) ──► 텔레그램 / 웹푸시
```

cron 이 매일/매주 외부 API 에서 데이터를 가져와 Supabase 에 적재 → 사이트는 Supabase 만 읽음.
사용자가 페이지 열 때마다 외부 API 를 부르는 곳은 거의 없음 (예외 §3).

---

## 2. 외부 API ↔ cron 매핑

| 외부 API | 무엇을 가져오나 | Python 모듈 | 어디 적재 (Supabase) | cron |
|---|---|---|---|---|
| **FRED** | 거시지표 (M2, 금리, CPI, ...) | `app/macro/fetch.py` (FRED API) | `macro_series` | `daily-scan.yml` 16시 (publish_macro 의존) |
| **yfinance** | 미국 주가 + 거시 ticker (`^VIX`, `^GSPC`, `JPY=X` 등) | `app/macro/fetch.py`, `app/book/analyzer.py` (fallback) | `macro_series`, `bars_daily` | `daily-scan.yml` |
| **pykrx / FDR** | KR 주가 + 종목 마스터 | `app/db/seed_tickers.py`, `app/book/analyzer.py` | `tickers`, `bars_daily` | `weekly-tickers-refresh.yml` 일요일 10시 |
| **Nasdaq Trader** (FTP) | US 종목 마스터 (NASDAQ / NYSE / AMEX) | `app/db/seed_tickers.py` | `tickers` | `weekly-tickers-refresh.yml` |
| **Wikipedia** (S&P 500) | S&P 500 구성 + 섹터 | `app/data/universe.py` | `tickers` (seed_tickers 가 호출) | `weekly-tickers-refresh.yml` |
| **DART OpenAPI** | KR 회사 펀더멘털 (매출/영업이익/자산/...) | `app/data/ingest_dart.py` | `fundamentals` → `financials_eval` / `factors_eval` | `weekly-fundamentals.yml` 토요일 11시 |
| **Naver Finance** | KR 뉴스 + 테마 + 종목별 섹터 | `app/db/ingest_news.py`, `ingest_themes.py`, `ingest_kr_sector.py` | `news`, `themes`, `theme_daily`, `theme_members` | `daily-scan.yml` |
| **DART (공시)** | KR 공시 (사업보고서, 분기보고서, 대규모기업집단 등) | `app/db/ingest_news.py` (DART 부분) | `disclosures` | `daily-scan.yml` |
| **KIS OpenAPI** | KR 외국인/기관 매매 동향 | `app/db/ingest_investor_flow.py` | `investor_flow` | `daily-scan.yml` |
| **Google OAuth** | 로그인 | (NextAuth 직접) | `users` (이메일/이름) | 사용자가 로그인할 때 (즉시) |
| **Telegram Bot API** | 알림 발송 (outbound) + 메시지 수신 (inbound webhook) | `app/db/telegram_worker.py` (out), `/api/telegram/webhook` (in) | — / `users.telegram_chat_id` | out: cron 안. in: 사용자가 보낼 때 즉시 |
| **Browser Push (FCM/Mozilla autopush)** | PWA 푸시 발송 | `app/db/webpush.py` | — | cron 안 (telegram_worker 와 함께) |

---

## 3. Cron workflow 별 상세

### `daily-scan.yml` — 매일 16시 KST (Mon-Fri)
사이트의 매일 한 번 데이터 갱신 + 알림 발송 메인.

| 스텝 | 명령 | 외부 호출 | Supabase 쓰기 |
|---|---|---|---|
| scan_daily | `python -m app.db.scan_daily --markets KOSPI KOSDAQ NASDAQ --years 5` | (Supabase bars_daily read) | `scan_results`, `analyze_results`, `chart_data` |
| publish_macro | `python -m app.db.publish_macro` | FRED, yfinance | `macro_state`, `macro_series` (fetch 도 같이) |
| ingest_themes | `python -m app.db.ingest_themes` | Naver Finance | `themes`, `theme_daily`, `theme_members` |
| ingest_news | `python -m app.db.ingest_news` | Naver, DART | `news`, `disclosures` |
| ingest_investor_flow | `python -m app.db.ingest_investor_flow` | KIS API | `investor_flow` |
| telegram_worker | `python -m app.db.telegram_worker` | Telegram + WebPush | `alerts` |

**예상 시간**: 9,570 종목 × 0.4초 = **약 60-70분** (단일 job 6시간 한도 안에서 OK).

### `weekly-tickers-refresh.yml` — 일요일 10시 KST
**신규 상장 / 폐지 종목 추적.**

```
python -m app.db.seed_tickers --markets kospi kosdaq us --refresh
```
- pykrx + FDR + Nasdaq Trader 에서 ticker 마스터 fetch
- 새 종목 INSERT, 사라진 종목 `is_active = false` 마킹

### `weekly-fundamentals.yml` — 토요일 11시 KST
DART 펀더멘털 갱신 + 평가.

```
python -m app.data.ingest_dart       # DART → Supabase fundamentals
python -m app.db.eval_financials     # fundamentals → financials_eval + factors_eval
```
- 분기 단위로만 변하니 주간 빈도면 충분

### `keepalive.yml` — 매일 10:30 KST
Supabase 무료 플랜의 1주 inactivity pause 방지용 ping. 가벼움.

### `ci.yml` — PR 시
Python smoke + Next.js typecheck + lint + Playwright E2E. cron 아님.

---

## 4. Next.js API route 별 데이터 source

| Route | 메서드 | 데이터 source | 권한 |
|---|---|---|---|
| `/api/auth/[...nextauth]` | GET/POST | Google OAuth | public |
| `/api/access-request` | GET/POST | Supabase `users`, `access_requests` | 로그인 |
| `/api/admin/access-requests` | GET/POST | Supabase `users`, `access_requests` | admin |
| `/api/alert-preferences` | GET/PUT | Supabase `alert_preferences` | 로그인 |
| `/api/chart` | GET | Supabase `chart_data` (cron 사전계산) | 로그인 |
| `/api/quote/[ticker]` | GET | Supabase `bars_daily` (최신 2봉) | 로그인 |
| `/api/search` | GET | Supabase `tickers` (pg_trgm) | 로그인 |
| `/api/push/subscribe` | POST/DELETE | Supabase `push_subscriptions` | 로그인 |
| `/api/telegram/link-token` | GET/POST/DELETE | Supabase `telegram_link_tokens`, `users` | 로그인 |
| `/api/telegram/webhook` | POST | Telegram → Supabase `users`, `telegram_link_tokens` | webhook secret |
| `/api/telegram/consume` | POST | Supabase (link-token consume) | shared secret (legacy long-poll 용) |
| `/api/trade-log` | GET/POST/DELETE | Supabase `trade_log` | 로그인 |
| `/api/watchlist` | GET/POST/DELETE | Supabase `watchlist` | 로그인 |
| `/api/e2e-test/issue-session` | POST | Supabase `users` (테스트 유저 upsert) | E2E_TEST_TOKEN |

**모두 Supabase 또는 외부 API 직접.** FastAPI 호출 0건.

---

## 5. Next.js 페이지 별 데이터 source

| Page | 데이터 source | 캐싱 |
|---|---|---|
| `/login` | — (정적) | 정적 |
| `/dashboard` | Supabase `macro_state` | `revalidate = 60` (60초 ISR) |
| `/recommendations` | Supabase `scan_results` + `tickers` | `revalidate = 60` |
| `/themes` | Supabase `themes` + `theme_daily` | `revalidate = 60` |
| `/themes/[id]` | Supabase `theme_members` + `scan_results` + `tickers` | `revalidate = 60` |
| `/stocks` | (정적 검색 페이지) | 정적 |
| `/stocks/[ticker]` | Supabase `analyze_results` + `watchlist` (per-user) + 클라이언트 fetch (`/api/chart`, `/api/quote`, `StockContextTabs` 가 fetch) | `force-dynamic` (per-user) |
| `/watchlist` | Supabase `watchlist` (per-user) | `force-dynamic` |
| `/closing-trade` | Supabase `watchlist` + `scan_results` + `trade_log` (per-user) | `force-dynamic` |
| `/settings/alerts` | Supabase `alert_preferences` + `users` (per-user) | `force-dynamic` |
| `/admin/access` | Supabase `users` + `access_requests` (admin) | `force-dynamic` |
| `/pending` | Supabase `users` + `access_requests` (per-user) | `force-dynamic` |

---

## 6. 데이터 신선도 (사용자가 사이트에서 보는 데이터의 나이)

| 데이터 | 갱신 cron | 최악의 stale |
|---|---|---|
| `/dashboard` macro | daily-scan 16시 | 1일 |
| `/recommendations`, `/themes`, `/closing-trade` 신호 | daily-scan | 1일 |
| `/stocks/[ticker]` 차트 + 분석 (`chart_data`, `analyze_results`) | daily-scan | 1일 |
| `/stocks/[ticker]` 시세 (`/api/quote`) | daily-scan (bars_daily) | 1일 (실시간 X) |
| `/stocks/[ticker]` 뉴스 / 공시 | daily-scan | 1일 |
| `/stocks/[ticker]` 재무 / 팩터 (`financials_eval`, `factors_eval`) | weekly-fundamentals 토요일 | 7일. UI에 "마지막 갱신 ..." + 14일 초과시 경고 |
| `tickers` 마스터 (신규/폐지) | weekly-tickers-refresh 일요일 | 7일 |

**"신선도 표시"** 의미: 사이트 종목 상세 페이지의 재무/팩터 탭에 "마지막 갱신: YYYY-MM-DD" 작은 배지가 뜸. 14일 초과면 노란 경고 — cron 이 멈춘 걸 즉시 알 수 있게.

---

## 7. 인프라 / 환경변수 한눈에

| 어디 | 무엇 | 필요 환경변수 |
|---|---|---|
| **Vercel** (Next.js 사이트) | `web-next/` 빌드 | `AUTH_SECRET`, `AUTH_GOOGLE_ID/SECRET`, `ADMIN_EMAILS`, `NEXT_PUBLIC_SUPABASE_*`, `SUPABASE_SERVICE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `NEXT_PUBLIC_VAPID_PUBLIC_KEY` |
| **Supabase** | Postgres + Auth + RLS | (사용 측에서 만) |
| **GitHub Actions** | cron 실행 | `SUPABASE_*`, `FRED_API_KEY`, `DART_API_KEY`, `KIS_*`, `TELEGRAM_BOT_TOKEN`, `VAPID_*` |
| **Telegram BotFather** | 봇 토큰 + webhook URL 1회 등록 | (등록만, 환경변수 X) |

자세한 setup: [DEPLOY.md](DEPLOY.md).

---

## 8. 제거된 것들 (역사 — 코드에 없음)

- **FastAPI 백엔드** (`app/api/server.py`, `book_api.py`) — Phase 6에서 제거. 사이트는 Supabase 직접.
- **DuckDB 로컬 staging** (`data/pit.duckdb`, `app/data/pit_db.py`) — Phase 7 + 후속에서 제거. 모든 데이터 Supabase 단일 store.
- **ML 스택** (`app/model`, `app/features`, `app/backtest`, `app/cli`, `app/paper`, `app/train.py`) — 피봇 후 정리. Sharpe 추구 → 책 충실 도구로 전환.
- **24/7 텔레그램 봇 워커** (Render Worker, long-poll) — Telegram webhook으로 Vercel 안에 통합.
