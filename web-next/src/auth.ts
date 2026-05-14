/**
 * NextAuth (Auth.js) v5 setup — Google OAuth with email whitelist.
 *
 * Required env vars:
 *   AUTH_SECRET            — `openssl rand -base64 32`
 *   AUTH_GOOGLE_ID         — Google OAuth Client ID
 *   AUTH_GOOGLE_SECRET     — Google OAuth Client Secret
 *   AUTH_ALLOWED_EMAILS    — comma-separated whitelist (e.g. "you@gmail.com,friend@gmail.com")
 */
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

function getAllowedEmails(): string[] {
  const raw = process.env.AUTH_ALLOWED_EMAILS ?? "";
  return raw
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
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
      const allowed = getAllowedEmails();
      // If whitelist is empty, allow only in development.
      if (allowed.length === 0) {
        return process.env.NODE_ENV !== "production";
      }
      return allowed.includes(email);
    },
    async session({ session, token }) {
      if (session.user && token.sub) {
        // Type augmentation: see next-auth.d.ts
        (session.user as { id?: string }).id = token.sub;
      }
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
});
