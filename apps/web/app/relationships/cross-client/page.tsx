"use client";

import { useState, useEffect } from "react";
import { Copy, CheckCircle, XCircle, Search } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

interface CrossClientMatch {
  id: string;
  entity_id: string;
  client_a_id: string;
  client_b_id: string;
  match_type: string;
  confidence_score: number;
  is_confirmed: boolean | null;
  notes: string | null;
  entity?: { full_name: string; entity_type: string };
  created_at: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

export default function CrossClientMatchesPage() {
  const [matches, setMatches] = useState<CrossClientMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "pending" | "confirmed" | "rejected">("all");
  const [updating, setUpdating] = useState<string | null>(null);

  useEffect(() => {
    loadMatches();
  }, []);

  async function loadMatches() {
    setLoading(true);
    setError(null);
    try {
      const res: ApiResponse<CrossClientMatch[]> = await apiFetch("/api/relationships/cross-client-matches");
      if (res.success) {
        setMatches(res.data ?? []);
      } else {
        setError(res.error ?? "Failed to load cross-client matches");
      }
    } catch {
      setError("Network error — could not reach server");
    } finally {
      setLoading(false);
    }
  }

  async function handleReview(id: string, confirmed: boolean) {
    setUpdating(id);
    try {
      await apiFetch(`/api/relationships/cross-client-matches/${id}/review`, {
        method: "POST",
        body: JSON.stringify({ is_confirmed: confirmed }),
      });
      setMatches((prev) =>
        prev.map((m) => (m.id === id ? { ...m, is_confirmed: confirmed } : m))
      );
    } catch {
      // silent — match state stays unchanged
    } finally {
      setUpdating(null);
    }
  }

  const filtered = matches.filter((m) => {
    const name = m.entity?.full_name?.toLowerCase() ?? "";
    const matchesSearch = name.includes(search.toLowerCase());
    const matchesFilter =
      filter === "all" ||
      (filter === "pending" && m.is_confirmed === null) ||
      (filter === "confirmed" && m.is_confirmed === true) ||
      (filter === "rejected" && m.is_confirmed === false);
    return matchesSearch && matchesFilter;
  });

  const statusBadge = (m: CrossClientMatch) => {
    if (m.is_confirmed === null)
      return <Badge className="bg-yellow-800 text-yellow-300">Pending</Badge>;
    if (m.is_confirmed)
      return <Badge className="bg-emerald-800 text-emerald-300">Confirmed</Badge>;
    return <Badge className="bg-red-900 text-red-300">Rejected</Badge>;
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Copy className="w-6 h-6 text-violet-400" />
          Cross-Client Matches
        </h1>
        <p className="text-sm text-white/50 mt-1">
          Entities appearing across multiple clients — confirm or reject each match.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input
            className="w-full bg-[#1E293B] border border-white/10 rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500"
            placeholder="Search entity name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          {(["all", "pending", "confirmed", "rejected"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-2 rounded-lg text-xs font-medium capitalize transition-colors ${
                filter === f
                  ? "bg-violet-600 text-white"
                  : "bg-[#1E293B] text-white/50 hover:text-white"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16">
          <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {error && (
        <Card className="bg-red-950/30 border-red-800/40">
          <CardContent className="p-4 text-sm text-red-300">{error}</CardContent>
        </Card>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="text-center py-16 text-white/30 text-sm">
          No cross-client matches found.
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="space-y-3">
          {filtered.map((m) => (
            <Card key={m.id} className="bg-[#1E293B] border-white/10">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-white font-medium truncate">
                        {m.entity?.full_name ?? m.entity_id}
                      </span>
                      {statusBadge(m)}
                      <Badge className="bg-slate-700 text-slate-300 capitalize">
                        {m.match_type?.replace(/_/g, " ")}
                      </Badge>
                    </div>
                    <p className="text-xs text-white/40 mt-1">
                      Confidence: {Math.round((m.confidence_score ?? 0) * 100)}%
                    </p>
                    {m.notes && (
                      <p className="text-xs text-white/50 mt-1">{m.notes}</p>
                    )}
                  </div>

                  {m.is_confirmed === null && (
                    <div className="flex gap-2 shrink-0">
                      <button
                        disabled={updating === m.id}
                        onClick={() => handleReview(m.id, true)}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-800/40 text-emerald-300 hover:bg-emerald-700/50 text-xs font-medium transition-colors disabled:opacity-50"
                      >
                        <CheckCircle className="w-3.5 h-3.5" />
                        Confirm
                      </button>
                      <button
                        disabled={updating === m.id}
                        onClick={() => handleReview(m.id, false)}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-900/40 text-red-300 hover:bg-red-800/50 text-xs font-medium transition-colors disabled:opacity-50"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
