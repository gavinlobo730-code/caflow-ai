"use client";

import { ClientHeader } from "@/components/ClientHeader";

/**
 * What is left of the client workspace's own shell: its HEADER.
 *
 * It used to render `ClientNavProvider` + `ClientContextPanel` + the layout
 * around them — a second shell, with its own collapse, storage key, mobile
 * drawer, close-on-navigate effect and back link. `NavShell` owns all of that
 * once now, for both scopes, and `AppShell` hoisted the provider so the one
 * shell can render `ClientSections` beside the constant rail.
 *
 * The header stays because it is CONTENT, not chrome: the client's name and
 * the switcher that moves to the same section of a different client.
 */
export function ClientWorkspaceShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col h-full min-h-0">
      <ClientHeader />
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </div>
  );
}
