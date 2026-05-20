/**
 * NextAuth (Auth.js) v5 setup — Google OAuth + DB-backed access control.
 *
 * Required env vars:
 *   AUTH_SECRET            — `openssl rand -base64 32`
 *   AUTH_GOOGLE_ID         — Google OAuth Client ID
 *   AUTH_GOOGLE_SECRET     — Google OAuth Client Secret
 *   ADMIN_EMAILS           — comma-separated admin allowlist; on first
 *                            sign-in these accounts are auto-approved and
 *                            granted role='admin'.
 *
 * Anyone can complete Google sign-in, but only users with
 * access_status='approved' in the DB can actually access the app. New
 * users land on /pending where they can submit an access request; an
 * admin approves them from /admin/access.
 */
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { getServerClient } from "@/lib/supabase";

function getAdminEmails(): string[] {
  const raw = process.env.ADMIN_EMAILS ?? "";
  return raw
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
}

type SyncedUser = {
  id: string;
  role: "admin" | "user";
  access_status: "pending" | "approved" | "rejected";
};

/**
 * Upsert the user row on every sign-in and return their current
 * (role, access_status). Bootstraps admins from `ADMIN_EMAILS` env on
 * first contact, and re-promotes if the env was updated later.
 */
async function syncUser(email: string, name: string | null): Promise<SyncedUser> {
  const sb = getServerClient();
  const isAdmin = getAdminEmails().includes(email);

  const { data: existing } = await sb
    .from("users")
    .select("id, role, access_status")
    .eq("email", email)
    .maybeSingle();

  if (!existing) {
    const { data: inserted, error } = await sb
      .from("users")
      .insert({
        email,
        name,
        role: isAdmin ? "admin" : "user",
        access_status: isAdmin ? "approved" : "pending",
        approved_at: isAdmin ? new Date().toISOString() : null,
        last_login_at: new Date().toISOString(),
      })
      .select("id, role, access_status")
      .single();
    if (error) throw error;
    return inserted as SyncedUser;
  }

  const updates: Record<string, unknown> = {
    last_login_at: new Date().toISOString(),
  };
  let nextRole = existing.role as "admin" | "user";
  let nextStatus = existing.access_status as
    | "pending"
    | "approved"
    | "rejected";
  if (isAdmin && nextRole !== "admin") {
    updates.role = "admin";
    nextRole = "admin";
  }
  if (isAdmin && nextStatus !== "approved") {
    updates.access_status = "approved";
    updates.approved_at = new Date().toISOString();
    nextStatus = "approved";
  }
  await sb.from("users").update(updates).eq("id", existing.id);
  return { id: existing.id as string, role: nextRole, access_status: nextStatus };
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
    }),
  ],
  callbacks: {
    async signIn({ user }) {
      const email = (user.email ?? "").toLowerCase();
      if (!email) return false;
      try {
        const synced = await syncUser(email, user.name ?? null);
        // Block rejected accounts; pending CAN sign in but the proxy will
        // redirect them to /pending.
        return synced.access_status !== "rejected";
      } catch (e) {
        console.error("syncUser failed:", e);
        return false;
      }
    },
    async jwt({ token, user, trigger }) {
      // Refresh role + access_status from the DB:
      //   - on initial sign-in (`user.email` present)
      //   - on explicit `update()` call from a client component
      //   - EVERY request while the token says "pending" — this is the
      //     state that changes urgently (admin approval). 60 s TTL was
      //     too long; users clicking "대시보드로 이동" right after
      //     approval saw the click bounce silently back to /pending and
      //     thought the button was broken. With per-request refresh,
      //     the next click goes through immediately.
      //   - every 60 s otherwise (approved / rejected users — those
      //     states rarely change so cache is fine).
      const now = Date.now();
      const TTL_MS = 60_000;
      const tok = token as {
        role?: string;
        access_status?: string;
        _fetchedAt?: number;
      };
      const isPending = tok.access_status === "pending";
      const stale = (tok._fetchedAt ?? 0) < now - TTL_MS;
      const shouldRefresh =
        !!user?.email || trigger === "update" || isPending || stale;
      if (shouldRefresh) {
        const email = (user?.email ?? token.email ?? "").toString().toLowerCase();
        if (email) {
          const sb = getServerClient();
          const { data } = await sb
            .from("users")
            .select("id, role, access_status")
            .eq("email", email)
            .maybeSingle();
          if (data) {
            token.sub = data.id as string;
            tok.role = data.role as string;
            tok.access_status = data.access_status as string;
            tok._fetchedAt = now;
          }
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.sub) {
        const u = session.user as {
          id?: string;
          role?: string;
          access_status?: string;
        };
        u.id = token.sub;
        u.role = (token as { role?: string }).role;
        u.access_status = (token as { access_status?: string }).access_status;
      }
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
});
