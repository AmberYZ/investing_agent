import { AdminTabs } from "./AdminTabs";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-5xl px-6 py-10">
        <AdminTabs />
        {children}
      </main>
    </div>
  );
}
