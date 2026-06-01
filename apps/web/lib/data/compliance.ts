/**
 * Compliance Calendar data layer.
 * Auto-generates filing deadlines when a client is registered.
 * GSTR-1 due: 11th of following month (CGST Act Section 37)
 * GSTR-3B due: 20th of following month (CGST Act Section 39)
 * GSTR-9 due: 31st December (CGST Act Section 44)
 * TDS return: 31st of month following quarter end
 * Advance tax: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
 */
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
  task_id?: string;
  notes?: string;
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).single();
  if (!data) throw new Error("User not found");
  return data.firm_id;
}

/** Generate compliance deadlines for a financial year for a GST-registered client */
export function generateGSTDeadlines(clientId: string, firmId: string, financialYear: number) {
  // financialYear: 2025 means FY 2025-26 (Apr 2025 – Mar 2026)
  const entries: Omit<ComplianceEntry, "id">[] = [];

  for (let m = 0; m < 12; m++) {
    const periodYear = m < 9 ? financialYear : financialYear + 1; // Apr=0..Dec=8 in FY
    const actualMonth = (m + 3) % 12 + 1; // Apr=1 in calendar
    const actualYear = m < 9 ? financialYear : financialYear + 1;

    const periodStart = `${actualYear}-${String(actualMonth).padStart(2, "0")}-01`;
    const lastDay = new Date(actualYear, actualMonth, 0).getDate();
    const periodEnd = `${actualYear}-${String(actualMonth).padStart(2, "0")}-${lastDay}`;

    // Due month/year (following month) — CGST Act Section 37
    const dueMonth = actualMonth === 12 ? 1 : actualMonth + 1;
    const dueYear = actualMonth === 12 ? actualYear + 1 : actualYear;

    entries.push({
      firm_id: firmId,
      client_id: clientId,
      compliance_type: "GSTR1",
      period_start: periodStart,
      period_end: periodEnd,
      due_date: `${dueYear}-${String(dueMonth).padStart(2, "0")}-11`, // 11th
      filing_status: "pending",
    } as Omit<ComplianceEntry, "id"> & { firm_id: string });

    entries.push({
      firm_id: firmId,
      client_id: clientId,
      compliance_type: "GSTR3B",
      period_start: periodStart,
      period_end: periodEnd,
      due_date: `${dueYear}-${String(dueMonth).padStart(2, "0")}-20`, // 20th
      filing_status: "pending",
    } as Omit<ComplianceEntry, "id"> & { firm_id: string });

    void periodYear; // used implicitly
  }

  // GSTR-9 annual — CGST Act Section 44
  entries.push({
    firm_id: firmId,
    client_id: clientId,
    compliance_type: "GSTR9",
    period_start: `${financialYear}-04-01`,
    period_end: `${financialYear + 1}-03-31`,
    due_date: `${financialYear + 1}-12-31`,
    filing_status: "pending",
  } as Omit<ComplianceEntry, "id"> & { firm_id: string });

  return entries;
}

export async function seedComplianceCalendar(clientId: string): Promise<void> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  const currentYear = new Date().getFullYear();
  const currentMonth = new Date().getMonth() + 1;
  // Use current FY start
  const fyStart = currentMonth >= 4 ? currentYear : currentYear - 1;

  const entries = generateGSTDeadlines(clientId, firmId, fyStart);

  // Upsert — don't duplicate if already exists
  await sb.from("compliance_calendar").upsert(
    entries,
    { onConflict: "client_id,compliance_type,period_start", ignoreDuplicates: true }
  );
}

export async function getComplianceCalendar(
  clientId?: string,
  status?: string,
): Promise<ComplianceEntry[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  let q = sb.from("compliance_calendar")
    .select("*, clients(client_name)")
    .eq("firm_id", firmId)
    .order("due_date");

  if (clientId) q = q.eq("client_id", clientId);
  if (status) q = q.eq("filing_status", status);

  const { data, error } = await q;
  if (error) throw new Error(error.message);
  return (data ?? []) as ComplianceEntry[];
}

export async function updateFilingStatus(
  id: string,
  status: string,
  arnNumber?: string,
): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("compliance_calendar").update({
    filing_status: status,
    filed_date: status === "filed" ? new Date().toISOString().split("T")[0] : null,
    arn_number: arnNumber ?? null,
    updated_at: new Date().toISOString(),
  }).eq("id", id);
}

export async function getUpcomingDeadlines(days = 30): Promise<ComplianceEntry[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const today = new Date().toISOString().split("T")[0];
  const future = new Date(Date.now() + days * 86400000).toISOString().split("T")[0];

  const { data, error } = await sb.from("compliance_calendar")
    .select("*, clients(client_name)")
    .eq("firm_id", firmId)
    .in("filing_status", ["pending", "overdue", "in_progress"])
    .gte("due_date", today)
    .lte("due_date", future)
    .order("due_date");

  if (error) throw new Error(error.message);
  return (data ?? []) as ComplianceEntry[];
}
