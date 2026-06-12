"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { AlertOctagon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  return res.json();
}

type Grade = "A" | "B" | "C" | "D" | "F";

interface ClientScore {
  id: string; client_id: string; client_name?: string;
  overall_score: number; health_grade: Grade; is_critical: boolean; calculated_at?: string;
}

function scoreColor(s: number) { return s >= 70 ? "text-green-400" : s >= 40 ? "text-yellow-400" : "text-red-400"; }
function gradeBadge(g: Grade) {
  const m: Record<Grade, string> = { A: "bg-green-800 text-green-300", B: "bg-blue-800 text-blue-300", C: "bg-yellow-800 text-yellow-300", D: "bg-orange-800 text-orange-300", F: "bg-red-800 text-red-300" };
  return m[g] ?? "bg-gray-700 text-gray-300";
}
function formatDate(d?: string | null) { if (!d) return "—"; try { return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); } catch { return d; } }

export default function CriticalClientsPage() {
  const [clients, setClients] = useState<ClientScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const json = await apiFetch("/api/health/scores?is_critical=true");
        if (!json.success) throw new Error(json.error ?? "Failed");
        setClients(json.data ?? []);
      } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
      finally { setLoading(false); }
    })();
  }, []);

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center gap-3">
        <AlertOctagon size={20} className="text-red-400" />
        <div>
          <h1 className="text-base font-semibold text-white">Critical Clients</h1>
          <p className="text-xs text-slate-400">Health score below 40 — requires immediate attention</p>
        </div>
      </div>
      {error && <div className="bg-red-900/30 text-red-400 border border-red-800 rounded-lg px-4 py-3 text-sm">{error}</div>}
      {loading ? (
        <div className="space-y-2 animate-pulse">{[1,2,3].map(i => <div key={i} className="h-14 bg-white/[0.05] rounded-xl" />)}</div>
      ) : clients.length === 0 ? (
        <Card className="bg-gray-800 border-gray-700"><CardContent className="py-12 text-center"><p className="text-sm text-slate-500">No critical clients — all scores are 40 or above</p></CardContent></Card>
      ) : (
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead><tr className="text-xs text-slate-500 border-b border-gray-700">
                <th className="px-5 py-3 text-left font-medium">Client</th>
                <th className="px-3 py-3 text-left font-medium">Score</th>
                <th className="px-3 py-3 text-left font-medium">Grade</th>
                <th className="px-3 py-3 text-left font-medium">Last Calculated</th>
                <th className="px-3 py-3 text-left font-medium"></th>
              </tr></thead>
              <tbody className="divide-y divide-gray-700/50">
                {clients.map((c) => (
                  <tr key={c.id} className="hover:bg-gray-700/30">
                    <td className="px-5 py-3 text-white text-xs font-medium">{c.client_name ?? c.client_id.slice(0,12)}</td>
                    <td className="px-3 py-3"><span className={`font-bold ${scoreColor(c.overall_score)}`}>{c.overall_score}</span><span className="text-xs text-slate-500">/100</span></td>
                    <td className="px-3 py-3"><Badge className={`text-[10px] ${gradeBadge(c.health_grade)}`}>{c.health_grade}</Badge></td>
                    <td className="px-3 py-3 text-slate-400 text-xs">{formatDate(c.calculated_at)}</td>
                    <td className="px-3 py-3"><Link href={`/health/${c.client_id}`} className="text-xs text-blue-400 hover:underline">View →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
