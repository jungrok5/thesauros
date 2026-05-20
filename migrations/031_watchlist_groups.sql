-- 031 — watchlist groups: 사용자 정의 관심 그룹
--
-- 사용자 피드백 (2026-05-20): 관심 종목이 하나의 큰 리스트로만 보임.
-- "AI 테마 / 조선 테마 / 장기 관심 / 단기 관심" 같이 분류하고 싶음.
--
-- 디자인:
--   - 새 테이블 watchlist_groups (user_id, name, color, order_index)
--   - watchlist.group_id 추가 (nullable — NULL 이면 "기본" 그룹)
--   - category='holding' (보유) 은 그대로 — 그룹과 직교 (보유 종목은 자기
--     own 섹션 + 그룹별 섹션 두 곳 다 그룹화 가능)
--   - 그룹 삭제 시 group_id ON DELETE SET NULL — 종목 자체는 안 잃어버림

CREATE TABLE IF NOT EXISTS watchlist_groups (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- 사용자 라벨. 50자 — 한글 25자 정도 충분.
    name         VARCHAR(50) NOT NULL,
    -- Badge 색상 (Tailwind 토큰 이름). NULL = 기본 회색.
    -- emerald / sky / amber / violet / rose / zinc 6 옵션 UI 제공.
    color        VARCHAR(20),
    -- 화면 정렬 순서. 작은 값 = 위쪽.
    order_index  INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 같은 user 내 동일 이름 금지 (UPSERT 도 이름 충돌 방지).
    UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_groups_user
    ON watchlist_groups (user_id, order_index);

ALTER TABLE watchlist_groups ENABLE ROW LEVEL SECURITY;

-- watchlist 에 group_id 추가. ON DELETE SET NULL = 그룹 삭제해도
-- watchlist row 보존. NULL group_id 는 "분류 안 함" 으로 UI 에서 따로 섹션.
ALTER TABLE watchlist
    ADD COLUMN IF NOT EXISTS group_id BIGINT
        REFERENCES watchlist_groups(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_watchlist_group_id
    ON watchlist (user_id, group_id);
