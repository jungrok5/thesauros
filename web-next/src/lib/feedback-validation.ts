/**
 * Pure validators for /api/feedback payloads.
 *
 * Extracted from the route handler so we can unit-test the rules
 * without auth/DB plumbing. Keep parser + truncation here; the route
 * just dispatches to `parseFeedbackInput` and writes the result.
 */

export type FeedbackCategory = "bug" | "feature" | "other";
export const FEEDBACK_CATEGORIES: readonly FeedbackCategory[] = [
  "bug",
  "feature",
  "other",
] as const;

export const FEEDBACK_TITLE_MAX = 120;
export const FEEDBACK_BODY_MAX = 4000;
export const FEEDBACK_PAGE_URL_MAX = 500;

export type ParsedFeedback =
  | {
      ok: true;
      category: FeedbackCategory;
      title: string;
      body: string;
      pageUrl: string | null;
    }
  | { ok: false; error: string };

export function isFeedbackCategory(s: unknown): s is FeedbackCategory {
  return (
    typeof s === "string" &&
    (FEEDBACK_CATEGORIES as readonly string[]).includes(s)
  );
}

/**
 * Parse + validate the JSON body of a POST /api/feedback request.
 * Strings get trimmed + clipped to the documented maxes; missing or
 * over-length critical fields surface as `{ ok: false, error }` so
 * the route handler can return a 400 with a specific reason.
 */
export function parseFeedbackInput(body: unknown): ParsedFeedback {
  if (!body || typeof body !== "object") {
    return { ok: false, error: "invalid body" };
  }
  const b = body as Record<string, unknown>;

  const category = typeof b.category === "string" ? b.category.trim() : "";
  if (!isFeedbackCategory(category)) {
    return { ok: false, error: "invalid category" };
  }

  const title =
    typeof b.title === "string"
      ? b.title.trim().slice(0, FEEDBACK_TITLE_MAX)
      : "";
  const text =
    typeof b.body === "string"
      ? b.body.trim().slice(0, FEEDBACK_BODY_MAX)
      : "";
  if (!title || !text) {
    return { ok: false, error: "missing title or body" };
  }

  const pageUrl =
    typeof b.page_url === "string" && b.page_url
      ? b.page_url.slice(0, FEEDBACK_PAGE_URL_MAX)
      : null;

  return { ok: true, category, title, body: text, pageUrl };
}
