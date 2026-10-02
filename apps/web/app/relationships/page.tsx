"use client";

import { useState, useEffect, useMemo, type Dispatch, type SetStateAction } from "react";
import { arrayOrEmpty } from "@/lib/api/shape";
import { errorMessage } from "@/lib/api";
import { Plus, X } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { DataTable } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";
import { formatDate } from "@/lib/services/formatting";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// See loadEntities() below — no server-side ceiling on this endpoint, so this
// is just a generous request size, not an enforced cap.
const ENTITY_FETCH_LIMIT = 2000;

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
  // A refusal carries FastAPI's {detail} with no `error` key, so reading only
  // `.error` showed "Failed to create entity" for a 422 that had a reason.
  if (!res.ok) return { success: false, data: null, error: await errorMessage(res) };
  return res.json();
}
import { Badge } from "@/components/ui/badge";
import { Callout } from "@/components/ui/callout";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";

// ─── Types ───────────────────────────────────────────────────────────────────

// NOT exported: a Next.js `page.tsx` module may only export the framework's
// own reserved names (default, generateStaticParams, ...) — an extra named
// export here fails `tsc` against `.next/types/app/relationships/page.ts`.
// The entity detail page keeps its own copy of this shape for its Edit
// action rather than importing it from here.
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

interface EntityFormValues {
  full_name: string;
  entity_type: EntityType;
  pan: string;
  gstin: string;
  email: string;
  phone: string;
}

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

const EMPTY_FORM: EntityFormValues = {
  full_name: "",
  entity_type: "Individual",
  pan: "",
  gstin: "",
  email: "",
  phone: "",
};

// ─── Add Entity form ────────────────────────────────────────────────────────
//
// Extracted purely for readability inside this page. NOT exported: a
// `page.tsx` may only export the framework's own reserved names, so this
// can't be shared with the entity detail page directly — its Edit action
// (EntityDetailClient.tsx) keeps its own copy of the same field set and
// layout instead.

function EntityFormModal({
  title,
  form,
  setForm,
  onCancel,
  onSave,
  saving,
  saveError,
  saveLabel,
  savingLabel,
  saveDisabled,
}: {
  title: string;
  form: EntityFormValues;
  setForm: Dispatch<SetStateAction<EntityFormValues>>;
  onCancel: () => void;
  onSave: () => void;
  saving: boolean;
  saveError: string | null;
  saveLabel: string;
  savingLabel: string;
  /** An extra condition (e.g. another action in flight) that also disables Save. */
  saveDisabled?: boolean;
}) {
  return (
    <div className="fixed inset-0 bg-brand/60 flex items-center justify-center z-50 px-4">
      <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold text-brand">{title}</h2>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-700">
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-600 font-medium">Full Name *</label>
            <input
              value={form.full_name}
              onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
              className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder:text-ps-hint focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
              placeholder="Individual or entity name"
            />
          </div>
          <div>
            <label className="text-xs text-gray-600 font-medium">Entity Type</label>
            <select
              value={form.entity_type}
              onChange={(e) => setForm((f) => ({ ...f, entity_type: e.target.value as EntityType }))}
              className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
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
                onChange={(e) => setForm((f) => ({ ...f, pan: e.target.value.toUpperCase() }))}
                className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder:text-ps-hint font-mono focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
                placeholder="AAAAA9999A"
                maxLength={10}
              />
            </div>
            <div>
              <label className="text-xs text-gray-600 font-medium">GSTIN</label>
              <input
                value={form.gstin}
                onChange={(e) => setForm((f) => ({ ...f, gstin: e.target.value.toUpperCase() }))}
                className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder:text-ps-hint font-mono focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
                placeholder="22AAAAA0000A1ZC"
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
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder:text-ps-hint focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
                placeholder="contact@example.com"
              />
            </div>
            <div>
              <label className="text-xs text-gray-600 font-medium">Phone</label>
              <input
                type="tel"
                value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 placeholder:text-ps-hint focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
                placeholder="+91 98765 43210"
              />
            </div>
          </div>
        </div>
        {saveError && <Callout tone="problem">{saveError}</Callout>}
        <div className="flex gap-2 mt-5">
          <button
            onClick={onCancel}
            className="flex-1 text-sm text-gray-600 border border-gray-300 py-2 rounded-md hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={onSave}
            disabled={saving || !!saveDisabled || !form.full_name.trim()}
            className="flex-1 text-sm bg-brand text-white py-2 rounded-md hover:bg-brand-dark disabled:opacity-50"
          >
            {saving ? savingLabel : saveLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function RelationshipsPage() {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [entitiesCapped, setEntitiesCapped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [detectLoading, setDetectLoading] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = detectLoading || saving;
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
      // Backend defaults to 50 rows with no upper bound enforced (routers/relationships.py
      // list_entities) — request a generously high ceiling so it's never hit in practice,
      // and still detect it below in case some firm's registry ever does exceed it.
      const json: ApiResponse<Entity[]> = await apiFetch(`/api/relationships/entities?limit=${ENTITY_FETCH_LIMIT}`);
      if (!json.success) throw new Error(json.error ?? "Failed to load entities");
      setEntities(arrayOrEmpty(json.data));
      setEntitiesCapped(json.data.length === ENTITY_FETCH_LIMIT);
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
          // The form has always had a GSTIN box; the payload never sent it.
          gstin: form.gstin.trim().toUpperCase() || null,
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
      render: (e) => <span className="font-medium text-ps-ink">{e.full_name}</span> },
    { key: "entity_type", header: "Type", accessor: (e) => e.entity_type, sortable: true,
      render: (e) => <Badge className={`text-2xs ${ENTITY_TYPE_COLORS[e.entity_type]}`}>{e.entity_type}</Badge> },
    { key: "pan", header: "PAN", accessor: (e) => e.pan ?? "", searchable: true,
      render: (e) => <span className="font-mono text-xs text-ps-label">{e.pan || "—"}</span> },
    { key: "gstin", header: "GSTIN", accessor: (e) => e.gstin ?? "", searchable: true, defaultHidden: true,
      render: (e) => <span className="font-mono text-xs text-ps-label">{e.gstin || "—"}</span> },
    { key: "email", header: "Email", accessor: (e) => e.email ?? "", searchable: true,
      render: (e) => <span className="text-xs text-ps-label">{e.email || "—"}</span> },
    { key: "roles_count", header: "Roles", accessor: (e) => e.roles_count, sortable: true, align: "right" },
    { key: "linked_clients_count", header: "Linked Clients", accessor: (e) => e.linked_clients_count, sortable: true, align: "right" },
    { key: "created_at", header: "Created", accessor: (e) => e.created_at, sortable: true, defaultHidden: true,
      render: (e) => <span className="text-xs text-ps-label">{formatDate(e.created_at)}</span> },
  ], []);

  const filters: FilterDef<Entity>[] = useMemo(() => [
    { key: "entity_type", label: "Type", type: "select", accessor: (e) => e.entity_type,
      options: ENTITY_TYPES.map((t) => ({ value: t, label: t })) },
  ], []);

  return (
    <div className="p-6 space-y-5 bg-ps-bg min-h-full">
      {/* Toast */}
      {detectToast && (
        <div className="fixed top-4 right-4 z-50 bg-white border border-gray-200 text-gray-800 text-sm px-4 py-3 rounded-lg shadow-xl max-w-sm">
          {detectToast}
        </div>
      )}

      {/* Header */}
      <PageHeader
        title="Entity Registry"
        subtitle={
          <>
            {entities.length}{entitiesCapped ? "+" : ""} entities across all clients
            {entitiesCapped && " — refine your search to see more"}
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={handleDetectMatches}
              disabled={actionInFlight}
              className="text-sm text-brand border border-brand/30 px-3 py-1.5 rounded-md hover:bg-brand-light/20 disabled:opacity-50"
            >
              {detectLoading ? "Detecting…" : "Detect Matches"}
            </button>
            <button
              onClick={() => {
                setForm(EMPTY_FORM);
                setSaveError(null);
                setModalOpen(true);
              }}
              className="flex items-center gap-1.5 text-sm bg-brand text-white px-3 py-1.5 rounded-md hover:bg-brand-dark"
            >
              <Plus size={14} /> Add Entity
            </button>
          </div>
        }
      />

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
        emptyDescription="An entity is a person or a company that appears across your clients. Add one, or run match detection to find the ones your clients already share."
        emptyAction={
          <EmptyStateActions>
            <EmptyStateAction requires={["client", "write"]} icon={<Plus size={14} />} label="Add Entity"
              onClick={() => { setForm(EMPTY_FORM); setSaveError(null); setModalOpen(true); }} />
            <EmptyStateAction requires={["client", "write"]} variant="secondary" label="Detect Matches"
              disabled={actionInFlight} onClick={() => handleDetectMatches()} />
          </EmptyStateActions>
        }
        rowActions={(e) => (
          <a href={`/relationships/${e.id}`} className="text-xs font-medium text-brand hover:underline">
            View →
          </a>
        )}
      />

      {/* Add Entity Modal — see EntityFormModal above */}
      {modalOpen && (
        <EntityFormModal
          title="Add Entity"
          form={form}
          setForm={setForm}
          onCancel={() => setModalOpen(false)}
          onSave={handleAddEntity}
          saving={saving}
          saveError={saveError}
          saveLabel="Add Entity"
          savingLabel="Adding…"
          saveDisabled={detectLoading}
        />
      )}
    </div>
  );
}
