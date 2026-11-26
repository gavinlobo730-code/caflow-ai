/**
 * WHICH OF THE PRACTICE REPORTS A PERSON IS OFFERED (POST-A-447).
 *
 * The Reports page listed all four to everyone. Three read the reports router, whose routes ask `accounting` `read`
 * (Executive and above), and the compliance one reads the obligations, whose route asks `compliance` `read` (all
 * staff). So a Reviewer was offered four reports and refused three of them only after choosing one, with the server's
 * refusal as the first sign. A report is now offered only when the caller's own permissions admit the route it reads.
 *
 * `lib/reports/offered.test.ts` holds each pair to the route's `rbac(...)` in the API source, so a route that changes
 * its permission fails the test rather than leaving the page offering a report the server refuses.
 */

export type ReportId = "gst_summary" | "pl_statement" | "compliance_status" | "outstanding_invoices";

export const REPORT_REQUIRES: Readonly<Record<ReportId, readonly [string, string]>> = {
  gst_summary: ["accounting", "read"],
  pl_statement: ["accounting", "read"],
  compliance_status: ["compliance", "read"],
  outstanding_invoices: ["accounting", "read"],
};

/**
 * Whether a report is offered. While the caller's permissions are still being read (`resolved` false) nothing is
 * withheld, the rule the workspace menu uses, so a report does not flash in and out on the first frame; the route
 * still refuses whatever the caller cannot run.
 */
export function reportOffered(
  id: ReportId,
  can: (resource: string, action: string) => boolean,
  resolved: boolean,
): boolean {
  if (!resolved) return true;
  const [resource, action] = REPORT_REQUIRES[id];
  return can(resource, action);
}
