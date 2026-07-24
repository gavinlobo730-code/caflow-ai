"use client";

import { useState, useEffect } from "react";
import { PieChart, Search, ChevronRight } from "lucide-react";
import Link from "next/link";
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

interface Entity {
  id: string;
  full_name: string;
  entity_type: string;
  pan: string | null;
  roles?: { role_type: string; client_id: string; client_name?: string }[];
  outgoing?: { relationship_type: string; to_entity_id: string; to_entity_name?: string }[];
  incoming?: { relationship_type: string; from_entity_id: string; from_entity_name?: string }[];
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

const ENTITY_TYPE_COLORS: Record<string, string> = {
  Individual:        "bg-gray-100 text-gray-600",
  Proprietorship:    "bg-blue-100 text-blue-700",
  Partnership:       "bg-violet-100 text-violet-700",
  LLP:               "bg-purple-100 text-purple-700",
  "Private Limited": "bg-cyan-100 text-cyan-700",
  "Public Limited":  "bg-teal-100 text-teal-700",
  Trust:             "bg-emerald-100 text-emerald-700",
  Society:           "bg-green-100 text-green-700",
  HUF:               "bg-yellow-100 text-yellow-700",
  Other:             "bg-gray-100 text-gray-600",
};

export default function OwnershipMapPage() {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selected, setSelected] = useState<Entity | null>(null);
  const [detail, setDetail] = useState<Entity | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Distinguishes "detail fetch failed" from "no ownership relationships" —
  // a masked failure previously left a dead panel with no roles/relationship
  // sections and no error, indistinguishable from a slow/broken load.
  const [detailError, setDetailError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    loadEntities();
  }, []);

  async function loadEntities() {
    setLoading(true);
    setError(null);
    try {
      const res: ApiResponse<Entity[]> = await apiFetch("/api/relationships/entities");
      if (res.success) {
        setEntities(res.data ?? []);
      } else {
        setError(res.error ?? "Failed to load entities");
      }
    } catch {
      setError("Network error — could not reach server");
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id: string) {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const res: ApiResponse<Entity> = await apiFetch(`/api/relationships/entities/${id}`);
      if (res.success) setDetail(res.data);
      else setDetailError(res.error ?? "Failed to load ownership details");
    } catch {
      setDetailError("Network error — could not reach server");
    } finally {
      setDetailLoading(false);
    }
  }

  function selectEntity(e: Entity) {
    setSelected(e);
    setDetail(null);
    setDetailError(null);
    loadDetail(e.id);
  }

  const filtered = entities.filter((e) =>
    e.full_name.toLowerCase().includes(search.toLowerCase())
  );

  // Entities that appear as owners (have outgoing Director/Partner/Trustee relationships)
  const OWNERSHIP_TYPES = ["Director", "Partner", "Trustee", "Proprietor", "Karta", "Member", "Shareholder"];

  return (
    <div className="p-6 space-y-6 bg-[#F8FAFC] min-h-full">
      <div>
        <h1 className="text-2xl font-bold text-[#182350] flex items-center gap-2">
          <PieChart className="w-6 h-6 text-[#182350]" />
          Ownership Map
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Visualise ownership and directorship relationships across all entities.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Entity list */}
        <div className="lg:col-span-1 space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              className="w-full bg-white border border-gray-300 rounded-lg pl-9 pr-4 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:border-[#182350]"
              placeholder="Search entity…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 border-[#182350] border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {error && (
            <Card className="bg-red-50 border-red-200">
              <CardContent className="p-4 text-sm text-red-600">{error}</CardContent>
            </Card>
          )}

          {!loading && !error && filtered.length === 0 && (
            <p className="text-center py-8 text-gray-400 text-sm">No entities found.</p>
          )}

          <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
            {filtered.map((e) => (
              <button
                key={e.id}
                onClick={() => selectEntity(e)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  selected?.id === e.id
                    ? "bg-[#AFD2FA]/30 border-[#182350]/30"
                    : "bg-white border-gray-200 hover:border-[#182350]/20"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-gray-800 font-medium truncate">{e.full_name}</span>
                  <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />
                </div>
                <Badge
                  className={`mt-1 text-xs ${
                    ENTITY_TYPE_COLORS[e.entity_type] ?? "bg-gray-100 text-gray-600"
                  }`}
                >
                  {e.entity_type}
                </Badge>
              </button>
            ))}
          </div>
        </div>

        {/* Ownership detail panel */}
        <div className="lg:col-span-2">
          {!selected && (
            <div className="flex items-center justify-center h-full min-h-[300px] text-gray-400 text-sm">
              Select an entity to view its ownership map.
            </div>
          )}

          {selected && (
            <Card className="bg-white border-gray-200 shadow-sm">
              <CardContent className="p-5 space-y-5">
                <div>
                  <h2 className="text-lg font-semibold text-[#182350]">{selected.full_name}</h2>
                  <Badge
                    className={`mt-1 ${
                      ENTITY_TYPE_COLORS[selected.entity_type] ?? "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {selected.entity_type}
                  </Badge>
                  {selected.pan && (
                    <p className="text-xs text-gray-500 mt-1">PAN: {selected.pan}</p>
                  )}
                </div>

                {detailLoading && (
                  <div className="flex items-center justify-center py-8">
                    <div className="w-5 h-5 border-2 border-[#182350] border-t-transparent rounded-full animate-spin" />
                  </div>
                )}

                {!detailLoading && detailError && (
                  <div className="text-center py-8 space-y-2">
                    <p className="text-sm text-red-600 font-medium">{detailError}</p>
                    <button
                      onClick={() => loadDetail(selected.id)}
                      className="text-xs px-3 py-1 border border-gray-200 rounded hover:bg-gray-50 text-gray-700"
                    >
                      Retry
                    </button>
                  </div>
                )}

                {detail && (
                  <>
                    {/* Roles (linked clients) */}
                    {(detail.roles ?? []).length > 0 && (
                      <div>
                        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                          Roles in Clients
                        </h3>
                        <div className="space-y-2">
                          {(detail.roles ?? []).map((r, i) => (
                            <div
                              key={i}
                              className="flex items-center justify-between p-2 rounded-lg bg-gray-50 border border-gray-100"
                            >
                              <span className="text-sm text-gray-700">
                                {r.client_name ?? r.client_id}
                              </span>
                              <Badge className="bg-indigo-100 text-indigo-700 text-xs">
                                {r.role_type}
                              </Badge>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Outgoing relationships */}
                    {(detail.outgoing ?? []).filter((r) =>
                      OWNERSHIP_TYPES.includes(r.relationship_type)
                    ).length > 0 && (
                      <div>
                        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                          Owns / Directs
                        </h3>
                        <div className="space-y-2">
                          {(detail.outgoing ?? [])
                            .filter((r) => OWNERSHIP_TYPES.includes(r.relationship_type))
                            .map((r, i) => (
                              <div
                                key={i}
                                className="flex items-center justify-between p-2 rounded-lg bg-gray-50 border border-gray-100"
                              >
                                <Link
                                  href={`/relationships/${r.to_entity_id}`}
                                  className="text-sm text-[#182350] hover:text-[#182350]/70"
                                >
                                  {r.to_entity_name ?? r.to_entity_id}
                                </Link>
                                <Badge className="bg-[#182350]/10 text-[#182350] text-xs">
                                  {r.relationship_type}
                                </Badge>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}

                    {/* Incoming relationships */}
                    {(detail.incoming ?? []).filter((r) =>
                      OWNERSHIP_TYPES.includes(r.relationship_type)
                    ).length > 0 && (
                      <div>
                        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                          Owned By / Controlled By
                        </h3>
                        <div className="space-y-2">
                          {(detail.incoming ?? [])
                            .filter((r) => OWNERSHIP_TYPES.includes(r.relationship_type))
                            .map((r, i) => (
                              <div
                                key={i}
                                className="flex items-center justify-between p-2 rounded-lg bg-gray-50 border border-gray-100"
                              >
                                <Link
                                  href={`/relationships/${r.from_entity_id}`}
                                  className="text-sm text-[#182350] hover:text-[#182350]/70"
                                >
                                  {r.from_entity_name ?? r.from_entity_id}
                                </Link>
                                <Badge className="bg-gray-100 text-gray-600 text-xs">
                                  {r.relationship_type}
                                </Badge>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}

                    {(detail.roles ?? []).length === 0 &&
                      (detail.outgoing ?? []).length === 0 &&
                      (detail.incoming ?? []).length === 0 && (
                        <p className="text-sm text-gray-400 text-center py-4">
                          No ownership relationships recorded for this entity.
                        </p>
                      )}
                  </>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
