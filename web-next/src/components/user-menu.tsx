import { auth, signOut } from "@/auth";
import { LogOut } from "lucide-react";

export async function UserMenu() {
  const session = await auth();
  if (!session?.user) return null;
  return (
    <div className="flex items-center gap-3 text-sm text-zinc-400">
      <div className="flex flex-col items-end leading-tight">
        <span className="text-zinc-100">{session.user.name}</span>
        <span className="text-xs text-zinc-500">{session.user.email}</span>
      </div>
      <form
        action={async () => {
          "use server";
          await signOut({ redirectTo: "/login" });
        }}
      >
        <button
          type="submit"
          className="rounded-md border border-zinc-800 px-2.5 py-1.5 text-xs text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200 flex items-center gap-1.5"
        >
          <LogOut className="h-3.5 w-3.5" />
          로그아웃
        </button>
      </form>
    </div>
  );
}
