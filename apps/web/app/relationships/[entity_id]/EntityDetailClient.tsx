"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, CheckCircle, XCircle } from "lucide-react";
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

// ─── Types ───────────────────────────────────────────────────────────────────

interface Entity {
  id: string;
  full_name: string;
  entity_type: string;
  pan: string | null;
  gstin: string | null;
  email: string | null;
  phone: string | null;
  created_at: string;
}

interface EntityRole {
  id: string;
  client_id: string;
  client_name: string;
  role_type: string;
  ownership_pct: number | null;
  effective_from: string | null;
  effective_to: string | null;
}

interface EntityRelationship {
  id: string;
  related_entity_id: string;
  related_entity_name: string;
  relationship_type: string;
  notes: string | null;
}

interface CrossClientMatch {
  id: string;
  match_type: string;
  match_field: string;
  match_value: string;
  confidence_score: number;
  status: "pending" | "confirmed" | "dismissed";
  client_a_name: string;
  client_b_name: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

type TabId = "overview" | "roles" | "relationships" | "matches";

// ─── Component ───────────────────────────────────────────────────────────────

export default function EntityDetailPage() {
  const params = useParams();
  const entityId = params.entity_id as string;

  const [entity, setEntity] = useState<Entity | null>(null);
  const [roles, setRoles] = useState<EntityRole[]>([]);
  const [relationships, setRelationships] = useState<EntityRelationship[]>([]);
  const [matches, setMatches] = useState<CrossClientMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [processingMatchId, setProcessingMatchId] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // get_entity returns entity + embedded roles + embedded relationships
      const entityJson: ApiResponse<Entity & { roles: EntityRole[]; relationships: EntityRelationship[] }> =
        await apiFetch(`/api/relationships/entities/${entityId}`);
      if (!entityJson.success) throw new Error(entityJson.error ?? "Failed to load entity");
      setEntity(entityJson.data);
      setRoles(entityJson.data.roles ?? []);
      setRelationships(entityJson.data.relationships ?? []);

      // Cross-client matches filtered for this entity
      const matchesJson: ApiResponse<CrossClientMatch[]> = await apiFetch(
        `/api/relationships/cross-client-matches?entity_id=${entityId}`
      );
      setMatches(matchesJson.success ? matchesJson.data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [entityId]);

  useEffect(() => {
    if (entityId) loadAll();
  }, [entityId, loadAll]);

  async function handleMatchAction(matchId: string, action: "confirm" | "dismiss") {
    setProcessingMatchId(matchId);
    try {
      const json: ApiResponse<CrossClientMatch> = await apiFetch(
        `/api/relationships/cross-client-matches/${matchId}/review`,
        {
          method: "PATCH",
          body: JSON.stringify({ is_confirmed: action === "confirm" }),
        }
      );
      if (!json.success) throw new Error(json.error ?? "Action failed");
      setMatches((prev) =>
        prev.map((m) => (m.id === matchId ? { ...m, status: action === "confirm" ? "confirmed" : "dismissed" } : m))
      );
    } catch {
      // silently fail — user can retry
    } finally {
      setProcessingMatchId(null);
    }
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return "—";
    try {
      return new Date(dateStr).toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-5 bg-white/[0.08] rounded w-24" />
        <div className="h-32 bg-white/[0.05] rounded-xl" />
        <div className="h-64 bg-white/[0.05] rounded-xl" />
      </div>
    );
  }

  if (error || !entity) {
    return (
      <div className="p-6">
        <Link href="/relationships" className="flex items-center gap-1 text-xs text-slate-400 hover:text-white mb-4">
          <ChevronLeft size={14} /> Back
        </Link>
        <div className="bg-red-900/30 text-red-400 rounded-lg px-5 py-4 text-sm border border-red-800">
          {error ?? "Entity not found"}
        </div>
      </div>
    );
  }

  const TABS: { id: TabId; label: string; count?: number }[] = [
    { id: "overview", label: "Overview" },
    { id: "roles", label: "Roles", count: roles.length },
    { id: "relationships", label: "Relationships", count: relationships.length },
    { id: "matches", label: "Cross-Client Matches", count: matches.length },
  ];

  return (
    <div className="p-6 space-y-5">
      {/* Back nav */}
      <Link href="/relationships" className="flex items-center gap-1 text-xs text-slate-400 hover:text-white">
        <ChevronLeft size={14} /> Entity Registry
      </Link>

      {/* Entity header */}
      <div>
        <h1 className="text-xl font-semibold text-white">{entity.full_name}</h1>
        <p className="text-xs text-slate-400 mt-0.5">{entity.entity_type}</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-700">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-cyan-500 text-cyan-400"
                : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="ml-1 text-slate-600">({tab.count})</span>
            )}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {activeTab === "overview" && (
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-5">
            <div className="grid grid-cols-2 gap-4 text-sm">
              {[
                { label: "Full Name", value: entity.full_name },
                { label: "Entity Type", value: entity.entity_type },
                { label: "PAN", value: entity.pan, mono: true },
                { label: "GSTIN", value: entity.gstin, mono: true },
                { label: "Email", value: entity.email },
                { label: "Phone", value: entity.phone },
                { label: "Created", value: formatDate(entity.created_at) },
              ].map(({ label, value, mono }) => (
                <div key={label} className="space-y-0.5">
                  <p className="text-xs text-slate-500">{label}</p>
                  <p className={`text-white ${mono ? "font-mono" : ""}`}>{value || "—"}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Roles tab */}
      {activeTab === "roles" && (
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-0">
            {roles.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-sm text-slate-500">No roles found</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-gray-700">
                    <th className="px-5 py-3 text-left font-medium">Client</th>
                    <th className="px-3 py-3 text-left font-medium">Role Type</th>
                    <th className="px-3 py-3 text-left font-medium">Ownership %</th>
                    <th className="px-3 py-3 text-left font-medium">Effective From</th>
                    <th className="px-3 py-3 text-left font-medium">Effective To</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {roles.map((role) => (
                    <tr key={role.id} className="hover:bg-gray-700/30">
                      <td className="px-5 py-3 text-white font-medium">{role.client_name}</td>
                      <td className="px-3 py-3">
                        <Badge className="bg-cyan-800 text-cyan-300 text-[11px]">{role.role_type}</Badge>
                      </td>
                      <td className="px-3 py-3 text-slate-300">
                        {role.ownership_pct !== null ? `${role.ownership_pct}%` : "—"}
                      </td>
                      <td className="px-3 py-3 text-slate-400 text-xs">{formatDate(role.effective_from)}</td>
                      <td className="px-3 py-3 text-slate-400 text-xs">{formatDate(role.effective_to)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Relationships tab */}
      {activeTab === "relationships" && (
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-0">
            {relationships.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-sm text-slate-500">No linked entities found</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-gray-700">
                    <th className="px-5 py-3 text-left font-medium">Related Entity</th>
                    <th className="px-3 py-3 text-left font-medium">Relationship</th>
                    <th className="px-3 py-3 text-left font-medium">Notes</th>
                    <th className="px-5 py-3 text-right font-medium">View</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {relationships.map((rel) => (
                    <tr key={rel.id} className="hover:bg-gray-700/30">
                      <td className="px-5 py-3 text-white font-medium">{rel.related_entity_name}</td>
                      <td className="px-3 py-3">
                        <Badge className="bg-slate-700 text-slate-300 text-[11px]">{rel.relationship_type}</Badge>
                      </td>
                      <td className="px-3 py-3 text-slate-400 text-xs">{rel.notes || "—"}</td>
                      <td className="px-5 py-3 text-right">
                        <Link
                          href={`/relationships/${rel.related_entity_id}`}
                          className="text-xs text-cyan-400 hover:text-cyan-300"
                        >
                          View →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Cross-Client Matches tab */}
      {activeTab === "matches" && (
        <Card className="bg-gray-800 border-gray-700">
          <CardContent className="p-0">
            {matches.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-sm text-slate-500">No cross-client matches detected</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-gray-700">
                    <th className="px-5 py-3 text-left font-medium">Match Type</th>
                    <th className="px-3 py-3 text-left font-medium">Field / Value</th>
                    <th className="px-3 py-3 text-left font-medium">Clients</th>
                    <th className="px-3 py-3 text-left font-medium">Confidence</th>
                    <th className="px-3 py-3 text-left font-medium">Status</th>
                    <th className="px-5 py-3 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {matches.map((match) => (
                    <tr key={match.id} className="hover:bg-gray-700/30">
                      <td className="px-5 py-3">
                        <Badge className="bg-violet-800 text-violet-300 text-[11px]">{match.match_type}</Badge>
                      </td>
                      <td className="px-3 py-3">
                        <p className="text-slate-400 text-xs">{match.match_field}</p>
                        <p className="text-white text-xs font-mono">{match.match_value}</p>
                      </td>
                      <td className="px-3 py-3 text-slate-400 text-xs">
                        {match.client_a_name} ↔ {match.client_b_name}
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-gray-700 rounded-full max-w-[60px]">
                            <div
                              className="h-full bg-violet-500 rounded-full"
                              style={{ width: `${match.confidence_score}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-400">{match.confidence_score}%</span>
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <Badge
                          className={`text-[11px] ${
                            match.status === "confirmed"
                              ? "bg-green-800 text-green-300"
                              : match.status === "dismissed"
                              ? "bg-gray-700 text-gray-400"
                              : "bg-yellow-800 text-yellow-300"
                          }`}
                        >
                          {match.status}
                        </Badge>
                      </td>
                      <td className="px-5 py-3 text-right">
                        {match.status === "pending" && (
                          <div className="flex items-center justify-end gap-2">
                            <button
                              onClick={() => handleMatchAction(match.id, "confirm")}
                              disabled={processingMatchId === match.id}
                              className="flex items-center gap-1 text-xs text-green-400 hover:text-green-300 disabled:opacity-50"
                              title="Confirm"
                            >
                              <CheckCircle size={14} />
                            </button>
                            <button
                              onClick={() => handleMatchAction(match.id, "dismiss")}
                              disabled={processingMatchId === match.id}
                              className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
                              title="Dismiss"
                            >
                              <XCircle size={14} />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
