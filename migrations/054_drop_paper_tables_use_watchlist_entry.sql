-- 054 — Drop paper trading tables. Adopt watchlist.entry_price as the
--       sole "I started tracking this here" reference.
--
-- Why: 2026-05-28 user redesign. Paper trading (buy/sell/추매/분할매도)
-- added position-management overhead that diluted the screener-as-
-- entry-signal value. Replacement model: registering a ticker in the
-- watchlist snapshots the latest close into watchlist.entry_price; the
-- UI shows entry_price / current_price / return % so every tracked
-- ticker is automatically a "what if I'd bought when I added it"
-- experiment.
--
-- The watchlist.entry_price + entry_date columns already exist
-- (migrations/002_core_schema.sql:41-42) — they were defined but never
-- populated. This migration just clears the way by dropping the paper
-- tables. Application code (POST /api/watchlist) is updated separately
-- to start snapshotting entry_price on insert.
--
-- Stop-loss alerts will be revived via watchlist (notify_stop_loss.py)
-- scanning watchlist.category='holding' AND entry_price IS NOT NULL
-- AND current_price <= entry_price * 0.90.

-- Drop in dependency order — paper_fills references paper_positions
-- via FK; CASCADE handles indices/policies on both.
DROP TABLE IF EXISTS paper_fills CASCADE;
DROP TABLE IF EXISTS paper_positions CASCADE;

-- The pre-broker-standard table (migration 050). Kept around for
-- cooling period after the 2026-05-27 broker refactor; safe to drop
-- now that paper as a feature is going away.
DROP TABLE IF EXISTS paper_trade_alerts CASCADE;
DROP TABLE IF EXISTS paper_trades CASCADE;
