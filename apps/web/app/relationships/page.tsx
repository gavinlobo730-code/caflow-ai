"use client";

import { useState, useEffect, useMemo } from "react";
import { Plus, X } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { DataTable } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";
import { formatDate } from "@/lib/services/formatting";

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

  const columns: Column<Entity>[] = useMemo(() => [
    { key: "full_name", header: "Name", accessor: (e) => e.full_name, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (e) => <span className="font-medium text-[#1E293B]">{e.full_name}</span> },
    { key: "entity_type", header: "Type", accessor: (e) => e.entity_type, sortable: true,
      render: (e) => <Badge className={`text-[11px] ${ENTITY_TYPE_COLORS[e.entity_type]}`}>{e.entity_type}</Badge> },
    { key: "pan", header: "PAN", accessor: (e) => e.pan ?? "", searchable: true,
      render: (e) => <span className="font-mono text-xs text-[#64748B]">{e.pan || "—"}</span> },
    { key: "gstin", header: "GSTIN", accessor: (e) => e.gstin ?? "", searchable: true, defaultHidden: true,
      render: (e) => <span className="font-mono text-xs text-[#64748B]">{e.gstin || "—"}</span> },
    { key: "email", header: "Email", accessor: (e) => e.email ?? "", searchable: true,
      render: (e) => <span className="text-xs text-[#64748B]">{e.email || "—"}</span> },
    { key: "roles_count", header: "Roles", accessor: (e) => e.roles_count, sortable: true, align: "right" },
    { key: "linked_clients_count", header: "Linked Clients", accessor: (e) => e.linked_clients_count, sortable: true, align: "right" },
    { key: "created_at", header: "Created", accessor: (e) => e.created_at, sortable: true, defaultHidden: true,
      render: (e) => <span className="text-xs text-[#64748B]">{formatDate(e.created_at)}</span> },
  ], []);

  const filters: FilterDef<Entity>[] = useMemo(() => [
    { key: "entity_type", label: "Type", type: "select", accessor: (e) => e.entity_type,
      options: ENTITY_TYPES.map((t) => ({ value: t, label: t })) },
  ], []);

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

      {/* Registry table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={entities}
        columns={columns}
        filters={filters}
        getRowId={(e) => e.id}
        loading={loading}
        error={error}
        onRetry={loadEntities}
        onRefresh={loadEntities}
        searchPlaceholder="Search by name, PAN, GSTIN, or email…"
        initialSort={{ key: "full_name", dir: "asc" }}
        exportFilename="entity-registry"
        persistKey="relationships.entities"
        emptyTitle="No entities found"
        emptyDescription="Add an entity or run match detection to populate the registry."
        rowActions={(e) => (
          <a href={`/relationships/${e.id}`} className="text-xs font-medium text-[#182350] hover:underline">
            View →
          </a>
        )}
      />

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
