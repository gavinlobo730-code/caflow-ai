"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { CLIENT_SECTIONS } from "@/lib/workspace/ClientNavContext";

interface ClientContextPanelProps {
  clientId: string;
}

const SECTION_DESCRIPTIONS: Record<string, string> = {
  overview:     "Client summary & health",
  accounting:   "Books, journals & reports",
  compliance:   "GST, TDS & MCA filings",
  payroll:      "Staff & salary runs",
  "year-end":   "Year-end close process",
  tax:          "Income tax returns",
  documents:    "Files & folders",
  tasks:        "Action items",
  reports:      "Management reports",
  portal:       "Client portal access",
  "ai-insights":"AI analysis & drafts",
};

export function ClientContextPanel({ clientId }: ClientContextPanelProps) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full w-[200px] shrink-0 bg-[#0f0f16] border-r border-white/[0.06]">
      <div className="px-3 py-3 border-b border-white/5">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-white/25">
          Client Workspace
        </p>
      </div>

      <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {CLIENT_SECTIONS.map(({ id, label, href }) => {
          const target = href(clientId);
          const active = pathname.startsWith(target);
          return (
            <Link
              key={id}
              href={target}
              className={cn(
                "flex flex-col rounded-lg px-2.5 py-2 transition-all duration-100",
                active
                  ? "bg-violet-600/15 border border-violet-500/20"
                  : "hover:bg-white/5 border border-transparent"
              )}
            >
              <span
                className={cn(
                  "text-[12.5px] font-medium",
                  active ? "text-violet-300" : "text-white/55 group-hover:text-white/80"
                )}
              >
                {label}
              </span>
              {active && (
                <span className="text-[10px] text-violet-400/60 mt-0.5 leading-tight">
                  {SECTION_DESCRIPTIONS[id]}
                </span>
              )}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
