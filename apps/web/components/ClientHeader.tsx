"use client";

import { useEffect, useState } from "react";
import { ChevronDown, Building2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useClientNav, getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getLatestHealthScore } from "@/lib/services/health-score-compute";
import { HealthBadge } from "@/components/HealthBadge";

interface ClientData {
  id: string;
  client_name: string;
  entity_type?: string;
  gstin?: string;
}

function getFYOptions(): string[] {
  const current = getCurrentFinancialYear();
  const [startStr] = current.split("-");
  const start = parseInt(startStr, 10);
  return [
    `${start + 1}-${String(start + 2).slice(-2)}`,
    current,
    `${start - 1}-${String(start).slice(-2)}`,
    `${start - 2}-${String(start - 1).slice(-2)}`,
  ];
}

export function ClientHeader() {
  const { clientId, financialYear, setFinancialYear } = useClientNav();
  const [client, setClient] = useState<ClientData | null>(null);
  const [clientLoadFailed, setClientLoadFailed] = useState(false);
  const [fyOpen, setFyOpen] = useState(false);
  const [health, setHealth] = useState<{ overall_score: number; trend: "improving" | "stable" | "declining" | null } | null>(null);

  useEffect(() => {
    setClient(null);
    setClientLoadFailed(false);
    const supabase = getSupabaseClient();
    supabase
      .from("clients")
      .select("id, client_name, entity_type, gstin")
      .eq("id", clientId)
      .single()
      .then(({ data, error }) => {
        // Distinguishes "still loading" from "failed to load" — without
        // this, a failed fetch left the header showing "Loading…"
        // permanently, indistinguishable from a slow request in flight.
        if (data) {
          setClient(data as ClientData);
        } else {
          setClientLoadFailed(true);
          if (error) console.error("ClientHeader: failed to load client", error);
        }
      });
    getLatestHealthScore(clientId).then((h) => {
      if (h) setHealth({ overall_score: h.overall_score, trend: h.trend });
    }).catch((e) => console.error("ClientHeader: failed to load health score", e));
  }, [clientId]);

  const fyOptions = getFYOptions();

  return (
    <header className="flex items-center gap-4 h-12 pl-12 pr-4 md:px-4 bg-white border-b border-gray-200 shrink-0">
      <Building2 size={15} className="text-gray-400 shrink-0" />

      <div className="flex items-center gap-3 min-w-0 flex-1">
        <span className={cn("text-[13px] font-semibold truncate", clientLoadFailed ? "text-red-600" : "text-[#182350]")}>
          {client?.client_name ?? (clientLoadFailed ? "Couldn't load client" : "Loading…")}
        </span>
        {client?.entity_type && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 shrink-0">
            {client.entity_type}
          </span>
        )}
        {client?.gstin && (
          <span className="text-[10px] font-mono text-gray-500 shrink-0 hidden lg:inline">
            {client.gstin}
          </span>
        )}
      </div>

      {/* Health badge */}
      {health && (
        <HealthBadge score={health.overall_score} size="sm" trend={health.trend} />
      )}

      {/* FY Selector */}
      <div className="relative shrink-0">
        <button
          onClick={() => setFyOpen((o) => !o)}
          title={financialYear === getCurrentFinancialYear() ? undefined : "You are viewing a non-current financial year"}
          className={cn(
            "flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1.5 rounded-lg transition-colors",
            financialYear === getCurrentFinancialYear()
              ? "text-gray-500 hover:text-[#182350] bg-gray-100 hover:bg-gray-200"
              : "text-amber-700 bg-amber-100 hover:bg-amber-200",
          )}
        >
          FY {financialYear}
          {financialYear !== getCurrentFinancialYear() && (
            <span className="text-[9px] uppercase tracking-wide">• not current</span>
          )}
          <ChevronDown size={11} className={cn("transition-transform", fyOpen && "rotate-180")} />
        </button>

        {fyOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setFyOpen(false)} />
            <div className="absolute right-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded-lg shadow-xl py-1 min-w-[120px]">
              {fyOptions.map((fy) => (
                <button
                  key={fy}
                  onClick={() => { setFinancialYear(fy); setFyOpen(false); }}
                  className={cn(
                    "w-full text-left px-3 py-1.5 text-[11px] transition-colors",
                    fy === financialYear
                      ? "text-white bg-[#182350]"
                      : "text-gray-500 hover:text-[#182350] hover:bg-[#F8FAFC]"
                  )}
                >
                  FY {fy}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </header>
  );
}
