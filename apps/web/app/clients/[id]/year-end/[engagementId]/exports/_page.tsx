"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { FileText, BarChart3, Package, Download, Loader2, AlertTriangle } from "lucide-react";
import { yearEndApi, type ExportRecord, type EngagementStatus } from "@/lib/api/yearEnd";
import { getSupabaseClient } from "@/lib/supabase/client";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const EXPORT_CONFIGS: {
  type: "financial_statements" | "notes" | "complete_pack";
  label: string;
  description: string;
  icon: React.ElementType;
  primary?: boolean;
}[] = [
  {
    type: "financial_statements",
    label: "Financial Statements PDF",
    description: "Balance Sheet and P&L in Schedule III format",
    icon: BarChart3,
  },
  {
    type: "notes",
    label: "Notes to Accounts PDF",
    description: "All notes to accounts (auto-generated + manual)",
    icon: FileText,
  },
  {
    type: "complete_pack",
    label: "Complete Year-End Pack",
    description: "Financial statements + notes + adjustments register",
    icon: Package,
    primary: true,
  },
];

const TYPE_LABELS: Record<string, string> = {
  financial_statements: "Financial Statements",
  notes: "Notes to Accounts",
  complete_pack: "Complete Pack",
};

export default function ExportsPage() {
  const params = useParams<{ id: string; engagementId: string }>();
  const { engagementId } = params;

  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatingType, setGeneratingType] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [engagementStatus, setEngagementStatus] = useState<EngagementStatus | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Both are plain filtered/single-row selects (year_end_exports,
      // year_end_engagements; RLS-scoped to the firm) — no server-side
      // computation, so read directly instead of round-tripping through the
      // FastAPI backend. Mirrors routers/year_end_exports.py::list_exports
      // (same table, engagement_id filter, created_at-desc ordering) and
      // routers/year_end.py::get_engagement (single row by id) — only the
      // `status` field of the latter is used here.
      const supabase = getSupabaseClient();
      const [exRes, engRes] = await Promise.all([
        supabase
          .from("year_end_exports")
          .select("*")
          .eq("engagement_id", engagementId)
          .order("created_at", { ascending: false }),
        supabase.from("year_end_engagements").select("*").eq("id", engagementId).single(),
      ]);
      if (exRes.error) throw exRes.error;
      setExports((exRes.data as ExportRecord[]) ?? []);
      if (!engRes.error && engRes.data) setEngagementStatus((engRes.data as { status: EngagementStatus }).status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string, ok: boolean) {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 5000);
  }

  async function handleGenerate(type: "financial_statements" | "notes" | "complete_pack") {
    setGeneratingType(type);
    try {
      const res = await yearEndApi.exports.generate(engagementId, type);
      if (!res.success) throw new Error(res.error ?? "Failed to generate");
      setExports((prev) => [res.data, ...prev]);
      showToast(`${TYPE_LABELS[type]} generated successfully.`, true);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Generation failed", false);
    } finally {
      setGeneratingType(null);
    }
  }

  function handleDownload(record: ExportRecord) {
    if (!record.download_url) {
      showToast("Download URL not available. Please regenerate.", false);
      return;
    }
    window.open(record.download_url, "_blank");
  }

  // Most recent export per type
  const latestByType: Record<string, ExportRecord | undefined> = {};
  for (const exp of exports) {
    if (!latestByType[exp.export_type]) latestByType[exp.export_type] = exp;
  }

  const isDraft = engagementStatus === "draft" || engagementStatus === "in_review";

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-36 rounded-xl bg-[#F8FAFC] animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 max-w-4xl">
      {toast && (
        <div className={`rounded-lg px-4 py-3 text-xs font-medium border ${toast.ok ? "bg-green-50 border-green-100 text-green-700" : "bg-red-50 border-red-100 text-red-700"}`}>
          {toast.msg}
        </div>
      )}

      {/* Draft warning banner */}
      {isDraft && (
        <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <AlertTriangle size={14} className="text-amber-600 flex-shrink-0" />
          <p className="text-xs font-medium text-amber-700">
            DRAFT — All exports will be watermarked. Approve the engagement to generate final copies.
          </p>
        </div>
      )}

      {/* Export cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {EXPORT_CONFIGS.map((cfg) => {
          const latest = latestByType[cfg.type];
          const Icon = cfg.icon;
          const isGenerating = generatingType === cfg.type;

          return (
            <div
              key={cfg.type}
              className={`bg-white rounded-xl border p-4 space-y-3 flex flex-col ${
                cfg.primary ? "border-blue-200 bg-blue-50/30" : "border-[#F1F5F9]"
              }`}
            >
              <div className="flex items-start gap-2">
                <Icon size={16} className={cfg.primary ? "text-blue-600" : "text-[#64748B]"} />
                <div className="flex-1 min-w-0">
                  <p className={`text-xs font-semibold ${cfg.primary ? "text-blue-700" : "text-[#334155]"}`}>
                    {cfg.label}
                  </p>
                  <p className="text-[10px] text-[#94A3B8] mt-0.5">{cfg.description}</p>
                </div>
              </div>

              {latest && (
                <p className="text-[10px] text-[#94A3B8]">
                  Last generated: {timeAgo(latest.generated_at ?? latest.created_at)}
                  {(latest.is_draft ?? false) && " · DRAFT"}
                </p>
              )}

              <div className="flex gap-2 mt-auto">
                <button
                  onClick={() => handleGenerate(cfg.type)}
                  disabled={!!generatingType}
                  className={`flex-1 flex items-center justify-center gap-1.5 text-xs py-2 rounded-lg disabled:opacity-50 ${
                    cfg.primary
                      ? "bg-blue-600 text-white hover:bg-blue-700"
                      : "border border-[#E2E8F0] text-[#475569] hover:bg-[#F8FAFC]"
                  }`}
                >
                  {isGenerating ? <Loader2 size={11} className="animate-spin" /> : null}
                  {isGenerating ? "Generating…" : "Generate"}
                </button>
                {latest?.download_url && (
                  <button
                    onClick={() => handleDownload(latest)}
                    className="flex items-center gap-1 text-xs px-2 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]"
                    title="Download latest"
                  >
                    <Download size={11} />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Export history table */}
      {exports.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#F8FAFC]">
            <p className="text-xs font-semibold text-[#334155]">Export History</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="px-4 py-2.5 text-left font-semibold">Type</th>
                  <th className="px-3 py-2.5 text-left font-semibold">Version</th>
                  <th className="px-3 py-2.5 text-left font-semibold">Generated By</th>
                  <th className="px-3 py-2.5 text-left font-semibold">Date</th>
                  <th className="px-3 py-2.5 text-left font-semibold">Status</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Download</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {exports.map((exp) => (
                  <tr key={exp.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2.5 text-[#334155]">{TYPE_LABELS[exp.export_type] ?? exp.export_type}</td>
                    <td className="px-3 py-2.5 text-[#64748B]">v{exp.version_number ?? 1}</td>
                    <td className="px-3 py-2.5 text-[#475569]">{exp.generated_by ?? exp.created_by}</td>
                    <td className="px-3 py-2.5 text-[#64748B] whitespace-nowrap">
                      {new Date(exp.generated_at ?? exp.created_at).toLocaleDateString("en-IN", {
                        day: "numeric", month: "short", year: "numeric",
                      })}
                    </td>
                    <td className="px-3 py-2.5">
                      {(exp.is_draft ?? false) ? (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700">Draft</span>
                      ) : (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-green-100 text-green-700">Final</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {exp.download_url ? (
                        <button
                          onClick={() => handleDownload(exp)}
                          className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                        >
                          <Download size={11} /> Download
                        </button>
                      ) : (
                        <span className="text-[10px] text-[#CBD5E1]">Unavailable</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {exports.length === 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-10">
          <p className="text-xs text-[#94A3B8]">No exports generated yet. Click Generate above.</p>
        </div>
      )}
    </div>
  );
}
