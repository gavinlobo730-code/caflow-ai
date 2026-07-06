"use client";

/**
 * Service Catalogue management (Batch 6) — create/edit/archive/restore/search the
 * firm's reusable, SERVICES-ONLY billing presets. Not an inventory master: the
 * form captures billing defaults only (SAC, GST, unit price) — no stock, no
 * valuation, no quantity. Reuses the shared api client, HsnLookup and GST slabs.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Pencil, Archive, RotateCcw, Search, Loader2, BookMarked, X } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type ApiResp } from "@/lib/api/index";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { GST_RATES } from "@/lib/invoices/shared";
import {
  validateServiceForm, serviceFormToPayload, serviceToForm,
  formatServiceRate, formatServicePrice,
  type ServiceCatalogueItem, type ServiceFormInput,
} from "@/lib/catalogue/service";

type Filter = "active" | "archived";

const EMPTY_FORM: ServiceFormInput = {
  name: "", description: "", hsn_sac: "", gstRate: 18, rate: "", unit: "", notes: "",
};

export default function ServiceCataloguePage() {
  const [items, setItems] = useState<ServiceCatalogueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("active");
  const [editing, setEditing] = useState<ServiceCatalogueItem | "new" | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: "success" | "error" } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showToast(msg: string, kind: "success" | "error") {
    setToast({ msg, kind });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = (await api.serviceCatalogue.list({
        q: q.trim() || undefined,
        include_archived: filter === "archived",
        limit: 100,
      })) as ApiResp<ServiceCatalogueItem[]>;
      if (!res.success) { setError(true); return; }
      const rows = res.data ?? [];
      // include_archived returns both; the "archived" tab shows only archived.
      setItems(filter === "archived" ? rows.filter((r) => !r.is_active) : rows);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [q, filter]);

  useEffect(() => {
    const t = setTimeout(load, 200); // debounce search
    return () => clearTimeout(t);
  }, [load]);

  async function setActive(item: ServiceCatalogueItem, is_active: boolean) {
    try {
      const res = (await api.serviceCatalogue.update(item.id, { is_active })) as ApiResp<unknown>;
      if (!res.success) throw new Error(res.error ?? "Update failed");
      showToast(`${item.name} ${is_active ? "restored" : "archived"}`, "success");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Update failed", "error");
    }
  }

  return (
    <RoleGuard allowed={["Partner", "Manager"]}>
      <div className="p-6 max-w-4xl mx-auto space-y-5">
        {toast && (
          <div className={`fixed top-4 right-4 z-[70] px-4 py-2 rounded-lg text-sm shadow-lg ${toast.kind === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
            {toast.msg}
          </div>
        )}

        <div>
          <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-[#94A3B8] hover:text-[#475569] transition-colors mb-1">
            <ChevronLeft size={13} /> Settings
          </Link>
          <div className="flex items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold text-[#0F172A] flex items-center gap-2"><BookMarked size={18} className="text-emerald-600" /> Service Catalogue</h1>
              <p className="text-sm text-[#64748B] mt-0.5">Reusable service presets that pre-fill an invoice line. No stock or inventory — billing defaults only.</p>
            </div>
            <button
              onClick={() => setEditing("new")}
              className="flex items-center gap-1.5 text-sm bg-emerald-600 text-white px-3.5 py-2 rounded-lg hover:bg-emerald-700 whitespace-nowrap"
            >
              <Plus size={15} /> New Service
            </button>
          </div>
        </div>

        {/* Search + filter */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by name, SAC or description…"
              className="w-full pl-8 pr-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div className="flex rounded-lg border border-[#E2E8F0] overflow-hidden text-xs">
            {(["active", "archived"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-2 capitalize ${filter === f ? "bg-emerald-600 text-white" : "bg-white text-[#475569] hover:bg-[#F8FAFC]"}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          {loading ? (
            <div className="p-4 space-y-2">
              {[...Array(4)].map((_, i) => <div key={i} className="h-11 rounded bg-[#F8FAFC] animate-pulse" />)}
            </div>
          ) : error ? (
            <div className="p-8 text-center text-sm">
              <p className="text-[#334155] font-medium">Couldn&apos;t load the catalogue</p>
              <button onClick={load} className="mt-2 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Retry</button>
            </div>
          ) : items.length === 0 ? (
            <div className="p-10 text-center">
              <BookMarked size={26} className="mx-auto mb-2 text-[#CBD5E1]" />
              <p className="text-sm font-medium text-[#334155]">
                {q ? "No services match your search" : filter === "archived" ? "No archived services" : "No services yet"}
              </p>
              {!q && filter === "active" && (
                <button onClick={() => setEditing("new")} className="mt-3 text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">
                  Create your first service
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <thead>
                  <tr className="text-[11px] text-[#94A3B8] border-b border-[#F1F5F9]">
                    <th className="px-4 py-2 text-left font-semibold">Service</th>
                    <th className="px-4 py-2 text-left font-semibold">SAC/HSN</th>
                    <th className="px-4 py-2 text-right font-semibold">GST</th>
                    <th className="px-4 py-2 text-right font-semibold">Default price</th>
                    <th className="px-4 py-2 text-right font-semibold w-24"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {items.map((s) => (
                    <tr key={s.id} className={s.is_active ? "" : "bg-[#FAFAFA] text-[#94A3B8]"}>
                      <td className="px-4 py-2.5">
                        <p className="font-medium text-[#1E293B]">{s.name}{!s.is_active && <span className="ml-2 text-[10px] uppercase tracking-wide text-[#94A3B8]">archived</span>}</p>
                        {s.description && <p className="text-[11px] text-[#94A3B8] truncate max-w-[280px]">{s.description}</p>}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-[#64748B]">{s.hsn_sac || "—"}</td>
                      <td className="px-4 py-2.5 text-right text-[#334155]">{formatServiceRate(s.gst_rate_bps) || "—"}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-[#334155]">{formatServicePrice(s.default_rate_paise) || "—"}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => setEditing(s)} className="p-1.5 text-[#64748B] hover:text-emerald-600 hover:bg-emerald-50 rounded" aria-label="Edit"><Pencil size={14} /></button>
                          {s.is_active ? (
                            <button onClick={() => setActive(s, false)} className="p-1.5 text-[#64748B] hover:text-amber-600 hover:bg-amber-50 rounded" aria-label="Archive"><Archive size={14} /></button>
                          ) : (
                            <button onClick={() => setActive(s, true)} className="p-1.5 text-[#64748B] hover:text-emerald-600 hover:bg-emerald-50 rounded" aria-label="Restore"><RotateCcw size={14} /></button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {editing && (
        <ServiceFormModal
          existing={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(msg) => { setEditing(null); showToast(msg, "success"); load(); }}
          onError={(msg) => showToast(msg, "error")}
        />
      )}
    </RoleGuard>
  );
}

function ServiceFormModal({ existing, onClose, onSaved, onError }: {
  existing: ServiceCatalogueItem | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState<ServiceFormInput>(existing ? serviceToForm(existing) : EMPTY_FORM);
  const [attempted, setAttempted] = useState(false);
  const [saving, setSaving] = useState(false);
  const v = validateServiceForm(form);

  function set<K extends keyof ServiceFormInput>(k: K, val: ServiceFormInput[K]) {
    setForm((p) => ({ ...p, [k]: val }));
  }

  async function submit() {
    setAttempted(true);
    if (!v.ok) return;
    setSaving(true);
    try {
      const payload = serviceFormToPayload(form);
      const res = existing
        ? ((await api.serviceCatalogue.update(existing.id, payload)) as ApiResp<ServiceCatalogueItem>)
        : ((await api.serviceCatalogue.create(payload)) as ApiResp<ServiceCatalogueItem>);
      if (!res.success) throw new Error(res.error ?? "Save failed");
      if (res.data?.duplicate) { onError(`A service named “${form.name.trim()}” already exists.`); return; }
      onSaved(existing ? `${form.name.trim()} updated` : `${form.name.trim()} created`);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative w-full max-w-md bg-white rounded-xl shadow-xl p-5 space-y-3 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">{existing ? "Edit service" : "New service"}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>

        <Field label="Service name" error={attempted ? v.errors.name : undefined}>
          <input autoFocus value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Statutory Audit" className={inputCls} />
        </Field>
        <Field label="Description (optional)">
          <input value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Line description (defaults to the name)" className={inputCls} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Default SAC/HSN (optional)">
            <HsnLookup value={form.hsn_sac} onChange={(val) => set("hsn_sac", val)}
              onPick={(p) => { if (p.gst_rate_bps != null) set("gstRate", Math.round(p.gst_rate_bps / 100)); }}
              type="services" size="sm" ariaLabel="Default SAC or HSN" />
          </Field>
          <Field label="Default GST rate">
            <select value={form.gstRate} onChange={(e) => set("gstRate", parseFloat(e.target.value))} className={inputCls}>
              {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
            </select>
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Default price (₹, optional)" error={attempted ? v.errors.rate : undefined}>
            <input type="number" min="0" step="0.01" value={form.rate} onChange={(e) => set("rate", e.target.value)} placeholder="0.00" className={inputCls} />
          </Field>
          <Field label="Unit (optional)">
            <input value={form.unit} onChange={(e) => set("unit", e.target.value)} placeholder="e.g. OTH, HRS" className={inputCls} />
          </Field>
        </div>
        <Field label="Notes (optional)">
          <textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={2} placeholder="Internal note" className={inputCls} />
        </Field>

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} disabled={saving} className="text-sm px-3.5 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
          <button onClick={submit} disabled={saving} className="text-sm px-4 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 inline-flex items-center gap-1.5">
            {saving && <Loader2 size={14} className="animate-spin" />} {existing ? "Save changes" : "Create service"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputCls = "w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-xs font-medium text-[#475569]">{label}</span>
      {children}
      {error && <span className="block text-[11px] text-red-600">{error}</span>}
    </label>
  );
}
