-- 015_drop_news.sql — drop the per-stock news cache.
--
-- News is now fetched in real time from Naver Finance via
-- /api/news/[ticker] (5-minute ISR cache), so the DB copy is orphan.
-- DART disclosures stay in `disclosures` (separate table) because they
-- depend on a rate-limited API key.
--
-- CASCADE drops the RLS policy + idx_news_ticker_pub index together.

DROP TABLE IF EXISTS news CASCADE;
