# Supabase Migrations

> Supabase 무료 티어는 1주일 비활성 시 일시정지됩니다.
> 모든 DDL/seed 를 SQL 파일로 보관해 언제든 재구축 가능하도록 유지합니다.

## 적용 방법

### 1. 자동 (권장)
```powershell
.\.venv\Scripts\python.exe -m app.db.migrate up
```
- `migrations/*.sql` 을 순서대로 적용
- `_migrations` 테이블에 적용 이력 기록 → 같은 파일 중복 실행 안 됨

### 2. 수동 (Supabase Dashboard)
- SQL Editor 열기 → 파일 내용 복사 → Run

## 명령

```powershell
# 새 마이그레이션 적용
python -m app.db.migrate up

# 적용 이력 조회
python -m app.db.migrate status

# 처음부터 재구축 (모든 테이블 DROP 후 재적용)
python -m app.db.migrate reset --confirm

# 특정 파일까지만 적용
python -m app.db.migrate up --target 003_seeds.sql
```

## 파일 명명 규칙

`NNN_short_description.sql`
- `001_initial_schema.sql` — 기본 13개 테이블
- `002_rls_policies.sql`   — RLS 정책
- `003_indexes.sql`        — 인덱스
- `004_seeds_tickers.sql`  — 초기 ticker 마스터

## 비활성 일시정지 대응

Supabase 무료 프로젝트가 일시정지되면:
1. Dashboard 에서 **Restore project** 클릭 (몇 분 대기)
2. 데이터/스키마 모두 보존되어 있으면 바로 사용 가능
3. 프로젝트 삭제됐다면:
   - 새 프로젝트 생성
   - `.env` 의 `SUPABASE_URL`, `SUPABASE_DB_PASSWORD`, 키들 갱신
   - `python -m app.db.migrate up` → 자동 재구축
   - `python -m app.db.seed tickers` → ticker 마스터 재적재
   - daily scan 재실행
