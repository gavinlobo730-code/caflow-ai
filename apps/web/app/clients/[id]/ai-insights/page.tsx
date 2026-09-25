"use client";

import { useEffect, useState } from "react";
import { Sparkles, AlertTriangle, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SkeletonText } from "@/components/ui/skeleton";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { usePermissions } from "@/lib/auth/AuthContext";
import { api } from "@/lib/api";

interface AiInsight {
  id: string;
  insight_type: string;
  title: string;
  description: string;
  severity: "info" | "warning" | "critical";
  created_at: string;
}

export default function AiInsightsPage() {
  const { clientId } = useClientNav();
  const [insights, setInsights] = useState<AiInsight[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no insights generated yet" — a masked
  // failure here reads as a client with nothing to flag, which it may not be.
  const [loadFailed, setLoadFailed] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  // `rbac("report", "write")` is what the endpoint asks for. `resolved` keeps
  // the button out of the way while the permission map is still in flight,
  // rather than flashing a control the server would refuse.
  const { can, resolved } = usePermissions();
  const mayGenerate = resolved && can("report", "write");

  /**
   * ⚠️ THE GENERATOR EXISTED AND NOTHING COULD PRESS IT.
   * `domain/ai_insight_service.generate_insights_for_client` is written and
   * tested, `POST /api/ai-insights/generate/{client_id}` mounts it, and
   * `api.aiInsights.generate` has carried the method in `lib/api` with NO
   * caller — so this screen read `ai_insights` over PostgREST and showed an
   * empty list for every client, for ever, with a working writer one button
   * away. The `capital_wip` shape again.
   *
   * ⚠️ AND THE EMPTY STATE SAID SOMETHING FALSE: "Insights are generated
   * automatically as activity is recorded for this client." Nothing generates
   * them automatically — no job, no trigger, no posting path — so that
   * sentence told a CA to wait for something that was never going to happen,
   * which is worse than an empty screen that admits it.
   */
  async function generate() {
    if (!clientId || clientId === "_placeholder") return;
    setGenerating(true);
    setGenerateError(null);
    try {
      const res = await api.aiInsights.generate(clientId) as
        { success?: boolean; error?: string };
      // The router answers a refusal as HTTP 200 with `success: false`, the
      // same shape the GST workspace does — an unchecked call would show
      // "done" for a request the server declined.
      if (!res?.success) {
        setGenerateError(res?.error || "The insights could not be generated.");
        return;
      }
      await load();
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : "The insights could not be generated.");
    } finally {
      setGenerating(false);
    }
  }

  async function load() {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const { getSupabaseClient } = await import("@/lib/supabase/client");
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from("ai_insights")
        // insight_type, not "type" — PostgREST rejects the WHOLE select on one
        // unknown column, so this query used to 400 and the page rendered its
        // error state instead of any insights at all.
        .select("id, insight_type, title, description, severity, created_at")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false })
        .limit(20);
      if (error) throw error;
      setInsights(data ?? []);
      setLoadFailed(false);
    } catch {
      setInsights([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, [clientId]); // eslint-disable-line react-hooks/exhaustive-deps

  const SEVERITY_COLORS = {
    info: "bg-sev-low-surface border-sev-low-border text-sev-low",
    warning: "bg-sev-medium-surface border-sev-medium-border text-sev-medium",
    critical: "bg-sev-critical-surface border-sev-critical-border text-sev-critical",
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Sparkles size={15} className="text-gold" />
              AI Insights
            </CardTitle>
            {mayGenerate && (
              <button
                onClick={generate}
                disabled={generating || loading}
                className="shrink-0 flex items-center gap-1.5 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-label disabled:opacity-50"
              >
                {generating
                  ? <RefreshCw size={12} className="animate-spin" />
                  : <Sparkles size={12} />}
                {generating ? "Generating…" : "Generate"}
              </button>
            )}
          </div>
          {generateError && (
            <p className="text-xs text-state-problem mt-2">{generateError}</p>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3" role="status" aria-label="Loading insights">
              {[1, 2, 3].map((i) => (
                <div key={i} className="rounded-lg border border-ps-muted px-4 py-3">
                  <SkeletonText lines={2} />
                </div>
              ))}
            </div>
          ) : loadFailed ? (
            <div className="text-center py-12 space-y-2">
              <p className="text-sm text-red-600 font-medium">Couldn&apos;t load AI insights — the request failed or timed out.</p>
              <button disabled={loading} onClick={load} className="disabled:opacity-40 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">Retry</button>
            </div>
          ) : insights.length === 0 ? (
            <div className="text-center py-12 space-y-2">
              <Sparkles className="w-8 h-8 text-ps-disabled mx-auto" />
              <p className="text-sm text-ps-hint">No AI insights yet</p>
              <p className="text-xs text-ps-disabled max-w-sm mx-auto">
                {mayGenerate
                  ? "Nothing generates these on its own — press Generate to read this client's books, compliance and activity and record what it finds."
                  : "Nothing generates these on its own. Someone with report-write permission can generate them from this screen."}
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
