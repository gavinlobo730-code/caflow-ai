"use client";

import { useEffect, useState } from "react";
import { Sparkles, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

interface AiInsight {
  id: string;
  type: string;
  title: string;
  description: string;
  severity: "info" | "warning" | "critical";
  created_at: string;
}

export default function AiInsightsPage() {
  const { clientId } = useClientNav();
  const [insights, setInsights] = useState<AiInsight[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    async function load() {
      try {
        const { getSupabaseClient } = await import("@/lib/supabase/client");
        const supabase = getSupabaseClient();
        const { data } = await supabase
          .from("ai_insights")
          .select("id, type, title, description, severity, created_at")
          .eq("client_id", clientId)
          .order("created_at", { ascending: false })
          .limit(20);
        setInsights(data ?? []);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [clientId]);

  const SEVERITY_COLORS = {
    info: "bg-blue-50 border-blue-100 text-blue-700",
    warning: "bg-amber-50 border-amber-100 text-amber-700",
    critical: "bg-red-50 border-red-100 text-red-700",
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Sparkles size={15} className="text-[#B9915E]" />
            AI Insights
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="h-32 animate-pulse bg-[#F8FAFC] rounded" />
          ) : insights.length === 0 ? (
            <div className="text-center py-12 space-y-2">
              <Sparkles className="w-8 h-8 text-gray-200 mx-auto" />
              <p className="text-sm text-[#94A3B8]">No AI insights yet</p>
              <p className="text-xs text-[#CBD5E1]">
                Insights are generated automatically as activity is recorded for this client.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {insights.map((insight) => (
                <div
                  key={insight.id}
                  className={`rounded-lg border px-4 py-3 ${SEVERITY_COLORS[insight.severity] ?? SEVERITY_COLORS.info}`}
                >
                  <div className="flex items-start gap-2">
                    {insight.severity !== "info" && <AlertTriangle size={14} className="mt-0.5 shrink-0" />}
                    <div>
                      <p className="text-sm font-medium">{insight.title}</p>
                      {insight.description && (
                        <p className="text-xs mt-0.5 opacity-80">{insight.description}</p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
