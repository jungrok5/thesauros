# Thesauros

> 마태복음 6:20 — "보물을 하늘에 쌓아 두라(θησαυρός)."

추세추종 매매 룰 기반 자동 스캐너 + 매매 결정 보조 도구.
매일 16시 (KST) 자동 스캔 → 텔레그램 + 웹 푸시 알림.

---

## 아키텍처

```
GitHub Actions (cron)
  ├─ daily-scan.yml (16시 KST, Mon-Fri)
  │    ├─ scan_daily      ─► scan_results + analyze_results + chart_data
  │    ├─ publish_macro   ─► macro_state + macro_series (FRED/yfinance)
  │    ├─ ingest_themes   ─► themes / theme_daily / theme_members
  │    ├─ ingest_news     ─► news / disclosures
  │    ├─ ingest_investor_flow ─► investor_flow (KIS)
  │    └─ telegram_worker ─► alerts (Telegram + Web Push)
  ├─ weekly-tickers-refresh.yml (일 10시) ─► tickers (신규/폐지 마킹)
  ├─ weekly-fundamentals.yml (토 11시)    ─► fundamentals + financials/factors_eval
  └─ keepalive.yml (매일 10:30)           ─► Supabase ping

                          ┌────► Supabase Postgres (단일 store)
Next.js 16 (Vercel)  ─────┼────► Google OAuth
  - Server Components 가  └────► Telegram webhook (/api/telegram/webhook)
    Supabase 직접 조회
```

전체 데이터 흐름 / 외부 API 매핑 / 페이지별 source: [ARCHITECTURE.md](ARCHITECTURE.md)
배포 가이드: [DEPLOY.md](DEPLOY.md)

| 컴포넌트 | 위치 |
|---|---|
| Next.js 사이트 | `web-next/` — App Router, Auth.js v5, Tailwind v4 |
| Supabase 마이그레이션 | `migrations/*.sql` (`python -m app.db.migrate up`) |
| Python cron | `app/db/` (Supabase 통신) + `app/book/` (룰) + `app/data/` (KIS·KRX·DART) + `app/macro/` (FRED) |
| E2E | `web-next/e2e/` — Playwright |

---

## 핵심 페이지

| URL | 내용 |
|---|---|
| `/dashboard` | 거시 지표 + 시장 레짐 |
| `/recommendations` | 책 룰 통과 종목 |
| `/themes` / `/themes/[id]` | 테마별 종목 + 변동률 + 멤버 신호 |
| `/stocks/[ticker]` | 차트(MA + 패턴 + 4등분선) + 분석 + 뉴스/공시/펀더멘털 |
| `/watchlist` | 관심·보유 종목 + 목표가/손절가 인라인 편집 |
| `/closing-trade` | 종가매매 모드 — 보유 종목 10MA 신호등 + 매매 일지 |
| `/settings/alerts` | 텔레그램 연동 + PWA 푸시 + 알림 종류 토글 |
| `/admin/access` | 관리자 — 새 사용자 승인/반려 |
| `/pending` | 미승인 사용자 — 사용 요청 사유 입력 |

---

## 로컬 개발

```cmd
:: 첫 설치
install.bat
cd web-next && npm install && cd ..

:: 마이그레이션
python -m app.db.migrate up

:: 프런트 + 봇 (백엔드 없음)
run-all.bat

:: 개별
run-frontend.bat        :: Next.js (:3000)
run-bot.bat             :: 텔레그램 long-poll (dev 전용)
run-cron-daily.bat      :: GH Actions 동등 cron 로컬 실행
```

### 환경변수

**`web-next/.env.local`**
- `AUTH_SECRET`, `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`
- `ADMIN_EMAILS` (콤마구분, 첫 로그인 시 auto-approve + role=admin)
- `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`
- `NEXT_PUBLIC_VAPID_PUBLIC_KEY` (옵션)

**`.env`** (Python cron / bot)
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_PASSWORD`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`
- `FRED_API_KEY`, `DART_API_KEY`
- `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ENV` (`real`|`vts`)

VAPID 키 생성: `python -m app.db.vapid_keys`

---

## 테스트

```cmd
cd web-next
npx playwright test              :: 전체 (E2E_TEST_TOKEN 필요)
npm run test:e2e:public          :: 인증 없이도 OK
```

---

## 면책

학습/연구 도구입니다. 실거래 결과를 보장하지 않습니다.
모든 매매 판단과 손익은 본인 책임입니다. 자동매매는 의도적으로 미구현.
