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
import { PayrollPanel } from "@/components/panels/PayrollPanel";
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
  // Home is the CONTENT fallback for routes no workspace owns (e.g.
  // /platform, /search) so this panel is never left blank — a deliberate,
  // separate decision from the rail's highlight, which must stay null
  // there instead of falsely lighting Home (see WorkspaceContext).
  const panelWorkspace = activeWorkspace ?? "home";

  // NO BOX OF ITS OWN. `NavShell` owns the 220px, the white, the border and
  // the collapse; this component is the CONTENT — which panel, for which
  // workspace. It used to carry its own `w-[220px] bg-white border-r`, and a
  // second box inside the shell's is how a width comes to be set in two places
  // and drift.
  return (
    <div className="flex flex-col h-full">
      {isSettings ? (
        <SettingsPanel />
      ) : (
        <>
          {panelWorkspace === "home" && <HomePanel />}
          {panelWorkspace === "clients" && (
            <ClientsPanel onOpenSearch={onOpenSearch} />
          )}
          {panelWorkspace === "deadlines" && <DeadlinesPanel />}
          {panelWorkspace === "work" && <WorkPanel />}
          {panelWorkspace === "team" && <TeamPanel />}
          {panelWorkspace === "ai" && <AIPanel />}
          {panelWorkspace === "accounting" && <AccountingPanel />}
          {panelWorkspace === "payroll" && <PayrollPanel />}
          {panelWorkspace === "relationships" && <RelationshipsPanel />}
          {panelWorkspace === "health" && <HealthPanel />}
          {panelWorkspace === "practice" && <PracticePanel />}
          {panelWorkspace === "knowledge" && <KnowledgePanel />}
          {panelWorkspace === "engagements" && <EngagementsPanel />}
        </>
      )}
    </div>
  );
}
