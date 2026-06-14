"use client";

import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { HomePanel } from "@/components/panels/HomePanel";
import { ClientsPanel } from "@/components/panels/ClientsPanel";
import { DeadlinesPanel } from "@/components/panels/DeadlinesPanel";
import { WorkPanel } from "@/components/panels/WorkPanel";
import { TeamPanel } from "@/components/panels/TeamPanel";
import { AIPanel } from "@/components/panels/AIPanel";
import { AccountingPanel } from "@/components/panels/AccountingPanel";
import { RelationshipsPanel } from "@/components/panels/RelationshipsPanel";
import { HealthPanel } from "@/components/panels/HealthPanel";

interface ContextPanelProps {
  onOpenSearch: () => void;
}

export function ContextPanel({ onOpenSearch }: ContextPanelProps) {
  const { activeWorkspace } = useWorkspace();

  return (
    <div className="flex flex-col h-full w-[220px] shrink-0 bg-white border-r border-gray-200">
      {activeWorkspace === "home" && <HomePanel />}
      {activeWorkspace === "clients" && (
        <ClientsPanel onOpenSearch={onOpenSearch} />
      )}
      {activeWorkspace === "deadlines" && <DeadlinesPanel />}
      {activeWorkspace === "work" && <WorkPanel />}
      {activeWorkspace === "team" && <TeamPanel />}
      {activeWorkspace === "ai" && <AIPanel />}
      {activeWorkspace === "accounting" && <AccountingPanel />}
      {activeWorkspace === "relationships" && <RelationshipsPanel />}
      {activeWorkspace === "health" && <HealthPanel />}
    </div>
  );
}
