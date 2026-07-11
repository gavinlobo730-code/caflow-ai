"use client";

/**
 * Product/Service create/edit dialog — shared by ProductServiceManagerPanel
 * (opened from a Sales Invoice line's "+ Add Product/Service" overlay) and
 * the Sales Invoice's inline "+ Create Product/Service" flow (Final Invoice
 * Workflow Alignment: "Everything billed should exist as a Product or
 * Service" — there is ONE creation workflow, not a separate path per caller).
 *
 * Only Name is mandatory; everything else (description, kind, HSN/SAC, GST,
 * selling/purchase price, unit, category) is optional. HSN/SAC is browsed
 * from the firm's own HSN/SAC Library (HsnLookup) — never free-typed.
 *
 * `onSaved` hands back the full saved item (not just a toast string) so an
 * inline caller (the invoice) can auto-select it and fill the line; the
 * management page derives its own toast text from the returned item.
 */
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { api, type ApiResp } from "@/lib/api/index";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { GST_RATES } from "@/lib/invoices/shared";
import {
  validateServiceForm, serviceFormToPayload, serviceToForm,
  type ServiceCatalogueItem, type ServiceFormInput,
} from "@/lib/catalogue/service";

const EMPTY_FORM: ServiceFormInput = {
  name: "", description: "", kind: "service", hsn_sac: "", gstRate: 18,
  rate: "", purchasePrice: "", category: "", notes: "",
};

const inputCls = "w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500";

export function ProductServiceFormModal({
  clientId, existing, seedName, onClose, onSaved, onError,
}: {
  clientId: string;
  existing: ServiceCatalogueItem | null;
  /** Prefills Name from a search query that didn't match anything. */
  seedName?: string;
  onClose: () => void;
  onSaved: (item: ServiceCatalogueItem) => void;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState<ServiceFormInput>(
    existing ? serviceToForm(existing) : { ...EMPTY_FORM, name: seedName ?? "" },
  );
  const [attempted, setAttempted] = useState(false);
  const [saving, setSaving] = useState(false);
  // Shown INSIDE the modal, next to Create/Save — a save failure must never be
  // visible only via onError, since a caller may surface that somewhere the CA
  // isn't looking (e.g. a page-level banner behind this very modal on the
  // Sales Invoice's inline "+ Create Product/Service" flow). onError still
  // fires too, for callers that also want a toast or similar.
  const [saveError, setSaveError] = useState<string | null>(null);
  const v = validateServiceForm(form);

  function set<K extends keyof ServiceFormInput>(k: K, val: ServiceFormInput[K]) {
    setForm((p) => ({ ...p, [k]: val }));
    setSaveError(null);
  }

  function fail(msg: string) {
    setSaveError(msg);
    onError(msg);
  }

  async function submit() {
    setAttempted(true);
    if (!v.ok) return;
    setSaving(true);
    setSaveError(null);
    try {
      const payload = serviceFormToPayload(form, clientId);
      const res = existing
        ? ((await api.serviceCatalogue.update(existing.id, payload)) as ApiResp<ServiceCatalogueItem>)
        : ((await api.serviceCatalogue.create(payload)) as ApiResp<ServiceCatalogueItem>);
      if (!res.success || !res.data) throw new Error(res.error ?? "Save failed");
      if (res.data.duplicate) { fail(`"${form.name.trim()}" already exists for this client.`); return; }
      onSaved(res.data);
    } catch (e) {
      fail(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={existing ? "Edit Product/Service" : "New Product/Service"} onClose={onClose} maxWidthClass="max-w-md">
        <Field label="Name" error={attempted ? v.errors.name : undefined}>
          <input autoFocus value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Statutory Audit, Steel Rod" className={inputCls} />
        </Field>
        <Field label="Description (optional)">
          <input value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Line description shown on the invoice" className={inputCls} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Kind">
            <select value={form.kind} onChange={(e) => set("kind", e.target.value as "good" | "service")} className={inputCls}>
              <option value="service">Service</option>
              <option value="good">Product</option>
            </select>
          </Field>
          <Field label="Category (optional)">
            <input value={form.category} onChange={(e) => set("category", e.target.value)} placeholder="e.g. Compliance" className={inputCls} />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="HSN/SAC (optional)">
            <HsnLookup value={form.hsn_sac} onChange={(val) => set("hsn_sac", val)}
              onPick={(p) => { if (p.gst_rate_bps != null) set("gstRate", Math.round(p.gst_rate_bps / 100)); }}
              type={form.kind === "good" ? "goods" : "services"} size="sm" ariaLabel="HSN or SAC code" />
          </Field>
          <Field label="Default GST rate">
            <select value={form.gstRate} onChange={(e) => set("gstRate", parseFloat(e.target.value))} className={inputCls}>
              {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
            </select>
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Selling price (₹, optional)" error={attempted ? v.errors.rate : undefined}>
            <input type="number" min="0" step="0.01" value={form.rate} onChange={(e) => set("rate", e.target.value)} placeholder="0.00" className={inputCls} />
          </Field>
          <Field label="Purchase price (₹, optional)" error={attempted ? v.errors.purchasePrice : undefined}>
            <input type="number" min="0" step="0.01" value={form.purchasePrice} onChange={(e) => set("purchasePrice", e.target.value)} placeholder="0.00" className={inputCls} />
          </Field>
        </div>
        <Field label="Notes (optional)">
          <textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={2} placeholder="Internal note" className={inputCls} />
        </Field>

        {saveError && (
          <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{saveError}</p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} disabled={saving} className="text-sm px-3.5 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
          <button onClick={submit} disabled={saving} className="text-sm px-4 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 inline-flex items-center gap-1.5">
            {saving && <Loader2 size={14} className="animate-spin" />} {existing ? "Save changes" : "Create"}
          </button>
        </div>
    </Modal>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-xs font-medium text-[#475569]">{label}</span>
      {children}
      {error && <span className="block text-[11px] text-red-600">{error}</span>}
    </label>
  );
}
