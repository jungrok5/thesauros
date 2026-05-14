import { auth } from "@/auth";

export default async function SettingsPage() {
  const session = await auth();
  return (
    <div className="space-y-4 max-w-2xl">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
        <h2 className="text-sm font-medium text-zinc-300 mb-2">계정</h2>
        <dl className="space-y-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-zinc-500">이름</dt>
            <dd>{session?.user?.name ?? "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-zinc-500">이메일</dt>
            <dd className="font-mono">{session?.user?.email ?? "—"}</dd>
          </div>
        </dl>
      </div>
      <p className="text-xs text-zinc-500">
        텔레그램 알림 채널, 관심 종목 동기화 등은 M5에서 추가.
      </p>
    </div>
  );
}
