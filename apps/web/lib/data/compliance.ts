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
import { getSupabaseClient } from "@/lib/supabase/client";

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

/**
 * Direct-Supabase variant of getComplianceCalendar, for the internal-staff
 * client workspace ONLY (apps/web/app/clients/[id]/compliance/page.tsx).
 *
 * list_obligations (routers/compliance_ops.py) does a plain
 * compliance_record_service.list_records() (.eq(firm_id).eq(client_id), see
 * repositories/compliance_records_repository.py) and then applies
 * core.authz.filter_by_client() — assignment scope: Partner sees the whole
 * firm, every other role only sees clients present in their own
 * user_client_assignments rows (Module 9.0 / M2, M5).
 *
 * Migration 084_assignment_scoped_rls.sql puts the identical check
 * (public.can_access_client(), keyed off the same user_client_assignments
 * table, same Partner-is-firm-wide exception) directly on compliance_records
 * as a RESTRICTIVE policy — it ANDs with the firm-isolation policy from
 * 005_supabase_auth_rls.sql and the internal-client guardrail from
 * 074_internal_client_rls_guardrails.sql, so a browser session authenticated
 * via getSupabaseClient() (anon key + user JWT, real RLS enforcement — unlike
 * the backend's service-role key) gets a result set that is a subset-or-equal
 * of what filter_by_client() would return, never a superset. Verified safe to
 * read directly for that reason.
 *
 * NOT wired into getComplianceCalendar() itself: that function is also called
 * from app/deadlines/page.tsx, app/reports/page.tsx,
 * app/clients/[id]/overview/page.tsx, and app/client-portal/page.tsx. The
 * portal page authenticates portal users through a separate identity table
 * (client_portal_users, hardened in 163_harden_client_portal_users_rls.sql)
 * whose relationship to user_client_assignments/RLS has not been verified —
 * changing the shared function would silently change what a portal client
 * can read, which is outside what this conversion checked. Also note
 * risk_score is computed in Python (_compute_risk_score in
 * domain/compliance_record_service.py), not a stored column, so it comes
 * back undefined here; the compliance page doesn't render it.
 */
export async function getComplianceCalendarDirect(clientId: string): Promise<ComplianceEntry[]> {
  const { data, error } = await getSupabaseClient()
    .from("compliance_records")
    .select(
      "id, client_id, compliance_type, obligation_type, period_start, period_end, due_date, status, filed_date, acknowledgement_no, notes"
    )
    .eq("client_id", clientId)
    .is("deleted_at", null)
    .order("due_date");
  // Throws (rather than swallowing to []) so the caller can distinguish a
  // genuinely empty calendar from a failed fetch — the only call site
  // (clients/[id]/compliance/page.tsx) is responsible for surfacing this.
  if (error) throw error;
  return ((data ?? []) as RawObligation[]).map(toEntry);
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
