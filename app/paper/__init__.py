"""Paper-trading layer (P4).

Records the system's recommendations daily without real money, then later
evaluates how they performed. This is the *only* honest validation of
whether back-test alpha persists out-of-sample.

Pipeline:
  1. `record_snapshot()` — every day after market close, take the current
     screening recommendations + write to `paper_trades` table.
  2. `evaluate_open_trades()` — periodically, check exit conditions:
        - target hit                   → close + WIN
        - stop hit                     → close + STOP
        - 90 trading days held          → close + TIMEOUT
     Realized return is stored.
  3. `paper_metrics()` — aggregate: win rate, avg return, hit ratio per
     pattern type, etc.
"""
