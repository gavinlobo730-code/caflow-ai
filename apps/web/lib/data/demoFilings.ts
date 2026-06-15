/**
 * Data layer for DEMO MODE filing simulations (PR-3).
 * Reads/writes the demo_filings table — kept entirely separate from real
 * compliance_calendar.filing_status so a simulation can never be mistaken for
 * a real filing.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "./getFirmId";
import { isDemoReference } from "@/lib/filing/demoFiling";
import type { ComplianceEntry } from "./compliance";

export interface DemoFiling {
  id: string;
  firm_id: string;
  client_id: string | null;
  compliance_entry_id: string | null;
  compliance_type: string;
  period_start: string | null;
  period_end: string | null;
  demo_reference: string;
  demo_status: string;
  simulated_at: string;
}

/** All demo filings for the firm, keyed by compliance_entry_id for easy overlay. */
export async function getDemoFilingsByEntry(clientId?: string): Promise<Record<string, DemoFiling>> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  let q = sb.from("demo_filings").select("*").eq("firm_id", firmId);
  if (clientId) q = q.eq("client_id", clientId);
  const { data } = await q;
  const map: Record<string, DemoFiling> = {};
  for (const row of (data ?? []) as DemoFiling[]) {
    if (row.compliance_entry_id) map[row.compliance_entry_id] = row;
  }
  return map;
}

/** Count of simulated filings for the firm (for the dashboard indicator). */
export async function getDemoFilingCount(): Promise<number> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { count } = await sb
    .from("demo_filings")
    .select("id", { count: "exact", head: true })
    .eq("firm_id", firmId);
  return count ?? 0;
}

/**
 * Persist a simulated filing for a compliance entry. Upserts on the entry so
 * re-simulating updates the existing demo record. Defensive: refuses to store
 * anything that isn't a recognised demo reference.
 */
export async function saveDemoFiling(entry: ComplianceEntry, demoReference: string): Promise<void> {
  if (!isDemoReference(demoReference)) {
    throw new Error("Refusing to save a non-demo reference for a simulated filing.");
  }
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data: auth } = await sb.auth.getUser();
  await sb.from("demo_filings").upsert(
    {
      firm_id: firmId,
      client_id: entry.client_id,
      compliance_entry_id: entry.id,
      compliance_type: entry.compliance_type,
      period_start: entry.period_start ?? null,
      period_end: entry.period_end ?? null,
      demo_reference: demoReference,
      demo_status: "demo_filed",
      simulated_by: auth?.user?.id ?? null,
      simulated_at: new Date().toISOString(),
    },
    { onConflict: "compliance_entry_id" },
  );
}
