-- 019_decide_access_request_rpc.sql
--
-- Admin approval / rejection used to update `users` and upsert
-- `access_requests` as two separate REST calls; PostgREST has no
-- multi-statement transaction support, so a failure between the two
-- left the audit trail and the user.access_status out of sync.
--
-- This function bundles both into a single atomic Postgres transaction.
-- Called from web-next/src/app/api/admin/access-requests/route.ts via
-- the supabase-js `.rpc()` helper.

CREATE OR REPLACE FUNCTION decide_access_request(
    p_user_id    UUID,
    p_decision   TEXT,        -- 'approved' | 'rejected'
    p_decided_by UUID,
    p_note       TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF p_decision NOT IN ('approved', 'rejected') THEN
        RAISE EXCEPTION 'invalid decision: %', p_decision;
    END IF;

    UPDATE users
       SET access_status = p_decision,
           approved_at   = CASE WHEN p_decision = 'approved'
                                THEN now() ELSE approved_at END,
           approved_by   = CASE WHEN p_decision = 'approved'
                                THEN p_decided_by ELSE approved_by END
     WHERE id = p_user_id;

    INSERT INTO access_requests (user_id, decision, decided_at, decided_by, note)
    VALUES (p_user_id, p_decision, now(), p_decided_by, p_note)
    ON CONFLICT (user_id) DO UPDATE SET
        decision    = EXCLUDED.decision,
        decided_at  = EXCLUDED.decided_at,
        decided_by  = EXCLUDED.decided_by,
        note        = EXCLUDED.note;
END;
$$;

-- Only the service_role (used by the API route) needs to invoke this;
-- anon/authenticated should not be able to call it directly.
REVOKE ALL ON FUNCTION decide_access_request(UUID, TEXT, UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION decide_access_request(UUID, TEXT, UUID, TEXT) TO service_role;
