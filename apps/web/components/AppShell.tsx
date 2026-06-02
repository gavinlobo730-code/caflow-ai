"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";

const NO_SHELL_PATHS = ["/login", "/login/", "/onboarding", "/onboarding/"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const showShell = !NO_SHELL_PATHS.includes(pathname);

  if (!showShell) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[hsl(220,20%,97%)]">
      <Sidebar />
      <main className="flex-1 overflow-auto pt-12 md:pt-0 min-w-0">
        {children}
      </main>
    </div>
  );
}
