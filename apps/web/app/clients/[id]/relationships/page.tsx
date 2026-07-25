"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, X, Network } from "lucide-react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { formatDate as formatDateShared } from "@/lib/services/formatting";
import { TableSkeleton } from "@/components/ui/skeleton";

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

interface EntityRole {
  id: string;
  entity_id: string;
  entity_name?: string;
  role_type: string;
  ownership_percent?: number;
  effective_from?: string;
  effective_to?: string;
}

interface CrossClientMatch {
  id: string;
  pan: string;
  entity_id: string;
  client_id_a: string;
  client_id_b: string;
  match_type: string;
  is_reviewed: boolean;
  is_confirmed?: boolean;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

const ROLE_TYPE_COLORS: Record<string, string> = {
  Director:               "bg-blue-100 text-blue-700",
  Shareholder:            "bg-purple-100 text-purple-700",
  Partner:                "bg-violet-100 text-violet-700",
  Trustee:                "bg-teal-100 text-teal-700",
  Proprietor:             "bg-cyan-100 text-cyan-700",
  Guarantor:              "bg-orange-100 text-orange-700",
  "Authorized Signatory": "bg-emerald-100 text-emerald-700",
};

function formatDate(d?: string | null) {
  if (!d) return "—";
  try { return formatDateShared(d); }
  catch { return d; }
}

export default function ClientRelationshipsPage() {
  const { clientId } = useClientNav();
  const [roles, setRoles] = useState<EntityRole[]>([]);
  const [matches, setMatches] = useState<CrossClientMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addRoleModal, setAddRoleModal] = useState(false);
  const [roleForm, setRoleForm] = useState({ entity_id: "", role_type: "Director", ownership_percent: "" });
  const [savingRole, setSavingRole] = useState(false);
  const [detectLoading, setDetectLoading] = useState(false);

  const loadAll = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      // Direct Supabase read (not api/relationships/cross-client-matches) — a
      // plain read with no server-side computation, so routing it through the
      // FastAPI backend only adds a cold-start hit. Mirrors
      // routers/relationships.py's list_cross_client_matches (reviewed=false,
      // newest first), but scoped server-side to THIS client instead of
      // fetching every unreviewed match for the whole firm and filtering
      // client-side: a cross_client_matches row references two different
      // clients (client_id_a / client_id_b), so "scoped to this client" means
      // either side references it — same condition the old code applied
      // in-browser after the firm-wide fetch.
      const db = getSupabaseClient();
      const { data, error: matchesError } = await db
        .from("cross_client_matches")
        .select("*")
        .eq("reviewed", false)
        .or(`client_id_a.eq.${clientId},client_id_b.eq.${clientId}`)
        .order("created_at", { ascending: false });
      if (matchesError) throw matchesError;
      setMatches((data as CrossClientMatch[]) ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function handleDetectMatches() {
    setDetectLoading(true);
    try {
      await apiFetch("/api/relationships/cross-client-matches/detect", {
        method: "POST",
        body: JSON.stringify({}),
      });
      await loadAll();
    } catch { /* non-fatal */ }
    finally { setDetectLoading(false); }
  }

  async function handleAddRole() {
    if (!roleForm.entity_id || !roleForm.role_type) return;
    setSavingRole(true);
    try {
      const json: ApiResponse<EntityRole> = await apiFetch(
        `/api/relationships/entities/${roleForm.entity_id}/roles`,
        {
          method: "POST",
          body: JSON.stringify({
            client_id: clientId,
            role_type: roleForm.role_type,
            ownership_percent: roleForm.ownership_percent ? parseInt(roleForm.ownership_percent, 10) : null,
          }),
        }
      );
      if (!json.success) throw new Error(json.error ?? "Failed to add role");
      setRoles((prev) => [json.data, ...prev]);
      setAddRoleModal(false);
      setRoleForm({ entity_id: "", role_type: "Director", ownership_percent: "" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add role");
    } finally {
      setSavingRole(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <TableSkeleton cols={5} rows={4} />
        <TableSkeleton cols={4} rows={3} />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-[#182350]">Relationships</h1>
          <p className="text-xs text-gray-500 mt-0.5">Directors, shareholders, and related parties</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleDetectMatches}
            disabled={detectLoading}
            className="flex items-center gap-1 text-xs text-amber-700 border border-amber-300 px-2.5 py-1.5 rounded hover:bg-amber-50 disabled:opacity-50"
          >
            <Network size={12} /> Detect Matches
          </button>
          <button
            onClick={() => setAddRoleModal(true)}
            className="flex items-center gap-1 text-xs bg-[#182350] text-white px-3 py-1.5 rounded-md hover:bg-[#0D1635]"
          >
            <Plus size={12} /> Add Role
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 border border-red-200 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {/* Entity Roles */}
      <div>
        <h2 className="text-sm font-semibold text-[#182350] mb-3">
          Associated Entities
          <span className="ml-2 text-xs text-gray-500 font-normal">({roles.length})</span>
        </h2>
        <Card className="bg-white border border-gray-200">
          <CardContent className="p-0">
            {roles.length === 0 ? (
              <div className="py-10 text-center">
                <p className="text-sm text-gray-500">No entities linked to this client</p>
                <Link href="/relationships" className="mt-2 block text-xs text-[#182350] hover:text-[#0D1635]">
                  Go to Entity Registry →
                </Link>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Entity</th>
                    <th className="px-3 py-3 text-left font-medium">Role</th>
                    <th className="px-3 py-3 text-left font-medium">Ownership %</th>
                    <th className="px-3 py-3 text-left font-medium">From</th>
                    <th className="px-3 py-3 text-left font-medium">To</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {roles.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3">
                        <Link href={`/relationships/${r.entity_id}`} className="text-xs text-blue-600 hover:underline">
                          {r.entity_name ?? r.entity_id.slice(0, 8) + "…"}
                        </Link>
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={`text-[10px] ${ROLE_TYPE_COLORS[r.role_type] ?? "bg-gray-100 text-gray-600"}`}>
                          {r.role_type}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-gray-500 text-xs">
                        {r.ownership_percent != null ? `${r.ownership_percent}%` : "—"}
                      </td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{formatDate(r.effective_from)}</td>
                      <td className="px-3 py-3 text-gray-500 text-xs">{formatDate(r.effective_to)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Cross-client matches */}
      {matches.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-amber-700 mb-3">
            ⚠ Cross-Client Matches ({matches.length})
          </h2>
          <Card className="bg-white border border-amber-200">
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-gray-200">
                    <th className="px-5 py-3 text-left font-medium">Match Type</th>
                    <th className="px-3 py-3 text-left font-medium">PAN</th>
                    <th className="px-3 py-3 text-left font-medium">Other Client</th>
                    <th className="px-3 py-3 text-left font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {matches.map((m) => (
                    <tr key={m.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3">
                        <Badge className="bg-amber-100 text-amber-700 text-[10px]">{m.match_type.toUpperCase()}</Badge>
                      </td>
                      <td className="px-3 py-3 text-gray-700 text-xs font-mono">{m.pan}</td>
                      <td className="px-3 py-3 text-gray-500 text-xs">
                        {m.client_id_a === clientId ? m.client_id_b.slice(0, 8) : m.client_id_a.slice(0, 8)}…
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={m.is_confirmed ? "bg-red-100 text-red-700 text-[10px]" : "bg-amber-100 text-amber-700 text-[10px]"}>
                          {m.is_reviewed ? (m.is_confirmed ? "Confirmed" : "Dismissed") : "Pending"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Add Role Modal */}
      {addRoleModal && (
        <div className="fixed inset-0 bg-gray-900/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-[#182350]">Link Entity to Client</h2>
              <button onClick={() => setAddRoleModal(false)} className="text-gray-400 hover:text-gray-700"><X size={16} /></button>
            </div>
            <p className="text-xs text-gray-600 mb-4">
              Enter the Entity ID from the{" "}
              <Link href="/relationships" className="text-[#182350] hover:underline">Entity Registry</Link>.
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-600">Entity ID *</label>
                <input
                  value={roleForm.entity_id}
                  onChange={(e) => setRoleForm({ ...roleForm, entity_id: e.target.value.trim() })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 font-mono focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="UUID from entity registry"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Role Type *</label>
                <select
                  value={roleForm.role_type}
                  onChange={(e) => setRoleForm({ ...roleForm, role_type: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                >
                  {["Director", "Shareholder", "Partner", "Trustee", "Proprietor", "Guarantor", "Authorized Signatory", "Karta (HUF)", "Beneficiary", "Manager", "Other"].map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-600">Ownership % (optional)</label>
                <input
                  type="number"
                  min="0" max="100"
                  value={roleForm.ownership_percent}
                  onChange={(e) => setRoleForm({ ...roleForm, ownership_percent: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]"
                  placeholder="e.g. 51"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button onClick={() => setAddRoleModal(false)} className="flex-1 text-sm text-gray-600 border border-gray-200 py-2 rounded-md hover:bg-gray-50">Cancel</button>
              <button
                onClick={handleAddRole}
                disabled={savingRole || !roleForm.entity_id}
                className="flex-1 text-sm bg-[#182350] text-white py-2 rounded-md hover:bg-[#0D1635] disabled:opacity-50"
              >
                {savingRole ? "Linking…" : "Link Entity"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
