"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { TopNav } from "@/components/top-nav";
import { AnnouncementPopup } from "@/components/announcement-popup";
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
    <main className="h-dvh overflow-hidden bg-[#f7f7f8] text-stone-900">
      <div className="flex h-full min-w-0">
        <TopNav />
        <div className="min-w-0 flex-1 overflow-hidden px-2 py-2 sm:px-3 sm:py-3">{children}</div>
        <AnnouncementPopup />
      </div>
    </main>
  );
}
