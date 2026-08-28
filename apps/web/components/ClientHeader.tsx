"use client";

import { useEffect, useState } from "react";
import { Building2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getLatestHealthScore } from "@/lib/services/health-score-compute";
import { HealthBadge } from "@/components/HealthBadge";

interface ClientData {
  id: string;
  client_name: string;
  entity_type?: string;
  gstin?: string;
}

export function ClientHeader() {
  const { clientId } = useClientNav();
  const [client, setClient] = useState<ClientData | null>(null);
  const [clientLoadFailed, setClientLoadFailed] = useState(false);
  const [health, setHealth] = useState<{ overall_score: number; trend: "improving" | "stable" | "declining" | null } | null>(null);

  useEffect(() => {
    setClient(null);
    setClientLoadFailed(false);
    // clientId is empty on the first render after a route change, and is the
    // literal "_placeholder" on the statically-exported shell before the real
    // id is read from the URL. Sending either to PostgREST produced
    // `id=eq.` against a uuid column — SQLSTATE 22P02, "invalid input syntax
    // for type uuid", logged in production on every client page load. The
    // request could never have succeeded, and its failure also tripped
    // setClientLoadFailed, so the header flashed "Couldn't load client"
    // before the real fetch replaced it.
    //
    // Same guard the journal editor already uses for exactly this reason.
    if (!clientId || clientId === "_placeholder") return;
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

    </header>
  );
}
