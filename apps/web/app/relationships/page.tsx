"use client";

import { useState, useEffect } from "react";
import { Plus, X, Search } from "lucide-react";
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
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ─── Types ───────────────────────────────────────────────────────────────────

type EntityType =
  | "Individual"
  | "Proprietorship"
  | "Partnership"
  | "LLP"
  | "Private Limited"
  | "Public Limited"
  | "Trust"
  | "Society"
  | "HUF"
  | "Other";

interface Entity {
  id: string;
  full_name: string;
  entity_type: EntityType;
  pan: string | null;
  gstin: string | null;
  email: string | null;
  phone: string | null;
  roles_count: number;
  linked_clients_count: number;
  created_at: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const ENTITY_TYPES: EntityType[] = [
  "Individual",
  "Proprietorship",
  "Partnership",
  "LLP",
  "Private Limited",
  "Public Limited",
  "Trust",
  "Society",
  "HUF",
  "Other",
];

const ENTITY_TYPE_COLORS: Record<EntityType, string> = {
  Individual:       "bg-gray-100 text-gray-600",
  Proprietorship:   "bg-blue-100 text-blue-700",
  Partnership:      "bg-violet-100 text-violet-700",
  LLP:              "bg-purple-100 text-purple-700",
  "Private Limited":"bg-cyan-100 text-cyan-700",
  "Public Limited": "bg-teal-100 text-teal-700",
  Trust:            "bg-emerald-100 text-emerald-700",
  Society:          "bg-green-100 text-green-700",
  HUF:              "bg-yellow-100 text-yellow-700",
  Other:            "bg-gray-100 text-gray-600",
};

const EMPTY_FORM = {
  full_name: "",
  entity_type: "Individual" as EntityType,
  pan: "",
  gstin: "",
  email: "",
  phone: "",
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function RelationshipsPage() {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<EntityType | "All">("All");
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [detectLoading, setDetectLoading] = useState(false);
  const [detectToast, setDetectToast] = useState<string | null>(null);

  useEffect(() => {
    loadEntities();
  }, []);

  useEffect(() => {
    if (detectToast) {
      const t = setTimeout(() => setDetectToast(null), 4000);
      return () => clearTimeout(t);
    }
  }, [detectToast]);

  async function loadEntities() {
    setLoading(true);
    setError(null);
    try {
      const json: ApiResponse<Entity[]> = await apiFetch("/api/relationships/entities");
      if (!json.success) throw new Error(json.error ?? "Failed to load entities");
      setEntities(json.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleAddEntity() {
    if (!form.full_name.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const json: ApiResponse<Entity> = await apiFetch("/api/relationships/entities", {
        method: "POST",
        body: JSON.stringify({
          full_name: form.full_name.trim(),
          entity_type: form.entity_type,
          pan: form.pan.trim().toUpperCase() || null,
          email: form.email.trim() || null,
          phone: form.phone.trim() || null,
        }),
      });
      if (!json.success) throw new Error(json.error ?? "Failed to create entity");
      setEntities((prev) => [json.data, ...prev]);
      setModalOpen(false);
      setForm(EMPTY_FORM);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleDetectMatches() {
    setDetectLoading(true);
    setDetectToast(null);
    try {
      const json: ApiResponse<{ new_matches_detected: number }> = await apiFetch(
        "/api/relationships/cross-client-matches/detect",
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!json.success) throw new Error(json.error ?? "Detection failed");
      setDetectToast(`Detection complete — ${json.data.new_matches_detected} match(es) found`);
    } catch (e) {
      setDetectToast(e instanceof Error ? e.message : "Detection failed");
    } finally {
      setDetectLoading(false);
    }
  }

  const filtered = entities.filter((e) => {
    const matchType = typeFilter === "All" || e.entity_type === typeFilter;
    const q = search.toLowerCase();
    const matchSearch =
      !search ||
      e.full_name.toLowerCase().includes(q) ||
      (e.pan ?? "").toLowerCase().includes(q) ||
      (e.email ?? "").toLowerCase().includes(q);
    return matchType && matchSearch;
  });

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse bg-[#F8FAFC] min-h-full">
        <div className="h-6 bg-gray-200 rounded w-48" />
        <div className="h-10 bg-gray-100 rounded" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 bg-gray-100 rounded-xl" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-[#F8FAFC] min-h-full">
        <div className="bg-red-50 text-red-600 rounded-lg px-5 py-4 text-sm border border-red-200">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 bg-[#F8FAFC] min-h-full">
      {/* Toast */}
      {detectToast && (
        <div className="fixed top-4 right-4 z-50 bg-white border border-gray-200 text-gray-800 text-sm px-4 py-3 rounded-lg shadow-xl max-w-sm">
          {detectToast}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#182350]">Entity Registry</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {entities.length} entities across all clients
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleDetectMatches}
            disabled={detectLoading}
            className="text-sm text-[#182350] border border-[#182350]/30 px-3 py-1.5 rounded-md hover:bg-[#AFD2FA]/20 disabled:opacity-50"
          >
            {detectLoading ? "Detecting…" : "Detect Matches"}
          </button>
          <button
            onClick={() => {
              setForm(EMPTY_FORM);
              setSaveError(null);
              setModalOpen(true);
            }}
            className="flex items-center gap-1.5 text-sm bg-[#182350] text-white px-3 py-1.5 rounded-md hover:bg-[#0D1635]"
          >
            <Plus size={14} /> Add Entity
          </button>
        </div>
      </div>

      {/* Search & Filter */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, PAN, or email…"
            className="w-full pl-8 pr-4 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as EntityType | "All")}
          className="px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
        >
          <option value="All">All Types</option>
          {ENTITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {/* Table */}
      <Card className="bg-white border-gray-200 shadow-sm">
        <CardContent className="p-0">
          {filtered.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-sm text-gray-500">No entities found</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 border-b border-gray-200">
                  <th className="px-5 py-3 text-left font-medium">Name</th>
                  <th className="px-3 py-3 text-left font-medium">Type</th>
                  <th className="px-3 py-3 text-left font-medium">PAN</th>
                  <th className="px-3 py-3 text-left font-medium">Email</th>
                  <th className="px-3 py-3 text-left font-medium">Roles</th>
                  <th className="px-3 py-3 text-left font-medium">Linked Clients</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((entity) => (
                  <tr key={entity.id} className="hover:bg-[#AFD2FA]/10 group">
                    <td className="px-5 py-3 text-gray-800 font-medium">{entity.full_name}</td>
                    <td className="px-3 py-3">
                      <Badge className={`text-[11px] ${ENTITY_TYPE_COLORS[entity.entity_type]}`}>
                        {entity.entity_type}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-gray-500">
                      {entity.pan || "—"}
                    </td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{entity.email || "—"}</td>
                    <td className="px-3 py-3 text-center">
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                        {entity.roles_count}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                        {entity.linked_clients_count}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right">
                      <a
                        href={`/relationships/${entity.id}`}
                        className="text-xs text-[#182350] hover:text-[#182350]/70 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        View →
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Add Entity Modal */}
      {modalOpen && (
        <div className="fixed inset-0 bg-[#182350]/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-[#182350]">Add Entity</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-700">
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-600 font-medium">Full Name *</label>
                <input
                  value={form.full_name}
                  onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                  placeholder="Individual or entity name"
                />
              </div>
              <div>
                <label className="text-xs text-gray-600 font-medium">Entity Type</label>
                <select
                  value={form.entity_type}
                  onChange={(e) => setForm({ ...form, entity_type: e.target.value as EntityType })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                >
                  {ENTITY_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-600 font-medium">PAN</label>
                  <input
                    value={form.pan}
                    onChange={(e) => setForm({ ...form, pan: e.target.value.toUpperCase() })}
                    className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 font-mono focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                    placeholder="AAAAA9999A"
                    maxLength={10}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600 font-medium">GSTIN</label>
                  <input
                    value={form.gstin}
                    onChange={(e) => setForm({ ...form, gstin: e.target.value.toUpperCase() })}
                    className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 font-mono focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                    placeholder="22AAAAA0000A1Z5"
                    maxLength={15}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-600 font-medium">Email</label>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                    placeholder="contact@example.com"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600 font-medium">Phone</label>
                  <input
                    type="tel"
                    value={form.phone}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })}
                    className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#182350]"
                    placeholder="+91 98765 43210"
                  />
                </div>
              </div>
            </div>
            {saveError && (
              <p className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-md border border-red-200">
                {saveError}
              </p>
            )}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setModalOpen(false)}
                className="flex-1 text-sm text-gray-600 border border-gray-300 py-2 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAddEntity}
                disabled={saving || !form.full_name.trim()}
                className="flex-1 text-sm bg-[#182350] text-white py-2 rounded-md hover:bg-[#0D1635] disabled:opacity-50"
              >
                {saving ? "Adding…" : "Add Entity"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
