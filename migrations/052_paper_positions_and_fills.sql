-- 052: paper_positions + paper_fills — broker-standard schema.
--
-- 2026-05-27 reform replacing the original paper_trades single-table
-- model. The user-facing surface is a POSITION (one per ticker
-- active at a time); the system records every individual BUY / SELL
-- as a FILL row. 분할 매도 / 추매 stop polluting the position list
-- with synthetic split rows — instead they become buy/sell fills
-- on the same position.
--
-- paper_trades (migration 050+051) is kept as-is for one cycle so the
-- existing 2 rows (development test data) don't get orphaned mid-
-- migration. The data-migration step below copies open trades into
-- a position + buy fill, and closed trades into position + buy fill
-- + sell fill. Once verified live, paper_trades can be dropped.

------------------------------------------------------------------
-- paper_positions: one row per (user, ticker, opened_at era).
-- After a position closes (shares_open hits 0), a brand-new buy
-- opens a NEW position so the closed-trade win_rate stays unambiguous.
------------------------------------------------------------------
create table if not exists paper_positions (
  id                  uuid primary key default gen_random_uuid(),
  user_id             text not null,
  ticker              text not null,
  status              text not null default 'open'
                      check (status in ('open', 'closed')),

  -- aggregate (updated on every fill)
  shares_open         numeric(18, 6) not null default 0,
  total_invested_krw  numeric(18, 2) not null default 0,
  realized_pnl_krw    numeric(18, 2) not null default 0,

  -- snapshotted plan from the first buy on this position. Subsequent
  -- 추매 fills may carry their own stop/target on the fill row but
  -- the position-level numbers stay anchored to the original plan
  -- so the BookVerdict snapshot doesn't drift.
  initial_entry_price numeric(18, 4),
  initial_stop_loss   numeric(18, 4),
  initial_target      numeric(18, 4),

  notes               text,
  opened_at           timestamptz not null default now(),
  closed_at           timestamptz,
  updated_at          timestamptz not null default now()
);

-- One open position per (user, ticker) at a time. Closed positions
-- can stack, hence the partial index.
create unique index if not exists paper_positions_open_unique
  on paper_positions (user_id, ticker)
  where status = 'open';

create index if not exists paper_positions_user_status_idx
  on paper_positions (user_id, status);

------------------------------------------------------------------
-- paper_fills: append-only log of every BUY and SELL on a position.
------------------------------------------------------------------
create table if not exists paper_fills (
  id              uuid primary key default gen_random_uuid(),
  position_id     uuid not null references paper_positions(id) on delete cascade,
  user_id         text not null,            -- denormalized for RLS + audit
  side            text not null check (side in ('buy', 'sell')),

  fill_date       date not null default current_date,
  fill_price      numeric(18, 4) not null,
  shares          numeric(18, 6) not null check (shares > 0),
  amount_krw      numeric(18, 2) not null check (amount_krw > 0),

  -- optional per-fill plan snapshot (mostly for buy)
  stop_loss       numeric(18, 4),
  target          numeric(18, 4),

  -- for sell fills only — realized at time of fill
  pnl_krw         numeric(18, 2),
  pnl_pct         numeric(10, 4),
  status_at_fill  text                       -- closed_stop / closed_target / closed_manual
                  check (status_at_fill is null
                         or status_at_fill in ('closed_stop',
                                               'closed_target',
                                               'closed_manual')),

  reason          text,
  alert_sent_at   timestamptz,               -- dedup for notify_paper_alerts
  created_at      timestamptz not null default now()
);

create index if not exists paper_fills_position_idx
  on paper_fills (position_id, fill_date);
create index if not exists paper_fills_user_idx
  on paper_fills (user_id);

------------------------------------------------------------------
-- updated_at trigger on paper_positions
------------------------------------------------------------------
create or replace function paper_positions_set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists paper_positions_updated_at on paper_positions;
create trigger paper_positions_updated_at
  before update on paper_positions
  for each row execute function paper_positions_set_updated_at();

------------------------------------------------------------------
-- RLS — each user sees only their own positions / fills.
------------------------------------------------------------------
alter table paper_positions enable row level security;
alter table paper_fills     enable row level security;

drop policy if exists paper_positions_self on paper_positions;
create policy paper_positions_self on paper_positions
  for all
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

drop policy if exists paper_fills_self on paper_fills;
create policy paper_fills_self on paper_fills
  for all
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

grant all on paper_positions to service_role;
grant all on paper_fills     to service_role;

------------------------------------------------------------------
-- Data migration: copy paper_trades into paper_positions + paper_fills.
-- For multi-row tickers (추매 from Phase 4), each old row becomes a
-- separate buy fill on the same position. The earliest entry_date
-- becomes the position's opened_at + initial_* plan snapshot.
------------------------------------------------------------------
do $$
declare
  rec record;
  pos_id uuid;
begin
  for rec in
    select distinct user_id, ticker
    from paper_trades
  loop
    -- Status: any open trade keeps the position open; otherwise closed.
    -- For closed positions, sum shares_open will be 0.
    insert into paper_positions (
      user_id, ticker, status,
      shares_open, total_invested_krw, realized_pnl_krw,
      initial_entry_price, initial_stop_loss, initial_target,
      notes, opened_at, closed_at
    )
    select
      rec.user_id,
      rec.ticker,
      case when exists (
        select 1 from paper_trades
        where user_id = rec.user_id and ticker = rec.ticker
          and status = 'open'
      ) then 'open' else 'closed' end,
      coalesce(sum(case when status = 'open' then shares end), 0),
      sum(amount_krw),
      coalesce(sum(case when status != 'open'
                        and exit_price is not null
                        then (exit_price - entry_price) * shares end), 0),
      (select entry_price from paper_trades
       where user_id = rec.user_id and ticker = rec.ticker
       order by entry_date asc limit 1),
      (select stop_loss from paper_trades
       where user_id = rec.user_id and ticker = rec.ticker
       order by entry_date asc limit 1),
      (select target from paper_trades
       where user_id = rec.user_id and ticker = rec.ticker
       order by entry_date asc limit 1),
      (select notes from paper_trades
       where user_id = rec.user_id and ticker = rec.ticker
       order by entry_date asc limit 1),
      (select min(entry_date) from paper_trades
       where user_id = rec.user_id and ticker = rec.ticker)::timestamptz,
      (select max(exit_date) from paper_trades
       where user_id = rec.user_id and ticker = rec.ticker
         and status != 'open')::timestamptz
    from paper_trades
    where user_id = rec.user_id and ticker = rec.ticker
    returning id into pos_id;

    -- Buy fills — one per old row.
    insert into paper_fills (
      position_id, user_id, side, fill_date, fill_price, shares,
      amount_krw, stop_loss, target, reason, created_at
    )
    select pos_id, user_id, 'buy', entry_date, entry_price,
           shares, amount_krw, stop_loss, target,
           coalesce(notes, '매수'), created_at
    from paper_trades
    where user_id = rec.user_id and ticker = rec.ticker;

    -- Sell fills — for any old row that's not open.
    insert into paper_fills (
      position_id, user_id, side, fill_date, fill_price, shares,
      amount_krw, status_at_fill, pnl_krw, pnl_pct, reason,
      alert_sent_at, created_at
    )
    select
      pos_id, user_id, 'sell',
      exit_date, exit_price, shares,
      shares * exit_price,
      status,
      (exit_price - entry_price) * shares,
      (exit_price - entry_price) / entry_price * 100,
      coalesce(exit_reason, '청산'),
      coalesce(stop_alert_sent_at, target_alert_sent_at),
      created_at
    from paper_trades
    where user_id = rec.user_id and ticker = rec.ticker
      and status != 'open'
      and exit_price is not null;
  end loop;
end $$;
