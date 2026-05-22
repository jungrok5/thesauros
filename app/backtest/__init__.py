"""Backtest framework — verify the book's signals against historical data.

Phase 1 (MVP, this commit): single-ticker × single-signal backtest.
  - Load 5y weekly bars for one ticker from Supabase
  - At each historical Friday close, run analyze_ticker() against the
    bars ending that date (PIT-safe slice)
  - Collect dates where the requested signal fired
  - Compute simple-return over the next N weeks per fire
  - Report win-rate, average / median return, payoff ratio

Phase 2 (planned, separate PR): book's 11 real-world cases OOS check —
  pin specific ticker × pattern × known +%, fail if the engine misses.

Phase 3 (planned): full portfolio simulator with capital allocation,
  exit rules, transaction-cost model.

CLAUDE.md §3 pre/post-flight rules (PIT, universe, costs, seed) apply
— see test_single_signal_backtest.py for the static verification.
"""
