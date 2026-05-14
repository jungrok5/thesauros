import { auth, signOut } from "@/auth";
import { LogOut } from "lucide-react";

export async function UserMenu() {
  const session = await auth();
  if (!session?.user) return null;
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      <div className="flex flex-col items-end leading-tight">
        <span className="text-foreground">{session.user.name}</span>
        <span className="text-xs">{session.user.email}</span>
      </div>
      <form
        action={async () => {
          "use server";
          await signOut({ redirectTo: "/login" });
        }}
      >
        <button
          type="submit"
          className="rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-muted hover:text-foreground flex items-center gap-1.5 transition-colors"
        >
          <LogOut className="h-3.5 w-3.5" />
          로그아웃
        </button>
      </form>
    </div>
  );
}
