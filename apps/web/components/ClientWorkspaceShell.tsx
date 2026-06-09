"use client";

import { usePathname } from "next/navigation";
import { ClientNavProvider, getSectionForPathname } from "@/lib/workspace/ClientNavContext";
import { ClientRail } from "@/components/ClientRail";
import { ClientContextPanel } from "@/components/ClientContextPanel";
import { ClientHeader } from "@/components/ClientHeader";

interface ClientWorkspaceShellProps {
  clientId: string;
  children: React.ReactNode;
}

export function ClientWorkspaceShell({ clientId, children }: ClientWorkspaceShellProps) {
  const pathname = usePathname();
  const initialSection = getSectionForPathname(pathname);

  return (
    <ClientNavProvider clientId={clientId} initialSection={initialSection}>
      {/* Dual-rail layout fills the full height provided by AppShell's <main> */}
      <div className="flex h-full overflow-hidden">
        {/* Rail 1 — 52px icon strip */}
        <ClientRail clientId={clientId} />

        {/* Rail 2 — 200px contextual sub-nav (desktop only) */}
        <div className="hidden md:flex">
          <ClientContextPanel clientId={clientId} />
        </div>

        {/* Main content area */}
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
          <ClientHeader clientId={clientId} />
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
      </div>
    </ClientNavProvider>
  );
}
