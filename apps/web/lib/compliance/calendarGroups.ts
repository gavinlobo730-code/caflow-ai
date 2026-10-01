/**
 * How the obligation calendar groups what the server sent (practice_management-17).
 *
 * THE SERVER ALREADY DECIDED EVERY DATE. `GET /api/compliance/obligations/calendar`
 * returns `compliance_records` whose `due_date` was computed by
 * `services/compliance_engine` — the 22nd or 24th for a QRMP client's GSTR-3B, the
 * state-group rule, a filed return — and this module changes none of it. It only
 * folds a hundred rows that fall on one day into the rows a person can read: ONE
 * chip per (due date, obligation, period), carrying how many clients it covers and
 * how many of them are done, with the clients one click away.
 *
 * WHAT IT DOES NOT DO. It states no due date, derives none and moves none: a group
 * lands on the day its rows' own `due_date` says. It names an obligation by the
 * `period_label` the engine wrote ("GSTR-3B Jun 2026") and keeps no table of
 * labels. The colour category is a presentation hint read off the obligation-type
 * string with the same prefix rule `/deadlines` filters by.
 *
 * THE OLD CALENDAR attached every deadline to ALL clients, built them in the
 * browser, and kept its done tick in component state: gone on refresh, and never
 * recorded anywhere. A tick here is a `markFiled` call, so it persists, locks the
 * period where the server says it does, and survives a reload.
 */
import type { ComplianceEntry } from "../data/compliance.ts";
import { isOverdue } from "./overdue.ts";

export type CalendarCategory = "GST" | "IncomeTax" | "TDS" | "MCA" | "Payroll" | "Other";

/** A presentation hint (a colour), read off the stored obligation type. */
export function categoryOf(complianceType: string): CalendarCategory {
  const t = (complianceType ?? "").toUpperCase();
  if (t.startsWith("MCA")) return "MCA";
  // The three monthly payroll DEPOSITS end this way and nothing else does. Asked
  // before TDS because TDS_SALARY_DEPOSIT is the one that would otherwise match it.
  if (t.endsWith("_DEPOSIT")) return "Payroll";
  if (t.startsWith("TDS") || t === "TCS_RETURN") return "TDS";
  if (t.startsWith("GSTR") || t.startsWith("GST") || t === "PMT06") return "GST";
  if (t.startsWith("ITR") || t === "ADVANCE_TAX" || t === "TAX_AUDIT") return "IncomeTax";
  return "Other";
}

/** A row that is not a `compliance_records` row: a form counted from a company's own
 *  AGM date by the MCA workspace, which has nothing to tick. */
export interface ExternalItem {
  client_id: string;
  company_name: string;
  description: string;
}

export interface ObligationGroup {
  key: string;
  due_date: string;
  compliance_type: string;
  label: string;
  category: CalendarCategory;
  entries: ComplianceEntry[];
  external: ExternalItem[];
  /** Everything the group covers: the clients with a record, or the companies. */
  total: number;
  filed: number;
  /** "Not applicable" is a decision, so it owes nothing and is not "still to do". */
  not_applicable: number;
  overdue: number;
  /** Still to do: neither filed nor marked not applicable. */
  open: number;
}

function groupKey(e: Pick<ComplianceEntry, "due_date" | "compliance_type" | "period_label">): string {
  return `${(e.due_date ?? "").slice(0, 10)}|${e.compliance_type}|${e.period_label ?? ""}`;
}

/** One group per (due date, obligation, period). A row sent twice — it can be in
 *  the window AND in the overdue bucket — is counted once. */
export function groupObligations(
  entries: readonly ComplianceEntry[],
  todayISO: string,
  external: readonly (ExternalItem & { due_date: string; label: string })[] = [],
): ObligationGroup[] {
  const seen = new Set<string>();
  const groups = new Map<string, ObligationGroup>();

  for (const e of entries) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    const key = groupKey(e);
    let g = groups.get(key);
    if (!g) {
      g = {
        key, due_date: (e.due_date ?? "").slice(0, 10), compliance_type: e.compliance_type,
        label: e.period_label || e.compliance_type, category: categoryOf(e.compliance_type),
        entries: [], external: [], total: 0, filed: 0, not_applicable: 0, overdue: 0, open: 0,
      };
      groups.set(key, g);
    }
    g.entries.push(e);
    g.total += 1;
    if (e.filing_status === "filed") g.filed += 1;
    else if (e.filing_status === "na") g.not_applicable += 1;
    else g.open += 1;
    if (isOverdue(e, todayISO)) g.overdue += 1;
  }

  for (const x of external) {
    const key = `${x.due_date}|MCA|${x.label}`;
    let g = groups.get(key);
    if (!g) {
      g = {
        key, due_date: x.due_date, compliance_type: "MCA", label: x.label, category: "MCA",
        entries: [], external: [], total: 0, filed: 0, not_applicable: 0, overdue: 0, open: 0,
      };
      groups.set(key, g);
    }
    g.external.push({ client_id: x.client_id, company_name: x.company_name, description: x.description });
    g.total += 1;
    g.open += 1;
    if (x.due_date < todayISO) g.overdue += 1;
  }

  return Array.from(groups.values()).sort((a, b) =>
    a.due_date.localeCompare(b.due_date) || a.label.localeCompare(b.label));
}

export function groupsOnDay(groups: readonly ObligationGroup[], iso: string): ObligationGroup[] {
  return groups.filter((g) => g.due_date === iso);
}

/** The next `n` groups that still have something to do, due today or later. */
export function upcomingGroups(groups: readonly ObligationGroup[], todayISO: string, n = 10): ObligationGroup[] {
  return groups.filter((g) => g.open > 0 && g.due_date >= todayISO).slice(0, n);
}

/** Groups with at least one overdue row, earliest first. */
export function overdueGroups(groups: readonly ObligationGroup[]): ObligationGroup[] {
  return groups.filter((g) => g.overdue > 0);
}
