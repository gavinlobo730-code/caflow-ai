/**
 * What a half-typed purchase bill keeps in the tab, and how it comes back
 * (frontend_ux-23). Pure — no React, no storage — so the rules run under plain
 * `node --test`; `lib/drafts/unsentDraft.ts` stores it and
 * `components/purchases/PurchaseBillEditor.tsx` offers it.
 *
 * RAW FIELDS ONLY, the journal draft's rule applied to a bill. Kept: the header
 * fields as typed, and per line the description, HSN/SAC, quantity and rate
 * AS TYPED (strings), the GST rate and unit chosen, the account and catalogue id
 * picked, the CGST §17(5) decision (`itc_eligible` and its reason) and the two
 * cess boxes. Not kept: the totals, the TDS figure, the supply split, the
 * vendor-history chips, the near-duplicate answer, the catalogue ROW a line was
 * linked to (the id is kept and the row is looked up again), and the stored
 * path of an uploaded invoice — that is something the server handed back and
 * the save would carry it straight into the bill, so a draft edited by hand must
 * not be able to point a bill at somebody else's file. Everything that matters
 * to money is recomputed by the server from what the save sends.
 *
 * THE AI-01 FLAGS TRAVEL WITH THE LINE. A line read off an invoice that did not
 * state its GST rate carries `unread: ["gst_rate"]` and a placeholder 0, and the
 * flag — not the 0 — is what stops the line being saved at a rate nobody chose.
 * A restore that dropped the flag would turn that placeholder into a rate the
 * CA appears to have confirmed, which is the defect AI-01 closed. So the flag is
 * kept, checked against `UNREAD_FIELDS` itself, and a flag it does not recognise
 * discards the whole draft.
 */
import { readField } from "../drafts/unsentDraft.ts";
import { UNREAD_FIELDS, type UnreadField } from "./extractedLine.ts";
import type { PurchaseBillLine } from "./billEditor.ts";

export interface BillDraftLine {
  description: string;
  hsn_sac: string;
  qty: string;
  rate: string;
  gst_rate: number;
  unit: string;
  expense_account_id: string;
  service_catalogue_id: string;
  /** Absent means eligible — migration 240's own default, which `lineIsItcEligible` reads. */
  itc_eligible?: boolean;
  blocked_credit_reason?: string;
  cessPercent?: string;
  cessPerUnit?: string;
  unread?: UnreadField[];
  unitAsPrinted?: string;
}

export interface BillDraftFields {
  vendorId: string;
  billNo: string;
  ourReference: string;
  form15caAckNo: string;
  form15caFiledOn: string;
  form15cbUdin: string;
  notes: string;
  billDate: string;
  dueDate: string;
  isReverseCharge: boolean;
  currency: string;
  exchangeRate: string;
  /** Only THAT an invoice file was attached, never where it is stored. It lets
   *  the restore say the file is not part of a draft; see `withoutDocument`. */
  documentAttached: boolean;
  lines: BillDraftLine[];
}

/** A bill with more lines than this is not one being typed by hand. */
export const MAX_DRAFT_BILL_LINES = 200;

// ─── the editor's line <-> the draft's line ─────────────────────────────────

/** The raw fields of an editor line, and nothing else — `_k`, `product` and
 *  `hsnMatches` do not leave this function. An optional field that is absent
 *  stays absent, so a draft and the form it came from compare equal. */
export function draftLineOf(l: PurchaseBillLine): BillDraftLine {
  return {
    description: l.description,
    hsn_sac: l.hsn_sac,
    qty: l.qty,
    rate: l.rate,
    gst_rate: l.gst_rate,
    unit: l.unit,
    expense_account_id: l.expense_account_id,
    service_catalogue_id: l.service_catalogue_id,
    ...(l.itc_eligible === undefined ? {} : { itc_eligible: l.itc_eligible }),
    ...(l.blocked_credit_reason ? { blocked_credit_reason: l.blocked_credit_reason } : {}),
    ...(l.cessPercent ? { cessPercent: l.cessPercent } : {}),
    ...(l.cessPerUnit ? { cessPerUnit: l.cessPerUnit } : {}),
    ...(l.unread?.length ? { unread: [...l.unread] } : {}),
    ...(l.unitAsPrinted ? { unitAsPrinted: l.unitAsPrinted } : {}),
  };
}

/** The editor line a draft line becomes. The caller adds its own `_k`. */
export function editorLineOf(d: BillDraftLine): PurchaseBillLine {
  return { ...d, ...(d.unread ? { unread: [...d.unread] } : {}) };
}

// ─── reading one back ───────────────────────────────────────────────────────

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** A date input's value: empty, or a calendar-shaped ISO date. */
function dateOrEmpty(raw: unknown): string | undefined {
  const s = readField.string(raw, 10);
  if (s === undefined) return undefined;
  return s === "" || ISO_DATE.test(s) ? s : undefined;
}

/** `undefined` — the key is absent, which is fine; `null` — it is present and
 *  wrong, which is not. */
function optionalString(raw: unknown, max: number): string | undefined | null {
  if (raw === undefined) return undefined;
  const s = readField.string(raw, max);
  return s === undefined ? null : s;
}

function unreadOf(raw: unknown): UnreadField[] | undefined | null {
  if (raw === undefined) return undefined;
  const list = readField.list(raw, UNREAD_FIELDS.length);
  if (!list) return null;
  const out: UnreadField[] = [];
  for (const f of list) {
    if (typeof f !== "string" || !(UNREAD_FIELDS as readonly string[]).includes(f)) return null;
    if (!out.includes(f as UnreadField)) out.push(f as UnreadField);
  }
  return out.length ? out : undefined;
}

function lineOf(raw: unknown): BillDraftLine | null {
  const r = readField.record(raw);
  if (!r) return null;
  const description = readField.string(r.description, 2_000);
  const hsn_sac = readField.string(r.hsn_sac, 30);
  const qty = readField.string(r.qty, 40);
  const rate = readField.string(r.rate, 40);
  const unit = readField.string(r.unit, 20);
  const expense_account_id = readField.string(r.expense_account_id, 100);
  const service_catalogue_id = readField.string(r.service_catalogue_id, 100);
  const gst_rate = readField.finiteNumber(r.gst_rate);
  if (description === undefined || hsn_sac === undefined || qty === undefined ||
      rate === undefined || unit === undefined || expense_account_id === undefined ||
      service_catalogue_id === undefined || gst_rate === undefined ||
      gst_rate < 0 || gst_rate > 100) return null;

  const blocked = optionalString(r.blocked_credit_reason, 500);
  const cessPercent = optionalString(r.cessPercent, 40);
  const cessPerUnit = optionalString(r.cessPerUnit, 40);
  const unitAsPrinted = optionalString(r.unitAsPrinted, 40);
  const unread = unreadOf(r.unread);
  const itc = r.itc_eligible === undefined ? undefined : readField.boolean(r.itc_eligible);
  if (blocked === null || cessPercent === null || cessPerUnit === null ||
      unitAsPrinted === null || unread === null ||
      (r.itc_eligible !== undefined && itc === undefined)) return null;

  return {
    description, hsn_sac, qty, rate, gst_rate, unit, expense_account_id, service_catalogue_id,
    ...(itc === undefined ? {} : { itc_eligible: itc }),
    ...(blocked ? { blocked_credit_reason: blocked } : {}),
    ...(cessPercent ? { cessPercent } : {}),
    ...(cessPerUnit ? { cessPerUnit } : {}),
    ...(unread ? { unread } : {}),
    ...(unitAsPrinted ? { unitAsPrinted } : {}),
  };
}

/** Rebuild a draft from whatever JSON came back, or `null`. One bad line
 *  discards the whole draft rather than quietly dropping a line of the bill: a
 *  bill restored with a line missing is one the CA might save without noticing,
 *  and the total they check it against would simply be smaller. */
export function validateBillDraft(raw: unknown): BillDraftFields | null {
  const r = readField.record(raw);
  if (!r) return null;
  const vendorId = readField.string(r.vendorId, 100);
  const billNo = readField.string(r.billNo, 200);
  const ourReference = readField.string(r.ourReference, 200);
  const form15caAckNo = readField.string(r.form15caAckNo, 200);
  const form15caFiledOn = dateOrEmpty(r.form15caFiledOn);
  const form15cbUdin = readField.string(r.form15cbUdin, 200);
  const notes = readField.string(r.notes, 4_000);
  const billDate = dateOrEmpty(r.billDate);
  const dueDate = dateOrEmpty(r.dueDate);
  const isReverseCharge = readField.boolean(r.isReverseCharge);
  const currency = readField.string(r.currency, 8);
  const exchangeRate = readField.string(r.exchangeRate, 40);
  const documentAttached = readField.boolean(r.documentAttached);
  const rawLines = readField.list(r.lines, MAX_DRAFT_BILL_LINES);
  if (vendorId === undefined || billNo === undefined || ourReference === undefined ||
      form15caAckNo === undefined || form15caFiledOn === undefined ||
      form15cbUdin === undefined || notes === undefined || billDate === undefined ||
      dueDate === undefined || isReverseCharge === undefined || currency === undefined ||
      exchangeRate === undefined || documentAttached === undefined || !rawLines) return null;

  const lines: BillDraftLine[] = [];
  for (const l of rawLines) {
    const line = lineOf(l);
    if (!line) return null;
    lines.push(line);
  }
  return {
    vendorId, billNo, ourReference, form15caAckNo, form15caFiledOn, form15cbUdin, notes,
    billDate, dueDate, isReverseCharge, currency, exchangeRate, documentAttached, lines,
  };
}

// ─── what "typed into" means ────────────────────────────────────────────────

/** The fields as the person typed them, with the one fact that is not typing
 *  taken out. Attaching an invoice file to a bill with nothing else on it is not
 *  work worth keeping, and counting it would offer back an empty bill. Both
 *  sides of the comparison go through this. */
export function withoutDocument(f: BillDraftFields): BillDraftFields {
  return { ...f, documentAttached: false };
}

// ─── applying one ───────────────────────────────────────────────────────────

export interface BillDraftContext {
  /** An existing draft bill is being edited: its supplier, currency, exchange
   *  rate and reverse-charge flag were frozen at creation (`PurchaseBillUpdateIn`
   *  has none of them, and the editor shows each read-only), so a restore may
   *  not change them. */
  isEdit: boolean;
  current: { vendorId: string; currency: string; exchangeRate: string; isReverseCharge: boolean };
  /** The suppliers a bill can be raised against NOW. */
  vendorIds: ReadonlySet<string>;
  /** This client's chart NOW. */
  accountIds: ReadonlySet<string>;
  /** The foreign currencies the bill's picker offers NOW — empty while
   *  multi-currency is off for the client or the list has not loaded. */
  currencyCodes: ReadonlySet<string>;
}

export interface AppliedBillDraft {
  fields: BillDraftFields;
  /** The supplier in the draft is no longer one this bill can name. */
  vendorDropped: boolean;
  /** Lines whose account is no longer in this client's chart. */
  accountsDropped: number;
  /** The draft was in a foreign currency the picker no longer offers. */
  currencyDropped: boolean;
  /** The catalogue ids the lines carry, for the caller's ONE lookup. */
  catalogueIds: string[];
}

/** What a restore puts into the form, checked against what this client holds
 *  NOW. A supplier or an account that has since been deactivated or deleted is
 *  not left selected — a picker would show it blank while the state still
 *  carried the id, and the server would refuse the save over an id the CA
 *  cannot see. The line stays, with its amounts, and the CA picks again. */
export function applyBillDraft(draft: BillDraftFields, ctx: BillDraftContext): AppliedBillDraft {
  let accountsDropped = 0;
  const lines = draft.lines.map((l) => {
    if (l.expense_account_id && !ctx.accountIds.has(l.expense_account_id)) {
      accountsDropped++;
      return { ...l, expense_account_id: "" };
    }
    return l;
  });
  const vendorDropped = !ctx.isEdit && !!draft.vendorId && !ctx.vendorIds.has(draft.vendorId);
  // A foreign currency the picker does not offer would be a bill in a currency
  // with no control to see or change it, so it falls back to INR with its rate.
  const currencyDropped = !ctx.isEdit && !!draft.currency && !ctx.currencyCodes.has(draft.currency);
  const catalogueIds = Array.from(new Set(
    lines.map((l) => l.service_catalogue_id).filter((id) => !!id)));
  return {
    fields: {
      ...draft,
      vendorId: ctx.isEdit ? ctx.current.vendorId : (vendorDropped ? "" : draft.vendorId),
      currency: ctx.isEdit ? ctx.current.currency : (currencyDropped ? "" : draft.currency),
      exchangeRate: ctx.isEdit ? ctx.current.exchangeRate : (currencyDropped ? "" : draft.exchangeRate),
      isReverseCharge: ctx.isEdit ? ctx.current.isReverseCharge : draft.isReverseCharge,
      lines,
    },
    vendorDropped,
    accountsDropped,
    currencyDropped,
    catalogueIds,
  };
}

/** After the one catalogue lookup. A line whose catalogue row came back gets it
 *  (the picker shows its name); one whose row did NOT — deleted since, or
 *  another client's id — loses the link, because a line cannot be saved without
 *  one and "linked to something you cannot see" is worse than "pick one". Call
 *  it only when the lookup SUCCEEDED: a failed lookup says nothing about any
 *  id, and the caller leaves the lines as they are. */
export function linkCatalogue<P extends { id: string }, L extends { service_catalogue_id: string; product?: P | null }>(
  lines: L[], found: ReadonlyMap<string, P>,
): { lines: L[]; missing: number } {
  let missing = 0;
  const out = lines.map((l) => {
    if (!l.service_catalogue_id) return l;
    const hit = found.get(l.service_catalogue_id);
    if (hit) return { ...l, product: hit };
    missing++;
    return { ...l, service_catalogue_id: "", product: null };
  });
  return { lines: out, missing };
}

/** The sentence under the banner after a restore, or null when nothing needs
 *  saying. Each thing the draft cannot carry is named, because a restore that
 *  quietly differs from what was typed is the one the CA does not recheck. */
export function billRestoreNote(a: AppliedBillDraft, o: {
  catalogueMissing: number; documentAttached: boolean;
}): string | null {
  const notes: string[] = [];
  if (a.vendorDropped) notes.push("The supplier in the draft can no longer be used — pick one again.");
  if (a.currencyDropped) {
    notes.push("The draft was in a foreign currency that is not available on this bill now, so it is back in INR — choose the currency and rate again.");
  }
  if (a.accountsDropped > 0) {
    notes.push(`${a.accountsDropped} account${a.accountsDropped === 1 ? "" : "s"} in the draft ${a.accountsDropped === 1 ? "is" : "are"} no longer in this client's chart — pick ${a.accountsDropped === 1 ? "it" : "them"} again.`);
  }
  if (o.catalogueMissing > 0) {
    notes.push(`${o.catalogueMissing} line${o.catalogueMissing === 1 ? "" : "s"} lost ${o.catalogueMissing === 1 ? "its" : "their"} product or service because it is no longer in the catalogue — pick ${o.catalogueMissing === 1 ? "it" : "them"} again.`);
  }
  if (o.documentAttached) {
    notes.push("The invoice file you uploaded is not kept in a draft — upload it again to attach it to this bill.");
  }
  return notes.length ? notes.join(" ") : null;
}
