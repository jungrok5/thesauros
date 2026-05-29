# Thesauros — agent rules

이 저장소에서 코드 작성/수정 시 **반드시** 지켜야 하는 규칙. 어겼다 발견되면 메모리에 negative feedback 으로 저장됨.

## 1. 구현 후 5단계 (절대 스킵 금지)

매 마일스톤(논리적 단위 작업) 완료 시:

1. **빌드 통과 확인** — Python: `python -m pytest app/book/tests/ app/db/tests/` / Web: `cd web-next && npx tsc --noEmit && npx eslint . && npx vitest run`
2. **회귀 테스트 추가** — 방금 구현한 동작에 대한 테스트 작성. 버그 픽스면 그 버그가 다시 들어오면 잡힐 테스트.
3. **전체 테스트 통과** — 새 테스트 + 기존 테스트 모두 green
4. **커밋 + 푸시** — `git push origin main`
5. **CI 통과 확인** — `gh run watch <id> --repo jungrok5/thesauros`

사용자가 "테스트 건너뛰어", "푸시 하지 마" 명시적으로 말한 경우만 일부 스킵 가능. 그 외엔 5단계 모두.

## 2. 모든 버그는 테스트로 차단

방금 잡은 버그는 **반드시** 같은 종류의 버그가 다시 들어오지 못하게 만드는 테스트가 추가돼야 한다. "고쳤다" 만으로 끝나면 다음 컴팩트에서 잊혀지고 재발한다.

테스트가 누적되어 **`테스트만 돌려도 기본 안정성이 확보`** 되는 수준이 목표.

대표 카테고리:
- **로직 버그**: synthetic 데이터로 단위 테스트 (`app/book/tests/test_pattern_invariants.py` 패턴)
- **데이터 가정 버그** (예: PostgREST 1000행 cap): 의존 가정을 명시적으로 테스트 (`web-next/src/__tests__/`)
- **UI/auth 흐름 버그** (예: callbackUrl 보존): Playwright E2E (`web-next/e2e/*.spec.ts`)
- **구성 충돌 버그** (예: middleware.ts vs proxy.ts): 정적 검사 스크립트 (`scripts/check-config.sh` 또는 CI step)

## 3. 측정 전/후 검증 (Python 분석)

```
Pre-flight  : PIT 안전성 · universe 시점성 · warmup/train/test 분리 · 거래비용 모델 · seed · cache hash
Post-flight : 합리성 · 일관성 · bias 5종 · bootstrap p · sub-period · sanity
```

자세히는 `~/.claude/projects/c--Project-finance/memory/feedback_test_verify_always.md` 참조.

## 4. 코드/UX 작성 원칙

- 책 정신: 매매는 안 할수록 좋고, 좋은 자리에서만. 시스템이 1.00 만점을 주는 종목 중 stale 패턴 (돌파 후 +30%↑) 은 진짜 매수 자리 아님 — UX 에서 명시.
- 정보를 점수 하나로 뭉개지 말고 (예: book_score 1.00) **다축으로 분해해서 노출** (추세 / 패턴 / 거래량 sub-score, 월/주/일 매트릭스, 신선도 chip).
- 모든 페이지 상단에 "한 줄 평" (BookVerdict 같은) — 사용자가 7개 섹션 종합 안 해도 의사 결정 가능.
- 패턴 운영: detector의 `entry` 필드는 completed 시 last_close 로 채워짐 → freshness 계산은 `extra.neckline` / `rim` / `ma_240` / `ma_value` 사용. `entry` fallback 금지.
- 한글 라벨: signal_type 의 raw snake_case (`pattern_double_bottom`) 절대 노출하지 말 것. `web-next/src/lib/signal-labels.ts` / Python `_SIGNAL_LABELS` 사용.

## 5. 알려진 함정 (피해야 할 패턴)

- **PostgREST 응답 cap**: Supabase 기본 1000행. `.in()` + `.order()` 만 쓰면 silently 잘림. 항상 `.limit()` 명시 + 필요한 데이터만 fetch.
- **Job-level `if: ${{ secrets.X != '' }}`**: GitHub Actions 이거 거부 → workflow 통째 0초 실패. step-level `if` 만 사용.
- **Next.js 16: `middleware.ts` → `proxy.ts`**: 둘 다 있으면 빌드 OOM. 항상 `web-next/src/proxy.ts` 만.
- **React 16 strict purity**: 컴포넌트 render 중 `Date.now()`, `Math.random()` 금지 — server-side에서 prop 으로 전달.
- **yfinance**: GH Actions Azure IP 차단 → US 티커 401/빈응답. Naver weekCandle/monthCandle 로 대체. 자세히 `~/.claude/projects/.../memory/project_us_yfinance_blocked.md`.
- **scan_results.signal_type 분포**: pattern_* 에 매수/매도 혼재 (쌍바닥 vs 이중천장). 필터 옵션 분리해야 사용자 혼동 없음.
- **Look-ahead via today snapshot**: 과거 트레이드를 today-snapshot 메트릭 (시총 / sector 분류 / shares) 으로 재랭킹/필터링하면 17년 백테스트가 +12pp CAGR 부풀려질 수 있음. L2 cap_q 가 정확히 이 함정에 빠짐 (2026-05-29 audit). 모든 ranking factor 는 PIT proxy 로 검증해야 production 으로 보낼 수 있음. 자세히 `~/.claude/projects/.../memory/project_l2_lookahead_audit.md`.

## 6. 메모리 활용

`~/.claude/projects/c--Project-finance/memory/` 에 누적된 feedback/project 메모리는 매 세션 시작 시 MEMORY.md 인덱스를 통해 자동 로드된다. 위 규칙은 그 중 가장 강한 것만 옮긴 것 — 새 메모리 추가 시 여기로도 옮길지 검토.

핵심 메모리:
- `feedback_work_cycle.md` — 위 §1 의 원본
- `feedback_test_verify_always.md` — 위 §3
- `feedback_proactive_followup.md` — 측정 시 누락된 차원 자동 점검
- `project_thesauros_deploy_state.md` — Vercel/Supabase/cron 운영 현황
- `project_weekly_pivot_phase2.md` — 일봉 폐기 → 주봉/월봉 전환의 배경
