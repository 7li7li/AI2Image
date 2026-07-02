"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { TopNav } from "@/components/top-nav";
import { normalizeAppPath } from "@/lib/routes";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const normalizedPathname = normalizeAppPath(pathname);

  if (normalizedPathname === "/" || normalizedPathname === "/login") {
    return <main className="min-h-screen text-stone-900">{children}</main>;
  }

  return (
    <main className="yan-soft-grid h-dvh overflow-hidden px-2 py-2 text-stone-900 sm:px-3 sm:py-3 lg:px-4">
      <div className="yan-app-surface mx-auto flex h-[calc(100dvh-1rem)] max-w-[1800px] flex-col overflow-hidden rounded-lg sm:h-[calc(100dvh-1.5rem)]">
        <TopNav />
        <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-2 py-3 sm:px-4 sm:py-4 lg:px-5">{children}</div>
      </div>
    </main>
  );
}
