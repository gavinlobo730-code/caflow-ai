"use client";

import { useState, useEffect } from "react";
import { Search, Network, ArrowRight } from "lucide-react";
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
  pan?: string;
  email?: string;
  roles?: { role_type: string; client_id: string }[];
  relationships?: { relationship_type: string; from_entity_id: string; to_entity_id: string }[];
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

export default function RelationshipExplorerPage() {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selected, setSelected] = useState<Entity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    loadEntities();
  }, []);

  async function loadEntities() {
    setLoading(true);
    setError(null);
    try {
      const json: ApiResponse<Entity[]> = await apiFetch("/api/relationships/entities?limit=100");
      if (!json.success) throw new Error(json.error ?? "Failed to load");
      setEntities(json.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelect(entity: Entity) {
    // Load full entity data (includes embedded roles + relationships)
    try {
      const json: ApiResponse<Entity> = await apiFetch(`/api/relationships/entities/${entity.id}`);
      if (json.success) setSelected(json.data);
      else setSelected(entity);
    } catch {
      setSelected(entity);
    }
  }

  const filtered = entities.filter((e) => {
    const q = search.toLowerCase();
    return (
      !q ||
      e.full_name.toLowerCase().includes(q) ||
      (e.pan ?? "").toLowerCase().includes(q) ||
      (e.email ?? "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="p-6 space-y-5 bg-[#F8FAFC] min-h-full">
      <div>
        <h1 className="text-2xl font-bold text-[#182350] flex items-center gap-2">
          <Network size={20} className="text-[#182350]" />
          Relationship Explorer
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Select an entity to explore its roles and relationships
        </p>
      </div>

      {error && (
        <div className="bg-red-50 text-red-600 border border-red-200 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* Left — entity list */}
        <div className="md:col-span-1 space-y-3">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search entities…"
              className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-gray-300 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
            />
          </div>
          {loading ? (
            <div className="space-y-2 animate-pulse">
              {[1, 2, 3, 4].map((i) => <div key={i} className="h-12 bg-gray-100 rounded-lg" />)}
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-gray-500 py-4 text-center">No entities found</p>
          ) : (
            <div className="space-y-1.5 max-h-[60vh] overflow-y-auto">
              {filtered.map((e) => (
                <button
                  key={e.id}
                  onClick={() => handleSelect(e)}
                  className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                    selected?.id === e.id
                      ? "bg-[#AFD2FA]/30 border-[#182350]/30"
                      : "bg-white border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  <p className="text-xs font-medium text-gray-800 truncate">{e.full_name}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <Badge className={`text-[9px] px-1.5 ${ENTITY_TYPE_COLORS[e.entity_type] ?? "bg-gray-100 text-gray-600"}`}>
                      {e.entity_type}
                    </Badge>
                    {e.pan && <span className="text-[10px] text-gray-500 font-mono">{e.pan}</span>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right — relationship detail */}
        <div className="md:col-span-2">
          {!selected ? (
            <Card className="bg-white border-gray-200 shadow-sm h-full flex items-center justify-center">
              <CardContent className="py-16 text-center">
                <Network size={40} className="text-gray-300 mx-auto mb-3" />
                <p className="text-sm text-gray-500">Select an entity to explore relationships</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {/* Entity header */}
              <Card className="bg-white border-gray-200 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <h2 className="text-base font-semibold text-[#182350]">{selected.full_name}</h2>
                      <div className="flex items-center gap-3 mt-1">
                        <Badge className={`text-[10px] ${ENTITY_TYPE_COLORS[selected.entity_type] ?? "bg-gray-100 text-gray-600"}`}>
                          {selected.entity_type}
                        </Badge>
                        {selected.pan && <span className="text-xs text-gray-500 font-mono">PAN: {selected.pan}</span>}
                        {selected.email && <span className="text-xs text-gray-500">{selected.email}</span>}
                      </div>
                    </div>
                    <Link
                      href={`/relationships/${selected.id}`}
                      className="text-xs text-[#182350] hover:text-[#182350]/70 flex items-center gap-1"
                    >
                      View Full Profile <ArrowRight size={12} />
                    </Link>
                  </div>
                </CardContent>
              </Card>

              {/* Roles */}
              {(selected.roles ?? []).length > 0 && (
                <Card className="bg-white border-gray-200 shadow-sm">
                  <CardContent className="p-5">
                    <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                      Client Roles ({selected.roles!.length})
                    </h3>
                    <div className="space-y-2">
                      {selected.roles!.map((r, i) => (
                        <div key={i} className="flex items-center gap-3 px-3 py-2 bg-gray-50 rounded-md">
                          <Badge className="bg-blue-100 text-blue-700 text-[10px]">{r.role_type}</Badge>
                          <span className="text-xs text-gray-500 font-mono">{r.client_id.slice(0, 12)}…</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Relationships */}
              {(selected.relationships ?? []).length > 0 && (
                <Card className="bg-white border-gray-200 shadow-sm">
                  <CardContent className="p-5">
                    <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                      Entity Relationships ({selected.relationships!.length})
                    </h3>
                    <div className="space-y-2">
                      {selected.relationships!.map((r, i) => {
                        const isFrom = r.from_entity_id === selected.id;
                        const otherId = isFrom ? r.to_entity_id : r.from_entity_id;
                        const otherEntity = entities.find((e) => e.id === otherId);
                        return (
                          <div key={i} className="flex items-center gap-3 px-3 py-2 bg-gray-50 rounded-md">
                            <span className="text-xs text-gray-800">{selected.full_name}</span>
                            <ArrowRight size={12} className="text-[#182350] shrink-0" />
                            <Badge className="bg-[#182350]/10 text-[#182350] text-[10px]">{r.relationship_type}</Badge>
                            <ArrowRight size={12} className="text-[#182350] shrink-0" />
                            <button
                              onClick={() => { const e = entities.find((e) => e.id === otherId); if (e) handleSelect(e); }}
                              className="text-xs text-[#182350] hover:underline"
                            >
                              {otherEntity?.full_name ?? otherId.slice(0, 12) + "…"}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              )}

              {(selected.roles ?? []).length === 0 && (selected.relationships ?? []).length === 0 && (
                <Card className="bg-white border-gray-200 shadow-sm">
                  <CardContent className="py-10 text-center">
                    <p className="text-sm text-gray-500">No roles or relationships recorded</p>
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
