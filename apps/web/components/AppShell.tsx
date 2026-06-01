"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";

const NO_SHELL_PATHS = ["/login"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const showShell = !NO_SHELL_PATHS.includes(pathname);

  if (!showShell) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
