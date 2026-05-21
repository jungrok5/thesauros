-- 042 — theme_metrics RPC: per-theme aggregate (등락률 + action 분포 + 대표 종목)
--
-- Why RPC instead of client-side aggregation:
--   themes ~265 × avg 24 members = ~6,400 ticker rows. To compute per-theme
--   1-week change + action distribution from PostgREST client, you'd need to
--   fetch every (ticker, latest 2 bars) + every analyze_results row — well
--   past the 1000-row cap. DB-side aggregation collapses it to ~265 rows.
--
-- No new ingest cron — function reads only from existing tables (themes,
-- theme_members, bars W, analyze_results, tickers).

CREATE OR REPLACE FUNCTION theme_metrics()
RETURNS TABLE (
  theme_id          INT,
  name              TEXT,
  members           INT,
  updated_at        TIMESTAMPTZ,
  avg_change_pct    NUMERIC,    -- 평균 1주 등락률 (소수: 0.012 = +1.2 %)
  up_count          INT,        -- 상승 종목 수
  down_count        INT,        -- 하락 종목 수
  strong_buy        INT,
  buy               INT,
  hold              INT,
  avoid             INT,
  top_tickers       TEXT[]      -- 대표 종목 3개 (STRONG_BUY → BUY → 나머지, book_score desc)
)
LANGUAGE sql STABLE
AS $$
  WITH latest_close AS (
    -- ticker 별 최신 주봉 close.
    SELECT DISTINCT ON (ticker)
           ticker, close
      FROM bars
     WHERE granularity = 'W'
     ORDER BY ticker, bar_date DESC
  ), prev_close AS (
    -- ticker 별 직전 주봉 close — 'second newest' via ROW_NUMBER.
    SELECT ticker, close
      FROM (
        SELECT ticker, close,
               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY bar_date DESC) AS rn
          FROM bars
         WHERE granularity = 'W'
      ) s
     WHERE s.rn = 2
  ), member_metrics AS (
    SELECT
      tm.theme_id,
      tm.ticker,
      tk.name AS ticker_name,
      lc.close AS close,
      pc.close AS prev,
      CASE
        WHEN pc.close IS NULL OR pc.close = 0 THEN NULL
        ELSE (lc.close / pc.close) - 1
      END AS change_pct,
      ar.result->>'action' AS action,
      COALESCE((ar.result->>'book_score')::NUMERIC, 0) AS book_score
    FROM theme_members tm
    LEFT JOIN tickers tk          ON tk.ticker = tm.ticker
    LEFT JOIN latest_close lc     ON lc.ticker = tm.ticker
    LEFT JOIN prev_close pc       ON pc.ticker = tm.ticker
    LEFT JOIN analyze_results ar  ON ar.ticker = tm.ticker
  ), agg AS (
    SELECT
      mm.theme_id,
      COUNT(*)::INT                                               AS member_count,
      AVG(mm.change_pct)                                          AS avg_change_pct,
      SUM(CASE WHEN mm.change_pct > 0 THEN 1 ELSE 0 END)::INT     AS up_count,
      SUM(CASE WHEN mm.change_pct < 0 THEN 1 ELSE 0 END)::INT     AS down_count,
      SUM(CASE WHEN mm.action = 'STRONG_BUY' THEN 1 ELSE 0 END)::INT AS strong_buy,
      SUM(CASE WHEN mm.action = 'BUY'        THEN 1 ELSE 0 END)::INT AS buy,
      SUM(CASE WHEN mm.action = 'HOLD'       THEN 1 ELSE 0 END)::INT AS hold,
      SUM(CASE WHEN mm.action IN ('AVOID','SELL','SELL_OR_SHORT') THEN 1 ELSE 0 END)::INT AS avoid
    FROM member_metrics mm
    GROUP BY mm.theme_id
  ), top AS (
    -- 테마 안의 종목을 action priority 로 정렬한 뒤 상위 3개의 한글 이름을
    -- array_agg. STRONG_BUY=4 → BUY=3 → 나머지=2, 동률은 book_score desc.
    SELECT theme_id,
           ARRAY_AGG(COALESCE(ticker_name, ticker) ORDER BY pri DESC, book_score DESC)
             FILTER (WHERE rn <= 3) AS top_tickers
    FROM (
      SELECT
        mm.theme_id, mm.ticker, mm.ticker_name, mm.book_score,
        CASE mm.action
          WHEN 'STRONG_BUY' THEN 4
          WHEN 'BUY'        THEN 3
          WHEN 'HOLD'       THEN 2
          ELSE 1
        END AS pri,
        ROW_NUMBER() OVER (
          PARTITION BY mm.theme_id
          ORDER BY CASE mm.action
                     WHEN 'STRONG_BUY' THEN 4
                     WHEN 'BUY'        THEN 3
                     WHEN 'HOLD'       THEN 2
                     ELSE 1
                   END DESC,
                   mm.book_score DESC
        ) AS rn
      FROM member_metrics mm
    ) ranked
    GROUP BY theme_id
  )
  -- themes.members 는 ingest 시 snapshot 이라 실제 theme_members count
  -- 와 어긋날 수 있음 (12 → snapshot 29 vs actual 93). RPC 는 정확한
  -- count 를 위해 agg.member_count 사용.
  SELECT
    t.theme_id,
    t.name,
    COALESCE(a.member_count, 0),
    t.updated_at,
    a.avg_change_pct,
    COALESCE(a.up_count, 0),
    COALESCE(a.down_count, 0),
    COALESCE(a.strong_buy, 0),
    COALESCE(a.buy, 0),
    COALESCE(a.hold, 0),
    COALESCE(a.avoid, 0),
    tp.top_tickers
  FROM themes t
  LEFT JOIN agg a  ON a.theme_id = t.theme_id
  LEFT JOIN top tp ON tp.theme_id = t.theme_id
  ORDER BY COALESCE(a.member_count, 0) DESC;
$$;

GRANT EXECUTE ON FUNCTION theme_metrics() TO anon, authenticated;
