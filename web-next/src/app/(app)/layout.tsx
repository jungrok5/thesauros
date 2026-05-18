import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { Sidebar, MobileNav } from "@/components/sidebar";
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
      {/* Mobile drawer lives at the layout root so its fixed/z-50 drawer
          isn't trapped inside the header's stacking context (header has
          backdrop-blur which creates one, breaking the drawer overlay). */}
      <MobileNav isAdmin={isAdmin} />
      <Sidebar isAdmin={isAdmin} />
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 flex items-center justify-between gap-3 px-4 md:px-6 border-b border-border bg-background/80 backdrop-blur sticky top-0 z-10">
          {/* Spacer that aligns with the hamburger button on mobile — the
              actual button is rendered by <MobileNav> above (positioned
              with `fixed`, 44px tap target). */}
          <div className="md:hidden w-11" aria-hidden="true" />
          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6 overflow-x-auto">{children}</main>
      </div>
    </div>
  );
}
