"use client";

/**
 * DebitNoteEditor — dedicated create/edit experience for Purchase Debit
 * Notes, mirroring PurchaseBillEditor's architecture (InvoiceWorkspaceLayout,
 * dirty-changes guard, per-field validation, live GST preview, attachment)
 * instead of the old inline modal on the Purchases page. No business logic
 * is duplicated: totals shown here are a preview (lib/purchases/
 * debitNoteEditor.ts, unit-tested, matches the backend's own
 * _compute_line_gst exactly); the backend remains authoritative and
 * recomputes everything on save.
 *
 * Once issued, a debit note is immutable except notes/document_url (CGST Act
 * §34 — correct it with a fresh note, not an edit); there is deliberately no
 * Cancel/reversal path, unlike Purchase Bills.
 */
import { parseLineAmounts } from "@/lib/money/lineInput";
import { useState, useRef, useEffect } from "react";
import { Trash2, Plus, Loader2, AlertCircle, Upload } from "lucide-react";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { VendorLookup, type VendorLike } from "@/components/lookups/VendorLookup";
import { EntityLookup } from "@/components/lookups/EntityLookup";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";
import { UQC_CODES } from "@/lib/constants/uqc";
import { hasChanges, useUnsavedChanges } from "@/lib/invoices/dirtyState";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { apiCall, getAuthToken, fmt, GST_RATES } from "@/lib/invoices/shared";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import {
  isValidDebitNoteLine, previewDebitNoteTotals, validateDebitNoteEditor,
  type DebitNoteEditorLine,
} from "@/lib/purchases/debitNoteEditor";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const EMPTY_LINE: DebitNoteEditorLine = { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "NOS", service_catalogue_id: "" };

type EditorLine = DebitNoteEditorLine & { _k: number; product?: ServiceCatalogueItem | null };

function todayISO(): string {
  return new Date().toISOString().split("T")[0];
}

/** Purchase-side product/service prefill — uses purchase_price_paise, NOT
 * default_rate_paise (the sell price), same fix as PurchaseBillEditor. */
function purchaseServiceToLine(item: ServiceCatalogueItem): Partial<DebitNoteEditorLine> {
  return {
    description: (item.description ?? "").trim(),
    hsn_sac: item.hsn_sac ?? "",
    rate: item.purchase_price_paise ? String(item.purchase_price_paise / 100) : "",
    gst_rate: item.gst_rate_bps == null ? 0 : item.gst_rate_bps / 100,
    unit: item.unit ?? "NOS",
  };
}

export interface OpenBillOption {
  id: string;
  our_reference: string | null;
  bill_no: string | null;
  net_payable_paise: number;
  paid_paise: number;
  debited_paise: number;
  credit_note_paise: number;
}

function billOutstanding(b: OpenBillOption): number {
  return b.net_payable_paise + (b.credit_note_paise ?? 0) - b.paid_paise - b.debited_paise;
}

/** Server line shape (from GET /api/debit-notes/{id}). */
export interface DebitNoteLineDetail {
  id?: string;
  description: string;
  hsn_sac: string | null;
  quantity: number;
  unit?: string | null;
  rate_paise: number;
  gst_rate_bps: number;
  service_catalogue_id?: string | null;
}

export interface DebitNoteDetail {
  id: string;
  vendor_id: string;
  debit_note_no: string;
  debit_note_date: string;
  purchase_bill_id?: string | null;
  reason?: string | null;
  is_interstate?: boolean;
  is_reverse_charge?: boolean;
  status: string;
  notes?: string | null;
  document_url?: string | null;
  taxable_amount_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  total_gst_paise?: number;
  total_paise?: number;
  applied_paise?: number;
  journal_entry_id?: string | null;
  created_at?: string | null;
  lines: DebitNoteLineDetail[];
}

function detailLinesToEditorLines(lines: DebitNoteDetail["lines"]): EditorLine[] {
  return lines.map((l, i) => ({
    description: l.description ?? "",
    hsn_sac: l.hsn_sac ?? "",
    qty: String(l.quantity ?? 1),
    rate: String((l.rate_paise ?? 0) / 100),
    gst_rate: Math.round((l.gst_rate_bps ?? 0) / 100),
    unit: l.unit ?? "NOS",
    service_catalogue_id: l.service_catalogue_id ?? "",
    _k: i,
  }));
}

export function DebitNoteEditor({
  clientId, clientName, vendors, existing, duplicateSeed, onDone, onCancel,
}: {
  clientId: string;
  clientName?: string;
  vendors: VendorLike[];
  /** Set → edit an existing draft/issued note (PATCH). Absent/null → create (POST). */
  existing?: DebitNoteDetail | null;
  /** "Duplicate debit note" prefill — create mode only. purchase_bill_id is
   * deliberately NOT copied (see lib/purchases/debitNoteDuplicateSeed.ts). */
  duplicateSeed?: DebitNoteDetail | null;
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const today = todayISO();
  const isEdit = !!existing;
  const initialLines: EditorLine[] =
    existing && existing.lines.length > 0 ? detailLinesToEditorLines(existing.lines)
    : duplicateSeed && duplicateSeed.lines.length > 0 ? detailLinesToEditorLines(duplicateSeed.lines)
    : [{ ...EMPTY_LINE, _k: 0 }];

  const [vendorId, setVendorId] = useState(existing?.vendor_id ?? duplicateSeed?.vendor_id ?? "");
  const [dnDate, setDnDate] = useState(existing?.debit_note_date ?? today);
  const [reason, setReason] = useState(existing?.reason ?? duplicateSeed?.reason ?? "");
  const [notes, setNotes] = useState(existing?.notes ?? duplicateSeed?.notes ?? "");
  const [billId, setBillId] = useState(existing?.purchase_bill_id ?? "");
  const [openBills, setOpenBills] = useState<OpenBillOption[]>([]);
  const [isInterstate, setIsInterstate] = useState(existing?.is_interstate ?? duplicateSeed?.is_interstate ?? false);
  const [isReverseCharge, setIsReverseCharge] = useState(existing?.is_reverse_charge ?? duplicateSeed?.is_reverse_charge ?? false);
  // Once issued, everything except notes/document_url is frozen — a
  // correction goes through a fresh note (CGST Act §34), not an edit
  // (routers/debit_notes.py's update_debit_note enforces this identically).
  const isLocked = isEdit && existing?.status !== "draft";
  const [lines, setLines] = useState<EditorLine[]>(initialLines);
  const keyRef = useRef(initialLines.length);
  const nextKey = () => keyRef.current++;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);

  // Attachment — plain upload, no AI extraction (a debit note is CA-authored
  // against an existing bill, not scanned from an incoming document).
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [documentUrl, setDocumentUrl] = useState<string | null>(existing?.document_url ?? null);

  async function loadOpenBills(vId: string) {
    if (!vId) { setOpenBills([]); return; }
    const supabase = getSupabaseClient();
    const { data } = await selectAll(() => supabase
      .from("purchase_bills")
      .select("id, our_reference, bill_no, net_payable_paise, paid_paise, debited_paise, credit_note_paise")
      .eq("client_id", clientId)
      .eq("vendor_id", vId)
      .in("status", ["received", "partially_paid", "paid"])
      .order("bill_date", { ascending: false })
      .order("id"));
    setOpenBills(data ?? []);
  }

  useEffect(() => {
    if (vendorId) loadOpenBills(vendorId);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once for the initial vendor (create from duplicate seed, or edit)
  }, []);

  // Rehydrate each existing line's Product/Service picker — same fix as
  // PurchaseBillEditor.tsx (detailLinesToEditorLines only keeps the id).
  useEffect(() => {
    if (!isEdit || !existing?.id) return;
    const ids = Array.from(new Set(
      initialLines.map((l) => l.service_catalogue_id).filter((id): id is string => !!id),
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
          prev.map((l) => (l.service_catalogue_id && byId.has(l.service_catalogue_id) && !l.product
            ? { ...l, product: byId.get(l.service_catalogue_id) }
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
    vendorId: existing?.vendor_id ?? "",
    dnDate: existing?.debit_note_date ?? today,
    reason: existing?.reason ?? "",
    notes: existing?.notes ?? "",
    billId: existing?.purchase_bill_id ?? "",
    isInterstate: existing?.is_interstate ?? false,
    isReverseCharge: existing?.is_reverse_charge ?? false,
    lines: initialLines,
  });
  const currentSnapshot = { vendorId, dnDate, reason, notes, billId, isInterstate, isReverseCharge, lines };
  const dirty = hasChanges(initialSnapshot.current, currentSnapshot);
  const { confirmLeave } = useUnsavedChanges(dirty && !saving, undefined, confirmDialog);

  // ── Live preview totals + validation ────────────────────────────────────
  const totals = previewDebitNoteTotals(lines, isInterstate);
  const validation = validateDebitNoteEditor({ vendorId, debitNoteDate: dnDate, lines });
  const selectedBill = openBills.find((b) => b.id === billId);

  function onVendorChange(id: string) {
    if (isEdit) return; // vendor is part of the note's identity once created — same lock rationale as Purchase Bill
    setVendorId(id);
    setBillId("");
    loadOpenBills(id);
  }

  function setLine(idx: number, patch: Partial<EditorLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }
  function onPickProduct(idx: number, item: ServiceCatalogueItem) {
    setLine(idx, { ...purchaseServiceToLine(item), product: item, service_catalogue_id: item.id });
  }
  function addLine() {
    setLines((prev) => [...prev, { ...EMPTY_LINE, _k: nextKey() }]);
  }

  async function handleUpload() {
    if (!uploadFile) return;
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("client_id", clientId);
      const token = await getAuthToken();
      const res = await fetch(`${API}/api/debit-notes/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      const json = await res.json();
      if (json.success && json.data?.document_url) {
        setDocumentUrl(json.data.document_url as string);
      } else {
        setError(json.error || "Attachment upload failed.");
      }
    } catch {
      setError("Attachment upload failed.");
    } finally {
      setUploading(false);
    }
  }

  // ── Save ─────────────────────────────────────────────────────────────────
  async function save() {
    setAttempted(true);
    if (!validation.ok) {
      setError(validation.errors.vendor ?? validation.errors.debitNoteDate ?? validation.errors.lines ?? "Fix the highlighted fields.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const token = await getAuthToken();
      const linePayload = lines.filter(isValidDebitNoteLine).map((l) => ({
        description: l.description,
        hsn_sac: l.hsn_sac || undefined,
        quantity: parseLineAmounts(l.qty, l.rate)!.quantity,
        unit: l.unit || undefined,
        // Non-null by construction: the filter above is isValidDebitNoteLine,
        // which is now parseLineAmounts itself. The old form here was
        // Math.round((parseFloat(l.rate) || 0) * 100) — exact for a plain
        // decimal and silently 100 paise for "1,25,000".
        rate_paise: parseLineAmounts(l.qty, l.rate)!.ratePaise,
        gst_rate_percent: l.gst_rate,
        service_catalogue_id: l.service_catalogue_id || undefined,
      }));

      if (isEdit && existing) {
        const patchPayload = isLocked
          ? { notes: notes.trim() || undefined, document_url: documentUrl || undefined }
          : {
              vendor_id: vendorId,
              debit_note_date: dnDate,
              purchase_bill_id: billId || undefined,
              reason: reason.trim() || undefined,
              is_interstate: isInterstate,
              is_reverse_charge: isReverseCharge,
              notes: notes.trim() || undefined,
              document_url: documentUrl || undefined,
              lines: linePayload,
            };
        const upd = await apiCall(`/api/debit-notes/${existing.id}`, "PATCH", patchPayload, token);
        if (!upd.success) throw new Error(upd.error ?? "Failed to update debit note");
      } else {
        const result = await apiCall(
          "/api/debit-notes/",
          "POST",
          {
            client_id: clientId,
            vendor_id: vendorId,
            debit_note_date: dnDate,
            purchase_bill_id: billId || undefined,
            reason: reason.trim() || undefined,
            is_interstate: isInterstate,
            is_reverse_charge: isReverseCharge,
            notes: notes.trim() || undefined,
            document_url: documentUrl || undefined,
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
  const fieldErr = (msg?: string) => (attempted && msg ? <p className="mt-1 text-[10px] text-red-600">{msg}</p> : null);

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
      {isReverseCharge && (
        <p className="text-[10px] text-amber-700">
          Reverse charge — the GST above was self-assessed by you, not paid to the vendor (CGST Act §9(3)/(4)).
        </p>
      )}
      <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1.5 mt-1">
        <span>Debit Note Total</span>
        <span className="font-mono">{fmt(totals.grand_total_paise)}</span>
      </div>
      {selectedBill && (
        <p className="text-[10px] text-[#94A3B8] pt-1">
          Bill outstanding: {fmt(billOutstanding(selectedBill))}
          {totals.grand_total_paise > billOutstanding(selectedBill) && (
            <span className="block text-amber-700 mt-0.5">
              Exceeds the bill&apos;s outstanding — issuing will be rejected unless this is reduced.
            </span>
          )}
        </p>
      )}
      <p className="text-[10px] text-[#94A3B8] pt-1">
        Preview — GST is confirmed by the server on save.
      </p>
      {attempted && !validation.ok && (
        <div className="flex items-start gap-1.5 text-[10px] text-red-600 bg-red-50 rounded px-2 py-1.5">
          <AlertCircle size={12} className="mt-px flex-shrink-0" />
          <span>{validation.errors.vendor ?? validation.errors.debitNoteDate ?? validation.errors.lines}</span>
        </div>
      )}
    </div>
  );

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: clientName || "Client", href: `/clients/${clientId}` },
        { label: "Purchases", href: `/clients/${clientId}/purchases?tab=debit-notes` },
        { label: isEdit ? `Edit ${existing?.debit_note_no || "Debit Note"}` : "New Debit Note" },
      ]}
      title={isEdit ? `Edit ${existing?.debit_note_no || "Debit Note"}` : "New Debit Note"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">{isEdit ? (existing?.status ?? "draft") : "Draft"}</span>}
      dirtyHint={dirty ? <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> Unsaved changes</span> : undefined}
      toolbar={toolbar}
      summary={summary}
    >
      <div className="space-y-5">
        <section className="bg-amber-50 border border-amber-100 rounded-lg p-3 space-y-2">
          <p className="text-xs font-medium text-amber-800 flex items-center gap-1.5"><Upload size={12} /> Attachment</p>
          {!isLocked && (
            <div className="flex items-center gap-2">
              <input type="file" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} className="text-xs text-[#475569]" />
              <button onClick={handleUpload} disabled={!uploadFile || uploading} className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40">
                {uploading ? "Uploading…" : "Upload"}
              </button>
            </div>
          )}
          {documentUrl && (
            <p className="text-[10px] text-amber-700">📎 Attachment on file — supporting evidence for this return.</p>
          )}
        </section>

        {/* Party + metadata */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor *</label>
              <VendorLookup vendors={vendors} value={vendorId} onChange={onVendorChange} ariaLabel="Vendor" disabled={isEdit} />
              {isEdit && <p className="mt-1 text-[10px] text-[#94A3B8]">Vendor can&apos;t be changed once a debit note exists.</p>}
              {fieldErr(validation.errors.vendor)}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">DN Date *</label>
              <input type="date" value={dnDate} onChange={(e) => setDnDate(e.target.value)} disabled={isLocked}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
              {fieldErr(validation.errors.debitNoteDate)}
              {isLocked && <p className="mt-1 text-[10px] text-[#94A3B8]">Frozen once issued — issue a fresh debit note to correct (CGST Act §34).</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Against Bill (optional)</label>
              <EntityLookup
                items={openBills}
                value={billId}
                onChange={setBillId}
                getId={(b) => b.id}
                getLabel={(b) => b.our_reference ?? b.bill_no ?? "—"}
                getSecondary={(b) => `${fmt(billOutstanding(b))} outstanding`}
                getSearchFields={(b) => [b.our_reference ?? "", b.bill_no ?? ""]}
                clearable
                disabled={!vendorId || isLocked}
                placeholder="— Standalone / Select bill —"
                ariaLabel="Against bill"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Reason</label>
              <input value={reason} onChange={(e) => setReason(e.target.value)} disabled={isLocked} placeholder="Goods returned / rate correction / excess billed"
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
            </div>
            <div className="flex flex-col justify-end gap-2 pb-1.5">
              <label className={`flex items-center gap-2 text-xs text-[#475569] ${isLocked ? "opacity-50" : "cursor-pointer"}`}>
                <input type="checkbox" checked={isInterstate} disabled={isLocked} onChange={(e) => setIsInterstate(e.target.checked)} className="rounded" />
                Interstate (IGST)
              </label>
              <label className={`flex items-center gap-2 text-xs text-[#475569] ${isLocked ? "opacity-50" : "cursor-pointer"}`}>
                <input type="checkbox" checked={isReverseCharge} disabled={isLocked} onChange={(e) => setIsReverseCharge(e.target.checked)} className="rounded" />
                Reverse Charge (RCM)
              </label>
            </div>
            <div className="col-span-2 lg:col-span-3">
              <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Internal notes — not shown to the vendor" rows={2}
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
                  const g = previewDebitNoteTotals([line], isInterstate);
                  const invalid = attempted && !isValidDebitNoteLine(line) && (line.description.trim() || line.rate || line.hsn_sac);
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
