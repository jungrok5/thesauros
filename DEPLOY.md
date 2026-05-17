# 배포 가이드

> **요약 (현재 아키텍처)**: Vercel (사이트) + Supabase (DB) +
> GitHub Actions (cron · 알림 발송) + Telegram webhook (Vercel 안에 통합) =
> 모두 무료 또는 무료 한도 안. **FastAPI 백엔드 / 24/7 봇 워커 모두 없습니다.**

## 컴포넌트 책임

| 컴포넌트 | 책임 | 어디서? |
|---|---|---|
| **GitHub Actions cron** | 매일 / 주간 발동 → scan_daily / publish_macro / publish_chart / weekly-fundamentals / weekly-tickers-refresh / telegram_worker(알림 발송) | GitHub Actions (필수) |
| **텔레그램 알림 발송** (`app/db/telegram_worker.py`) | scan_results 보고 사용자에게 메시지 push (아웃바운드) | 위 cron 안에서 1회 실행 |
| **텔레그램 봇 메시지 수신** (`/api/telegram/webhook`) | `/start` `/help` `/link <토큰>` 처리 (인바운드) | **Vercel route** — Telegram 이 webhook 으로 push, 별도 호스팅 X |
| **PWA 푸시 발송** | telegram_worker 가 텔레그램과 함께 호출 | 위 cron 안에서 한 번 |

알림 **발송** 과 봇 **수신** 모두 별도 24/7 프로세스 없이 동작합니다.

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
| `TELEGRAM_BOT_TOKEN` | BotFather 봇 토큰 | Production, Preview |
| `TELEGRAM_WEBHOOK_SECRET` | `openssl rand -hex 32` (Telegram setWebhook 시 같이 등록) | Production, Preview |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | VAPID public (PWA 푸시, 옵션) | Production, Preview |
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

- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `DATABASE_URL`, `SUPABASE_DB_PASSWORD`
- `FRED_API_KEY`, `DART_API_KEY`
- `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ENV` (`vts` or `real`)
- `TELEGRAM_BOT_TOKEN`
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`

활성화 후 `Actions` 탭에서 첫 실행 수동 트리거 (Run workflow) → 정상 동작 확인.

---

## 5. 텔레그램 봇 (Webhook)

봇이 사용자의 `/start`, `/link <토큰>`, `/help` 메시지를 받기 위해
**Telegram → Vercel webhook** 을 한 번 등록하면 끝입니다. 별도 호스팅 없음.

### 5.1 환경변수

| 변수 | 어디에 | 값 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Vercel + GitHub Actions | BotFather 발급 토큰 |
| `TELEGRAM_WEBHOOK_SECRET` | Vercel 만 | `openssl rand -hex 32` |

### 5.2 Telegram 에 webhook 등록 (한 번만)

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<your-vercel-domain>/api/telegram/webhook",
    "secret_token": "<TELEGRAM_WEBHOOK_SECRET>",
    "allowed_updates": ["message"]
  }'
```

`{"ok":true,...}` 응답이면 성공.

### 5.3 확인

1. `@your_bot` 에게 `/start` → 봇이 도움말 응답
2. 웹사이트 `/settings/alerts` → "토큰 발급" → 텔레그램에서 `/link <토큰>` →
   "✅ 연동 완료!" + `users.telegram_chat_id` 채워짐

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
| 텔레그램 `/link` 무반응 | Telegram setWebhook 안 했거나 `TELEGRAM_WEBHOOK_SECRET` 불일치. `curl .../getWebhookInfo` 로 확인 |
| 푸시 알림 켜기 실패 ("VAPID 키 미설정") | `NEXT_PUBLIC_VAPID_PUBLIC_KEY` 미설정 |

---

## 9. 비용 (현재 구성)

| 항목 | 무료 한도 | 현재 사용 (참고) |
|---|---|---|
| Vercel Hobby | 무제한 (개인 비상업) | OK |
| Supabase Free | DB 500MB | **622 MB — 한도 초과** (대부분 `bars_daily`). 옵션 §10 |
| Supabase Free | Auth 50,000 MAU + 무제한 API 요청 | OK |
| GitHub Actions | Public repo 무제한 / **Private repo 2,000분/월** | 측정 시 ~1,500분/월 — 빠듯하지만 가능 |
| Telegram Bot API | 30 msg/sec, webhook 무제한 | OK |
| Google OAuth | 무료 | OK |

**현 상태: Supabase 데이터 한도 초과 — 조치 필요 (§10).**

## 10. 데이터 다이어트 + Supabase Free→Pro→Free 사이클

`bars_daily` 가 비대 (5년 × 9.5K 종목 = ~1.7GB potential). 자유 한도 500MB
를 넘으면 **Supabase 가 DB 를 자동 read-only 모드로 잠궈서 모든 cron 이
멈춥니다**. 다음 절차로 한 번 정리:

### 10.1 Universe 축소 결정 (이미 적용됨, commit 51d8a56)

cron 명령:
```
python -m app.db.scan_daily --markets KOSPI KOSDAQ NASDAQ NYSE \
  --sp500-only --years 2
```
- KR 전체 (KOSPI 923 + KOSDAQ 1,778) + 미국 S&P 500 = 약 3,200 종목
- 2년치 일봉 ≈ 230MB
- US 중소형주는 cron 대상에서 제외 (사이트엔 "분석 데이터 없음" 표시)
- 책의 240주 MA (=4.6년) 는 일부 종목에서 제한 → 144주 MA 로 대체

### 10.2 한 번에 정리 (read-only 모드라면 먼저 Pro 업그레이드 필요)

DB 가 이미 read-only 면 Supabase Dashboard → Project Settings → Plan →
**Pro 로 임시 업그레이드** ($25/월. 일할 계산되어 며칠만 쓰고 다운그레이드
하면 일부만 청구). 그 다음:

```cmd
python -m scripts.cleanup_after_pro --execute
```

이 스크립트가 다음을 순차 실행:
1. `DELETE FROM bars_daily WHERE bar_date < CURRENT_DATE - INTERVAL '2 years'`
2. `DELETE FROM bars_daily WHERE ticker NOT IN (KR 전체 + S&P 500)`
3. `VACUUM FULL bars_daily` (디스크 실제 회수)
4. 최종 사이즈 출력

500MB 이하면 Pro → Free 다운그레이드 안전. 사이즈 측정:
```python
python -c "from app.db import get_conn; ..."
```
또는 Supabase dashboard → Database → Reports.

### 10.3 다른 옵션

| 옵션 | 효과 | 비용 |
|---|---|---|
| **A. 위 절차 (Pro 1개월 + 정리 + Free 복귀)** | 영구적, 한 번만 | $25 1회 |
| B. Supabase Pro 유지 | 8GB DB, auto-pause 없음 | $25/월 |
| C. Neon Postgres (3GB) | 새 무료 한도, DSN 교체 | $0 |

---

## 11. GitHub Actions billing / Public 전환

Private repo 는 GitHub Actions 무료 2,000분/월. 우리 측정 ~1,500분/월
필요라 빠듯하고, 결제 실패 시 즉시 cron 정지:
> "The job was not started because recent account payments have failed
> or your spending limit needs to be increased."

해결책:
- **Settings → Billing & plans** 에서 결제 수단 갱신
- 또는 **repo 를 Public 전환** (Actions 무제한)

### Public 전환 안전성 (이미 확인)

- `.env`, `.env.local` 모두 `.gitignore` 됨 ✅
- git history 에 hardcoded secret 패턴 0건 ✅
- tracked 파일 중 `.env.example` (placeholder 만) ✅
- 코드 안 `eyJ...` 같은 JWT/key 0건 ✅

→ 안전하게 public 전환 가능. **Repo Settings → Danger Zone → Change visibility**.

### 12. 로컬 cron (billing 풀리기 전 임시)

PC 가 켜져있는 동안 매일 한 번 실행:

```cmd
run-cron-daily.bat
```

5개 step (scan_daily / publish_macro / ingest_themes / investor_flow /
telegram_worker) 을 GitHub Actions cron 과 동일한 순서로 실행. 작업
스케줄러 (Windows) 에 등록하면 자동화 가능 — 매일 16:30 KST trigger.
