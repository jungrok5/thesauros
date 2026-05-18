/**
 * Sanitize the `callbackUrl` query string from /login. Only allow paths
 * within our own site so an attacker can't craft a link like
 * `/login?callbackUrl=//evil.com/...` and have the post-login redirect
 * send the user off-site.
 */

export function safeCallback(raw: string | undefined, fallback = "/dashboard"): string {
  if (!raw) return fallback;
  // Reject anything that doesn't start with a single leading slash:
  // - "https://evil.com" (absolute URL)
  // - "//evil.com/x" (protocol-relative)
  // - "evil.com/x" (no leading slash)
  // - "" (empty)
  if (!raw.startsWith("/") || raw.startsWith("//")) return fallback;
  // Optional extra hardening: reject backslash escapes that some
  // browsers normalise to "/" (treating "/\\evil.com" as a path).
  if (raw.startsWith("/\\")) return fallback;
  return raw;
}
