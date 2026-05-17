# Thesauros

> 마태복음 6:20 — "보물을 하늘에 쌓아 두라(θησαυρός)."

저자 『추세추종 매매 룰』(출판사, 2026)의 룰을
**그대로 자동화한** 개인용 매매 결정 도구. 매일 16시 (KST) 자동 스캔
→ 텔레그램 + 웹 푸시 알림.

> 이 프로젝트는 한때 LightGBM 멀티팩터 백테스트(ML alpha 추구)로 시작했지만,
> Phase 5b 검증에서 측정된 alpha 가 거의 전부 survivorship bias + naive cost
> 였음이 드러나 — **책 충실한 매매 의사결정 도구로 피봇**했습니다.
> 그 이전 페이즈의 ML/백테스트 코드와 실험 결과는 git history 에만 남아
> 있습니다 (`git log --before 2026-05-17`).

---

## 아키텍처

```
GitHub Actions (cron, 매일 16시 KST)
  ├─ app.db.scan_daily        ─►  scan_results + analyze_results + chart_data
  ├─ app.db.publish_macro     ─►  macro_state
  ├─ app.db.ingest_themes     ─►  themes / theme_daily / theme_members
  ├─ app.db.ingest_investor_flow ─► investor_flow (KIS)
  ├─ app.db.seed_tickers      ─►  tickers master (KOSPI/KOSDAQ/US 9,570종)
  └─ app.db.telegram_worker   ─►  alerts (텔레그램 + 웹 푸시)

                          ┌────► Supabase Postgres (single source of truth)
                          │
Next.js 16 (Vercel)  ─────┼────► NextAuth (Google OAuth)
  - Server Components 가  │
    Supabase 직접 조회    └────► (FastAPI 없음)

Render Worker (long-poll, 선택)
  └─ app.db.telegram_bot      ─►  사용자 셀프 연동 (/link <token>)
```

| 컴포넌트 | 위치 |
|---|---|
| Next.js 사이트 | `web-next/` — App Router, Auth.js v5, Tailwind v4 |
| Supabase 마이그레이션 | `migrations/*.sql` — 한 번에 적용은 `python -m app.db.migrate up` |
| Python cron 작업 | `app/db/` (Supabase 통신) + `app/book/` (책 룰) + `app/data/` (KIS·KRX·DART 수집) + `app/macro/` (FRED) |
| 책 본문 / 차트 분석 | `book_images/` |
| E2E 테스트 | `web-next/e2e/` — Playwright |

---

## 핵심 페이지

| URL | 내용 |
|---|---|
| `/dashboard` | 거시 지표 25개 + 시장 레짐 (publish_macro 가 매일 발행) |
| `/recommendations` | 책 룰 통과 종목 (scan_results 의 action=BUY/STRONG_BUY) |
| `/themes` / `/themes/[id]` | 테마별 종목 + 1D/1M 변화 + 멤버 신호 |
| `/stocks/[ticker]` | 차트(MA + 패턴 + 4등분선) + 책 분석 + 뉴스/공시/펀더멘털 탭 |
| `/watchlist` | 관심·보유 종목 + 목표가/손절가 인라인 편집, 도달 시 자동 알림 |
| `/closing-trade` | 종가매매 모드 — 보유 종목 10MA 신호등 + 매매 일지 |
| `/settings/alerts` | 텔레그램 연동 (1회용 토큰), 웹 푸시 구독, 알림 종류 토글 |
| `/admin/access` | 관리자 전용 — 새 사용자 승인/반려 |
| `/pending` | 미승인 사용자 랜딩 — 사용 요청 사유 입력 |

---

## 로컬 개발

```cmd
:: 첫 설치
install.bat
cd web-next && npm install && cd ..

:: 마이그레이션 (Supabase)
python -m app.db.migrate up

:: 전체 dev 스택 (프런트 + 텔레그램 봇, 백엔드 없음)
run-all.bat

:: 또는 개별
run-frontend.bat        :: Next.js 만 (포트 3000)
run-bot.bat             :: telegram_bot.py long-poll
```

### 필수 환경변수

`web-next/.env.local`:
- `AUTH_SECRET` — `openssl rand -base64 32`
- `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET` — Google Cloud Console
- `ADMIN_EMAILS` — 관리자 이메일 (콤마구분, 첫 로그인 시 auto-approve + role=admin)
- `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`
- `TELEGRAM_LINK_SECRET` — 봇 ↔ 웹 인증용 공유 비밀
- `NEXT_PUBLIC_VAPID_PUBLIC_KEY` — 웹 푸시 (옵션, 없으면 PWA 구독 UI 가 안내만)

`.env` (Python cron / bot):
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` 같은 DB 접속
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_LINK_SECRET`, `WEB_BASE_URL`
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`
- `FRED_API_KEY`, `DART_API_KEY`
- `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ENV` (`real|vts`)

VAPID 키 생성: `python -m app.db.vapid_keys`

---

## E2E

```cmd
cd web-next
:: 인증 안 한 페이지만
npm run test:e2e:public

:: 전체 (E2E_TEST_TOKEN 필요, .env.local 에 설정됨)
npx playwright test
```

현재 통과: **26 / 26** (access-control, hydration, mobile-nav, dashboard-supabase,
authed-watchlist, public, book-site).

---

## 배포

- **Web (Next.js)** → Vercel. Root Directory `web-next`. env 변수 위 목록 그대로
- **Telegram bot worker** → Render Free Worker (`python -m app.db.telegram_bot`),
  또는 본인 PC `run-bot.bat`
- **Daily cron** → GitHub Actions (`.github/workflows/*.yml`)
- **DB** → Supabase (Seoul ap-northeast-2 pooler)

자세한 가이드: [DEPLOY.md](DEPLOY.md)

---

## 면책

학습/연구 도구입니다. 실거래 결과를 보장하지 않습니다.
모든 매매 판단과 손익은 본인 책임입니다.
자동매매는 의도적으로 미구현입니다.
