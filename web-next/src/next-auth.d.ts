import "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      id?: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
      role?: "admin" | "user";
      access_status?: "pending" | "approved" | "rejected";
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    role?: "admin" | "user";
    access_status?: "pending" | "approved" | "rejected";
  }
}
