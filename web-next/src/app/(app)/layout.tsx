import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { UserMenu } from "@/components/user-menu";
import { ThemeToggle } from "@/components/theme-toggle";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  const u = session.user as { role?: string; access_status?: string };
  if (u.access_status && u.access_status !== "approved") {
    redirect("/pending");
  }
  const isAdmin = u.role === "admin";
  return (
    <div className="flex min-h-screen">
      <Sidebar isAdmin={isAdmin} />
      <div className="flex-1 flex flex-col">
        <header className="h-14 flex items-center justify-end gap-3 px-6 border-b border-border bg-background/80 backdrop-blur sticky top-0 z-10">
          <ThemeToggle />
          <UserMenu />
        </header>
        <main className="flex-1 p-6 overflow-x-auto">{children}</main>
      </div>
    </div>
  );
}
