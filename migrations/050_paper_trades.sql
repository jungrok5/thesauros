-- 050: paper_trades — forward-test ("가짜 매수") store.
--
-- Why: sweep_all_24w.csv + portfolio.py give a 17-year retrospective
-- ("did this work in 2009-2026?"). Forward-test answers the other
-- question users actually ask: "if I follow the site's verdict from
-- *today*, does it work?"
--
-- A row = one paper position. Created via the "📒 가짜 매수" button on
-- a stock detail page or screener row. The user supplies amount_krw;
-- entry_price + stop_loss + target are snapshotted from the analyzer's
-- entry_plan at click time so the user sees the SAME numbers the page
-- showed when they "bought".
--
-- Lifecycle:
--   created     status = 'open'
--   stop hit    → 'closed_stop'   (10MA 이탈 alert auto-closes)
--   target hit  → 'closed_target' (partial profit-take prompt)
--   manual      → 'closed_manual' (user clicked 청산)
--
-- Exits are recorded as their own columns (exit_date / price /
-- reason) so closed trades stay queryable for the win-rate / payoff
-- stats panel on /paper.

create table if not exists paper_trades (
  id            uuid primary key default gen_random_uuid(),
  user_id       text not null,
  ticker        text not null,
  entry_date    date not null default current_date,
  entry_price   numeric(18, 4) not null,
  amount_krw    numeric(18, 2) not null,
  shares        numeric(18, 6) not null,    -- amount_krw / entry_price
  stop_loss     numeric(18, 4),
  target        numeric(18, 4),
  notes         text,
  status        text not null default 'open'
                check (status in (
                  'open', 'closed_stop', 'closed_target', 'closed_manual'
                )),
  exit_date     date,
  exit_price    numeric(18, 4),
  exit_reason   text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- The list-by-user query (server-rendered /paper page + dashboard
-- summary) hits both filters; status comes second since "open" rows
-- dominate the working set.
create index if not exists paper_trades_user_status_idx
  on paper_trades (user_id, status);

-- For the per-ticker "show my paper position" chip on stock detail
-- pages (so the user doesn't double-buy the same name).
create index if not exists paper_trades_user_ticker_idx
  on paper_trades (user_id, ticker)
  where status = 'open';

create or replace function paper_trades_set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists paper_trades_updated_at on paper_trades;
create trigger paper_trades_updated_at
  before update on paper_trades
  for each row execute function paper_trades_set_updated_at();

-- RLS: each user reads/writes only their own rows.
alter table paper_trades enable row level security;

drop policy if exists paper_trades_self on paper_trades;
create policy paper_trades_self on paper_trades
  for all
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Service role bypass (Next.js server-rendered fetches use the
-- service key, then constrain to the logged-in user in the API
-- layer).
grant all on paper_trades to service_role;
