-- 051: paper_trades alert tracking.
--
-- Phase 2 of forward-test: auto-detect stop_loss / target hits and
-- fan out Telegram + push alerts so the user doesn't have to refresh
-- /paper to know the trade plan triggered.
--
-- Two new columns on the existing table — simpler than a sidecar
-- table because each row needs at most one stop alert and one target
-- alert in its lifetime. Once sent, the column stays non-null so the
-- cron job doesn't re-alert on the next run.
--
-- Why timestamp (not boolean): handy for "when did this trade trigger"
-- support questions + future "alert latency from price cross" stat.

alter table paper_trades
  add column if not exists stop_alert_sent_at timestamptz;

alter table paper_trades
  add column if not exists target_alert_sent_at timestamptz;

-- Index for the cron's "any open trade with stop_alert_sent_at IS NULL
-- and current price below stop_loss" scan. Partial because we only
-- ever query rows that haven't been alerted yet — once
-- stop_alert_sent_at IS NOT NULL, the row stops participating.
create index if not exists paper_trades_open_unalerted_idx
  on paper_trades (ticker)
  where status = 'open'
    and (stop_alert_sent_at is null or target_alert_sent_at is null);
