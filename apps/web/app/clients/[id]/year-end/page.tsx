"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Plus, Loader2, Calendar, ChevronRight, FileCode } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { ListSkeleton } from "@/components/ui/skeleton";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const FY_OPTIONS = ["2025-26", "2024-25", "2023-24", "2022-23"];

const STATUS_BADGE: Record<string, string> = {
  draft:     "bg-[#F1F5F9] text-[#475569]",
  in_review: "bg-amber-100 text-amber-700",
  approved:  "bg-blue-100 text-blue-700",
  locked:    "bg-green-100 text-green-700",
};

interface Engagement {
  id: string;
  financial_year: string;
  status: string;
  engagement_name: string | null;
  created_at: string;
}

async function apiFetch(path: string, opts?: RequestInit) {
  const { supabase } = await import("@/lib/supabase/client");
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

export default function YearEndPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const clientId = params.id;

  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedFY, setSelectedFY] = useState(FY_OPTIONS[0]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    setError(null);
    try {
      // Plain filtered select (year_end_engagements, RLS-scoped to the firm) —
      // no server-side computation, so read directly instead of round-tripping
      // through the FastAPI backend (which cold-starts on its hosting tier).
      // Mirrors routers/year_end.py::list_engagements: same table, same
      // client_id filter, same created_at-desc ordering.
      const supabase = getSupabaseClient();
      const { data, error: sbError } = await supabase
        .from("year_end_engagements")
        .select("*")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });
      if (sbError) throw sbError;
      setEngagements((data as Engagement[]) ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function handleCreate() {
    setCreating(true);
    setCreateError(null);
    try {
      const res = await apiFetch("/api/year-end/engagements", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, financial_year: selectedFY }),
      });
      if (!res.success) throw new Error(res.error ?? "Failed to create");
      setShowCreate(false);
      router.push(`/clients/${clientId}/year-end/${res.data.id}`);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="p-6 max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">Year-End Engagements</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">Schedule III financial statements, notes, and audit pack</p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href={`/clients/${clientId}/year-end/xbrl`}
            className="flex items-center gap-1.5 text-xs bg-white border border-[#E2E8F0] text-[#334155] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
          >
            <FileCode size={12} /> XBRL Filing
          </Link>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <Plus size={12} /> New Engagement
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">New Year-End Engagement</p>
          <div>
            <label className="text-xs text-[#64748B] mb-1 block">Financial Year</label>
            <select
              value={selectedFY}
              onChange={(e) => setSelectedFY(e.target.value)}
              className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {FY_OPTIONS.map((fy) => (
                <option key={fy} value={fy}>{fy}</option>
              ))}
            </select>
          </div>
          {createError && <p className="text-xs text-red-600">{createError}</p>}
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC]">
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
            >
              {creating && <Loader2 size={10} className="animate-spin" />}
              Create
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <ListSkeleton rows={3} />
      ) : error ? (
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
          {error} <button onClick={load} className="ml-2 underline text-xs">Retry</button>
        </div>
      ) : engagements.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-2">
          <Calendar size={28} className="text-gray-200 mx-auto" />
          <p className="text-sm text-[#64748B]">No year-end engagements yet</p>
          <p className="text-xs text-[#94A3B8]">Click &quot;New Engagement&quot; to start the year-end close process.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {engagements.map((eng) => (
            <button
              key={eng.id}
              onClick={() => router.push(`/clients/${clientId}/year-end/${eng.id}`)}
              className="w-full bg-white rounded-xl border border-[#F1F5F9] px-4 py-3 flex items-center gap-3 hover:bg-[#F8FAFC] text-left"
            >
              <Calendar size={16} className="text-blue-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[#1E293B]">
                  {eng.engagement_name ?? `FY ${eng.financial_year}`}
                </p>
                <p className="text-[10px] text-[#94A3B8]">
                  Created {new Date(eng.created_at).toLocaleDateString("en-IN")}
                </p>
              </div>
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full capitalize ${STATUS_BADGE[eng.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                {eng.status.replace("_", " ")}
              </span>
              <ChevronRight size={14} className="text-[#CBD5E1] flex-shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
