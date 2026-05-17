# 배포 가이드

> **요약**: Vercel (사이트) + Supabase (DB) + GitHub Actions (cron · 알림 발송)
> = 필수 4종. **텔레그램 봇 long-poll 워커는 새 사용자 셀프 연동이 필요할 때만**
> 추가로 호스팅합니다 (옵션). FastAPI 백엔드는 없습니다.

## 컴포넌트 책임 (헷갈리기 쉬운 부분)

| 컴포넌트 | 책임 | 동작 | 어디서? |
|---|---|---|---|
| **GitHub Actions cron** | 매일 16시 KST 발동 → scan_daily / publish_macro / publish_chart / **telegram_worker (알림 발송)** 순차 실행 | 매번 짧게 (수 분), 끝나면 종료 | GitHub Actions (필수) |
| **텔레그램 알림 발송** (`telegram_worker.py`) | scan_results 보고 사용자에게 텔레그램 메시지 push (아웃바운드) | cron 안에서 1회 실행 | 위 GitHub Actions 가 호출 |
| **텔레그램 봇 메시지 수신** (`/api/telegram/webhook`) | 사용자가 봇에게 보낸 `/link <토큰>` 같은 메시지 수신 (인바운드) | Telegram → Vercel route 로 push (webhook 방식) | Vercel 안에 통합 — 별도 호스팅 X |
| **PWA 푸시 발송** | telegram_worker 가 텔레그램과 함께 호출 | cron 안에서 한 번 | 위 GitHub Actions |

핵심: 알림 **발송** 은 GitHub Actions 만으로 됩니다. 봇 **수신** (사용자 셀프 연동
용) 은 long-poll 이라 GitHub Actions 로 안 됩니다 — 별도 호스팅 필요.

## 0. 사전 준비

| 서비스 | 무엇 | 필수 여부 |
|---|---|---|
| **Vercel** | https://vercel.com — Next.js 호스팅 (Hobby 무료) | 필수 |
| **Supabase** | https://supabase.com — Postgres (무료 500MB) | 필수 |
| **GitHub Actions** | repo 의 `.github/workflows/*.yml` cron (Public repo 무제한) | 필수 — 사이트의 데이터/알림 발동기 |
| **Google Cloud Console** | OAuth 2.0 클라이언트 (무료) | 필수 (로그인) |
| **Telegram BotFather** | 봇 토큰 — `@candle_trend_bot` 같은 봇 1개 | 텔레그램 알림 원하면 필수 |

---

## 1. Supabase

### 1.1 프로젝트 생성

1. supabase.com → New project
2. **Region: Northeast Asia (ap-northeast-2, Seoul)** — 한국 사용자 latency
3. DB password 안전한 곳에 저장
4. Project 생성 후 `Settings → API`:
   - **Project URL** → `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`
   - **anon public** → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - **service_role secret** → `SUPABASE_SERVICE_KEY` (서버 전용, 브라우저 X)

### 1.2 마이그레이션 적용

로컬에서:
```cmd
:: .env 에 SUPABASE_URL + SUPABASE_SERVICE_KEY 또는 DATABASE_URL 설정 후
python -m app.db.migrate up
```

`migrations/001 ~ 012` 모두 적용됩니다.

### 1.3 첫 데이터 적재 (옵션 — cron 이 알아서 채우긴 함)

```cmd
python -m app.db.seed_tickers --markets kospi kosdaq us
python -m app.db.publish_macro
python -m app.db.scan_daily --markets KOSPI KOSDAQ NASDAQ --years 5
```

---

## 2. Google OAuth

1. console.cloud.google.com → 프로젝트 생성
2. `APIs & Services → Credentials → Create credentials → OAuth client ID`
3. Application type: **Web application**
4. Authorized JavaScript origins: `https://<your-vercel-domain>` (배포 후 추가 가능)
5. Authorized redirect URIs:
   - `http://localhost:3000/api/auth/callback/google` (dev)
   - `https://<your-vercel-domain>/api/auth/callback/google` (prod)
6. Client ID / Secret 저장 → `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`

> **주의**: Vercel 배포 후 production 도메인을 redirect URI 에 반드시 추가해야
> 로그인이 됩니다. 그렇지 않으면 `redirect_uri_mismatch` 에러가 납니다.

---

## 3. Vercel

### 3.1 프로젝트 import

1. vercel.com → Add New → Project → GitHub 에서 `thesauros` 선택
2. **Root Directory** 를 반드시 **`web-next`** 로 변경 (기본값은 repo root, 잘못됨)
3. Framework: Next.js (자동 감지)
4. Build/Install Command 는 [`vercel.json`](web-next/vercel.json) 에서 지정됨

### 3.2 환경변수 설정 (Settings → Environment Variables)

| 변수 | 값 | 환경 |
|---|---|---|
| `AUTH_SECRET` | `openssl rand -base64 32` | Production, Preview |
| `AUTH_GOOGLE_ID` | Google Cloud OAuth Client ID | Production, Preview |
| `AUTH_GOOGLE_SECRET` | Google Cloud OAuth Client Secret | Production, Preview |
| `ADMIN_EMAILS` | `you@gmail.com` (콤마구분) | Production, Preview |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase Project URL | Production, Preview |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key | Production, Preview |
| `SUPABASE_SERVICE_KEY` | Supabase service_role key | Production, Preview |
| `TELEGRAM_LINK_SECRET` | 32+ bytes hex (web ↔ bot 공유) | Production, Preview |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | VAPID public (옵션) | Production, Preview |
| `E2E_TEST_TOKEN` | **설정하지 말 것** (dev 전용) | — |

### 3.3 첫 배포

Vercel 이 자동으로 빌드 → 배포. 5분 이내 `https://thesauros.vercel.app` 같은 URL 발급.

### 3.4 첫 로그인

1. 본인 이메일이 `ADMIN_EMAILS` 에 있는지 확인 (없으면 일반 사용자로 가입됨)
2. 사이트 접속 → Google 로그인
3. `users` 테이블에 자동으로 row 생성, `role=admin`, `access_status=approved` (env 매칭 시)
4. `/dashboard` 로 이동되면 성공
5. 다른 사용자가 가입하면 `/pending` 으로 안내됨 → `/admin/access` 에서 본인이 승인

---

## 4. GitHub Actions cron (필수)

> **이게 사이트의 발동기입니다.** 매일 16시 KST 에 워크플로가 발동되어
> 모든 데이터 갱신과 **텔레그램/푸시 알림 발송**이 이 안에서 일어납니다.
> 봇 워커 없이도 알림은 여기서 다 보내집니다.

`.github/workflows/` 에 이미 정의됨. Repository → Settings → Secrets and
variables → Actions 에 다음 환경변수 추가:

- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `DATABASE_URL`
- `FRED_API_KEY`, `DART_API_KEY`
- `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ENV`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_LINK_SECRET`
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`

활성화 후 `Actions` 탭에서 첫 실행 수동 트리거 (Run workflow) → 정상 동작 확인.

---

## 5. 텔레그램 봇 — Webhook (권장, 추가 호스팅 불필요)

> 봇이 사용자 메시지를 받는 방식 두 가지:
> - **Webhook (권장)**: 텔레그램이 메시지를 우리 Vercel 의 `/api/telegram/webhook`
>   으로 POST. **별도 호스팅 0**.
> - **Long-poll (레거시)**: `app/db/telegram_bot.py` 가 24/7 떠서 폴링. 별도
>   호스팅 필요 (Render Worker / 본인 PC). 새 배포에서는 안 씁니다.

### 5.1 환경변수 추가

| 변수 | 어디에 | 값 |
|---|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | **Vercel 만** | `openssl rand -hex 32` (32 hex chars) |
| `TELEGRAM_BOT_TOKEN` | Vercel + GitHub Actions | BotFather 의 봇 토큰 |
| `TELEGRAM_LINK_SECRET` | (long-poll 안 쓰면 불필요) | 레거시 |

### 5.2 Telegram 에 webhook 등록 (한 번만)

다음 cURL 을 본인 PC 에서 실행. `<BOT_TOKEN>` 과 `<SECRET>` 자리에 위에서 생성한
값을 넣으세요.

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<your-vercel-domain>/api/telegram/webhook",
    "secret_token": "<SECRET>",
    "allowed_updates": ["message"]
  }'
```

응답이 `{"ok":true,"result":true,"description":"Webhook was set"}` 이면 끝.

### 5.3 확인

1. 텔레그램에서 `@your_bot` 에게 `/start` 보내기 → 봇이 도움말 응답하면 성공
2. 웹사이트 `/settings/alerts` → "토큰 발급" → 텔레그램에서 `/link <토큰>` →
   "✅ 연동 완료!" 응답 + DB `users.telegram_chat_id` 채워짐 확인

### 5.4 (참고) Long-poll 봇으로 돌아가야 할 때

Webhook 은 외부에서 접근 가능한 HTTPS URL 이 필수입니다. 로컬 개발 (Vercel 배포
전) 에서 봇을 시험해보려면 long-poll 이 편합니다:

```cmd
:: 로컬 dev 전용
run-bot.bat
```

(`app/db/telegram_bot.py` 는 dev 편의용으로 유지됩니다. 프로덕션 배포에는 위
webhook 만 쓰세요.)

---

## 6. VAPID 키 (웹 푸시)

```cmd
python -m app.db.vapid_keys
```

두 줄 출력 — `VAPID_PUBLIC_KEY=...`, `VAPID_PRIVATE_KEY=...` 를:
- Vercel: `NEXT_PUBLIC_VAPID_PUBLIC_KEY` (브라우저용)
- GitHub Actions / Render Worker: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL=mailto:you@gmail.com`

키 생성은 일회성. 한 번 발급된 키는 재발급 시 모든 기존 구독자가 끊어집니다.

---

## 7. 첫 배포 후 체크리스트

- [ ] Vercel 빌드 성공 (`Building`, `Generating static pages`, `Deploying`)
- [ ] `https://your-domain.vercel.app/login` 접속 → Google 버튼 보임
- [ ] Google 로그인 → `/dashboard` 도달 + macro 데이터 표시
- [ ] (관리자) `/admin/access` 메뉴 보임
- [ ] (관리자 아닌 본인) `/pending` 으로 라우팅 + 요청 폼 동작
- [ ] `/stocks/AAPL` → 차트 + 분석 표시 (cron 이 적어도 1회 돌았다면)
- [ ] GitHub Actions `scan_daily` 워크플로 수동 실행 → DB 에 `analyze_results` row 생성
- [ ] 텔레그램 `/link <token>` 으로 본인 계정 연동 → `users.telegram_chat_id` 채워짐
- [ ] PWA 푸시 구독 (`/settings/alerts` → `푸시 알림 켜기`) → `push_subscriptions` row 생성

---

## 8. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| Vercel 빌드 실패: `next: command not found` | Root Directory 가 `web-next` 가 아님 |
| `redirect_uri_mismatch` (Google 로그인) | Google Cloud Console 에서 Vercel 도메인을 redirect URI 에 추가 |
| `/api/auth/...` 가 500 | `AUTH_SECRET` 미설정 |
| Dashboard 가 "거시 데이터 없음" | `python -m app.db.publish_macro` 한 번도 안 돌았음 — cron 수동 실행 |
| `/stocks/[ticker]` 가 "분석 데이터 없음" | 그 종목이 아직 `scan_daily` 에 포함 안 됨 — `--tickers <T>` 로 수동 실행 |
| 텔레그램 `/link` 가 "❌ 봇 인증 실패" | Vercel 과 Render Worker 의 `TELEGRAM_LINK_SECRET` 이 다름 |
| 푸시 알림 켜기 실패 ("VAPID 키 미설정") | `NEXT_PUBLIC_VAPID_PUBLIC_KEY` 미설정 |

---

## 9. 비용 (현재 구성)

| 항목 | 무료 |
|---|---|
| Vercel Hobby | 무제한 (개인 비상업) |
| Supabase Free | DB 500MB / Auth 50,000 MAU / 50K Edge calls |
| GitHub Actions | Public repo 무제한 / Private 2,000분/월 |
| Telegram Bot API | 무료 (rate limit 30 msg/sec), webhook 으로 Vercel 안에 통합 |
| Google OAuth | 무료 |
| Telegram Bot API | 무료 (rate limit 30 msg/sec) |

**총 운영비: $0** (현재 사용량 기준)
