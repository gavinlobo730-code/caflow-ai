/**
 * What a supplier's earlier bills propose for the line being typed (ai-23).
 *
 * THE SERVER DECIDES, THE BROWSER CARRIES. `domain/purchases/bill_history`
 * learns the expense account, the §17(5) treatment and the TDS notice from this
 * supplier's received bills — and resolves, per HSN/SAC, whether the specific
 * code or the supplier as a whole answers — and `GET /api/purchase-bills/
 * vendor-history` serves the result with its evidence. This file holds the
 * shape of that answer, reads it defensively, and says which of the answers is
 * still worth showing beside a line the CA has or has not filled in. It decides
 * nothing about accounting.
 *
 * NOTHING HERE APPLIES ANYTHING. `accountPatch` and `itcPatch` BUILD the change a
 * click would make; the editor calls them only from an `onClick`, and a guard
 * (`vendorHistory.test.ts`) reads the editor's source to hold it to that. A
 * suggestion that filled itself in would be the automation the item refuses: an
 * account chosen on the strength of three earlier bills, on a fourth that is
 * different, and invisible because it arrived already looking like the CA's own
 * decision.
 *
 * A PAYLOAD THAT IS NOT THE EXPECTED SHAPE IS NO DATA (`lib/api/shape.ts`). The
 * parser answers null for anything that is not an object the server marked
 * `checked`, so a cold-starting backend, a refusal answered as HTTP 200 or a
 * redeploy window where the field does not exist yet shows no chip rather than
 * a crash — and a mock-mode answer (`checked: false`) shows none either, because
 * "nothing was looked at" is not "there is no history".
 *
 * Pure (no React, no browser), so it runs under `node --test`.
 */
import { arrayOrEmpty, objectOrNull } from "../api/shape.ts";

export interface HistoryOption {
  value: string | boolean;
  label: string | null;
  times: number;
  last_seen: string | null;
}

export interface HistorySuggestion {
  value: string | boolean;
  label: string | null;
  times_seen: number;
  total_seen: number;
  share_bps: number;
  last_seen: string | null;
  basis: "hsn" | "supplier";
  scope: string;
  /** ITC only: the §17(5) clause the winning lines carried, or null. */
  reason: string | null;
  /** The server's own sentence: "Coded this way 3 of 3 times, for HSN/SAC 9972". */
  sentence: string;
  alternatives: HistoryOption[];
}

export interface LineSuggestions {
  expense_account: HistorySuggestion | null;
  itc: HistorySuggestion | null;
}

export interface TdsNotice {
  section: string;
  supplier_record_section: string | null;
  sentence: string;
}

export interface VendorHistory {
  vendor: LineSuggestions;
  byHsn: Record<string, LineSuggestions>;
  tds: TdsNotice | null;
  billsConsidered: number;
  gaps: string[];
}

const NONE: LineSuggestions = { expense_account: null, itc: null };

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function parseOption(raw: unknown): HistoryOption | null {
  const o = objectOrNull<Record<string, unknown>>(raw);
  if (!o) return null;
  const value = typeof o.value === "string" || typeof o.value === "boolean" ? o.value : null;
  const times = num(o.times);
  if (value === null || times === null) return null;
  return { value, label: str(o.label), times, last_seen: str(o.last_seen) };
}

function parseSuggestion(raw: unknown): HistorySuggestion | null {
  const o = objectOrNull<Record<string, unknown>>(raw);
  if (!o) return null;
  const value = typeof o.value === "string" || typeof o.value === "boolean" ? o.value : null;
  const timesSeen = num(o.times_seen);
  const totalSeen = num(o.total_seen);
  const sentence = str(o.sentence);
  // A suggestion that cannot say how often it happened is not evidence, and
  // evidence is the whole of what makes one worth showing.
  if (value === null || timesSeen === null || totalSeen === null || sentence === null) return null;
  return {
    value,
    label: str(o.label),
    times_seen: timesSeen,
    total_seen: totalSeen,
    share_bps: num(o.share_bps) ?? 0,
    last_seen: str(o.last_seen),
    basis: o.basis === "hsn" ? "hsn" : "supplier",
    scope: typeof o.scope === "string" ? o.scope : "",
    reason: str(o.reason),
    sentence,
    alternatives: arrayOrEmpty<unknown>(o.alternatives)
      .map(parseOption)
      .filter((a): a is HistoryOption => a !== null),
  };
}

function parseLine(raw: unknown): LineSuggestions {
  const o = objectOrNull<Record<string, unknown>>(raw);
  if (!o) return NONE;
  return { expense_account: parseSuggestion(o.expense_account), itc: parseSuggestion(o.itc) };
}

/** The served answer, or null when it is not one worth showing. Takes `unknown`
 *  because it IS the narrowing boundary. */
export function parseVendorHistory(data: unknown): VendorHistory | null {
  const o = objectOrNull<Record<string, unknown>>(data);
  if (!o || o.checked !== true) return null;
  const byHsnRaw = objectOrNull<Record<string, unknown>>(o.by_hsn) ?? {};
  const byHsn: Record<string, LineSuggestions> = {};
  for (const [hsn, line] of Object.entries(byHsnRaw)) byHsn[hsn] = parseLine(line);
  const tds = objectOrNull<Record<string, unknown>>(o.tds);
  const section = str(tds?.section);
  const sentence = str(tds?.sentence);
  return {
    vendor: parseLine(o.vendor),
    byHsn,
    tds: tds && section && sentence
      ? { section, sentence, supplier_record_section: str(tds.supplier_record_section) }
      : null,
    billsConsidered: num(o.bills_considered) ?? 0,
    gaps: arrayOrEmpty<unknown>(o.gaps).filter((g): g is string => typeof g === "string"),
  };
}

/** The HSN/SAC codes worth asking about: distinct, trimmed, non-empty, sorted so
 *  the same bill always produces the same request. */
export function distinctHsns(lines: ReadonlyArray<{ hsn_sac: string }>): string[] {
  return Array.from(new Set(lines.map((l) => l.hsn_sac.trim()).filter(Boolean))).sort();
}

/** What the server resolved for a line: its HSN's own answer, or the supplier's
 *  for a line with no HSN. A code the server was not asked about gets NOTHING —
 *  the supplier's answer would be a guess standing in for evidence that was
 *  never looked up, and the request is re-sent when the codes change. */
export function suggestionsFor(history: VendorHistory | null, hsn: string): LineSuggestions {
  if (!history) return NONE;
  const key = hsn.trim();
  if (!key) return history.vendor;
  return history.byHsn[key] ?? NONE;
}

/** What is still worth putting beside a line.
 *
 *  The account chip shows only where the account is BLANK: once the CA has
 *  chosen, the choice stands and a chip repeating or contradicting it is a nag.
 *  The ITC chip shows only where the line is still marked eligible, which is
 *  the one state the suggestion would change. */
export function chipsForLine(
  history: VendorHistory | null,
  line: { hsn_sac: string; expense_account_id: string; itc_eligible?: boolean },
): LineSuggestions {
  const s = suggestionsFor(history, line.hsn_sac);
  return {
    expense_account:
      s.expense_account && typeof s.expense_account.value === "string"
      && !line.expense_account_id ? s.expense_account : null,
    itc: s.itc && s.itc.value === false && line.itc_eligible !== false ? s.itc : null,
  };
}

/** The change a click on the account chip makes. Never called except from one. */
export function accountPatch(s: HistorySuggestion): { expense_account_id: string } | null {
  return typeof s.value === "string" ? { expense_account_id: s.value } : null;
}

/** The change a click on the ITC chip makes. The clause is the one the earlier
 *  lines carried, or blank — and a blank one leaves the §17(5) clause select
 *  flagged, exactly as ticking the box by hand does, so a clause nobody
 *  recorded is never invented. */
export function itcPatch(s: HistorySuggestion): { itc_eligible: false; blocked_credit_reason: string } {
  return { itc_eligible: false, blocked_credit_reason: s.reason ?? "" };
}
