# 배포 가이드

> **요약**: Vercel (Next.js) + Supabase (Postgres) + GitHub Actions (cron) +
> 선택적으로 Render Worker (텔레그램 봇). FastAPI 서버는 없습니다.

---

## 0. 사전 준비

| 서비스 | 무엇 |
|---|---|
| **Vercel** | https://vercel.com — Next.js 호스팅 (Hobby 무료) |
| **Supabase** | https://supabase.com — Postgres (무료 500MB) |
| **GitHub** | 이 repo 가 푸시되어 있어야 함 |
| **Google Cloud Console** | OAuth 2.0 클라이언트 (무료) |
| **Telegram BotFather** | (선택) 봇 토큰 — @candle_trend_bot 같은 봇 1개 생성 |
| **Render** | (선택) 텔레그램 봇 워커 호스팅 — 무료 Worker |

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

## 4. GitHub Actions cron

`.github/workflows/` 안에 이미 정의되어 있습니다. Repository 의 Settings → Secrets and variables → Actions 에 다음 환경변수 추가:

- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `DATABASE_URL`
- `FRED_API_KEY`, `DART_API_KEY`
- `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ENV`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_LINK_SECRET`
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`

워크플로 활성화 후 `Actions` 탭에서 첫 실행을 수동으로 트리거 (워크플로 페이지 → Run workflow) 해서 정상 동작 확인.

---

## 5. (선택) 텔레그램 봇 워커

사용자 셀프 연동 (`/link <token>`) 을 처리하려면 long-poll 워커가 24/7 떠 있어야 합니다.

### 옵션 A: Render Free Worker

1. render.com → New → Background Worker → GitHub repo 연결
2. **Root Directory**: 빈 값 (repo root)
3. **Runtime**: Python 3.x
4. **Build command**: `pip install -r requirements.txt`
5. **Start command**: `python -m app.db.telegram_bot --verbose`
6. Environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_LINK_SECRET` (Vercel 과 동일 값)
   - `WEB_BASE_URL=https://<your-vercel-domain>` (consume endpoint 호출용)

### 옵션 B: 본인 PC

```cmd
run-bot.bat
```

PC 가 꺼지면 자동 연동도 멈추지만, 이미 연동된 계정의 알림 발송은 영향 없습니다.

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
| Render Worker | 750시간/월 (24h × 31일 = 744h, 빠듯하지만 가능) |
| Google OAuth | 무료 |
| Telegram Bot API | 무료 (rate limit 30 msg/sec) |

**총 운영비: $0** (현재 사용량 기준)
