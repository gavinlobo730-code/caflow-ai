/**
 * Maps the Compliance workspace's authoritative dashboard response
 * (compliance_obligation_service.aggregate_dashboard, IST-aware, canonical
 * compliance_records) onto the main Dashboard's KPI tiles (H13).
 *
 * Previously the main Dashboard queried the legacy `compliance_entries` view
 * directly with UTC dates, silently disagreeing with the Compliance
 * workspace's counts. Both pages must now read the exact same numbers.
 */
export interface ComplianceDashboardSummary {
  due_this_month: number;
  overdue: number;
}

export interface ComplianceDashboardResponse {
  success: boolean;
  data: { summary: ComplianceDashboardSummary } | null;
  error: string | null;
}

export function mapComplianceKpis(
  resp: ComplianceDashboardResponse | null | undefined
): { filingsDueThisMonth: number; overdueFilings: number } {
  const summary = resp?.success ? resp.data?.summary : undefined;
  return {
    filingsDueThisMonth: summary?.due_this_month ?? 0,
    overdueFilings: summary?.overdue ?? 0,
  };
}
