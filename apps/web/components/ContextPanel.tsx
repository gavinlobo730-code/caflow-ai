"use client";

import { usePathname } from "next/navigation";
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
import { PracticePanel } from "@/components/panels/PracticePanel";
import { KnowledgePanel } from "@/components/panels/KnowledgePanel";
import { SettingsPanel } from "@/components/panels/SettingsPanel";
import { EngagementsPanel } from "@/components/panels/EngagementsPanel";

interface ContextPanelProps {
  onOpenSearch: () => void;
}

export function ContextPanel({ onOpenSearch }: ContextPanelProps) {
  const { activeWorkspace } = useWorkspace();
  const pathname = usePathname();
  const isSettings = pathname.startsWith("/settings");

  return (
    <div className="flex flex-col h-full w-[220px] shrink-0 bg-white border-r border-gray-200">
      {isSettings ? (
        <SettingsPanel />
      ) : (
        <>
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
          {activeWorkspace === "practice" && <PracticePanel />}
          {activeWorkspace === "knowledge" && <KnowledgePanel />}
          {activeWorkspace === "engagements" && <EngagementsPanel />}
        </>
      )}
    </div>
  );
}
