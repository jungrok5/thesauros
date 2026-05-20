-- 030 — disclosure alerts: per-user toggle + dedupe state
--
-- 사용자 watchlist 종목에 새 공시가 올라오면 텔레그램 푸시. 기존 alerts
-- 테이블 + telegram_worker 인프라 재사용. 두 가지만 새로 만든다:
--
--   1. alert_preferences.enable_disclosure — 사용자별 on/off 토글
--   2. disclosure_alert_seen — (user_id, rcept_no) 이미 알림 보낸
--      공시는 다시 안 보냄. alerts 테이블만으로는 같은 공시 type 이
--      여러 종목에 걸쳐 발생할 때 충돌 가능. PK 강제로 멱등.
--
-- 알림 흐름 (daily-scan 새 step):
--   1) watchlist 종목 추출 (전체 사용자 union)
--   2) DART list.json 으로 최근 24h 공시 fetch + disclosures upsert
--   3) (user, rcept_no) NOT IN disclosure_alert_seen 인 새 공시만 알림
--   4) telegram_worker.send_telegram() + alerts INSERT + seen INSERT

ALTER TABLE alert_preferences
    ADD COLUMN IF NOT EXISTS enable_disclosure BOOLEAN NOT NULL DEFAULT true;

-- ============================================================
-- 알림 발송 dedupe 테이블 — (user, rcept_no) PK 로 멱등성 강제
-- ============================================================
CREATE TABLE IF NOT EXISTS disclosure_alert_seen (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rcept_no VARCHAR(20) NOT NULL,
    -- 알림 보낸 시점 — retention sweep 시 7일 이상 지난 row 정리.
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, rcept_no)
);

CREATE INDEX IF NOT EXISTS idx_disclosure_alert_seen_sent
    ON disclosure_alert_seen (sent_at DESC);

ALTER TABLE disclosure_alert_seen ENABLE ROW LEVEL SECURITY;
-- service-key only — 사용자가 직접 읽을 일 없음 (UI 는 alerts 테이블 사용).
