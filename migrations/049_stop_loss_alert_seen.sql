-- 049 — Stop-loss alert dedup table (Phase Telegram-SL)
--
-- 보유 종목 (watchlist.category = 'holding') 의 weekly 종가가 entry_price
-- 대비 -10% 떨어지면 Telegram 알림. 매주 1회 중복 방지를 위해 (user,
-- ticker, bar_date) PK 의 seen 테이블 사용. 가격이 -10% 위로 회복한
-- 후 다시 하락하면 다음 주봉에서 다시 알림 가능.

CREATE TABLE IF NOT EXISTS stop_loss_alert_seen (
    user_id              UUID    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker               TEXT    NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    alerted_at_bar_date  DATE    NOT NULL,
    entry_price          NUMERIC NOT NULL,
    bar_close_price      NUMERIC NOT NULL,
    drop_pct             NUMERIC NOT NULL,
    sent_telegram        BOOLEAN NOT NULL DEFAULT false,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, ticker, alerted_at_bar_date)
);

CREATE INDEX IF NOT EXISTS idx_sl_alert_user_ticker
    ON stop_loss_alert_seen (user_id, ticker, alerted_at_bar_date DESC);

ALTER TABLE stop_loss_alert_seen ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sl_alert_seen_read ON stop_loss_alert_seen;
CREATE POLICY sl_alert_seen_read ON stop_loss_alert_seen FOR SELECT
    USING (user_id::text = current_user OR auth.role() = 'service_role');

DROP POLICY IF EXISTS sl_alert_seen_write ON stop_loss_alert_seen;
CREATE POLICY sl_alert_seen_write ON stop_loss_alert_seen FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

COMMENT ON TABLE stop_loss_alert_seen IS
  'Phase Telegram-SL: dedup for "보유 종목 -10% 떨어졌음" 알림. '
  '(user, ticker, alerted_at_bar_date) PK 로 동일 주봉 중복 차단. '
  '회복 후 다시 하락 시 다음 주 다른 bar_date 라 알림 재발송 가능.';
