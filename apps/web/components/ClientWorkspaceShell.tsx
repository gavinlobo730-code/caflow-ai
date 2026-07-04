"use client";

import { ClientNavProvider } from "@/lib/workspace/ClientNavContext";
import { ClientContextPanel } from "@/components/ClientContextPanel";
import { ClientHeader } from "@/components/ClientHeader";

interface ClientWorkspaceShellProps {
  children: React.ReactNode;
}

export function ClientWorkspaceShell({ children }: ClientWorkspaceShellProps) {
  return (
    <ClientNavProvider>
      <div className="flex h-full overflow-hidden">
        {/* Single collapsible sidebar — handles desktop + mobile drawer */}
        <ClientContextPanel />

        {/* Main content area */}
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
          <ClientHeader />
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
      </div>
    </ClientNavProvider>
  );
}
