-- 060 — Dedup table for the new book-faithful exit alerts.
--
-- Replaces stop_loss_alert_seen for the alert tracking. The -10% rule
-- is being retired (not in the book) and replaced by the book's three
-- actual exits — 종목별 월봉 10MA 깨짐 / 장대양봉 4등분 25% 깨짐 /
-- 천장 패턴. stop_loss_alert_seen stays in place for historical reads
-- but no new rows will be inserted; notify_stop_loss.py is removed.
--
-- One row per (user, ticker, kind, bar_date) so the alerter never
-- alerts the same user about the same week twice for the same rule.

CREATE TABLE IF NOT EXISTS book_exit_alert_seen (
    user_id              UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker               VARCHAR(20)  NOT NULL,
    kind                 VARCHAR(32)  NOT NULL,   -- 'monthly_10ma' | 'quartile_25'
    alerted_at_bar_date  DATE         NOT NULL,
    entry_price          NUMERIC,
    bar_close_price      NUMERIC,
    sent_telegram        BOOLEAN      NOT NULL DEFAULT false,
    inserted_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, ticker, kind, alerted_at_bar_date)
);

CREATE INDEX IF NOT EXISTS idx_book_exit_alert_user_time
    ON book_exit_alert_seen (user_id, inserted_at DESC);

-- RLS — owner read-only. Service-role writes (cron only).
ALTER TABLE book_exit_alert_seen ENABLE ROW LEVEL SECURITY;
ALTER TABLE book_exit_alert_seen FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_book_exit_alert_self_read ON book_exit_alert_seen;
CREATE POLICY p_book_exit_alert_self_read ON book_exit_alert_seen
    FOR SELECT TO authenticated
    USING (user_id = current_user_id());

COMMENT ON TABLE book_exit_alert_seen IS
    'Dedup ledger for book-faithful exit Telegram alerts. One row per (user, ticker, kind, bar_date). Replaces stop_loss_alert_seen for new writes — the -10% rule was retired 2026-05-29 in favor of the book''s actual exits (월봉 10MA / 4등분 25% / 천장 패턴).';
