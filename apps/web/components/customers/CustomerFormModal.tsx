"use client";

/**
 * Customer create/edit dialog — extracted from the Sales → Customers tab's
 * inline form (Sales Invoice Import Alignment) so the SAME creation workflow
 * can be reused by the CSV import "resolve missing references" step: a row
 * naming a customer that doesn't exist yet for this client opens this dialog
 * seeded with that name, exactly like the Product/Service importer flow
 * (one creation workflow, not a separate path per caller — the same
 * principle ProductServiceFormModal already established).
 *
 * `onSaved` hands back the full saved customer (not just a toast string) so
 * the import resolver can use its id immediately; the Customers-tab caller
 * derives its own toast text from the returned record.
 */
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { StateLookup } from "@/components/lookups/StateLookup";
import {
  apiCall, getAuthToken, INDIAN_STATES, type Customer,
} from "@/lib/invoices/shared";
import { clearReports } from "@/lib/accounting/reportCache";
import {
  PAYMENT_TERM_PRESETS, CUSTOM_TERM, termLabelForDays, daysForTermLabel,
} from "@/lib/sales/paymentTerms";

/** Validate GSTIN format: 2-digit state + PAN(10) + entity# + Z + check (CGST Act §25) */
export function isValidGstin(gstin: string): boolean {
  return /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(gstin);
}

/** Validate PAN format: AAAAA9999A (IT Act §139A) */
export function isValidPan(pan: string): boolean {
  return /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test(pan);
}

const inputCls = "w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";

export function CustomerFormModal({
  clientId, existing, seedName, onClose, onSaved, onError,
}: {
  clientId: string;
  existing: Customer | null;
  /** Prefills Name — e.g. from an import row's unmatched customer name. */
  seedName?: string;
  onClose: () => void;
  onSaved: (customer: Customer) => void;
  /** Forwarded save errors. If omitted, the dialog shows its own inline message. */
  onError?: (msg: string) => void;
}) {
  const [name, setName] = useState(existing?.name ?? seedName ?? "");
  const [gstin, setGstin] = useState(existing?.gstin ?? "");
  const [stateCode, setStateCode] = useState(existing?.state_code ?? "");
  const [pan, setPan] = useState(existing?.pan ?? "");
  const [email, setEmail] = useState(existing?.email ?? "");
  const [phone, setPhone] = useState(existing?.phone ?? "");
  const [city, setCity] = useState(existing?.city ?? "");
  const [state, setState] = useState(existing?.state ?? "");
  const [openingBalance, setOpeningBalance] = useState(
    existing ? (existing.opening_balance_paise / 100).toFixed(2) : "",
  );
  const [creditDays, setCreditDays] = useState(String(existing?.credit_days ?? 30));
  // Payment Terms = a label over credit days (the default for this customer's
  // future invoices). "Custom" reveals a free credit-days input.
  const [termCustom, setTermCustom] = useState<boolean>(
    () => termLabelForDays(existing?.credit_days ?? 30) === CUSTOM_TERM,
  );
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const termValue = termCustom ? CUSTOM_TERM : termLabelForDays(parseInt(creditDays, 10));
  function onTermChange(label: string) {
    if (label === CUSTOM_TERM) { setTermCustom(true); return; }
    const d = daysForTermLabel(label);
    if (d == null) return;
    setTermCustom(false);
    setCreditDays(String(d));
  }

  // Auto-fill state code from GSTIN (first 2 digits)
  function handleGstinChange(val: string) {
    const upper = val.toUpperCase();
    setGstin(upper);
    if (upper.length >= 2) setStateCode(upper.slice(0, 2));
  }

  function fail(msg: string) {
    if (onError) onError(msg); else setLocalError(msg);
  }

  async function handleSave() {
    if (!name.trim()) { fail("Name is required"); return; }
    if (gstin && !isValidGstin(gstin)) { fail("Invalid GSTIN format (e.g. 27AABCU9603R1ZX)"); return; }
    if (pan && !isValidPan(pan)) { fail("Invalid PAN format (e.g. ABCDE1234F)"); return; }

    setSaving(true); setLocalError(null);
    try {
      // All amounts in integer paise — user enters rupees, multiply by 100
      const openingBalancePaise = Math.round(parseFloat(openingBalance || "0") * 100);
      const token = await getAuthToken();

      const result = existing
        // UPDATE via the backend PATCH so an opening-balance change auto-posts
        // to the General Ledger (the backend regenerates the opening
        // journal). No direct Supabase write, no manual "post" step.
        ? await apiCall(`/api/customers/${existing.id}`, "PATCH", {
            name: name.trim(),
            gstin: gstin.trim(),
            state_code: stateCode,
            pan: pan.trim(),
            email: email.trim(),
            phone: phone.trim(),
            city: city.trim(),
            state: state.trim(),
            opening_balance_paise: openingBalancePaise,
            credit_days: parseInt(creditDays) || 30,
            is_active: true,
          }, token)
        : await apiCall("/api/customers/", "POST", {
            client_id: clientId,
            name: name.trim(),
            gstin: gstin.trim() || undefined,
            state_code: stateCode || undefined,
            pan: pan.trim() || undefined,
            email: email.trim() || undefined,
            phone: phone.trim() || undefined,
            city: city.trim() || undefined,
            state: state.trim() || undefined,
            opening_balance_paise: openingBalancePaise,
            credit_days: parseInt(creditDays) || 30,
          }, token);
      if (!result.success || !result.data) throw new Error(result.error ?? "Failed to save customer");
      // The backend may have auto-posted/updated the opening-balance journal, so
      // invalidate cached accounting reports for this client.
      clearReports(clientId);
      onSaved(result.data as Customer);
    } catch (err) {
      fail(err instanceof Error ? err.message : "Failed to save customer");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={existing ? "Edit Customer" : "Add Customer"} onClose={onClose} maxWidthClass="max-w-2xl">
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="col-span-2 lg:col-span-1">
          <label className="block text-xs font-medium text-[#475569] mb-1">Name *</label>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="ABC Pvt Ltd" className={inputCls} />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">GSTIN</label>
          <input
            value={gstin} onChange={(e) => handleGstinChange(e.target.value)}
            placeholder="27AABCU9603R1ZX" maxLength={15}
            className={`${inputCls} font-mono ${gstin && !isValidGstin(gstin) ? "border-red-300" : ""}`}
          />
          {gstin && !isValidGstin(gstin) && <p className="text-[10px] text-red-500 mt-0.5">Invalid GSTIN</p>}
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">State Code</label>
          <StateLookup states={INDIAN_STATES} value={stateCode} onChange={setStateCode} placeholder="— Select —" ariaLabel="State code" />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">PAN</label>
          <input
            value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())}
            placeholder="ABCDE1234F" maxLength={10}
            className={`${inputCls} font-mono ${pan && !isValidPan(pan) ? "border-red-300" : ""}`}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="billing@abc.com" className={inputCls} />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Phone</label>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 98765 43210" className={inputCls} />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">City</label>
          <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Mumbai" className={inputCls} />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">State</label>
          <input value={state} onChange={(e) => setState(e.target.value)} placeholder="Maharashtra" className={inputCls} />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Opening Balance (₹)</label>
          <input type="number" min="0" step="0.01" value={openingBalance} onChange={(e) => setOpeningBalance(e.target.value)}
            placeholder="0.00" className={`${inputCls} text-right font-mono`} />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Payment Terms</label>
          <select value={termValue} onChange={(e) => onTermChange(e.target.value)} className={inputCls}>
            {PAYMENT_TERM_PRESETS.map((t) => <option key={t.label} value={t.label}>{t.label}</option>)}
            <option value={CUSTOM_TERM}>Custom</option>
          </select>
          {termCustom && (
            <input type="number" min="0" value={creditDays} onChange={(e) => setCreditDays(e.target.value)}
              placeholder="Credit days" aria-label="Custom credit days" className={`mt-1 ${inputCls}`} />
          )}
          <p className="mt-1 text-[10px] text-[#94A3B8]">Default terms for this customer&apos;s new invoices.</p>
        </div>
      </div>

      {localError && !onError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{localError}</p>}
      <div className="flex gap-3 justify-end">
        <button onClick={onClose} disabled={saving} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
        <button onClick={handleSave} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
          {saving && <Loader2 size={13} className="animate-spin" />} {saving ? "Saving…" : existing ? "Update Customer" : "Add Customer"}
        </button>
      </div>
    </Modal>
  );
}
