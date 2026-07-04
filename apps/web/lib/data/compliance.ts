/**
 * Compliance data layer — thin wrapper over the canonical backend engine
 * (compliance_records / routers/compliance_ops.py). All due-date generation,
 * status-workflow validation, and assignment-scoping happen server-side;
 * this file only fetches and adapts the response shape.
 *
 * ComplianceEntry keeps the field names/vocabulary this data layer's five
 * consumer pages have always used (filing_status: pending/in_progress/
 * filed/overdue/na; arn_number; compliance_type as the granular obligation
 * type e.g. GSTR1/GSTR3B/TDS26Q) — genuinely equivalent to the canonical
 * 8-status workflow for these pages' purposes, since none of them ever
 * exposed the intermediate review-workflow states (Awaiting Documents/
 * In Progress/Ready For Review/Ready To File) as distinct concepts; they
 * only ever needed pending vs in-progress vs filed vs overdue.
 *
 * GSTR-1 due: 11th of following month (CGST Act Section 37)
 * GSTR-3B due: 20th of following month (CGST Act Section 39)
 * GSTR-9 due: 31st December (CGST Act Section 44)
 * TDS return: 31st of month following quarter end
 * Advance tax: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
 */
import { api } from "@/lib/api";
import type { ApiResp } from "@/lib/api";

export interface ComplianceEntry {
  id: string;
  client_id: string;
  compliance_type: string;
  period_start: string;
  period_end: string;
  due_date: string;
  filing_status: string;
  filed_date?: string;
  arn_number?: string;
  notes?: string;
  risk_score?: number;
}

interface RawObligation {
  id: string;
  client_id: string;
  compliance_type: string;
  obligation_type?: string | null;
  period_start: string;
  period_end: string;
  due_date: string;
  status: string;
  filed_date?: string | null;
  acknowledgement_no?: string | null;
  notes?: string | null;
  risk_score?: number;
}

const STATUS_TO_FILING_STATUS: Record<string, string> = {
  "Not Started": "pending",
  "Awaiting Documents": "pending",
  "In Progress": "in_progress",
  "Ready For Review": "in_progress",
  "Ready To File": "in_progress",
  "Filed": "filed",
  "Completed": "filed",
  "Overdue": "overdue",
};

function toEntry(raw: RawObligation): ComplianceEntry {
  return {
    id: raw.id,
    client_id: raw.client_id,
    compliance_type: raw.obligation_type || raw.compliance_type,
    period_start: raw.period_start,
    period_end: raw.period_end,
    due_date: raw.due_date,
    filing_status: STATUS_TO_FILING_STATUS[raw.status] ?? "pending",
    filed_date: raw.filed_date ?? undefined,
    arn_number: raw.acknowledgement_no ?? undefined,
    notes: raw.notes ?? undefined,
    risk_score: raw.risk_score,
  };
}

/** Fetches compliance obligations (assignment-scoped server-side), optionally
 * for one client. */
export async function getComplianceCalendar(clientId?: string): Promise<ComplianceEntry[]> {
  const params: Record<string, string> = {};
  if (clientId) params.client_id = clientId;
  const res = (await api.complianceOps.obligations(params)) as ApiResp<{ obligations: RawObligation[]; total: number }>;
  return (res.data?.obligations ?? []).map(toEntry);
}

/** Generates the client's statutory obligations for the current FY
 * (idempotent — safe to call every time the calendar is empty). Server-side
 * equivalent of the old client-side GST-deadline generator; also covers
 * ITR/TDS/MCA when the client has an active service engagement for them. */
export async function seedComplianceCalendar(clientId: string): Promise<void> {
  await api.complianceOps.generate({ client_id: clientId });
}

/** Marks an obligation filed, walking the canonical workflow's remaining
 * steps server-side. Optionally records an ARN/acknowledgement number. */
export async function markFiled(id: string, arnNumber?: string): Promise<void> {
  await api.complianceOps.markFiled(id, arnNumber);
}
