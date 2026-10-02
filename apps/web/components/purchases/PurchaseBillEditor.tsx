"use client";

/**
 * PurchaseBillEditor — dedicated create experience for Purchase Bills,
 * mirroring the Sales Invoice editor's architecture (InvoiceWorkspaceLayout,
 * dirty-changes guard, per-field validation, live GST preview) instead of
 * the old inline modal. No business logic is duplicated: totals shown here
 * are a preview (lib/purchases/billEditor.ts, unit-tested, floor-based —
 * matches the backend's own _compute_line_gst exactly); the backend remains
 * authoritative and recomputes everything on save.
 */
import { useState, useRef, useEffect } from "react";
import { Trash2, Plus, Loader2, AlertCircle, AlertTriangle, Upload } from "lucide-react";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { VendorLookup, type VendorLike } from "@/components/lookups/VendorLookup";
import { AccountLookup, type AccountLike } from "@/components/lookups/AccountLookup";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import { purchaseServiceToLine, type ServiceCatalogueItem } from "@/lib/catalogue/service";
import { UQC_CODES } from "@/lib/constants/uqc";
import { estimateBaseMinor } from "@/lib/services/currencyPreview";
import { useServerTdsPreview } from "@/lib/purchases/serverTdsPreview";
import { formatMoney } from "@/lib/services/formatting";
import { hasChanges, useUnsavedChanges } from "@/lib/invoices/dirtyState";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { DraftOffer } from "@/components/ui/draft-offer";
import { useUnsentDraft } from "@/lib/drafts/useUnsentDraft";
import {
  applyBillDraft, billRestoreNote, draftLineOf, editorLineOf, linkCatalogue,
  validateBillDraft, withoutDocument, type BillDraftFields,
} from "@/lib/purchases/billDraft";
import { apiCall, apiGet, getAuthToken, fmt, gstRateOptions, gstRateToPercent, type CurrencyOption } from "@/lib/invoices/shared";
import { getSupabaseClient } from "@/lib/supabase/client";
import { todayLocalISO } from "@/lib/dateMath";
import {
  isValidBillLine, previewBillTotals, validateBillEditor, findBlockedCreditHits,
  BLOCKED_CREDIT_REASONS, ineligibleGstPaise, buildLinePayload,
  lineIsItcEligible, reasonForHintLabel, supplySplitPreview,
  type PurchaseBillLine,
} from "@/lib/purchases/billEditor";
import {
  lineFromExtraction, unreadAfterEdit, type ExtractedLine,
} from "@/lib/purchases/extractedLine";
import {
  parseVendorHistory, distinctHsns, chipsForLine, accountPatch, itcPatch,
  type VendorHistory,
} from "@/lib/purchases/vendorHistory";
import { Callout } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { objectWithLists } from "@/lib/api/shape";
import { Button } from "@/components/ui/button";
import { DateInput } from "@/components/ui/date-input";
import { useDateProblems } from "@/lib/dates/useDateProblems";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface PurchaseVendor extends VendorLike {
  tds_applicable?: boolean;
  tds_section?: string | null;
  tds_rate_bps?: number;
  is_active?: boolean;
}

type EditorLine = PurchaseBillLine & {
  _k: number;
  product?: ServiceCatalogueItem | null;
  /** Catalogue items sharing this line's HSN/SAC, looked up right after AI
   * extraction (see handleExtract) — undefined means "not looked up" (e.g.
   * a manually-added blank line), [] means "looked up, no match". A single
   * match auto-links; multiple render as one-click chips instead of forcing
   * a manual catalogue search the CA has no way to aim (they only know the
   * HSN code shown on the line, not which preset name it maps to). */
  hsnMatches?: ServiceCatalogueItem[];
};
const EMPTY_LINE: PurchaseBillLine = { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "NOS", expense_account_id: "", service_catalogue_id: "" };

/** AI-01 — a field the document did not state, drawn so the CA cannot mistake it
 *  for one that was read. Tokens only: `state-attention` is the palette's amber. */
const UNREAD_CLASS = "border-state-attention-border bg-state-attention-surface";
const NOT_STATED_TITLE = "The document did not state this, so it has been left for you.";
function unreadOn(l: EditorLine, f: NonNullable<EditorLine["unread"]>[number]): boolean {
  return !!l.unread?.includes(f);
}

function todayISO(): string {
  return todayLocalISO();
}

interface ExtractedInvoice {
  vendor_name?: string;
  vendor_gstin?: string;
  invoice_no?: string;
  invoice_date?: string;
  /** Every figure here may be null — null is "the document did not say" and 0
   *  is an answer (AI-01). See lib/purchases/billEditor.ts's ExtractedLine. */
  line_items?: ExtractedLine[];
  taxable_amount_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  total_paise?: number;
}

/** `totals_check` from POST /api/document-intelligence-v1/extract-invoice.
 *  The arithmetic is the server's (domain/extraction_totals.py) — the
 *  tolerance is a rule about CGST s.170's round-off, not a display choice, and
 *  this screen renders the verdict rather than reaching one. */
interface ExtractionTotalsCheck {
  /** False when the document's own total could not be read — an unread figure
   *  is not a disagreement. */
  checked: boolean;
  sum_of_parts_paise: number;
  total_paise: number;
  difference_paise: number;
  agrees: boolean;
  tolerance_paise: number;
  note: string | null;
  /** Each failing check's own sentence, with its own amounts (header sum, lines
   *  against the taxable value, tax at the lines' rates). Absent from a backend one
   *  deploy behind, which is why the screen falls back to `note`. */
  failures?: string[];
}

/** `supplier_check` from the same response (domain/extraction_checks.py): the
 *  supplier GSTIN against its own check digit, and IGST against CGST+SGST for the
 *  States involved. Reports; the screen never decides either. */
interface ExtractionSupplierCheck {
  /** `valid` is null where there was no GSTIN to test, and false only where the
   *  check digit (or the shape) failed. */
  gstin?: { checked: boolean; present: boolean; valid: boolean | null; problem: string | null };
  failures?: { check: string; reason: string }[];
}

/** One bill the server believes this one may be a second copy of.
 *  Shape of domain/purchases/near_duplicate.NearDuplicate. */
type NearDuplicate = {
  bill_id: string;
  bill_no: string;
  bill_date: string | null;
  total_paise: number;
  reason: "same_number_different_spelling" | "same_amount_near_date";
  detail: string;
};

/** Server line shape (from GET /api/purchase-bills/{id}). */
export interface PurchaseBillLineDetail {
  id?: string;
  description: string;
  hsn_sac: string | null;
  quantity: number;
  unit?: string | null;
  rate_paise: number;
  gst_rate_bps: number;
  taxable_amount_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  line_total_paise?: number;
  expense_account_id?: string | null;
  service_catalogue_id?: string | null;
  /** CGST Act §17(5), migration 240. Absent on a row written before the column
   *  existed — read as eligible, which is the column's own default. */
  itc_eligible?: boolean | null;
  /** GST compensation cess, migration 374 — both limbs and the amount they
   *  produce. See lib/purchases/billEditor.ts's PurchaseBillLine. */
  cess_rate_bps?: number | null;
  cess_specific_paise_per_unit?: number | null;
  cess_paise?: number | null;
  blocked_credit_reason?: string | null;
}

/** Full purchase-bill detail (Edit route). vendor_id is NOT editable via
 * PATCH (backend has no vendor_id field on PurchaseBillUpdateIn — changing
 * the vendor would invalidate the frozen TDS section/rate) so the Edit
 * route only ever shows this for context, never mutates it. */
export interface PurchaseBillDetail {
  id: string;
  vendor_id: string;
  bill_no: string;
  our_reference?: string | null;
  bill_date: string;
  due_date: string | null;
  credit_days?: number | null;
  is_reverse_charge?: boolean;
  is_interstate?: boolean;
  status: string;
  notes?: string | null;
  document_url?: string | null;
  // Rule 37BB, per REMITTANCE — a vendor paid four times in a year needs four
  // Form 15CAs, which is why these are on the bill and not on the vendor.
  form_15ca_ack_no?: string | null;
  form_15ca_filed_on?: string | null;
  form_15cb_udin?: string | null;
  txn_currency?: string | null;
  exchange_rate?: string | null;
  taxable_amount_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  total_gst_paise?: number;
  total_paise?: number;
  tds_paise?: number;
  tds_rate_bps?: number;
  tds_section?: string | null;
  net_payable_paise?: number;
  paid_paise?: number;
  // Sum of issued debit notes against this bill (routers/debit_notes.py) —
  // reduces the payable alongside paid_paise, so outstanding is
  // net_payable − paid − debited (mirrors purchase_payments._claim_bill_outstanding).
  debited_paise?: number;
  // Sum of issued purchase credit notes against this bill (routers/
  // purchase_credit_notes.py, CGST Act §34(3) — a vendor undercharge) —
  // INCREASES the payable: outstanding = (net_payable + credit_note_paise) − paid − debited.
  credit_note_paise?: number;
  journal_entry_id?: string | null;
  received_at?: string | null;
  created_at?: string | null;
  lines: PurchaseBillLineDetail[];
}

/** existing.lines is the server line shape — shared here so re-editing a
 * draft can't drift from how it was originally saved. */
function detailLinesToEditorLines(lines: PurchaseBillDetail["lines"]): EditorLine[] {
  return lines.map((l, i) => ({
    description: l.description ?? "",
    hsn_sac: l.hsn_sac ?? "",
    qty: String(l.quantity ?? 1),
    rate: String((l.rate_paise ?? 0) / 100),
    gst_rate: gstRateToPercent(l.gst_rate_bps),
    unit: l.unit ?? "NOS",
    expense_account_id: l.expense_account_id ?? "",
    service_catalogue_id: l.service_catalogue_id ?? "",
    itc_eligible: l.itc_eligible ?? true,
    blocked_credit_reason: l.blocked_credit_reason ?? "",
    // Compensation cess (migration 374). Rehydrated because update_purchase_bill
    // deletes and reinserts every line from whatever is sent back, so a cess
    // the editor did not carry would be silently dropped on the next save —
    // understating both the vendor payable and the ITC claim.
    cessPercent: !l.cess_rate_bps ? undefined : String(l.cess_rate_bps / 100),
    cessPerUnit: !l.cess_specific_paise_per_unit
      ? undefined : String(l.cess_specific_paise_per_unit / 100),
    _k: i,
  }));
}

export function PurchaseBillEditor({
  clientId, clientName, clientStateCode, vendors, accounts, existing, duplicateSeed, onDone, onCancel,
}: {
  clientId: string;
  clientName?: string;
  /** This client's own GST state code — vendor.state_code differing from
   * this drives the CGST+SGST vs IGST preview split (CGST Act §8). The
   * backend independently recomputes is_interstate from the live vendor/
   * client rows on save; this is preview-only. */
  clientStateCode: string;
  vendors: PurchaseVendor[];
  accounts: AccountLike[];
  /** Set → edit an existing draft bill (PATCH). Absent/null → create (POST). */
  existing?: PurchaseBillDetail | null;
  /** "Duplicate bill" prefill (lib/purchases/duplicateSeed) — create mode
   * only. Copies vendor, lines, RCM flag and notes; deliberately NOT the
   * vendor invoice number (each vendor bill has its own), dates, reference,
   * or the attachment (which belongs to the original bill). */
  duplicateSeed?: PurchaseBillDetail | null;
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
  const [selectedVendor, setSelectedVendor] = useState<PurchaseVendor | null>(() => {
    const seedVendorId = existing?.vendor_id ?? duplicateSeed?.vendor_id;
    return seedVendorId ? vendors.find((v) => v.id === seedVendorId) ?? null : null;
  });
  const [billNo, setBillNo] = useState(existing?.bill_no ?? "");
  const [ourReference, setOurReference] = useState(existing?.our_reference ?? "");
  // THE RULE 37BB PAPERWORK, WHICH THE PLATFORM ASKED FOR AND COULD NOT TAKE
  // (TDS-25). Migration 311 added all three columns, `routers/purchase_bills.py`
  // accepts them on create AND on the soft-update allowlist (they are filed
  // after the bill, so they must stay editable on a received one), and
  // `tds_register_service` raises a gap on every §195 bill whose
  // `form_15ca_ack_no` is blank. Since PUR-14 that gap REACHES the CA — so the
  // product told them, on every foreign remittance, to record something no
  // screen let them record.
  const [form15caAckNo, setForm15caAckNo] = useState(existing?.form_15ca_ack_no ?? "");
  const [form15caFiledOn, setForm15caFiledOn] = useState(existing?.form_15ca_filed_on ?? "");
  const [form15cbUdin, setForm15cbUdin] = useState(existing?.form_15cb_udin ?? "");
  const [notes, setNotes] = useState(existing?.notes ?? duplicateSeed?.notes ?? "");
  const [billDate, setBillDate] = useState(existing?.bill_date ?? today);
  const [dueDate, setDueDate] = useState(existing?.due_date ?? "");
  const [isReverseCharge, setIsReverseCharge] = useState(existing?.is_reverse_charge ?? duplicateSeed?.is_reverse_charge ?? false);
  // Once a bill is received/partially-paid/paid, the backend only accepts
  // our_reference/notes/due_date/document_url on PATCH (routers/purchase_bills.py
  // _SOFT_BILL_UPDATE_FIELDS) — bill_no/bill_date/lines are frozen; a correction
  // to those needs a Debit Note instead (CGST Act §34). Locking them here too
  // (not just server-side) means the CA never fills in a full edit only to have
  // it rejected on save.
  const isLocked = isEdit && existing?.status !== "draft";
  const [lines, setLines] = useState<EditorLine[]>(initialLines);
  // Compensation cess reaches a handful of trades — aerated waters, pan
  // masala, tobacco, coal, motor vehicles — so its two columns are revealed
  // rather than always shown. ON from the start whenever the bill already
  // carries cess, so the fields can never be hidden from the document that
  // has them. Same shape as the sales InvoiceEditor.
  const [showCess, setShowCess] = useState<boolean>(
    () => initialLines.some((l) => l.cessPercent || l.cessPerUnit));
  const keyRef = useRef(initialLines.length);
  const nextKey = () => keyRef.current++;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // PUR-32. A bill the server thinks may already be recorded under a different
  // number. Held HERE rather than passed to onDone, because onDone closes the
  // editor and a warning the CA cannot read is not a warning. The bill IS
  // saved by the time this is set — it is a check, not a refusal, and
  // domain/purchases/near_duplicate carries the argument for that.
  const [nearDupes, setNearDupes] = useState<NearDuplicate[] | null>(null);
  // The same answer, asked BEFORE the save. Separate state because the two say
  // different things: one is "you are about to book this twice", the other is
  // "you just did". Both come from the one rule in apps/api.
  const [dupeAhead, setDupeAhead] = useState<NearDuplicate[]>([]);
  // ai-23. What this supplier's earlier bills propose for the lines being typed,
  // with the evidence. A PROPOSAL: nothing in it is written to a line except by
  // a click on one of the chips below (see lib/purchases/vendorHistory.ts).
  const [history, setHistory] = useState<VendorHistory | null>(null);
  const [attempted, setAttempted] = useState(false);
  // A date typed as text that is not a date reads as blank to the form; the
  // save has to know which it was (frontend_ux-19).
  const dates = useDateProblems();

  // AI Upload (Extract) — create-only; re-extracting into an already-saved
  // draft would silently overwrite manually-corrected fields.
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [aiExtracted, setAiExtracted] = useState<Record<string, unknown> | null>(null);
  // The server's arithmetic check on the extraction's own five header figures
  // (PUR-21). Computed in apps/api — domain/extraction_totals.py — because the
  // tolerance is a rule about CGST s.170's round-off, not a display choice.
  const [aiTotals, setAiTotals] = useState<ExtractionTotalsCheck | null>(null);
  const [aiSupplier, setAiSupplier] = useState<ExtractionSupplierCheck | null>(null);
  // Storage PATH of the uploaded invoice (not a browser-openable URL — the
  // "Documents" bucket is private) — set on any upload attempt, whether or
  // not AI extraction itself succeeds, so the original file is retained as
  // ITC/audit evidence (CGST Rule 36(1)) even on a failed extraction.
  const [documentUrl, setDocumentUrl] = useState<string | null>(existing?.document_url ?? null);

  // Multi-currency — frozen at creation; not user-editable in edit mode
  // (PurchaseBillUpdateIn has no currency/exchange_rate field), but still
  // seeded from `existing` so preview totals render in the bill's own
  // currency rather than silently reverting to INR.
  const [currency, setCurrency] = useState(
    isEdit && existing?.txn_currency && existing.txn_currency !== "INR" ? existing.txn_currency : "",
  );
  const [exchangeRate, setExchangeRate] = useState(
    isEdit && existing?.exchange_rate ? String(existing.exchange_rate) : "",
  );
  const [mcActive, setMcActive] = useState(false);
  const [currencies, setCurrencies] = useState<CurrencyOption[]>([]);

  useEffect(() => {
    if (isEdit || !clientId) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getAuthToken();
        const pol = await apiGet(`/api/currencies/policy?client_id=${clientId}`, token);
        if (cancelled) return;
        const active = Boolean(pol.success && (pol.data as { active?: boolean } | null)?.active);
        setMcActive(active);
        if (!active) return;
        const list = await apiGet(`/api/currencies?active_only=true`, token);
        if (!cancelled && list.success) setCurrencies((list.data as CurrencyOption[]) ?? []);
      } catch { /* best-effort: multi-currency is optional */ }
    })();
    return () => { cancelled = true; };
  }, [clientId, isEdit]);

  // Rehydrate each existing line's Product/Service picker. detailLinesToEditorLines
  // deliberately keeps only service_catalogue_id from the server (not the full
  // catalogue object), so on load every line's picker shows blank
  // ("+ Add Product/Service") even though a product IS linked, right up until
  // the CA re-picks something. One batched by-id lookup fixes that. Not
  // filtered to is_active — a bill can reference a since-archived preset, and
  // its name should still show, especially since the picker is disabled in
  // locked mode. Same fix as InvoiceEditor.tsx (same underlying pattern).
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
        // Keep the dirty-check snapshot in lockstep — otherwise this
        // rehydration itself would flip the editor to "Unsaved changes".
        initialSnapshot.current = { ...initialSnapshot.current, lines: withProducts(initialSnapshot.current.lines) };
      } catch {
        // Best-effort: a failed lookup just leaves those lines' pickers blank,
        // same as before this fix — never blocks editing.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-once per loaded bill; initialLines is derived from `existing` and stable for its lifetime
  }, [isEdit, existing?.id, clientId]);

  const isForeign = currency !== "" && currency !== "INR";
  const rateNum = parseFloat(exchangeRate);
  function fmtAmt(paise: number): string {
    return isForeign ? formatMoney(paise, currency) : fmt(paise);
  }

  // ── Dirty detection ──────────────────────────────────────────────────────
  const initialSnapshot = useRef({
    vendorId: existing?.vendor_id ?? "",
    billNo: existing?.bill_no ?? "",
    ourReference: existing?.our_reference ?? "",
    form15caAckNo: existing?.form_15ca_ack_no ?? "",
    form15caFiledOn: existing?.form_15ca_filed_on ?? "",
    form15cbUdin: existing?.form_15cb_udin ?? "",
    notes: existing?.notes ?? "",
    billDate: existing?.bill_date ?? today,
    dueDate: existing?.due_date ?? "",
    isReverseCharge: existing?.is_reverse_charge ?? false,
    lines: initialLines, currency, exchangeRate,
  });
  const currentSnapshot = { vendorId, billNo, ourReference, notes, billDate, dueDate, isReverseCharge, lines, currency, exchangeRate,
    form15caAckNo, form15caFiledOn, form15cbUdin };
  const dirty = hasChanges(initialSnapshot.current, currentSnapshot);
  const { confirmLeave } = useUnsavedChanges(dirty && !saving, undefined, confirmDialog);

  // ── An unsent draft, offered back after a reload (frontend_ux-23) ─────────
  // The RAW fields, in this tab's sessionStorage (lib/purchases/billDraft is the
  // list of what is kept and what is not). "Dirty" here is against what THIS
  // form opened with, and is its own comparison rather than `dirty` above: a
  // duplicated bill opens with a vendor and lines already on it, so it is
  // "unsaved" from the first render, and keeping that seed as a draft would
  // offer a bill back to itself after every reload.
  const draftFields: BillDraftFields = {
    vendorId, billNo, ourReference, form15caAckNo, form15caFiledOn, form15cbUdin,
    notes, billDate, dueDate, isReverseCharge, currency, exchangeRate,
    documentAttached: !!documentUrl,
    lines: lines.map(draftLineOf),
  };
  const [pristineDraft] = useState<BillDraftFields>(draftFields);
  const draftDirty = !isLocked
    && hasChanges(withoutDocument(pristineDraft), withoutDocument(draftFields));
  const draft = useUnsentDraft<BillDraftFields>({
    kind: "purchase-bill", clientId,
    // A bill copied from another is a different starting point from a blank one.
    entityId: existing?.id ?? (duplicateSeed ? `copy-${duplicateSeed.id}` : "new"),
    fields: draftFields, dirty: draftDirty, validate: validateBillDraft,
    // A received bill takes only a handful of soft fields; there is no form to keep.
    enabled: !isLocked,
  });
  const [restoreNote, setRestoreNote] = useState<string | null>(null);

  /** Called from the banner's button and from nowhere else. */
  function restoreDraft() {
    const offered = draft.restore();
    if (!offered) return;
    const applied = applyBillDraft(offered, {
      isEdit,
      current: { vendorId, currency, exchangeRate, isReverseCharge },
      vendorIds: new Set(vendors.filter((v) => v.is_active !== false).map((v) => v.id)),
      accountIds: new Set(accounts.map((a) => a.id).filter((id): id is string => !!id)),
      // What the Currency picker offers right now: nothing while multi-currency
      // is off for this client or its list has not arrived.
      currencyCodes: new Set(mcActive
        ? currencies.filter((c) => c.code !== "INR").map((c) => c.code) : []),
    });
    const f = applied.fields;
    if (!isEdit) {
      setVendorId(f.vendorId);
      setSelectedVendor(vendors.find((v) => v.id === f.vendorId) ?? null);
      setIsReverseCharge(f.isReverseCharge);
      setCurrency(f.currency);
      setExchangeRate(f.exchangeRate);
    }
    setBillNo(f.billNo);
    setOurReference(f.ourReference);
    setForm15caAckNo(f.form15caAckNo);
    setForm15caFiledOn(f.form15caFiledOn);
    setForm15cbUdin(f.form15cbUdin);
    setNotes(f.notes);
    setBillDate(f.billDate);
    setDueDate(f.dueDate);
    const restored: EditorLine[] = f.lines.length > 0
      ? f.lines.map((l) => ({ ...editorLineOf(l), _k: nextKey() }))
      : [{ ...EMPTY_LINE, _k: nextKey() }];
    setLines(restored);
    setShowCess(restored.some((l) => l.cessPercent || l.cessPerUnit));
    setError(null);
    setAttempted(false);
    // The invoice file is NOT in a draft (billDraft says why). If the form in
    // front of the CA has none attached, say so; if one is attached already —
    // an edit of a saved draft, or a fresh upload — nothing was lost.
    const noteWith = (catalogueMissing: number) => billRestoreNote(applied, {
      catalogueMissing, documentAttached: offered.documentAttached && !documentUrl,
    });
    setRestoreNote(noteWith(0));
    if (!applied.catalogueIds.length) return;
    // The draft's catalogue ids are looked up ONCE, here: each line gets its
    // product row back and one whose row is gone loses the link
    // (billDraft.linkCatalogue). That is computed OUTSIDE the state updater,
    // because an updater runs when React next renders and the count it finds is
    // needed for the note now.
    (async () => {
      try {
        const { data, error: lookupError } = await getSupabaseClient()
          .from("service_catalogue")
          .select("*")
          .eq("client_id", clientId)
          .in("id", applied.catalogueIds);
        // A failed lookup says nothing about any id: leave the lines as restored.
        if (lookupError || !data) return;
        const byId = new Map((data as ServiceCatalogueItem[]).map((s) => [s.id, s]));
        const linked = linkCatalogue(restored, byId);
        const patch = new Map(linked.lines.map((l) => [
          l._k, { product: l.product, service_catalogue_id: l.service_catalogue_id }]));
        const restoredId = new Map(restored.map((l) => [l._k, l.service_catalogue_id]));
        // Only a line still holding the id the restore gave it: a CA who has
        // already picked something else on it has decided, and that stands.
        setLines((prev) => prev.map((l) => {
          const p = patch.get(l._k);
          return p && l.service_catalogue_id === restoredId.get(l._k) ? { ...l, ...p } : l;
        }));
        if (linked.missing > 0) setRestoreNote(noteWith(linked.missing));
      } catch {
        // Best-effort, like the edit route's own rehydration: the lines stay as restored.
      }
    })();
  }

  // ── Interstate preview (CGST Act §8) — server recomputes independently ──
  // `supplySplit.caption` says which side's state is unknown when the split is
  // a default rather than a decision (sweep-client-purchases-03).
  const supplySplit = supplySplitPreview(clientStateCode, selectedVendor);
  const isInterstate = supplySplit.isInterstate;

  // ── Live preview totals + validation ────────────────────────────────────
  const totals = previewBillTotals(lines, isInterstate);
  // RCM (CGST Act §9(3)/(4)): the vendor invoices WITHOUT tax — the GST shown
  // is self-assessed (paid via GSTR-3B, ITC claimable), so the amount owed to
  // the vendor is the taxable value alone. Mirrors the backend's
  // _compute_bill_lines_and_totals; the server remains authoritative.
  const vendorTotalPaise = isReverseCharge ? totals.taxable_paise : totals.grand_total_paise;
  // ── Is this bill already recorded under another number? (PUR-32) ─────────
  // Asked of the server, debounced, whenever the four fields it needs settle.
  // The rule is entirely in apps/api — domain/purchases/near_duplicate — and
  // this only carries the question and renders the answer. Never blocks: two
  // identical bills from one supplier on one day are ordinary, so a refusal
  // here would refuse real work.
  const dupeProbeKey = isEdit ? "" : [clientId, vendorId, billDate,
                                      billNo.trim(), vendorTotalPaise].join("|");
  useEffect(() => {
    if (!vendorId || !billDate) { setDupeAhead([]); return; }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const token = await getAuthToken();
        const res = await apiCall("/api/purchase-bills/near-duplicates", "POST", {
          client_id: clientId, vendor_id: vendorId,
          bill_no: billNo.trim() || undefined, bill_date: billDate,
          total_paise: vendorTotalPaise,
        }, token);
        if (cancelled) return;
        const data = res.data as { near_duplicates?: NearDuplicate[] } | undefined;
        setDupeAhead(res.success ? (data?.near_duplicates ?? []) : []);
      } catch {
        // A warning that could not be fetched is silence, never a blocked save.
        if (!cancelled) setDupeAhead([]);
      }
    }, 600);
    return () => { cancelled = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dupeProbeKey]);

  // ── What did this supplier's earlier bills say? (ai-23) ──────────────────
  // Asked of the server whenever the supplier or the set of HSN/SAC codes on the
  // bill changes, debounced. The learning is entirely in apps/api —
  // domain/purchases/bill_history — and is scoped to this firm, this client and
  // this supplier there. Only on a NEW bill: an existing one is already coded.
  // A lookup that fails is silence, never a blocked bill.
  const historyHsns = distinctHsns(lines);
  const historyKey = isEdit || !vendorId ? "" : [clientId, vendorId, ...historyHsns].join("|");
  useEffect(() => {
    if (!historyKey) { setHistory(null); return; }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const token = await getAuthToken();
        const qs = new URLSearchParams({ client_id: clientId, vendor_id: vendorId });
        for (const h of historyHsns) qs.append("hsn", h);
        const res = await apiGet(`/api/purchase-bills/vendor-history?${qs.toString()}`, token);
        if (cancelled) return;
        setHistory(res.success ? parseVendorHistory(res.data) : null);
      } catch {
        if (!cancelled) setHistory(null);
      }
    }, 600);
    return () => { cancelled = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyKey]);

  const validation = validateBillEditor({ vendorId, billDate, lines, isForeign, exchangeRate });
  const estBaseTotal = isForeign && rateNum > 0 ? estimateBaseMinor(vendorTotalPaise, rateNum) : vendorTotalPaise;

  // TDS COMES FROM THE SERVER, because only the server can compute it. This was
  // `estimateForeignTds(estBaseTaxable, vendor.tds_rate_bps)` — a bare rate x
  // base — while the save branches on RESIDENCY first: a non-resident goes
  // through s.195 (rate by nature of income, plus surcharge and cess, and a
  // refusal where chargeability or the treaty position is unknown), a resident
  // through resolve_tds with the section threshold, the YEAR'S AGGREGATE and
  // the s.206AA no-PAN floor. None of those inputs is in the browser, so a
  // sub-threshold s.194J bill previewed tax and saved zero, and a non-resident
  // bill previewed a resident rate (TDS-14). POST /api/purchase-bills/
  // tds-preview runs the identical code path the save runs.
  const tds = useServerTdsPreview({
    clientId, vendorId, billDate, lines: buildLinePayload(lines), isReverseCharge,
    currency: isForeign ? currency : undefined,
    exchangeRate: isForeign ? exchangeRate : undefined,
    excludeBillId: isEdit ? existing?.id : undefined,
    enabled: !!selectedVendor?.tds_applicable,
  });
  const tdsPaise = tds.data?.tds_paise ?? null;
  // In the bill's own currency when there is one — the server froze the rate,
  // so converting an INR deduction back here would be a second conversion.
  const netPayable = tds.data
    ? (isForeign ? tds.data.txn_net_payable : tds.data.net_payable_paise)
    : null;

  const accountNameById = new Map(accounts.map((a) => [a.id ?? "", a.account_name ?? a.name ?? ""]));
  const blockedCreditHits = findBlockedCreditHits(lines, accountNameById);
  // PUR-05. `itc_eligible` and `blocked_credit_reason` have been on the API,
  // the columns and the GSTR-3B computation since migration 240, and NO SCREEN
  // COULD SET THEM — so every purchase bill in the product claimed full credit,
  // §17(5) or not, and the reversal the return is supposed to make in Table
  // 4(B)(1) was always nil.
  // validateBillEditor carries the §17(5) refusal itself, so the save and the
  // message under the table cannot disagree; only the preview total is derived
  // here.
  const blockedGstPaise = ineligibleGstPaise(lines, isInterstate);

  function onVendorChange(id: string) {
    // Vendor is locked once a draft exists — PurchaseBillUpdateIn has no
    // vendor_id field (changing it would invalidate the frozen TDS section/
    // rate resolution), so the picker itself is disabled in edit mode too.
    if (isEdit) return;
    setVendorId(id);
    setSelectedVendor(vendors.find((v) => v.id === id) ?? null);
  }

  function setLine(idx: number, patch: Partial<EditorLine>) {
    // Typing into a field the document did not state IS the CA stating it, so
    // that field stops being flagged (AI-01).
    setLines((prev) => prev.map((l, i) => (
      i === idx ? { ...l, ...patch, unread: unreadAfterEdit(l.unread, patch) } : l)));
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

  // ── Enter goes to the next line (accounting-08) ───────────────────────────────────
  // A CA keying a bill of ten lines in Tally moves with the keyboard; this grid
  // had no key handling at all, so every line was a trip to the mouse. Enter in
  // one of the grid's PLAIN INPUTS (description, quantity, rate, the two cess
  // cells) moves to the SAME cell on the next line — down the column, the way a
  // spreadsheet does it — and on the last line adds one, but only when the line
  // has something on it, so Enter on an untouched blank line is not a way to
  // grow the bill.
  //
  // ONLY inputs that carry `data-cell` take part. The catalogue, HSN and account
  // pickers keep Enter (it selects an option), selects and checkboxes keep it
  // (it is how they are operated), and a delegated handler on the body is what
  // lets every cell opt in with one attribute instead of seven handlers.
  const gridRef = useRef<HTMLTableSectionElement>(null);
  const [focusCell, setFocusCell] = useState<{ row: number; cell: string } | null>(null);
  useEffect(() => {
    if (!focusCell) return;
    const rows = gridRef.current?.children;
    const input = rows?.[focusCell.row]?.querySelector<HTMLInputElement>(
      `[data-cell="${focusCell.cell}"]`);
    input?.focus();
    input?.select();
    setFocusCell(null);
  }, [focusCell]);

  function onLineGridKeyDown(e: React.KeyboardEvent<HTMLTableSectionElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return;
    const target = e.target as HTMLElement;
    const cell = target instanceof HTMLInputElement ? target.dataset.cell : undefined;
    if (!cell || !gridRef.current) return;
    const rowEl = target.closest("tr");
    const row = rowEl ? Array.prototype.indexOf.call(gridRef.current.children, rowEl) : -1;
    if (row < 0) return;
    e.preventDefault();
    if (row < lines.length - 1) { setFocusCell({ row: row + 1, cell }); return; }
    const last = lines[row];
    if (!last || !(last.description.trim() || last.rate || last.hsn_sac || last.service_catalogue_id)) return;
    addLine();
    setFocusCell({ row: row + 1, cell });
  }

  // Look up catalogue items sharing each extracted line's HSN/SAC (one
  // batched query, not one search per line) and either auto-link a single
  // confident match or attach the candidate list for the chip UI below.
  // Never touches description/rate/gst_rate/unit — those came straight off
  // the actual invoice and are authoritative for this specific bill; the
  // catalogue item is a link for reuse/inventory, not a source of truth.
  async function matchLinesByHsn(rawLines: EditorLine[]): Promise<EditorLine[]> {
    const codes = Array.from(new Set(rawLines.map((l) => l.hsn_sac.trim()).filter(Boolean)));
    if (!codes.length) return rawLines;
    try {
      const supabase = getSupabaseClient();
      const { data } = await supabase
        .from("service_catalogue")
        .select("*")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .in("hsn_sac", codes);
      const byHsn = new Map<string, ServiceCatalogueItem[]>();
      for (const item of (data as ServiceCatalogueItem[]) ?? []) {
        const code = (item.hsn_sac ?? "").trim();
        if (!code) continue;
        byHsn.set(code, [...(byHsn.get(code) ?? []), item]);
      }
      return rawLines.map((l) => {
        const code = l.hsn_sac.trim();
        if (!code) return l;
        const matches = byHsn.get(code) ?? [];
        return matches.length === 1
          ? { ...l, service_catalogue_id: matches[0].id, product: matches[0], hsnMatches: matches }
          : { ...l, hsnMatches: matches };
      });
    } catch {
      // Best-effort: a failed lookup just leaves lines unlinked, same as before.
      return rawLines;
    }
  }

  // ── AI document extraction ───────────────────────────────────────────────
  async function handleExtract() {
    if (!uploadFile) return;
    setExtracting(true);
    setAiExtracted(null);
    setAiTotals(null);
    setAiSupplier(null);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("client_id", clientId);
      const token = await getAuthToken();
      const res = await fetch(`${API}/api/document-intelligence-v1/extract-invoice`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      const json = await res.json();
      // The uploaded file is retained server-side as ITC/audit evidence
      // regardless of whether AI extraction itself succeeded.
      if (json.data?.document_url) setDocumentUrl(json.data.document_url as string);
      if (json.success && json.data?.extracted) {
        const ex = json.data.extracted as ExtractedInvoice;
        setAiExtracted(ex as unknown as Record<string, unknown>);
        setAiTotals(objectWithLists<ExtractionTotalsCheck>(json.data.totals_check, "failures"));
        const supplier = objectWithLists<ExtractionSupplierCheck>(json.data.supplier_check, "failures");
        setAiSupplier(supplier);
        if (ex.invoice_no) setBillNo(ex.invoice_no);
        if (ex.invoice_date) setBillDate(ex.invoice_date);
        // Match the extracted vendor — GSTIN first (exact, authoritative),
        // then the name, compared EXACTLY after trimming and lower-casing (it
        // said "fuzzy" here for a long time; it never was, and a near-miss
        // spelling is left for the CA to pick) — mirrors bill_from_document's
        // own server-side matching (routers/purchase_bills.py). Previously this extraction
        // path never attempted a vendor match at all, so the Vendor field
        // silently stayed empty even on a successful extraction.
        const gstin = ex.vendor_gstin?.trim().toUpperCase();
        const name = ex.vendor_name?.trim().toLowerCase();
        // A GSTIN is matched on only if the server did not find it WRONG (ai-02).
        // The model is typing fifteen characters it has looked at, and the server
        // tests them against the check digit; `valid === false` means this one
        // failed, so it identifies no registration and the vendor is not chosen by
        // it. `null` (nothing to test) and `true` both leave the match as it was.
        const gstinTrusted = supplier?.gstin?.valid !== false;
        const byGstin = gstin && gstinTrusted
          ? vendors.find((v) => v.gstin?.toUpperCase() === gstin)
          : undefined;
        const byName = name
          ? vendors.find((v) => v.name.trim().toLowerCase() === name)
          : undefined;
        const matched = byGstin ?? byName ?? null;
        if (matched) onVendorChange(matched.id);
        if (ex.line_items?.length) {
          // AI-01: nothing is invented here. A quantity, unit, rate or GST rate
          // the document did not state arrives as null and is shown EMPTY and
          // flagged, where this used to put 1, "NOS" and 18% on the line as if
          // they had been read — and a real 0% came back as 18%.
          const rawLines: EditorLine[] = ex.line_items.map((li) => ({
            ...lineFromExtraction(li),
            expense_account_id: "", service_catalogue_id: "",
            _k: nextKey(),
          }));
          setLines(await matchLinesByHsn(rawLines));
        }
        if (!matched && (gstin || name)) {
          setError(`AI extracted vendor "${ex.vendor_name ?? gstin}" but no matching vendor was found — select one manually.`);
        }
      } else {
        setError(json.error || "AI extraction failed. Please enter the bill details manually.");
      }
    } catch {
      setError("AI extraction failed. Please enter the bill details manually.");
    } finally {
      setExtracting(false);
    }
  }

  // ── Save ─────────────────────────────────────────────────────────────────
  async function save() {
    setAttempted(true);
    if (dates.first) { setError(dates.first); return; }
    if (!validation.ok) {
      setError(validation.errors.vendor ?? validation.errors.billDate ?? validation.errors.unread ?? validation.errors.lines ?? validation.errors.exchangeRate ?? "Fix the highlighted fields.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const token = await getAuthToken();
      const linePayload = buildLinePayload(lines);

      if (isEdit && existing) {
        // Once received, the backend only accepts our_reference/notes/due_date/
        // document_url (routers/purchase_bills.py's _SOFT_BILL_UPDATE_FIELDS) —
        // sending bill_date/bill_no/lines at all (even unchanged) gets the whole
        // PATCH rejected with 422, since the check is "was the key present",
        // not "did the value change". isLocked mirrors that exactly so a
        // received-bill edit never fails on fields the CA never touched.
        const patchPayload = isLocked
          ? {
              due_date: dueDate || undefined,
              our_reference: ourReference.trim() || undefined,
              notes: notes.trim() || undefined,
              document_url: documentUrl || undefined,
              // Rule 37BB, and EDITABLE ON A RECEIVED BILL on purpose:
              // Form 15CA is filed at the time of remittance, which is after
              // the bill is booked. `_SOFT_BILL_UPDATE_FIELDS` allows all
              // three for exactly that reason.
              form_15ca_ack_no: form15caAckNo.trim() || undefined,
              form_15ca_filed_on: form15caFiledOn || undefined,
              form_15cb_udin: form15cbUdin.trim() || undefined,
            }
          : {
              bill_date: billDate,
              due_date: dueDate || undefined,
              bill_no: billNo.trim() || undefined,
              our_reference: ourReference.trim() || undefined,
              notes: notes.trim() || undefined,
              document_url: documentUrl || undefined,
              lines: linePayload,
              // Rule 37BB, and EDITABLE ON A RECEIVED BILL on purpose:
              // Form 15CA is filed at the time of remittance, which is after
              // the bill is booked. `_SOFT_BILL_UPDATE_FIELDS` allows all
              // three for exactly that reason.
              form_15ca_ack_no: form15caAckNo.trim() || undefined,
              form_15ca_filed_on: form15caFiledOn || undefined,
              form_15cb_udin: form15cbUdin.trim() || undefined,
            };
        const upd = await apiCall(`/api/purchase-bills/${existing.id}`, "PATCH", patchPayload, token);
        if (!upd.success) throw new Error(upd.error ?? "Failed to update bill");
        // The server has the bill. Only now is the tab's copy of what was typed
        // stale; a refusal above leaves it where it was (frontend_ux-23).
        draft.clear();
      } else {
        const result = await apiCall(
          "/api/purchase-bills/",
          "POST",
          {
            client_id: clientId,
            vendor_id: vendorId,
            bill_date: billDate,
            due_date: dueDate || undefined,
            bill_no: billNo.trim() || undefined,
            our_reference: ourReference.trim() || undefined,
            notes: notes.trim() || undefined,
            is_reverse_charge: isReverseCharge,
            document_url: documentUrl || undefined,
            lines: linePayload,
            currency: isForeign ? currency : undefined,
            exchange_rate: isForeign ? exchangeRate : undefined,
            form_15ca_ack_no: form15caAckNo.trim() || undefined,
            form_15ca_filed_on: form15caFiledOn || undefined,
            form_15cb_udin: form15cbUdin.trim() || undefined,
          },
          token,
        );
        if (!result.success) throw new Error(result.error ?? "Failed to create bill");
        // Saved — including when the near-duplicate warning below keeps this
        // screen open: a draft left behind would be offered back as a bill that
        // was never recorded, and restoring it would record it twice.
        draft.clear();
        const warned = (result.data as { near_duplicates?: NearDuplicate[] } | undefined)
          ?.near_duplicates;
        if (warned?.length) {
          // Stay open. The bill is saved; what the CA has to do now is look at
          // the other document, and closing the drawer takes both the warning
          // and the context away.
          setNearDupes(warned);
          setSaving(false);
          return;
        }
      }
      const label = billNo.trim() || "Purchase bill";
      onDone(isEdit ? `${label} updated` : `${label} saved as draft`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save purchase bill");
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel() {
    if (await confirmLeave()) onCancel();
  }

  const busy = saving;
  const fieldErr = (msg?: string) => (attempted && msg ? <p className="mt-1 text-3xs text-state-problem">{msg}</p> : null);

  const toolbar = (
    <>
      <button onClick={handleCancel} disabled={busy} className="mr-auto text-xs px-3 py-1.5 text-ps-label hover:text-ps-body disabled:opacity-50">
        Cancel
      </button>
      <Button variant="plain" size="none" spinner={false} onClick={save} disabled={busy} className="text-xs px-3.5 py-1.5 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50 inline-flex items-center gap-1.5">
        {saving && <Loader2 size={12} className="animate-spin" />} {isEdit ? "Save Changes" : "Save Draft"}
      </Button>
    </>
  );

  const summary = (
    <div className="bg-white rounded-xl border border-ps-border p-4 space-y-2 text-xs">
      <p className="font-semibold text-ps-body">Summary{isForeign ? ` (${currency})` : ""}</p>
      <Row label="Taxable value" value={fmtAmt(totals.taxable_paise)} />
      {isInterstate ? (
        <Row label="IGST" value={fmtAmt(totals.igst_paise)} />
      ) : (
        <>
          <Row label="CGST" value={fmtAmt(totals.cgst_paise)} />
          <Row label="SGST" value={fmtAmt(totals.sgst_paise)} />
        </>
      )}
      {/* Its own row, never folded into the GST heads: GST (Compensation to
          States) Act 2017 s.11(2), proviso — credit of this cess "shall be
          utilised only towards payment of cess", so it stays a separate head
          from the bill all the way to GSTR-3B. */}
      {totals.cess_paise > 0 && (
        <Row label="Compensation cess" value={fmtAmt(totals.cess_paise)} />
      )}
      <p className={`text-3xs ${supplySplit.basis === "client_state_unknown" || supplySplit.basis === "vendor_state_unknown"
        ? "text-state-attention" : "text-ps-hint"}`}>
        {supplySplit.caption}
      </p>
      {isReverseCharge && (
        <p className="text-3xs text-state-attention">
          Reverse charge — the GST above is self-assessed by you (GSTR-3B 3.1(d)), not payable to the vendor.
        </p>
      )}
      {/* WHAT THE RETURN WILL REVERSE, shown before the bill is saved. Blocked
          credit stays in Table 4(A) — it is auto-populated from GSTR-2B and
          netting it there breaks the tie-up — and comes out in 4(B)(1) as a
          reversal "absolute in nature and not reclaimable" (Notification
          14/2022 with Circular 170/02/2022-GST). It is NOT in 4(D). */}
      {blockedGstPaise > 0 && (
        <div className="border-t border-ps-border pt-2 mt-1">
          <Row label="ITC blocked (§17(5))" value={fmtAmt(blockedGstPaise)} />
          <p className="text-3xs text-ps-hint">
            Claimed in GSTR-3B Table 4(A) and reversed in 4(B)(1). It does not
            change what you pay the vendor.
          </p>
        </div>
      )}
      <div className="flex justify-between font-semibold text-ps-ink border-t border-ps-border pt-1.5 mt-1">
        <span>{isReverseCharge ? "Payable to Vendor" : "Grand Total"}{isForeign ? ` (${currency})` : ""}</span>
        <span className="font-mono">{fmtAmt(vendorTotalPaise)}</span>
      </div>
      {isForeign && rateNum > 0 && <Row label="≈ INR total" value={fmt(estBaseTotal)} muted />}
      {selectedVendor?.tds_applicable && (
        <div className="border-t border-ps-border pt-2 mt-1 space-y-1.5">
          {/* The SECTION and the RATE come back with the figure. Neither is the
              vendor's stored tds_rate_bps: the rate actually applied depends on
              the payee's PAN (s.206AA), on residency (s.195 carries surcharge
              and cess), and on whether the year's aggregate has been crossed —
              the same vendor and the same amount deduct differently on the bill
              that crosses it. */}
          {tds.loading && <Row label="TDS" value="…" muted />}
          {!tds.loading && tds.error && (
            <p className="text-3xs text-state-problem bg-state-problem-surface rounded px-2 py-1.5">{tds.error}</p>
          )}
          {!tds.loading && !tds.error && tds.data && tdsPaise !== null && netPayable !== null && (
            <>
              <Row
                label={tds.data.tds_section
                  ? `TDS §${tds.data.tds_section} @ ${(tds.data.tds_rate_bps / 100).toFixed(2)}%`
                  : "TDS"}
                value={fmt(tdsPaise)} />
              <Row label="Net payable" value={fmtAmt(netPayable)} />
              {/* WHY that figure. A number with no reason is a number a CA
                  cannot check, and this one moves with the year's running
                  total. */}
              {tds.data.tds_basis && (
                <p className="text-3xs text-ps-hint">{tds.data.tds_basis}</p>
              )}
              {/* s.201(1A) runs at 1% a month on an under-deduction. The
                  shortfall is not lost — the next bill to the same payee
                  re-charges it — but a net payable of nil is not where a CA
                  should have to infer that from. */}
              {tds.data.tds_shortfall_paise > 0 && (
                <p className="text-3xs text-state-attention bg-state-attention-surface rounded px-2 py-1.5">
                  The year&apos;s aggregate demands {fmt(tds.data.tds_shortfall_paise)} more than this
                  bill can carry. It is recovered on the next bill to this payee; §201(1A) interest
                  runs at 1% a month until it is deducted.
                </p>
              )}
              {isForeign && <p className="text-3xs text-ps-hint">TDS is always deducted in ₹ per IT Act §194.</p>}
            </>
          )}
        </div>
      )}
      <p className="text-3xs text-ps-hint pt-1">
        GST above is a preview and is confirmed by the server on save. The TDS figure
        is computed by the server now, by the same code that will withhold it.
      </p>
      {attempted && !validation.ok && (
        <div className="flex items-start gap-1.5 text-3xs text-state-problem bg-state-problem-surface rounded px-2 py-1.5">
          <AlertCircle size={12} className="mt-px flex-shrink-0" />
          <span>{validation.errors.vendor ?? validation.errors.billDate ?? validation.errors.unread ?? validation.errors.lines ?? validation.errors.exchangeRate}</span>
        </div>
      )}
    </div>
  );

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: clientName || "Client", href: `/clients/${clientId}` },
        { label: "Purchases", href: `/clients/${clientId}/purchases` },
        { label: isEdit ? `Edit ${billNo || "Purchase Bill"}` : "New Purchase Bill" },
      ]}
      title={isEdit ? `Edit ${billNo || "Purchase Bill"}` : "New Purchase Bill"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-3xs font-medium bg-ps-muted text-ps-label">{isEdit ? (existing?.status ?? "draft").replace("_", " ") : "Draft"}</span>}
      dirtyHint={dirty ? <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-state-attention" /> Unsaved changes</span> : undefined}
      toolbar={toolbar}
      summary={summary}
    >
      <div className="space-y-5">
        {/* An unsent draft is OFFERED, never applied (frontend_ux-23). */}
        {draft.offer && (
          <DraftOffer
            what="purchase bill" savedAt={draft.offer.savedAt}
            onRestore={restoreDraft} onDiscard={draft.discard}
          />
        )}
        {restoreNote && (
          <p role="status" className="text-xs text-state-attention bg-state-attention-surface rounded px-3 py-2">
            {restoreNote}
          </p>
        )}

        {/* AI Upload — create-only; re-extracting into an already-saved draft
            would silently overwrite manually-corrected fields. */}
        {isEdit ? (
          documentUrl && (
            <section className="bg-state-attention-surface border border-state-attention-border rounded-lg p-3">
              <p className="text-3xs text-state-attention">
                📎 Original invoice attached — retained on this bill as supporting evidence (CGST Rule 36).
              </p>
            </section>
          )
        ) : (
          <section className="bg-state-attention-surface border border-state-attention-border rounded-lg p-3 space-y-2">
            <p className="text-xs font-medium text-state-attention flex items-center gap-1.5"><Upload size={12} /> Upload Invoice (AI Extract)</p>
            <div className="flex items-center gap-2">
              <input type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} className="text-xs text-ps-label" />
              <Button variant="plain" size="none" onClick={handleExtract} disabled={!uploadFile || extracting} className="text-xs px-3 py-1.5 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-40">
                {extracting ? "Extracting…" : "Extract"}
              </Button>
            </div>
            {aiExtracted && (
              <div className="mt-1 text-3xs text-state-attention bg-state-attention-surface rounded px-2 py-1.5">
                ✓ AI extracted data pre-filled below. <strong>Review before saving.</strong>
              </div>
            )}
            {/* WHAT THE DOCUMENT SAID, BESIDE WHAT THIS BILL WILL SAVE (PUR-21).
                The five header figures were read, coerced to integers and never
                looked at again: nothing checked that they add up, and nothing
                showed them to the CA, so a misread digit reached the draft with
                a "high" confidence badge on it. Both comparisons WARN and
                neither blocks — an invoice's own round-off line legitimately
                moves the total by up to 50 paise (CGST s.170), and refusing a
                save over that would stop a CA saving a correct bill. */}
            {aiExtracted && (
              <div className="mt-1 rounded border border-state-attention-border bg-white px-2 py-1.5 space-y-1">
                <p className="text-3xs font-medium text-ps-label">Read from the document</p>
                <div className="grid grid-cols-5 gap-1 text-3xs text-ps-label">
                  {([
                    ["Taxable", "taxable_amount_paise"],
                    ["CGST", "cgst_paise"],
                    ["SGST", "sgst_paise"],
                    ["IGST", "igst_paise"],
                    ["Total", "total_paise"],
                  ] as const).map(([label, key]) => (
                    <div key={key}>
                      <span className="block text-3xs uppercase tracking-wide text-ps-hint">{label}</span>
                      <span className="font-mono text-ps-body">
                        {fmt(Number(aiExtracted[key] ?? 0))}
                      </span>
                    </div>
                  ))}
                </div>
                {/* Each failing check says its own thing with its own amounts
                    (ai-02): the lines against the taxable value and the tax at the
                    lines' rates are different findings from the header sum, and
                    "off by" one figure cannot describe all three. A server one
                    deploy behind sends no `failures`, and the header sentence
                    below is what it always was. */}
                {aiTotals && !aiTotals.agrees && (aiTotals.failures?.length ?? 0) > 0 && (
                  <div className="space-y-1">
                    {(aiTotals.failures ?? []).map((reason, i) => (
                      <p key={i} className="flex items-start gap-1 text-3xs text-state-problem bg-state-problem-surface rounded px-1.5 py-1">
                        <AlertTriangle size={11} className="mt-px flex-shrink-0" />
                        <span>{reason}</span>
                      </p>
                    ))}
                  </div>
                )}
                {aiTotals?.checked && !aiTotals.agrees && (aiTotals.failures?.length ?? 0) === 0 && (
                  <p className="flex items-start gap-1 text-3xs text-state-problem bg-state-problem-surface rounded px-1.5 py-1">
                    <AlertTriangle size={11} className="mt-px flex-shrink-0" />
                    <span>
                      These do not add up — off by {fmt(Math.abs(aiTotals.difference_paise))}.{" "}
                      {aiTotals.note}
                    </span>
                  </p>
                )}
                {/* The supplier, checked beside the figures (ai-02): a GSTIN whose
                    check digit fails is a GSTIN the model misread, and IGST between
                    two same-State registrations is a tax head it misread or a place
                    of supply only the invoice can show. Both WARN. */}
                {(aiSupplier?.failures ?? []).map((f) => (
                  <p key={f.check} className="flex items-start gap-1 text-3xs text-state-problem bg-state-problem-surface rounded px-1.5 py-1">
                    <AlertTriangle size={11} className="mt-px flex-shrink-0" />
                    <span>{f.reason}</span>
                  </p>
                ))}
                {aiTotals && !aiTotals.checked && (
                  <p className="text-3xs text-ps-hint">{aiTotals.note}</p>
                )}
                {/* And against the lines actually going to be saved, once they
                    compute anything: previewBillTotals skips a line with no
                    Product/Service, and an extracted line has none until the CA
                    links one — so before that this would read "computes 0" on
                    every scan, which is true and useless. */}
                {totals.grand_total_paise > 0
                  && Number(aiExtracted.total_paise ?? 0) > 0
                  && Math.abs(totals.grand_total_paise - Number(aiExtracted.total_paise ?? 0)) > 100 && (
                  <p className="flex items-start gap-1 text-3xs text-state-attention bg-state-attention-surface rounded px-1.5 py-1">
                    <AlertTriangle size={11} className="mt-px flex-shrink-0" />
                    <span>
                      The lines below come to {fmtAmt(totals.grand_total_paise)} against the{" "}
                      {fmt(Number(aiExtracted.total_paise ?? 0))} read from the document.
                      Check the quantities, rates and GST rates before saving — the
                      bill is saved from the LINES.
                    </span>
                  </p>
                )}
              </div>
            )}
            {documentUrl && (
              <p className="text-3xs text-state-attention">
                📎 Original invoice attached — retained on this bill as supporting evidence (CGST Rule 36).
              </p>
            )}
          </section>
        )}

        {/* Party + metadata */}
        <section className="bg-white rounded-xl border border-ps-border p-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-ps-label mb-1">Vendor *</label>
              <VendorLookup vendors={vendors} value={vendorId} onChange={onVendorChange} ariaLabel="Vendor" disabled={isEdit} />
              {isEdit && <p className="mt-1 text-3xs text-ps-hint">Vendor can&apos;t be changed once a bill exists — it&apos;s locked to the TDS section resolved at creation.</p>}
              {fieldErr(validation.errors.vendor)}
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Vendor Invoice No.</label>
              <input value={billNo} onChange={(e) => setBillNo(e.target.value)} placeholder="INV-001" disabled={isLocked}
                className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand disabled:bg-ps-bg disabled:text-ps-hint" />
              {isLocked && <p className="mt-1 text-3xs text-ps-hint">Frozen once received.</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Our Reference</label>
              <input value={ourReference} onChange={(e) => setOurReference(e.target.value)} placeholder="Internal tracking no."
                className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
            </div>
            <div>
              <label htmlFor="bill-date" className="block text-xs font-medium text-ps-label mb-1">Bill Date *</label>
              <DateInput id="bill-date" value={billDate} onChange={setBillDate} onStateChange={dates.watch("billDate", "Bill date")} disabled={isLocked}
                className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand disabled:bg-ps-bg disabled:text-ps-hint" />
              {!dates.problems.billDate && fieldErr(validation.errors.billDate)}
              {isLocked && <p className="mt-1 text-3xs text-ps-hint">Frozen once received — issue a Debit Note to correct (CGST Act §34).</p>}
            </div>
            <div>
              <label htmlFor="bill-due-date" className="block text-xs font-medium text-ps-label mb-1">Due Date</label>
              <DateInput id="bill-due-date" value={dueDate} onChange={setDueDate} onStateChange={dates.watch("dueDate", "Due date")}
                anchor={dueDate || billDate}
                className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
            </div>
            <div className="flex flex-col justify-end pb-1.5">
              <label className={`flex items-center gap-2 text-xs text-ps-label ${isEdit ? "opacity-50" : "cursor-pointer"}`}>
                <input type="checkbox" checked={isReverseCharge} disabled={isEdit} onChange={(e) => setIsReverseCharge(e.target.checked)} className="rounded" />
                Reverse Charge (RCM)
              </label>
              <p className="mt-1 text-3xs text-ps-hint">
                {isEdit ? "Locked once a bill exists." : "CGST Act §9(3)/(4) — GTA, import of services, notified supplies, or purchases from an unregistered person in a specified category."}
              </p>
            </div>
            <div className="col-span-2 lg:col-span-4">
              <label className="block text-xs font-medium text-ps-label mb-1">Notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Internal notes — not shown to the vendor" rows={2}
                className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
            </div>
          </div>

          {mcActive && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-3 pt-3 border-t border-ps-border">
              <div>
                <label className="block text-xs font-medium text-ps-label mb-1">Currency</label>
                <select value={currency} onChange={(e) => { setCurrency(e.target.value); setExchangeRate(""); }}
                  className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand">
                  <option value="">INR (default)</option>
                  {currencies.filter((c) => c.code !== "INR").map((c) => (
                    <option key={c.code} value={c.code}>{c.code}{c.display_name ? ` — ${c.display_name}` : ""}</option>
                  ))}
                </select>
              </div>
              {isForeign && (
                <div>
                  <label className="block text-xs font-medium text-ps-label mb-1">Exchange Rate *</label>
                  <input type="number" min="0" step="0.0001" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)}
                    placeholder={`1 ${currency} = ? INR`}
                    className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand text-right font-mono" />
                  {fieldErr(validation.errors.exchangeRate)}
                </div>
              )}
            </div>
          )}
        </section>

        {/* ── Rule 37BB — the paperwork for a payment to a non-resident ──
            Shown when the SERVER says this bill withholds under §195, not when
            the browser guesses at the vendor's residency: the same preview
            that computes the tax decides it, so the panel and the deduction
            cannot disagree about who the payee is.

            §195(6) with Rule 37BB requires Form 15CA for a remittance to a
            non-resident, and Form 15CB — an accountant's certificate — for
            most chargeable ones. `tds_register_service` raises a gap on every
            §195 bill whose 15CA acknowledgement is blank, and since PUR-14
            that gap reaches the CA: the product spent months telling them to
            record something no screen let them record (TDS-25).

            RECORDED HERE, NEVER FILED FROM HERE. 15CA is filed on
            incometax.gov.in under the remitter's own login; this is where the
            acknowledgement goes afterwards. CLAUDE.md: never auto-submit. */}
        {tds.data?.tds_section === "195" && (
          <section className="bg-white rounded-xl border border-ps-border p-4">
            <h2 className="text-xs font-semibold text-ps-body">
              Foreign remittance — Form 15CA / 15CB (IT Act §195(6), Rule 37BB)
            </h2>
            <p className="mt-1 text-3xs text-ps-hint">
              File on incometax.gov.in under the remitter&apos;s login, then record
              the acknowledgement here. Nothing on this page is submitted to any
              portal. These three can still be edited after the bill is received,
              because the remittance happens later.
            </p>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
              <div>
                <label className="block text-xs font-medium text-ps-label mb-1">
                  Form 15CA acknowledgement no.
                </label>
                <input value={form15caAckNo} onChange={(e) => setForm15caAckNo(e.target.value)}
                  placeholder="As shown on the filed 15CA"
                  className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
              </div>
              <div>
                <label htmlFor="bill-15ca-date" className="block text-xs font-medium text-ps-label mb-1">
                  Form 15CA filed on
                </label>
                <DateInput id="bill-15ca-date" value={form15caFiledOn}
                  onChange={setForm15caFiledOn} onStateChange={dates.watch("form15caFiledOn", "Form 15CA filed on")}
                  anchor={form15caFiledOn || billDate}
                  className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
              </div>
              <div>
                <label className="block text-xs font-medium text-ps-label mb-1">
                  Form 15CB UDIN
                </label>
                <input value={form15cbUdin} onChange={(e) => setForm15cbUdin(e.target.value)}
                  placeholder="UDIN of the certifying member"
                  className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
                <p className="mt-1 text-3xs text-ps-hint">
                  What makes the certificate traceable to the member who signed it.
                </p>
              </div>
            </div>
            {!form15caAckNo.trim() && (
              <p className="mt-3 text-3xs text-state-attention bg-state-attention-surface rounded px-2 py-1.5">
                Recorded as a gap on the TDS register until the acknowledgement is
                entered. Not a refusal — the bill saves either way, because the
                15CA is filed when the money moves and that may be after this.
              </p>
            )}
          </section>
        )}

        {blockedCreditHits.length > 0 && (
          <div className="flex items-start gap-2 bg-state-attention-surface border border-state-attention-border rounded-lg px-3 py-2.5 text-xs text-state-attention">
            <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
            <div className="space-y-1">
              <p className="font-medium">Possible blocked ITC — review before saving (CGST Act §17(5))</p>
              {blockedCreditHits.map((h, i) => (
                <p key={i} className="flex items-start gap-2 flex-wrap">
                  <span>Line {h.lineIndex + 1} ({h.label}): {h.note}</span>
                  {/* The prompt and the control it points at now agree: marking
                      it from here preselects the clause the hint matched, so a
                      CA is not asked to find it again in a list of fourteen. */}
                  {lineIsItcEligible(lines[h.lineIndex]) && (
                    <button type="button" disabled={isLocked}
                      onClick={() => setLine(h.lineIndex, {
                        itc_eligible: false,
                        blocked_credit_reason: reasonForHintLabel(h.label) ?? "other",
                      })}
                      className="text-3xs px-1.5 py-0.5 rounded-full bg-white border border-state-attention-border text-state-attention hover:bg-state-attention-surface disabled:opacity-40">
                      Mark line {h.lineIndex + 1} blocked
                    </button>
                  )}
                </p>
              ))}
              <p className="text-3xs text-state-attention">This is a heuristic prompt, not a legal determination — confirm eligibility before claiming ITC.</p>
            </div>
          </div>
        )}

        {/* ai-23. Earlier bills from this supplier were assessed under a TDS
            section the supplier record no longer carries. A NOTICE and not a
            control: this bill's section is decided from the supplier record when
            it is created, so the sentence says what the bill WILL do. */}
        {history?.tds && (
          <Callout tone="attention" title="TDS section differs from earlier bills">
            {history.tds.sentence}
          </Callout>
        )}

        {/* Line items */}
        <section className="bg-white rounded-xl border border-ps-border p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <h2 className="text-xs font-semibold text-ps-body">Line items</h2>
            {!isLocked && (
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showCess}
                  onChange={(e) => setShowCess(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-ps-border-strong accent-brand-dark"
                />
                <span className="text-2xs text-ps-label">Compensation cess</span>
              </label>
            )}
          </div>
          {isLocked && (
            <p className="mb-2 text-3xs text-ps-hint">
              Frozen once received — issue a Debit Note to correct a quantity, rate, or item (CGST Act §34).
            </p>
          )}
          {/* fieldset disables every input/select/button in the table below in
              one shot, no need to thread `disabled` through each custom lookup
              component individually — native form-control disable propagates
              through any wrapper markup. */}
          <fieldset disabled={isLocked} className="border-0 p-0 m-0 min-w-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[860px]">
              <thead>
                <tr className="border-b border-ps-border text-ps-hint">
                  <th className="pb-2 text-left font-semibold w-36">Product/Service *</th>
                  <th className="pb-2 text-left font-semibold">Description</th>
                  <th className="pb-2 text-left font-semibold w-24">HSN/SAC</th>
                  <th className="pb-2 text-left font-semibold w-28">Expense Account</th>
                  <th className="pb-2 text-right font-semibold w-20">Qty</th>
                  <th className="pb-2 text-left font-semibold w-16">Unit</th>
                  <th className="pb-2 text-right font-semibold w-24">Rate ({isForeign ? currency : "₹"})</th>
                  <th className="pb-2 text-right font-semibold w-20">GST %</th>
                  {/* GST (Compensation to States) Act 2017 s.8(2) — "on the
                      basis of VALUE, QUANTITY or on such basis". Two limbs,
                      added: coal is per tonne, aerated waters a percentage,
                      cigarettes both. Per unit of THIS LINE'S UQC. */}
                  {showCess && (
                    <>
                      <th className="pb-2 text-right font-semibold w-20" title="Compensation cess, ad valorem">Cess %</th>
                      <th className="pb-2 text-right font-semibold w-24" title="Compensation cess per unit of this line's UQC">Cess/unit</th>
                    </>
                  )}
                  <th className="pb-2 text-right font-semibold w-24">Amount</th>
                  <th className="pb-2 w-6" />
                </tr>
              </thead>
              <tbody ref={gridRef} onKeyDown={onLineGridKeyDown} className="divide-y divide-ps-border">
                {lines.map((line, idx) => {
                  const g = previewBillTotals([line], isInterstate);
                  const invalid = attempted && !isValidBillLine(line) && (line.description.trim() || line.rate || line.hsn_sac);
                  return (
                    <tr key={line._k} className={invalid ? "bg-state-problem-surface/40" : undefined}>
                      <td className="py-1.5 pr-2">
                        <ServiceCataloguePicker clientId={clientId} value={line.product} onPick={(item) => onPickProduct(idx, item)} size="sm" ariaLabel={`Line ${idx + 1} product or service`} />
                        {/* HSN-based catalogue hints (see matchLinesByHsn) — only
                            relevant right after AI extraction; a manually-added
                            blank line has hsnMatches === undefined and shows nothing. */}
                        {line.hsnMatches && line.hsnMatches.length > 1 && !line.service_catalogue_id && (
                          <div className="mt-1 flex flex-wrap gap-1 items-center">
                            <span className="text-3xs text-ps-hint">HSN {line.hsn_sac} matches:</span>
                            {line.hsnMatches.map((m) => (
                              /* Raw, deliberately: the base is blue-50, for
                                 which there is no token, and mapping it to
                                 `working-surface` (= blue-100) would make it
                                 the same colour as its own hover — the
                                 surface-on-surface defect the token file
                                 records under `problem-hover`. */
                              <button key={m.id} type="button" onClick={() => onPickProduct(idx, m)}
                                className="text-3xs px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200">
                                {m.name}
                              </button>
                            ))}
                          </div>
                        )}
                        {line.hsnMatches && line.hsnMatches.length === 0 && line.hsn_sac.trim() && !line.service_catalogue_id && (
                          <p className="mt-1 text-3xs text-ps-disabled">No catalogue match for HSN {line.hsn_sac}</p>
                        )}
                        {line.hsnMatches?.length === 1 && line.service_catalogue_id === line.hsnMatches[0].id && (
                          <p className="mt-1 text-3xs text-state-ready">✓ Auto-linked from catalogue</p>
                        )}
                      </td>
                      <td className="py-1.5 pr-2">
                        <input data-cell="description" value={line.description} onChange={(e) => setLine(idx, { description: e.target.value })} placeholder="Item description" aria-label={`Line ${idx + 1} description`}
                          className="w-full px-2 py-1 border border-ps-border rounded focus:outline-none focus:ring-1 focus:ring-brand text-xs" />
                        {/* CGST ACT §17(5), UNDER THE DESCRIPTION AND NOT IN A
                            COLUMN OF ITS OWN. Eligible is the ordinary case, so
                            it is one checkbox; the fifteen-clause select appears
                            only once a line is marked, where a column would have
                            crowded out the figures on every row of every bill. */}
                        <label className="mt-1 flex items-center gap-1.5 text-3xs text-ps-label">
                          <input type="checkbox" checked={!lineIsItcEligible(line)}
                            aria-label={`Line ${idx + 1} ITC blocked under section 17(5)`}
                            onChange={(e) => setLine(idx, e.target.checked
                              ? { itc_eligible: false, blocked_credit_reason: line.blocked_credit_reason || "" }
                              // Unmarking clears the clause too. A stale reason
                              // on an eligible line is a sentence that
                              // contradicts the flag beside it.
                              : { itc_eligible: true, blocked_credit_reason: "" })} />
                          ITC blocked (§17(5))
                        </label>
                        {/* ai-23. Only where the earlier lines were BLOCKED — an
                            "eligible" history restates the column's default and is
                            not shown. Applies on a click and never before. */}
                        {(() => {
                          const s = chipsForLine(history, line).itc;
                          if (!s) return null;
                          return (
                            <div className="mt-1 text-3xs text-ps-hint" data-testid={`history-itc-${idx}`}>
                              <button type="button" disabled={isLocked}
                                onClick={() => setLine(idx, itcPatch(s))}
                                className="px-1.5 py-0.5 rounded-full bg-ps-muted border border-ps-border text-ps-body hover:bg-white disabled:opacity-40">
                                Mark ITC blocked
                              </button>
                              <span className="ml-1">
                                Earlier lines were blocked — {s.sentence.charAt(0).toLowerCase() + s.sentence.slice(1)}
                              </span>
                            </div>
                          );
                        })()}
                        {!lineIsItcEligible(line) && (
                          <>
                            <select value={line.blocked_credit_reason ?? ""}
                              aria-label={`Line ${idx + 1} section 17(5) clause`}
                              onChange={(e) => setLine(idx, { blocked_credit_reason: e.target.value })}
                              className={`mt-1 w-full px-1 py-1 border rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand text-3xs ${
                                (line.blocked_credit_reason ?? "").trim() === ""
                                  ? "border-state-problem" : "border-ps-border"}`}>
                              <option value="">— which clause? —</option>
                              {BLOCKED_CREDIT_REASONS.map((r) => (
                                <option key={r.code} value={r.code}>{r.clause} · {r.label}</option>
                              ))}
                            </select>
                            {BLOCKED_CREDIT_REASONS.find((r) => r.code === line.blocked_credit_reason)?.note && (
                              <p className="mt-0.5 text-3xs text-ps-hint">
                                {BLOCKED_CREDIT_REASONS.find((r) => r.code === line.blocked_credit_reason)!.note}
                              </p>
                            )}
                          </>
                        )}
                      </td>
                      <td className="py-1.5 px-1">
                        <HsnLookup clientId={clientId} value={line.hsn_sac} onChange={(v) => setLine(idx, { hsn_sac: v })}
                          onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate: p.gst_rate_bps / 100 }); }}
                          size="sm" chrome="plain" placeholder="Set HSN/SAC" ariaLabel="HSN or SAC code" />
                      </td>
                      <td className="py-1.5 px-1">
                        <AccountLookup accounts={accounts} value={line.expense_account_id} onChange={(id) => setLine(idx, { expense_account_id: id })} size="sm" placeholder="— Account —" ariaLabel="Expense account" />
                        {/* ai-23. A PROPOSAL from this supplier's earlier bills,
                            with its evidence, shown only while the account is
                            blank. The field is NOT filled in: a click is what
                            sets it, so an account never arrives looking like the
                            CA's own decision. */}
                        {(() => {
                          const s = chipsForLine(history, line).expense_account;
                          const patch = s ? accountPatch(s) : null;
                          if (!s || !patch) return null;
                          return (
                            <div className="mt-1 text-3xs text-ps-hint" data-testid={`history-account-${idx}`}>
                              <button type="button" disabled={isLocked}
                                onClick={() => setLine(idx, patch)}
                                className="px-1.5 py-0.5 rounded-full bg-ps-muted border border-ps-border text-ps-body hover:bg-white disabled:opacity-40">
                                Use {s.label ?? "this account"}
                              </button>
                              <span className="ml-1">{s.sentence}</span>
                            </div>
                          );
                        })()}
                      </td>
                      <td className="py-1.5 px-1">
                        <input data-cell="qty" type="number" min="0" step="0.001" value={line.qty} onChange={(e) => setLine(idx, { qty: e.target.value })} aria-label={`Line ${idx + 1} quantity`}
                          placeholder={unreadOn(line, "quantity") ? "?" : undefined}
                          title={unreadOn(line, "quantity") ? NOT_STATED_TITLE : undefined}
                          className={`w-full px-2 py-1 border rounded focus:outline-none focus:ring-1 focus:ring-brand text-right text-xs ${unreadOn(line, "quantity") ? UNREAD_CLASS : "border-ps-border"}`} />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={unreadOn(line, "unit") ? "" : (line.unit || "NOS")} onChange={(e) => setLine(idx, { unit: e.target.value })} aria-label={`Line ${idx + 1} unit`}
                          title={unreadOn(line, "unit")
                            ? (line.unitAsPrinted
                              ? `The document prints "${line.unitAsPrinted}", which is not one of the unit codes — choose the code. ${NOT_STATED_TITLE}`
                              : NOT_STATED_TITLE)
                            : undefined}
                          className={`w-full px-1 py-1 border rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand text-xs ${unreadOn(line, "unit") ? UNREAD_CLASS : "border-ps-border"}`}>
                          {unreadOn(line, "unit") && <option value="">— unit? —</option>}
                          {UQC_CODES.map((u) => <option key={u.code} value={u.code}>{u.code}</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-1">
                        <input data-cell="rate" type="number" min="0" step="0.01" value={line.rate} onChange={(e) => setLine(idx, { rate: e.target.value })} placeholder={unreadOn(line, "rate") ? "?" : "0.00"} aria-label={`Line ${idx + 1} rate`}
                          title={unreadOn(line, "rate") ? NOT_STATED_TITLE : undefined}
                          className={`w-full px-2 py-1 border rounded focus:outline-none focus:ring-1 focus:ring-brand text-right text-xs ${unreadOn(line, "rate") ? UNREAD_CLASS : "border-ps-border"}`} />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={unreadOn(line, "gst_rate") ? "" : line.gst_rate} onChange={(e) => setLine(idx, { gst_rate: parseFloat(e.target.value) })} aria-label={`Line ${idx + 1} GST rate`}
                          title={unreadOn(line, "gst_rate") ? NOT_STATED_TITLE : undefined}
                          className={`w-full px-1 py-1 border rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand text-xs ${unreadOn(line, "gst_rate") ? UNREAD_CLASS : "border-ps-border"}`}>
                          {unreadOn(line, "gst_rate") && <option value="">— rate? —</option>}
                          {gstRateOptions(line.gst_rate).map((r) => <option key={r} value={r}>{r}%</option>)}
                        </select>
                      </td>
                      {showCess && (
                        <>
                          <td className="py-1.5 px-1">
                            <input data-cell="cessPercent" type="number" min="0" step="0.01"
                              value={line.cessPercent ?? ""}
                              onChange={(e) => setLine(idx, { cessPercent: e.target.value })}
                              placeholder="0" aria-label={`Line ${idx + 1} compensation cess percent`}
                              className="w-full px-2 py-1 border border-ps-border rounded focus:outline-none focus:ring-1 focus:ring-brand text-right text-xs" />
                          </td>
                          <td className="py-1.5 px-1">
                            <input data-cell="cessPerUnit" type="number" min="0" step="0.01"
                              value={line.cessPerUnit ?? ""}
                              onChange={(e) => setLine(idx, { cessPerUnit: e.target.value })}
                              placeholder="0.00" aria-label={`Line ${idx + 1} compensation cess per unit`}
                              className="w-full px-2 py-1 border border-ps-border rounded focus:outline-none focus:ring-1 focus:ring-brand text-right text-xs" />
                          </td>
                        </>
                      )}
                      <td className="py-1.5 px-2 text-right font-mono text-ps-body">{g.grand_total_paise > 0 ? fmtAmt(g.grand_total_paise) : "—"}</td>
                      <td className="py-1.5">
                        {lines.length > 1 && (
                          <button onClick={() => removeLine(idx)} className="text-ps-disabled hover:text-state-problem" aria-label="Remove line">
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
          {lines.some((l) => l.unread?.length) && (
            <p className="mt-2 text-3xs text-state-attention">
              Amber, empty fields were not stated on the document and have been left for you
              rather than guessed — a quantity, rate or GST rate must be entered before the bill
              can be saved. A unit left blank is saved as NOS.
            </p>
          )}
          {fieldErr(validation.errors.unread)}
          {fieldErr(validation.errors.lines)}
          {fieldErr(validation.errors.itc)}
        </section>

        {!nearDupes && dupeAhead.length > 0 && (
          <div className="text-xs bg-state-attention-surface border border-state-attention-border rounded-lg px-3 py-2.5 space-y-1.5">
            <p className="font-semibold text-state-attention">
              This vendor already has {dupeAhead.length === 1 ? "a bill" : "bills"} that may be the
              same invoice.
            </p>
            <ul className="space-y-1.5">
              {dupeAhead.map(d => (
                <li key={d.bill_id} className="text-state-attention/90">
                  <span className="font-medium">
                    {d.bill_no || "(no number)"}
                    {d.bill_date ? ` · ${d.bill_date}` : ""} · {formatPaise(d.total_paise)}
                  </span>
                  <br />
                  {d.detail}
                </li>
              ))}
            </ul>
            <p className="text-state-attention/70">Nothing is blocked — save anyway if this is a separate bill.</p>
          </div>
        )}
        {nearDupes && (
          <div className="text-xs bg-state-attention-surface border border-state-attention-border rounded-lg px-3 py-2.5 space-y-2">
            <p className="font-semibold text-state-attention">
              Saved — but this vendor already has {nearDupes.length === 1 ? "a bill" : "bills"} that
              may be the same invoice.
            </p>
            <ul className="space-y-2">
              {nearDupes.map(d => (
                <li key={d.bill_id} className="text-state-attention/90">
                  <span className="font-medium">
                    {d.bill_no || "(no number)"}
                    {d.bill_date ? ` · ${d.bill_date}` : ""} · {formatPaise(d.total_paise)}
                  </span>
                  <br />
                  {d.detail}
                </li>
              ))}
            </ul>
            <p className="text-state-attention/70">
              Two bills from one supplier on one day are perfectly ordinary, so nothing has been
              blocked. If this is the same invoice twice, cancel one of them.
            </p>
            <button
              type="button"
              onClick={() => onDone(`${billNo.trim() || "Purchase bill"} saved as draft`)}
              className="rounded-md bg-state-attention px-3 py-1.5 text-2xs font-semibold text-white">
              I have checked — close
            </button>
          </div>
        )}
        {error && <Callout tone="problem">{error}</Callout>}
      </div>
    </InvoiceWorkspaceLayout>
  );
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className={`flex justify-between ${muted ? "text-ps-hint" : "text-ps-label"}`}>
      <span>{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
