"use client";

import { useState, useEffect, useCallback, type Dispatch, type SetStateAction } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, CheckCircle, XCircle, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Callout } from "@/components/ui/callout";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { getSupabaseClient } from "@/lib/supabase/client";
import { errorMessage } from "@/lib/api";
import { formatDate as formatDateShared } from "@/lib/services/formatting";

// Same shape and field set as the "Add Entity" form on the Entity Registry
// list (apps/web/app/relationships/page.tsx) — kept as its own copy here
// rather than imported, because a Next.js `page.tsx` may only export the
// framework's own reserved names (see the note beside EntityFormModal there).
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

interface EntityFormValues {
  full_name: string;
  entity_type: EntityType;
  pan: string;
  gstin: string;
  email: string;
  phone: string;
}

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
  // A refusal carries FastAPI's {detail} with no `error` key, so reading only
  // `.error` showed a bare "Failed to ..." for a 422 that had a reason — the
  // same fix the Add Entity form already carries.
  if (!res.ok) return { success: false, data: null, error: await errorMessage(res) };
  return res.json();
}

const EMPTY_EDIT_FORM: EntityFormValues = {
  full_name: "",
  entity_type: "Individual",
  pan: "",
  gstin: "",
  email: "",
  phone: "",
};

// ─── Edit Entity form ───────────────────────────────────────────────────────
//
// Same field set and layout as the Entity Registry's "Add Entity" form
// (apps/web/app/relationships/page.tsx) so the two never look or behave like
// two different products.

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
  saveDisabled?: boolean;
}) {
  const inputClass =
    "w-full mt-1 px-3 py-2 text-sm bg-ps-surface border border-ps-border-strong rounded-md text-ps-ink placeholder-ps-hint focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand";
  return (
    <div className="fixed inset-0 bg-brand/60 flex items-center justify-center z-50 px-4">
      <div className="bg-ps-surface border border-ps-border rounded-xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold text-brand">{title}</h2>
          <button onClick={onCancel} className="text-ps-hint hover:text-ps-body">
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-ps-label font-medium">Full Name *</label>
            <input
              value={form.full_name}
              onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
              className={inputClass}
              placeholder="Individual or entity name"
            />
          </div>
          <div>
            <label className="text-xs text-ps-label font-medium">Entity Type</label>
            <select
              value={form.entity_type}
              onChange={(e) => setForm((f) => ({ ...f, entity_type: e.target.value as EntityType }))}
              className={inputClass}
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
              <label className="text-xs text-ps-label font-medium">PAN</label>
              <input
                value={form.pan}
                onChange={(e) => setForm((f) => ({ ...f, pan: e.target.value.toUpperCase() }))}
                className={`${inputClass} font-mono`}
                placeholder="AAAAA9999A"
                maxLength={10}
              />
            </div>
            <div>
              <label className="text-xs text-ps-label font-medium">GSTIN</label>
              <input
                value={form.gstin}
                onChange={(e) => setForm((f) => ({ ...f, gstin: e.target.value.toUpperCase() }))}
                className={`${inputClass} font-mono`}
                placeholder="22AAAAA0000A1ZC"
                maxLength={15}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-ps-label font-medium">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                className={inputClass}
                placeholder="contact@example.com"
              />
            </div>
            <div>
              <label className="text-xs text-ps-label font-medium">Phone</label>
              <input
                type="tel"
                value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                className={inputClass}
                placeholder="+91 98765 43210"
              />
            </div>
          </div>
        </div>
        {saveError && <Callout tone="problem">{saveError}</Callout>}
        <div className="flex gap-2 mt-5">
          <button
            onClick={onCancel}
            className="flex-1 text-sm text-ps-label border border-ps-border-strong py-2 rounded-md hover:bg-ps-hover"
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
  // Defaults to true in the schema; treated as active unless the server says
  // otherwise so an older cached row with no such key still renders as active.
  is_active?: boolean | null;
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

function getEntityIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/^\/relationships\/([^/]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export default function EntityDetailPage() {
  // NOT useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real
  // /relationships/{id} URL (see scripts/generate-redirects.js), so
  // useParams().entity_id is the literal string "_placeholder" — both fetches
  // below then requested entity "_placeholder" and the page showed "Entity not
  // found" for every entity. window.location.pathname is always the real
  // browser URL; usePathname() is only a re-run trigger, since its own value is
  // the placeholder segment. This route is outside /clients/[id]/**, so there
  // is no ClientNavProvider to borrow — same fix as
  // lib/workspace/ClientNavContext.tsx, done locally.
  const pathname = usePathname();
  const [entityId, setEntityId] = useState<string>(getEntityIdFromLocation);
  useEffect(() => { setEntityId(getEntityIdFromLocation()); }, [pathname]);

  const [entity, setEntity] = useState<Entity | null>(null);
  const [roles, setRoles] = useState<EntityRole[]>([]);
  const [relationships, setRelationships] = useState<EntityRelationship[]>([]);
  const [matches, setMatches] = useState<CrossClientMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Scoped separately from the page-level `error`: a matches-fetch failure
  // shouldn't hide the whole (successfully-loaded) entity page behind the
  // "Entity not found" error screen — only the Matches tab needs to know.
  const [matchesError, setMatchesError] = useState<string | null>(null);
  // Scoped to the Cross-Client Matches tab/count only — see loadAll below.
  const [matchesLoading, setMatchesLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [processingMatchId, setProcessingMatchId] = useState<string | null>(null);
  const [matchActionError, setMatchActionError] = useState<string | null>(null);

  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editForm, setEditForm] = useState<EntityFormValues>(EMPTY_EDIT_FORM);
  const [editSaving, setEditSaving] = useState(false);
  const [editSaveError, setEditSaveError] = useState<string | null>(null);
  const [statusSaving, setStatusSaving] = useState(false);
  const [statusSaveError, setStatusSaveError] = useState<string | null>(null);

  const loadMatches = useCallback(async () => {
    setMatchesLoading(true);
    try {
      const matchesJson: ApiResponse<CrossClientMatch[]> = await apiFetch(
        `/api/relationships/cross-client-matches?entity_id=${entityId}`
      );
      if (!matchesJson.success) throw new Error(matchesJson.error ?? "Failed to load cross-client matches");
      setMatches(matchesJson.data);
      setMatchesError(null);
    } catch (e) {
      setMatches([]);
      setMatchesError(e instanceof Error ? e.message : "Failed to load cross-client matches");
    } finally {
      setMatchesLoading(false);
    }
  }, [entityId]);

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

      // Cross-client matches filtered for this entity — a failure here must
      // not masquerade as "no cross-client matches detected", and must not
      // hold up the rest of the page either: not awaited, so the `finally`
      // below (and the skeleton it clears) does not wait on it. Matches load
      // independently under their own `matchesLoading`, scoped to the
      // Matches tab/count.
      void loadMatches();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [entityId, loadMatches]);

  useEffect(() => {
    // "" until the effect above resolves the id, "_placeholder" only if the
    // build-time shell URL is opened directly. Neither can load anything, so
    // clear the skeleton and fall through to the "Entity not found" panel
    // below rather than leaving a skeleton up forever.
    if (!entityId || entityId === "_placeholder") { setLoading(false); return; }
    loadAll();
  }, [entityId, loadAll]);

  async function handleMatchAction(matchId: string, action: "confirm" | "dismiss") {
    setProcessingMatchId(matchId);
    setMatchActionError(null);
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
    } catch (e) {
      // The buttons must not appear to do nothing on failure.
      setMatchActionError(e instanceof Error ? e.message : "Action failed. Please retry.");
    } finally {
      setProcessingMatchId(null);
    }
  }

  function openEditModal() {
    if (!entity) return;
    setEditForm({
      full_name: entity.full_name,
      entity_type: (entity.entity_type as EntityType) || "Individual",
      pan: entity.pan ?? "",
      gstin: entity.gstin ?? "",
      email: entity.email ?? "",
      phone: entity.phone ?? "",
    });
    setEditSaveError(null);
    setEditModalOpen(true);
  }

  async function handleSaveEdit() {
    if (!editForm.full_name.trim()) return;
    setEditSaving(true);
    setEditSaveError(null);
    try {
      const json: ApiResponse<Entity> = await apiFetch(`/api/relationships/entities/${entityId}`, {
        method: "PATCH",
        body: JSON.stringify({
          full_name: editForm.full_name.trim(),
          entity_type: editForm.entity_type,
          pan: editForm.pan.trim().toUpperCase() || null,
          gstin: editForm.gstin.trim().toUpperCase() || null,
          email: editForm.email.trim() || null,
          phone: editForm.phone.trim() || null,
        }),
      });
      if (!json.success) throw new Error(json.error ?? "Failed to update entity");
      // Trust what the server actually stored rather than the values just
      // typed — the entity graph matches people across clients on these
      // fields, so the screen must show what was saved, not what was sent.
      setEntity((prev) => (prev ? { ...prev, ...json.data } : json.data));
      setEditModalOpen(false);
    } catch (e) {
      setEditSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setEditSaving(false);
    }
  }

  async function handleToggleActive() {
    if (!entity) return;
    const reactivating = entity.is_active === false;
    const ok = await confirmDialog({
      title: reactivating ? "Reactivate entity?" : "Deactivate entity?",
      message: reactivating
        ? `${entity.full_name} will appear in the Entity Registry again.`
        : `${entity.full_name} will be hidden from the Entity Registry. Its roles, relationships and history are kept.`,
      confirmLabel: reactivating ? "Reactivate" : "Deactivate",
      danger: !reactivating,
    });
    if (!ok) return;
    setStatusSaving(true);
    setStatusSaveError(null);
    try {
      const json: ApiResponse<Entity> = await apiFetch(`/api/relationships/entities/${entityId}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: reactivating }),
      });
      if (!json.success) throw new Error(json.error ?? "Failed to update entity");
      setEntity((prev) => (prev ? { ...prev, ...json.data } : json.data));
    } catch (e) {
      setStatusSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setStatusSaving(false);
    }
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return "—";
    try {
      return formatDateShared(dateStr);
    } catch {
      return dateStr;
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-5">
        <Skeleton className="h-3 w-32 bg-gray-700" />
        <div className="space-y-2">
          <Skeleton className="h-5 w-56 bg-gray-700" />
          <Skeleton className="h-3 w-24 bg-gray-700" />
        </div>
        <div className="flex gap-4 border-b border-gray-700 pb-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-3 w-20 bg-gray-700" />
          ))}
        </div>
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
          <div className="grid grid-cols-2 gap-4">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="space-y-1.5">
                <Skeleton className="h-2.5 w-16 bg-gray-700" />
                <Skeleton className="h-3 w-28 bg-gray-700" />
              </div>
            ))}
          </div>
        </div>
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
    // No count while the request is still in flight, so the tab doesn't flash
    // "(0)" before the real figure arrives.
    { id: "matches", label: "Cross-Client Matches", count: matchesLoading ? undefined : matches.length },
  ];
  const isInactive = entity.is_active === false;

  return (
    <div className="p-6 space-y-5">
      {/* Back nav */}
      <Link href="/relationships" className="flex items-center gap-1 text-xs text-slate-400 hover:text-white">
        <ChevronLeft size={14} /> Entity Registry
      </Link>

      {/* Entity header */}
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-white">{entity.full_name}</h1>
          {isInactive && <Badge variant="secondary" className="text-2xs">Inactive</Badge>}
        </div>
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
        <div className="space-y-3">
          <div className="flex items-center justify-end gap-3">
            {statusSaveError && <span className="text-xs text-destructive">{statusSaveError}</span>}
            <Button
              size="sm"
              variant="outline"
              onClick={openEditModal}
              disabled={statusSaving}
              className="h-auto text-xs font-medium px-3 py-1.5"
            >
              Edit
            </Button>
            <Button
              size="sm"
              variant={isInactive ? "secondary" : "destructive"}
              onClick={handleToggleActive}
              disabled={statusSaving}
              className="h-auto text-xs font-medium px-3 py-1.5"
            >
              {statusSaving ? "Saving…" : isInactive ? "Reactivate" : "Deactivate"}
            </Button>
          </div>
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
        </div>
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
                        <Badge className="bg-cyan-800 text-cyan-300 text-2xs">{role.role_type}</Badge>
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
                        <Badge className="bg-slate-700 text-slate-300 text-2xs">{rel.relationship_type}</Badge>
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
            {matchActionError && (
              <div className="px-5 py-2.5 border-b border-gray-700 text-xs text-red-400">{matchActionError}</div>
            )}
            {matchesLoading ? (
              <div className="text-center py-12">
                <p className="text-sm text-slate-500">Loading cross-client matches…</p>
              </div>
            ) : matchesError ? (
              <div className="text-center py-12 space-y-2">
                <p className="text-sm text-red-400 font-medium">{matchesError}</p>
                <button
                  onClick={loadMatches}
                  className="text-xs px-3 py-1 border border-gray-600 rounded hover:bg-gray-700 text-gray-300"
                >
                  Retry
                </button>
              </div>
            ) : matches.length === 0 ? (
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
                        <Badge className="bg-violet-800 text-violet-300 text-2xs">{match.match_type}</Badge>
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
                          className={`text-2xs ${
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

      {/* Edit Entity Modal — same field set and layout as the registry's Add Entity form */}
      {editModalOpen && (
        <EntityFormModal
          title="Edit Entity"
          form={editForm}
          setForm={setEditForm}
          onCancel={() => setEditModalOpen(false)}
          onSave={handleSaveEdit}
          saving={editSaving}
          saveError={editSaveError}
          saveLabel="Save"
          savingLabel="Saving…"
          saveDisabled={statusSaving}
        />
      )}
    </div>
  );
}
