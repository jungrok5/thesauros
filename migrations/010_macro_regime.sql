-- 010_macro_regime.sql — macro_state needs the full regime object too
--
-- The dashboard page reads regime info (score/note/vix_state/yield_curve)
-- directly from macro_state. Previously the FastAPI endpoint computed
-- regime on every request; now the daily `publish_macro` cron stores it.

ALTER TABLE macro_state ADD COLUMN IF NOT EXISTS regime JSONB;
    -- {regime, score, n_indicators, vix_state, yield_curve_inverted,
    --  note, components: [...]}
