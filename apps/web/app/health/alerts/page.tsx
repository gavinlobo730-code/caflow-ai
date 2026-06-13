"use client";

import { useState, useEffect } from "react";
import { Bell, CheckCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, { ...opts, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(opts?.headers ?? {}) } });
  return res.json();
}

interface HealthAlert {
  id: string; alert_type: string; severity: "low" | "medium" | "high" | "critical";
  message: string; client_id: string; is_resolved: boolean; created_at: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  low: "bg-blue-100 text-blue-700",
  medium: "bg-yellow-100 text-yellow-700",
  high: "bg-orange-100 text-orange-700",
  critical: "bg-red-100 text-red-700",
};
function formatDate(d: string) { try { return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); } catch { return d; } }

export default function HealthAlertsPage() {
  const [alerts, setAlerts] = useState<HealthAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const json = await apiFetch("/api/health/alerts");
        if (!json.success) throw new Error(json.error ?? "Failed");
        setAlerts(json.data ?? []);
      } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
      finally { setLoading(false); }
    })();
  }, []);

  async function handleResolve(alertId: string) {
    setResolving(alertId);
    try {
      const json = await apiFetch(`/api/health/alerts/${alertId}/resolve`, { method: "POST", body: JSON.stringify({}) });
      if (json.success) setAlerts((prev) => prev.filter((a) => a.id !== alertId));
    } catch { /* non-fatal */ }
    finally { setResolving(null); }
  }

  return (
    <div className="p-6 space-y-5 bg-[#F8FAFC] min-h-full">
      <div className="flex items-center gap-3">
        <Bell size={20} className="text-amber-500" />
        <div>
          <h1 className="text-2xl font-bold text-[#182350]">Health Alerts</h1>
          <p className="text-sm text-gray-500">Active unresolved alerts across all clients</p>
        </div>
      </div>
      {error && <div className="bg-red-50 text-red-600 border border-red-200 rounded-lg px-4 py-3 text-sm">{error}</div>}
      {loading ? (
        <div className="space-y-2 animate-pulse">{[1,2,3].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl" />)}</div>
      ) : alerts.length === 0 ? (
        <Card className="bg-white border-gray-200 shadow-sm"><CardContent className="py-12 text-center"><CheckCircle size={32} className="text-green-500 mx-auto mb-2" /><p className="text-sm text-gray-500">No active alerts — all clear</p></CardContent></Card>
      ) : (
        <div className="space-y-2">
          {alerts.map((a) => (
            <Card key={a.id} className="bg-white border-gray-200 shadow-sm">
              <CardContent className="p-4 flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge className={`text-[10px] ${SEVERITY_COLORS[a.severity] ?? "bg-gray-100 text-gray-600"}`}>{a.severity.toUpperCase()}</Badge>
                    <span className="text-[10px] text-gray-500">{a.alert_type}</span>
                  </div>
                  <p className="text-sm text-gray-800">{a.message}</p>
                  <p className="text-xs text-gray-500 mt-1">Client: {a.client_id.slice(0,12)}… · {formatDate(a.created_at)}</p>
                </div>
                <button
                  onClick={() => handleResolve(a.id)}
                  disabled={resolving === a.id}
                  className="shrink-0 text-xs text-emerald-700 border border-emerald-300 px-2.5 py-1 rounded hover:bg-emerald-50 disabled:opacity-50"
                >
                  {resolving === a.id ? "…" : "Resolve"}
                </button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
