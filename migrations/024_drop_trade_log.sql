-- 024_drop_trade_log.sql — drop the trade_log table.
--
-- trade_log was written by /api/trade-log and surfaced only on the
-- /closing-trade page, which was removed in the search-only pivot
-- (Phase 1, 2026-05-19). The component (TradeLogForm) + route are
-- gone now, leaving the table without any consumer.
--
-- The cron / alerts pipeline does NOT read trade_log — alerts trigger
-- off scan_results, not user trade records.

DROP TABLE IF EXISTS trade_log CASCADE;
