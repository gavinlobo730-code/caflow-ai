"use client";

/**
 * SalesDebitNoteEditor — dedicated create/edit experience for Sales Debit
 * Notes, mirroring DebitNoteEditor's architecture (InvoiceWorkspaceLayout,
 * dirty-changes guard, per-field validation, live GST preview) instead of
 * the old inline form on the Sales page. No business logic is duplicated:
 * totals shown here are a preview (lib/invoices/gst.ts's previewTotals,
 * matches sales_debit_notes.py's _compute_line_gst exactly — same rule as
 * sales_invoices.py); the backend remains authoritative and recomputes
 * everything on save.
 *
 * Deliberately mirrors the Sales Invoice baseline, not the Purchase Debit
 * Note: no Reverse Charge toggle (RCM doesn't apply sales-side) and no
 * attachment/upload section (the Sales Invoice editor has none either —
 * parity means matching the baseline, not exceeding it).
 *
 * Once issued, a debit note is immutable except `notes` (CGST Act §34 —
 * correct it with a fresh note, not an edit); there is deliberately no
 * Cancel/reversal path, unlike Sales Invoices.
 */
import { useState, useRef, useEffect } from "react";
import { Trash2, Plus, Loader2, AlertCircle } from "lucide-react";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { EntityLookup } from "@/components/lookups/EntityLookup";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import { serviceToLine, type ServiceCatalogueItem } from "@/lib/catalogue/service";
import { UQC_CODES } from "@/lib/constants/uqc";
import { hasChanges, useUnsavedChanges } from "@/lib/invoices/dirtyState";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { toInvoiceLinePayload } from "@/lib/invoices/lineItemPayload";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import {
  apiCall, getAuthToken, fmt, GST_RATES,
  previewTotals, isValidLine,
  type Customer, type InvoiceLine,
} from "@/lib/invoices/shared";
import { validateSalesDebitNoteEditor } from "@/lib/sales/salesDebitNoteEditor";

const EMPTY_LINE: InvoiceLine = { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "NOS" };

type EditorLine = InvoiceLine & { _k: number; product?: ServiceCatalogueItem | null };

function todayISO(): string {
  return new Date().toISOString().split("T")[0];
}

/** Open invoices this customer has — the "Against Invoice" picker. Filtered
 * (query-side) to non-draft, non-cancelled: a debit note corrects an
 * invoice that was actually issued (CGST Act §34(3)), matching the same
 * status filter Purchase Debit Note's "Against Bill" picker applies. */
export interface OpenInvoiceOption {
  id: string;
  invoice_no: string;
  total_paise: number;
  paid_paise: number;
  credited_paise: number;
  debit_note_paise: number;
}

function invoiceOutstanding(inv: OpenInvoiceOption): number {
  return (inv.total_paise + (inv.debit_note_paise ?? 0)) - inv.paid_paise - (inv.credited_paise ?? 0);
}

/** Server line shape (from GET /api/sales-debit-notes/{id}). */
export interface SalesDebitNoteLineDetail {
  id?: string;
  description: string;
  hsn_sac: string | null;
  quantity: number;
  unit?: string | null;
  rate_paise: number;
  gst_rate_bps: number;
  service_catalogue_id?: string | null;
}

export interface SalesDebitNoteDetail {
  id: string;
  customer_id: string;
  debit_note_no: string;
  debit_note_date: string;
  sales_invoice_id?: string | null;
  reason?: string | null;
  is_interstate?: boolean;
  status: string;
  notes?: string | null;
  taxable_amount_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  total_gst_paise?: number;
  total_paise?: number;
  applied_paise?: number;
  journal_entry_id?: string | null;
  created_at?: string | null;
  lines: SalesDebitNoteLineDetail[];
}

function detailLinesToEditorLines(lines: SalesDebitNoteDetail["lines"]): EditorLine[] {
  return lines.map((l, i) => ({
    description: l.description ?? "",
    hsn_sac: l.hsn_sac ?? "",
    qty: String(l.quantity ?? 1),
    rate: String((l.rate_paise ?? 0) / 100),
    gst_rate: Math.round((l.gst_rate_bps ?? 0) / 100),
    unit: l.unit ?? "NOS",
    serviceCatalogueId: l.service_catalogue_id ?? null,
    _k: i,
  }));
}

export function SalesDebitNoteEditor({
  clientId, clientName, customers, existing, duplicateSeed, onDone, onCancel,
}: {
  clientId: string;
  clientName?: string;
  customers: Customer[];
  /** Set → edit an existing draft/issued note (PATCH). Absent/null → create (POST). */
  existing?: SalesDebitNoteDetail | null;
  /** "Duplicate debit note" prefill — create mode only. sales_invoice_id is
   * deliberately NOT copied (see lib/sales/salesDebitNoteDuplicateSeed.ts). */
  duplicateSeed?: SalesDebitNoteDetail | null;
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const today = todayISO();
  const isEdit = !!existing;
  const initialLines: EditorLine[] =
    existing && existing.lines.length > 0 ? detailLinesToEditorLines(existing.lines)
    : duplicateSeed && duplicateSeed.lines.length > 0 ? detailLinesToEditorLines(duplicateSeed.lines)
    : [{ ...EMPTY_LINE, _k: 0 }];

  const [customerId, setCustomerId] = useState(existing?.customer_id ?? duplicateSeed?.customer_id ?? "");
  const [dnDate, setDnDate] = useState(existing?.debit_note_date ?? today);
  const [reason, setReason] = useState(existing?.reason ?? duplicateSeed?.reason ?? "");
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [invoiceId, setInvoiceId] = useState(existing?.sales_invoice_id ?? "");
  const [openInvoices, setOpenInvoices] = useState<OpenInvoiceOption[]>([]);
  const [isInterstate, setIsInterstate] = useState(existing?.is_interstate ?? duplicateSeed?.is_interstate ?? false);
  // Once issued, everything except notes is frozen — a correction goes
  // through a fresh note (CGST Act §34), not an edit (routers/
  // sales_debit_notes.py's update_sales_debit_note enforces this identically).
  const isLocked = isEdit && existing?.status !== "draft";
  const [lines, setLines] = useState<EditorLine[]>(initialLines);
  const keyRef = useRef(initialLines.length);
  const nextKey = () => keyRef.current++;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);

  async function loadOpenInvoices(custId: string) {
    if (!custId) { setOpenInvoices([]); return; }
    const supabase = getSupabaseClient();
    const { data } = await selectAll(() => supabase
      .from("client_sales_invoices")
      .select("id, invoice_no, total_paise, paid_paise, credited_paise, debit_note_paise")
      .eq("client_id", clientId)
      .eq("customer_id", custId)
      .in("status", ["issued", "partially_paid", "paid"])
      .order("invoice_date", { ascending: false })
      .order("id"));
    setOpenInvoices(data ?? []);
  }

  useEffect(() => {
    if (customerId) loadOpenInvoices(customerId);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once for the initial customer (create from duplicate seed, or edit)
  }, []);

  // Rehydrate each existing line's Product/Service picker — same fix as
  // InvoiceEditor.tsx (detailLinesToEditorLines only keeps the id).
  useEffect(() => {
    if (!isEdit || !existing?.id) return;
    const ids = Array.from(new Set(
      initialLines.map((l) => l.serviceCatalogueId).filter((id): id is string => !!id),
    ));
    if (!ids.length) return;
    let cancelled = false;
    (async () => {
      try {
        const supabase = getSupabaseClient();
        const { data } = await supabase
          .from("service_catalogue")
          .select("*")
          .eq("client_id", clientId)
          .in("id", ids);
        if (cancelled || !data?.length) return;
        const byId = new Map((data as ServiceCatalogueItem[]).map((s) => [s.id, s]));
        const withProducts = (prev: EditorLine[]): EditorLine[] =>
          prev.map((l) => (l.serviceCatalogueId && byId.has(l.serviceCatalogueId) && !l.product
            ? { ...l, product: byId.get(l.serviceCatalogueId) }
            : l));
        setLines(withProducts);
        initialSnapshot.current = { ...initialSnapshot.current, lines: withProducts(initialSnapshot.current.lines) };
      } catch {
        // Best-effort: a failed lookup just leaves those lines' pickers blank.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-once per loaded note
  }, [isEdit, existing?.id, clientId]);

  // ── Dirty detection ──────────────────────────────────────────────────────
  const initialSnapshot = useRef({
    customerId: existing?.customer_id ?? duplicateSeed?.customer_id ?? "",
    dnDate: existing?.debit_note_date ?? today,
    reason: existing?.reason ?? duplicateSeed?.reason ?? "",
    notes: existing?.notes ?? "",
    invoiceId: existing?.sales_invoice_id ?? "",
    isInterstate: existing?.is_interstate ?? duplicateSeed?.is_interstate ?? false,
    lines: initialLines,
  });
  const currentSnapshot = { customerId, dnDate, reason, notes, invoiceId, isInterstate, lines };
  const dirty = hasChanges(initialSnapshot.current, currentSnapshot);
  const { confirmLeave } = useUnsavedChanges(dirty && !saving, undefined, confirmDialog);

  // ── Live preview totals + validation — total is NOT rupee-rounded (the
  // backend applies no round-off to a debit note, unlike a Sales Invoice).
  const totals = previewTotals(lines, isInterstate, false);
  const validation = validateSalesDebitNoteEditor({ customerId, debitNoteDate: dnDate, lines });
  const selectedInvoice = openInvoices.find((i) => i.id === invoiceId);

  function onCustomerChange(id: string) {
    if (isEdit) return; // customer is part of the note's identity once created — same lock rationale as Purchase Debit Note
    setCustomerId(id);
    setInvoiceId("");
    loadOpenInvoices(id);
  }

  function setLine(idx: number, patch: Partial<EditorLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }
  function onPickProduct(idx: number, item: ServiceCatalogueItem) {
    setLine(idx, { ...serviceToLine(item), product: item, serviceCatalogueId: item.id });
  }
  function addLine() {
    setLines((prev) => [...prev, { ...EMPTY_LINE, _k: nextKey() }]);
  }

  // ── Save ─────────────────────────────────────────────────────────────────
  async function save() {
    setAttempted(true);
    if (!isLocked && !validation.ok) {
      setError(validation.errors.customer ?? validation.errors.debitNoteDate ?? validation.errors.lines ?? "Fix the highlighted fields.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const token = await getAuthToken();
      const linePayload = lines.filter(isValidLine).map(toInvoiceLinePayload);

      if (isEdit && existing) {
        const patchPayload = isLocked
          ? { notes: notes.trim() || undefined }
          : {
              customer_id: customerId,
              debit_note_date: dnDate,
              sales_invoice_id: invoiceId || undefined,
              reason: reason.trim() || undefined,
              is_interstate: isInterstate,
              notes: notes.trim() || undefined,
              lines: linePayload,
            };
        const upd = await apiCall(`/api/sales-debit-notes/${existing.id}`, "PATCH", patchPayload, token);
        if (!upd.success) throw new Error(upd.error ?? "Failed to update debit note");
      } else {
        const result = await apiCall(
          "/api/sales-debit-notes/",
          "POST",
          {
            client_id: clientId,
            customer_id: customerId,
            debit_note_date: dnDate,
            sales_invoice_id: invoiceId || undefined,
            reason: reason.trim() || undefined,
            is_interstate: isInterstate,
            lines: linePayload,
          },
          token,
        );
        if (!result.success) throw new Error(result.error ?? "Failed to create debit note");
      }
      onDone(isEdit ? "Debit note updated" : "Debit note saved as draft");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save debit note");
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel() {
    if (await confirmLeave()) onCancel();
  }

  const busy = saving;
  const fieldErr = (msg?: string) => (!isLocked && attempted && msg ? <p className="mt-1 text-[10px] text-red-600">{msg}</p> : null);

  const toolbar = (
    <>
      <button onClick={handleCancel} disabled={busy} className="mr-auto text-xs px-3 py-1.5 text-[#64748B] hover:text-[#334155] disabled:opacity-50">
        Cancel
      </button>
      <button onClick={save} disabled={busy} className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
        {saving && <Loader2 size={12} className="animate-spin" />} {isEdit ? "Save Changes" : "Save Draft"}
      </button>
    </>
  );

  const summary = (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-2 text-xs">
      <p className="font-semibold text-[#334155]">Summary</p>
      <Row label="Taxable value" value={fmt(totals.taxable_paise)} />
      {isInterstate ? (
        <Row label="IGST" value={fmt(totals.igst_paise)} />
      ) : (
        <>
          <Row label="CGST" value={fmt(totals.cgst_paise)} />
          <Row label="SGST" value={fmt(totals.sgst_paise)} />
        </>
      )}
      <p className="text-[10px] text-[#94A3B8]">
        {isInterstate ? "Interstate — IGST" : "Intra-state — CGST + SGST"} (CGST Act §8)
      </p>
      <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1.5 mt-1">
        <span>Debit Note Total</span>
        <span className="font-mono">{fmt(totals.grand_total_paise)}</span>
      </div>
      {selectedInvoice && (
        <p className="text-[10px] text-[#94A3B8] pt-1">
          Invoice outstanding today: {fmt(invoiceOutstanding(selectedInvoice))} — a debit note has no ceiling; it adds to what&apos;s owed.
        </p>
      )}
      <p className="text-[10px] text-[#94A3B8] pt-1">
        Preview — GST is confirmed by the server on save.
      </p>
      {!isLocked && attempted && !validation.ok && (
        <div className="flex items-start gap-1.5 text-[10px] text-red-600 bg-red-50 rounded px-2 py-1.5">
          <AlertCircle size={12} className="mt-px flex-shrink-0" />
          <span>{validation.errors.customer ?? validation.errors.debitNoteDate ?? validation.errors.lines}</span>
        </div>
      )}
    </div>
  );

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: clientName || "Client", href: `/clients/${clientId}` },
        { label: "Sales", href: `/clients/${clientId}/sales?tab=debit-notes` },
        { label: isEdit ? `Edit ${existing?.debit_note_no || "Debit Note"}` : "New Debit Note" },
      ]}
      title={isEdit ? `Edit ${existing?.debit_note_no || "Debit Note"}` : "New Debit Note"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">{isEdit ? (existing?.status ?? "draft") : "Draft"}</span>}
      dirtyHint={dirty ? <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> Unsaved changes</span> : undefined}
      toolbar={toolbar}
      summary={summary}
    >
      <div className="space-y-5">
        {/* Party + metadata */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Customer *</label>
              <CustomerLookup customers={customers} value={customerId} onChange={onCustomerChange} ariaLabel="Customer" disabled={isEdit} />
              {isEdit && <p className="mt-1 text-[10px] text-[#94A3B8]">Customer can&apos;t be changed once a debit note exists.</p>}
              {fieldErr(validation.errors.customer)}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">DN Date *</label>
              <input type="date" value={dnDate} onChange={(e) => setDnDate(e.target.value)} disabled={isLocked}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
              {fieldErr(validation.errors.debitNoteDate)}
              {isLocked && <p className="mt-1 text-[10px] text-[#94A3B8]">Frozen once issued — issue a fresh debit note to correct (CGST Act §34).</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Against Invoice (optional)</label>
              <EntityLookup
                items={openInvoices}
                value={invoiceId}
                onChange={setInvoiceId}
                getId={(i) => i.id}
                getLabel={(i) => i.invoice_no}
                getSecondary={(i) => `${fmt(invoiceOutstanding(i))} outstanding`}
                getSearchFields={(i) => [i.invoice_no]}
                clearable
                disabled={!customerId || isLocked}
                placeholder="— Standalone / Select invoice —"
                ariaLabel="Against invoice"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Reason</label>
              <input value={reason} onChange={(e) => setReason(e.target.value)} disabled={isLocked} placeholder="Undercharged / rate correction / additional charges"
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
            </div>
            <div className="flex items-end pb-1.5">
              <label className={`flex items-center gap-2 text-xs text-[#475569] ${isLocked ? "opacity-50" : "cursor-pointer"}`}>
                <input type="checkbox" checked={isInterstate} disabled={isLocked} onChange={(e) => setIsInterstate(e.target.checked)} className="rounded" />
                Interstate (IGST)
              </label>
            </div>
            <div className="col-span-2 lg:col-span-3">
              <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Internal notes — not shown to the customer" rows={2}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
        </section>

        {/* Line items */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <h2 className="text-xs font-semibold text-[#334155] mb-2">Line items</h2>
          {isLocked && (
            <p className="mb-2 text-[10px] text-[#94A3B8]">
              Frozen once issued — issue a fresh debit note to correct a quantity, rate, or item (CGST Act §34).
            </p>
          )}
          <fieldset disabled={isLocked} className="border-0 p-0 m-0 min-w-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[760px]">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="pb-2 text-left font-semibold w-36">Product/Service *</th>
                  <th className="pb-2 text-left font-semibold">Description</th>
                  <th className="pb-2 text-left font-semibold w-24">HSN/SAC</th>
                  <th className="pb-2 text-right font-semibold w-20">Qty</th>
                  <th className="pb-2 text-left font-semibold w-16">Unit</th>
                  <th className="pb-2 text-right font-semibold w-24">Rate (₹)</th>
                  <th className="pb-2 text-right font-semibold w-20">GST %</th>
                  <th className="pb-2 text-right font-semibold w-24">Amount</th>
                  <th className="pb-2 w-6" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {lines.map((line, idx) => {
                  const g = previewTotals([line], isInterstate, false);
                  const invalid = attempted && !isValidLine(line) && (line.description.trim() || line.rate || line.hsn_sac);
                  return (
                    <tr key={line._k} className={invalid ? "bg-red-50/40" : undefined}>
                      <td className="py-1.5 pr-2">
                        <ServiceCataloguePicker clientId={clientId} value={line.product} onPick={(item) => onPickProduct(idx, item)} size="sm" ariaLabel={`Line ${idx + 1} product or service`} />
                      </td>
                      <td className="py-1.5 pr-2">
                        <input value={line.description} onChange={(e) => setLine(idx, { description: e.target.value })} placeholder="Item description" aria-label={`Line ${idx + 1} description`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <HsnLookup clientId={clientId} value={line.hsn_sac} onChange={(v) => setLine(idx, { hsn_sac: v })}
                          onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate: p.gst_rate_bps / 100 }); }}
                          size="sm" chrome="plain" placeholder="Set HSN/SAC" ariaLabel="HSN or SAC code" />
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0" step="0.001" value={line.qty} onChange={(e) => setLine(idx, { qty: e.target.value })} aria-label={`Line ${idx + 1} quantity`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={line.unit || "NOS"} onChange={(e) => setLine(idx, { unit: e.target.value })} aria-label={`Line ${idx + 1} unit`}
                          className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs">
                          {UQC_CODES.map((u) => <option key={u.code} value={u.code}>{u.code}</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0" step="0.01" value={line.rate} onChange={(e) => setLine(idx, { rate: e.target.value })} placeholder="0.00" aria-label={`Line ${idx + 1} rate`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={line.gst_rate} onChange={(e) => setLine(idx, { gst_rate: parseFloat(e.target.value) })} aria-label={`Line ${idx + 1} GST rate`}
                          className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs">
                          {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono text-[#334155]">{g.grand_total_paise > 0 ? fmt(g.grand_total_paise) : "—"}</td>
                      <td className="py-1.5">
                        {lines.length > 1 && (
                          <button onClick={() => removeLine(idx)} className="text-[#CBD5E1] hover:text-red-600" aria-label="Remove line">
                            <Trash2 size={13} />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <button type="button" onClick={addLine} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 disabled:opacity-40 disabled:cursor-not-allowed">
            <Plus size={13} /> Add line
          </button>
          </fieldset>
          {fieldErr(validation.errors.lines)}
        </section>

        {error && <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}
      </div>
    </InvoiceWorkspaceLayout>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-[#475569]">
      <span>{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
