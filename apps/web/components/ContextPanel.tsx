"use client";

import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { HomePanel } from "@/components/panels/HomePanel";
import { ClientsPanel } from "@/components/panels/ClientsPanel";
import { CompliancePanel } from "@/components/panels/CompliancePanel";
import { AccountsPanel } from "@/components/panels/AccountsPanel";
import { TeamPanel } from "@/components/panels/TeamPanel";
import { AIPanel } from "@/components/panels/AIPanel";

interface ContextPanelProps {
  onOpenSearch: () => void;
}

export function ContextPanel({ onOpenSearch }: ContextPanelProps) {
  const { activeWorkspace } = useWorkspace();

  return (
    <div className="flex flex-col h-full w-[220px] shrink-0 bg-[#111118] border-r border-white/[0.06]">
      {activeWorkspace === "home" && <HomePanel />}
      {activeWorkspace === "clients" && (
        <ClientsPanel onOpenSearch={onOpenSearch} />
      )}
      {activeWorkspace === "compliance" && <CompliancePanel />}
      {activeWorkspace === "accounts" && <AccountsPanel />}
      {activeWorkspace === "team" && <TeamPanel />}
      {activeWorkspace === "ai" && <AIPanel />}
    </div>
  );
}
