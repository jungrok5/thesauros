# 배포 가이드

> **요약**: Vercel (사이트) + Supabase (DB) + GitHub Actions (cron · 알림 발송)
> = 필수 4종. **텔레그램 봇 long-poll 워커는 새 사용자 셀프 연동이 필요할 때만**
> 추가로 호스팅합니다 (옵션). FastAPI 백엔드는 없습니다.

## 컴포넌트 책임 (헷갈리기 쉬운 부분)

| 컴포넌트 | 책임 | 동작 | 어디서? |
|---|---|---|---|
| **GitHub Actions cron** | 매일 16시 KST 발동 → scan_daily / publish_macro / publish_chart / **telegram_worker (알림 발송)** 순차 실행 | 매번 짧게 (수 분), 끝나면 종료 | GitHub Actions (필수) |
| **텔레그램 알림 발송** (`telegram_worker.py`) | scan_results 보고 사용자에게 텔레그램 메시지 push (아웃바운드) | cron 안에서 1회 실행 | 위 GitHub Actions 가 호출 |
| **텔레그램 봇 워커** (`telegram_bot.py`) | 사용자가 봇에게 보낸 `/link <토큰>` 같은 메시지 수신 (인바운드, long-poll) | 25초 timeout 으로 무한 반복 → 24/7 떠 있어야 함 | Render Worker / 본인 PC / 다른 long-running 호스트 |
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
| **Render Worker** | https://render.com 무료 Worker — 봇 long-poll | **새 사용자 셀프 연동을 받을 때만** (자세히는 §5) |

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

## 5. 텔레그램 봇 long-poll 워커

> **언제 필요한가:**
> - ✅ **필요함**: 새 사용자가 사이트에서 `/settings/alerts → 토큰 발급` 누른 다음
>   본인 텔레그램에서 `/link <토큰>` 보내서 자동 연동시키려면.
> - ❌ **불필요**: 본인만 쓰거나, 새 사용자의 `chat_id` 를 본인이 직접 DB 에
>   `UPDATE users SET telegram_chat_id='...' WHERE email='...'` 로 넣어줄 거면.
>   알림 발송은 GitHub Actions cron 이 다 합니다.

GitHub Actions 로는 할 수 없습니다 — long-poll 은 25초 timeout 으로 무한 반복하는
24/7 프로세스이고, GH Actions 의 잡 수명/quota 모델과 안 맞습니다.

### 옵션 A: Render Free Worker (클라우드)

1. render.com → New → Background Worker → GitHub repo 연결
2. **Root Directory**: 빈 값 (repo root)
3. **Runtime**: Python 3.x
4. **Build command**: `pip install -r requirements.txt`
5. **Start command**: `python -m app.db.telegram_bot --verbose`
6. Environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_LINK_SECRET` (Vercel 의 값과 동일해야 함)
   - `WEB_BASE_URL=https://<your-vercel-domain>` (consume endpoint 호출용)

무료 750h/월 — 한 달 720h 라서 충분.

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
| Render Worker | (셀프 연동 쓸 때만) 750시간/월 — 24h×31=744h 라 1워커는 가능 |
| Google OAuth | 무료 |
| Telegram Bot API | 무료 (rate limit 30 msg/sec) |

**총 운영비: $0** (현재 사용량 기준)
