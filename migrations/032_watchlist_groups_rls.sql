-- 032 — watchlist_groups RLS policy
--
-- migration 031 에서 RLS enable 만 하고 policy 안 만듦. Service-key 는
-- RLS 우회하니까 web app 의 getServerClient() 호출은 영향 X 인 게
-- 정상. 그러나 미래에 anon / authenticated role 로 직접 접근하는
-- code path 가 생기거나, PostgREST 의 SCHEMA cache 가 어떤 이유로
-- service-role bypass 안 할 가능성 (production 사고 사례 있음).
--
-- 안전 fallback 으로 watchlist (p_watch_self) 와 같은 패턴 적용 —
-- current_user_id() 함수가 세션 JWT 에서 추출하는 user_id 와 match.

CREATE POLICY p_wg_self ON watchlist_groups
    FOR ALL
    USING (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());
