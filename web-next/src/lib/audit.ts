/**
 * Append-only audit log helper (migration 057).
 *
 * Insert one row per user-initiated destructive op so a compromised
 * session leaves a trail. Best-effort: any DB failure is logged and
 * swallowed — never blocks the caller's response.
 */
import { getServerClient } from "@/lib/supabase";

export interface AuditEntry {
  /** Internal users.id of the actor. */
  userId: string;
  /** Verb-shape tag, e.g. "watchlist.delete", "feedback.admin_patch". */
  action: string;
  /** Optional — what kind of thing was touched (ticker, feedback_id, …). */
  targetKind?: string;
  /** Optional — string-cast id of the affected entity. */
  targetId?: string;
  /** Optional — extra context (before/after diff, threshold, etc). */
  payload?: Record<string, unknown>;
}

export async function logAudit(entry: AuditEntry): Promise<void> {
  try {
    const sb = getServerClient();
    await sb.from("user_action_audit").insert({
      user_id: entry.userId,
      action: entry.action,
      target_kind: entry.targetKind ?? null,
      target_id: entry.targetId ?? null,
      payload: entry.payload ?? null,
    });
  } catch (e) {
    // Never let an audit-write failure crash the caller. Stderr log
    // for ops visibility; the underlying operation already succeeded.
    console.error("audit.log insert failed:", e);
  }
}
