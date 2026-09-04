"use client";

/**
 * Payroll Module — IT Act Section 192 (TDS on Salary), ESI Act, EPF Act
 * All monetary values stored and computed in integer paise.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  X, AlertCircle, Users,
  Download, CheckCircle, Clock, AlertTriangle, BarChart2,
  Receipt, CalendarDays, ArrowRight,
} from "lucide-react";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { toLocalISO } from "@/lib/dateMath";
import { useToast } from "@/components/ui/use-toast";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, type ApiResp } from "@/lib/api";
// Moved into a shared module when the roster became its own screen (People).
// One definition, two pages — copying them is how the salary register and the
// ECR each ended up implemented twice, with only one of them right.
import {
  apiErr, fmtRs,
  type Client, type Employee, type PayrollRun, type PayrollSlip,
} from "@/components/payroll/shared";

// ── Statutory Returns helpers ─────────────────────────────────────────────

/**
 * Given today's date, compute the list of statutory return deadlines
 * relevant for the current month/quarter.
 *
 * PF ECR: monthly, due 15th of following month (EPF Act)
 * ESI Return: half-yearly (Apr-Sep → Nov 11; Oct-Mar → May 11)
 * PT: monthly challan (Maharashtra example)
 * TDS 24Q: quarterly (IT Act Section 192)
 *   Q1 Apr-Jun → 31 Jul | Q2 Jul-Sep → 31 Oct | Q3 Oct-Dec → 31 Jan | Q4 Jan-Mar → 31 May
 */
function getStatutoryDeadlines(today: Date): {
  id: string;
  label: string;
  description: string;
  dueDate: Date;
  status: "overdue" | "due-soon" | "upcoming";
  portal: string;
}[] {
  const y = today.getFullYear();
  const m = today.getMonth(); // 0-indexed

  const deadlines = [];

  // PF ECR — due 15th of current month for prior month
  const pfMonth = m === 0 ? 11 : m - 1;
  const pfYear = m === 0 ? y - 1 : y;
  const pfDue = new Date(y, m, 15);
  const pfMonthName = new Date(pfYear, pfMonth, 1).toLocaleString("en-IN", { month: "long", year: "numeric" });
  deadlines.push({
    id: "pf-ecr",
    label: `PF ECR — ${pfMonthName}`,
    description: "Electronic Challan cum Return — EPFO Unified Portal",
    dueDate: pfDue,
    status: getDueDateStatus(pfDue, today),
    portal: "EPFO Unified Portal",
  });

  // ESI Return — half-yearly
  // Apr-Sep period → due Nov 11; Oct-Mar period → due May 11
  let esiDue: Date;
  let esiPeriod: string;
  if (m >= 3 && m <= 8) {
    // Apr–Sep period, due Nov 11 this year
    esiDue = new Date(y, 10, 11);
    esiPeriod = `Apr–Sep ${y}`;
  } else if (m >= 9) {
    // Oct–Dec, due May 11 next year
    esiDue = new Date(y + 1, 4, 11);
    esiPeriod = `Oct ${y}–Mar ${y + 1}`;
  } else {
    // Jan–Mar, due May 11 this year
    esiDue = new Date(y, 4, 11);
    esiPeriod = `Oct ${y - 1}–Mar ${y}`;
  }
  deadlines.push({
    id: "esi-return",
    label: `ESI Return — ${esiPeriod}`,
    description: "Half-yearly return — ESIC Portal (employees ≤ ₹21,000/month)",
    dueDate: esiDue,
    status: getDueDateStatus(esiDue, today),
    portal: "ESIC Portal",
  });

  // PT Challan — monthly, due by end of current month (state-dependent; showing general)
  const ptDue = new Date(y, m + 1, 0); // last day of current month
  deadlines.push({
    id: "pt-challan",
    label: `Professional Tax — ${today.toLocaleString("en-IN", { month: "long", year: "numeric" })}`,
    description: "Monthly PT challan — State treasury (Maharashtra: ₹200 if salary > ₹10,000)",
    dueDate: ptDue,
    status: getDueDateStatus(ptDue, today),
    portal: "State Treasury Portal",
  });

  // TDS 24Q — quarterly (IT Act Section 192)
  // Q1: Apr-Jun → 31 Jul | Q2: Jul-Sep → 31 Oct | Q3: Oct-Dec → 31 Jan | Q4: Jan-Mar → 31 May
  let tdsQuarter: string;
  let tdsDue: Date;
  if (m >= 3 && m <= 5) {
    tdsQuarter = `Q1 Apr–Jun ${y}`;
    tdsDue = new Date(y, 6, 31);
  } else if (m >= 6 && m <= 8) {
    tdsQuarter = `Q2 Jul–Sep ${y}`;
    tdsDue = new Date(y, 9, 31);
  } else if (m >= 9 && m <= 11) {
    tdsQuarter = `Q3 Oct–Dec ${y}`;
    tdsDue = new Date(y + 1, 0, 31);
  } else {
    tdsQuarter = `Q4 Jan–Mar ${y}`;
    tdsDue = new Date(y, 4, 31);
  }
  deadlines.push({
    id: "tds-24q",
    label: `TDS 24Q — ${tdsQuarter}`,
    description: "Quarterly TDS return on salary — IT Act Section 192 — filed on the e-filing portal (incometax.gov.in)",
    dueDate: tdsDue,
    status: getDueDateStatus(tdsDue, today),
    portal: "e-filing portal (incometax.gov.in)",
  });

  return deadlines;
}

function getDueDateStatus(
  due: Date,
  today: Date,
): "overdue" | "due-soon" | "upcoming" {
  const diffMs = due.getTime() - today.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return "overdue";
  if (diffDays <= 7) return "due-soon";
  return "upcoming";
}

/* The EPFO ECR and the ESIC return were BUILT HERE, in the browser, until
 * 2026-09-04. Both are now server-built — api.payroll.runEcr / runEsic, backed
 * by domain/payroll/{ecr,esic}.py.
 *
 * They are not coming back. The browser versions hardcoded NCP_DAYS to 0, put
 * PAN (or a fabricated "EMP0001") in the MEMBER_ID field that wants a UAN,
 * computed EPF wages on basic alone where EPF Act s.6 says basic + DA, and
 * decided ESI eligibility from the current month's gross instead of the Rule 50
 * contribution period — every one of them a rule the backend had already fixed.
 * CLAUDE.md's "zero business logic in the frontend" exists for exactly this: a
 * statutory remittance file is the last place a second implementation belongs.
 */

// ── TDS 24Q ─────────────────────────────────────────────────────────────────
//
// `generateTds24QData` USED TO LIVE HERE and has been deleted rather than left
// beside its replacement. It assembled a statutory return in the browser, from
// whatever payslips this screen happened to have loaded, and it disagreed with
// domain/payroll/form24q.py on the thing that matters most:
//
//   * it wrote "PAN NOT AVAILABLE" into the PAN column and carried on. §206AA
//     requires tax at the HIGHER of the specified rate or 20% where PAN is not
//     furnished, so a row declaring tax deducted at slab rates against no PAN
//     declares a SHORT deduction — and the employer, not the employee, carries
//     it. The server refuses the row.
//   * it never looked for a §192 challan, so it would produce a quarter with
//     nothing showing the tax was deposited.
//   * it never checked the runs were FINALISED, so a draft month's figures
//     could be filed and then move.
//   * it divided paise by 100 in floating point.
//
// The quarter's working paper is now GET /api/payroll/24q-source.csv, built
// from the same rows those refusals are computed on. Same fix as the salary
// register and the employee import: a statutory document is not a thing the
// browser assembles.

function downloadFile(content: string, filename: string, mimeType: string,
                     opts?: { bom?: boolean }) {
  // A BOM helps Excel read a CSV of ours. It must NEVER reach a government
  // upload: the EPFO ECR is a fixed-format text file where extra bytes break
  // parsing, and the ESIC CSV is uploaded to a portal, not opened in Excel.
  //
  // This used to be INFERRED from the mime type — csv got a BOM, text did not
  // — which was right only while every CSV on this page was ours. The moment
  // the server-built ESIC return came through here it would have been handed a
  // byte the server did not write. The caller says so now, because the caller
  // is the one who knows where the file is going.
  const body = (opts?.bom ?? mimeType.startsWith("text/csv")) ? "\uFEFF" + content : content;
  const blob = new Blob([body], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Determine the TDS 24Q quarter label for a given YYYY-MM month string */
/** Which 24Q quarter and financial year a payroll month falls in.
 *
 *  Returns what the SERVER needs — "Q2" and "2026-27" — not a display label.
 *  It replaced a label-only helper, which was fine while the CSV was built in
 *  the browser and useless once the quarter had to be named to an API.
 *
 *  The Indian FY runs April to March, so a January–March month belongs to the
 *  year BEFORE the calendar one. Getting that wrong files Q4 against next
 *  year's return. */
function tdsQuarterOf(month: string): { quarter: string; fy: string } {
  const [y, m] = month.split("-").map(Number);
  const quarter = m >= 4 && m <= 6 ? "Q1" : m >= 7 && m <= 9 ? "Q2"
                : m >= 10 && m <= 12 ? "Q3" : "Q4";
  const fyStart = m >= 4 ? y : y - 1;
  return { quarter, fy: `${fyStart}-${String(fyStart + 1).slice(2)}` };
}

// ── Employee Portal access modal ───────────────────────────────────────────
// The activation link comes back ONCE, from this call. Only its sha256 is
// stored server-side, so it can never be fetched again — which is why the link
// is shown here for copying, not just emailed and forgotten. Re-inviting mints
// a fresh link and invalidates this one.
/** THE CLIENT-MONTH QUEUE — the bureau's screen on the 3rd and the 10th.
 *
 *  ONE PAYROLL SURFACE (payroll v1 item 10). This page and
 *  /clients/[id]/payroll had grown into RIVALS: both let a CA add an employee,
 *  compute a run and read payslips, this one behind a client dropdown and that
 *  one inside the client's own workspace. Two places to do one job is how the
 *  salary register and the ECR each ended up implemented twice.
 *
 *  The client workspace is canonical — a payroll month is COMPLETED for one
 *  client, and that is where the client's ledger, attendance and statutory
 *  identity already live. What was missing was the other half: a month is
 *  FOUND across the firm, and there was no screen that answered "which of my
 *  forty clients still need doing". A CA opened each client in turn to find out.
 *
 *  So this leads INTO the workspace rather than competing with it: every row is
 *  a link, and nothing here computes or writes anything.
 *
 *  It reads GET /api/payroll/client-states, which answers for the whole firm in
 *  three queries rather than three per client, and which is scoped by
 *  filter_by_client — an Executive assigned to four clients sees four rows, not
 *  the headcount and net pay of all forty.
 */
type ClientMonthState = {
  client_id: string;
  client_name: string;
  payroll_enabled: boolean;
  inputs_due_day: number | null;
  run_status: string | null;
  headcount: number | null;
  total_net_paise: number | null;
};

/** What this client-month needs from a human, in the module's own vocabulary.
 *
 *  "Payroll off" and "not started" are DIFFERENT answers and the queue must not
 *  merge them: one is a decision the firm made, the other is work outstanding.
 *  That distinction is the whole reason client-states reports a disabled client
 *  rather than omitting it. */
function monthState(c: ClientMonthState): {
  label: string; className: string; note: string; needsWork: boolean;
} {
  if (!c.payroll_enabled) {
    return {
      label: "Not run", className: "bg-[#F1F5F9] text-[#64748B]",
      note: "Payroll is switched off for this client. A Partner turns it on in the client's payroll setup.",
      needsWork: false,
    };
  }
  if (c.run_status === "paid") {
    return { label: "Paid", className: "bg-green-100 text-green-700",
             note: "Salaries disbursed and the payment journal posted.", needsWork: false };
  }
  if (c.run_status === "finalized") {
    return { label: "Finalised", className: "bg-emerald-100 text-emerald-700",
             note: "The accrual is posted. Still to disburse.", needsWork: true };
  }
  if (c.run_status) {
    return { label: "Draft", className: "bg-blue-100 text-blue-700",
             note: `The run exists at "${c.run_status}" and has not been released.`, needsWork: true };
  }
  return { label: "Not started", className: "bg-amber-100 text-amber-700",
           note: "Payroll is on for this client and this month has no run yet.",
           needsWork: true };
}

function MonthQueueTab({ month, onMonthChange }: {
  month: string; onMonthChange: (m: string) => void;
}) {
  const [rows, setRows] = useState<ClientMonthState[]>([]);
  const [loading, setLoading] = useState(true);
  // A failed read must not render as "no clients" — that is indistinguishable
  // from a firm that runs payroll for nobody, and it is the mistake M17 fixed
  // across this module.
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.payroll.payrollClientStates(month) as
        ApiResp<{ month: string; clients: ClientMonthState[] }>;
      if (!res?.data) { setError("Could not load the payroll month."); setRows([]); return; }
      setRows(res.data.clients ?? []);
    } catch (e) {
      setError(apiErr(e, "Could not load the payroll month."));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => { load(); }, [load]);

  const outstanding = rows.filter(r => monthState(r).needsWork).length;
  const running = rows.filter(r => r.payroll_enabled).length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-row items-start justify-between flex-wrap gap-3">
          <div>
            <CardTitle className="text-base">The payroll month</CardTitle>
            <p className="text-xs text-[#64748B] mt-0.5">
              Every client you run payroll for, and what each still needs. Open a
              client to do the work.
            </p>
          </div>
          <input
            type="month" value={month} onChange={e => onMonthChange(e.target.value)}
            className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm outline-none focus:border-blue-400"
          />
        </div>
        {!loading && !error && rows.length > 0 && (
          <p className="text-xs text-[#475569] mt-3">
            {outstanding === 0
              ? `All ${running} payroll client(s) are done for this month.`
              : `${outstanding} of ${running} payroll client(s) still need work.`}
          </p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {loading ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">Loading the month…</p>
        ) : error ? (
          <div className="p-8 text-center">
            <p className="text-sm text-red-600 font-medium mb-2">{error}</p>
            <Button size="sm" variant="outline" onClick={load}>Retry</Button>
          </div>
        ) : rows.length === 0 ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">
            No client has payroll switched on. A Partner turns it on from a
            client&apos;s payroll setup.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                  <th className="text-left py-3 px-4">Client</th>
                  <th className="text-left py-3 px-4">State</th>
                  <th className="text-right py-3 px-4">Employees</th>
                  <th className="text-right py-3 px-4">Net pay</th>
                  <th className="text-left py-3 px-4">Inputs due</th>
                  <th className="py-3 px-4"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map(c => {
                  const st = monthState(c);
                  return (
                    <tr key={c.client_id} className="border-b hover:bg-[#F8FAFC]">
                      <td className="py-3 px-4 font-medium text-[#0F172A]">{c.client_name}</td>
                      <td className="py-3 px-4">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs ${st.className}`} title={st.note}>
                          {st.label}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-[#475569]">
                        {c.headcount ?? <span className="text-[#CBD5E1]">—</span>}
                      </td>
                      <td className="py-3 px-4 text-right font-mono">
                        {c.total_net_paise != null
                          ? fmtRs(c.total_net_paise)
                          : <span className="text-[#CBD5E1]">—</span>}
                      </td>
                      <td className="py-3 px-4 text-[#64748B] text-xs">
                        {c.inputs_due_day ? `Day ${c.inputs_due_day}` : "—"}
                      </td>
                      <td className="py-3 px-4 text-right">
                        {/* The link IS the point: this screen finds the work, the
                            client workspace does it. */}
                        <Link href={`/clients/${c.client_id}/payroll`}>
                          <Button size="sm" variant="outline" className="flex items-center gap-1.5">
                            Open<ArrowRight size={13} />
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}


/** THE EXCEPTION INDEX — the roster's statutory gaps, before a file is built.
 *
 *  Every statutory file payroll produces already refuses the rows it cannot
 *  honestly carry: the ECR a member with no UAN, the ESIC return one with no IP
 *  number, Form 24Q a deductee with no valid PAN. Each refusal is correct — and
 *  each lands at FILE-BUILD time, on the 7th, with the run already finalised and
 *  the journal already posted. The information was on the employee master the
 *  whole time and nothing asked.
 *
 *  This asks. It computes nothing and writes nothing; the server re-states what
 *  the file builders will say, early enough to do something about.
 */
function PayslipModal({ slip, onClose }: { slip: PayrollSlip; onClose: () => void }) {
  const emp = slip.employee!;
  const run = slip.run!;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-semibold">Payslip</h2>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => window.print()}>Print</Button>
            <button onClick={onClose}><X size={16} /></button>
          </div>
        </div>
        <div className="border-b pb-3 mb-3">
          <h3 className="font-bold text-lg text-[#0F172A]">{emp.name}</h3>
          <p className="text-sm text-[#475569]">{emp.designation} {emp.pan ? `• ${emp.pan}` : ""}</p>
          <p className="text-sm text-[#475569]">Month: {run.month}</p>
        </div>
        <table className="w-full text-sm">
          <tbody>
            <tr className="border-b">
              <td className="py-1 text-[#475569]">Gross Salary</td>
              <td className="py-1 text-right font-medium">{fmtRs(slip.gross_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-[#475569]">PF Deduction (12% of Basic)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.pf_employee_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-[#475569]">ESI Deduction (0.75%)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.esi_employee_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-[#475569]">Professional Tax</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.pt_paise)}</td>
            </tr>
            <tr className="border-b">
              <td className="py-1 text-[#475569]">TDS on Salary (IT Act Sec 192)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.tds_paise)}</td>
            </tr>
            <tr className="font-bold">
              <td className="py-2 text-[#0F172A]">Net Pay</td>
              <td className="py-2 text-right text-green-700">{fmtRs(slip.net_paise)}</td>
            </tr>
          </tbody>
        </table>
        <p className="text-[10px] text-[#94A3B8] mt-4 text-center">Generated by PracticeSync AI</p>
      </div>
    </div>
  );
}

// ── Statutory Returns Tab ─────────────────────────────────────────────────

function StatusBadge({ status }: { status: "overdue" | "due-soon" | "upcoming" | "filed" }) {
  if (status === "overdue") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
        <AlertTriangle size={11} />Overdue
      </span>
    );
  }
  if (status === "due-soon") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
        <Clock size={11} />Due Soon
      </span>
    );
  }
  if (status === "filed") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
        <CheckCircle size={11} />Filed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#F1F5F9] text-[#475569]">
      <Clock size={11} />Upcoming
    </span>
  );
}

function StatutoryReturnsTab({
  runs,
  slips,
  clients,
}: {
  runs: PayrollRun[];
  slips: PayrollSlip[];
  clients: Client[];
}) {
  const today = new Date();
  const deadlines = getStatutoryDeadlines(today);

  // Group runs by client for the "Generate" section
  const [selectedClientId, setSelectedClientId] = useState(clients[0]?.id ?? "");
  const [statutoryBusy, setStatutoryBusy] = useState<string | null>(null);
  const { toast } = useToast();

  const clientRuns = runs.filter(r => r.client_id === selectedClientId);

  function slipsForRun(runId: string): PayrollSlip[] {
    return slips.filter(s => s.run_id === runId);
  }

  /** Ask the SERVER for the statutory file, and let its refusal reach the CA.
   *
   *  The endpoint returns the text alongside `problems` and `filable` rather
   *  than a download, because a member the file cannot carry — no UAN, a
   *  ceiling breached, a zero-wage ESIC member with no reason code — has to be
   *  fixed before the upload, not after the portal rejects the batch. A run
   *  that is not finalised is refused outright with its own 409: the ECR
   *  reports contributions actually made, and a draft run's figures can still
   *  change. The browser version happily built one from a draft. */
  async function downloadStatutoryFile(
    run: PayrollRun,
    what: "ecr" | "esic",
    fetcher: () => Promise<unknown>,
  ) {
    setStatutoryBusy(`${run.id}:${what}`);
    try {
      const res = (await fetcher()) as {
        data?: { filename?: string; lines?: string; csv?: string;
                 problems?: string[]; filable?: boolean };
      };
      const d = res?.data;
      if (!d) throw new Error("The server returned no file.");
      const content = what === "ecr" ? d.lines : d.csv;
      const problems = d.problems ?? [];

      const label = what === "ecr" ? "ECR" : "ESIC return";
      // `is_filable` is `bool(members) and not problems` on both builders, so
      // the two false cases mean different things and a CA needs to be told
      // WHICH. There is no third case: a filable return never carries problems.
      if (!d.filable) {
        toast({
          title: problems.length ? `${label} blocked` : `Nothing to file`,
          description: problems.length
            ? problems.join(" · ")
            : `No member of this run carries a ${what === "ecr" ? "PF" : "ESI"} contribution, so there is no ${label} to build.`,
          variant: "destructive",
        });
        return;
      }
      if (!content) throw new Error("The server returned an empty file.");

      downloadFile(
        content,
        d.filename ?? `${what.toUpperCase()}_${run.month}.${what === "ecr" ? "txt" : "csv"}`,
        what === "ecr" ? "text/plain" : "text/csv",
        // Both go to a government portal. Neither gets a BOM.
        { bom: false },
      );
    } catch (e) {
      toast({
        title: `Couldn't build the ${what === "ecr" ? "ECR" : "ESIC return"}`,
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setStatutoryBusy(null);
    }
  }

  /** The server refuses the ECR and the ESIC return for a run that is not
   *  finalised, because both report contributions actually made. Say that on
   *  the button rather than spending a round trip to be told. */
  const isFiled = (run: PayrollRun) => run.status === "finalized" || run.status === "paid";

  const handleGeneratePfEcr = (run: PayrollRun) =>
    downloadStatutoryFile(run, "ecr", () => api.payroll.runEcr(run.id));

  const handleGenerateEsiStatement = (run: PayrollRun) =>
    downloadStatutoryFile(run, "esic", () => api.payroll.runEsic(run.id));

  /** # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
   *
   *  The quarter, not the month: 24Q is a QUARTERLY return, and this button has
   *  always sat on a run row. The month decides which quarter and which FY.
   */
  async function handleGenerate24Q(run: PayrollRun) {
    setStatutoryBusy(`${run.id}:24q`);
    try {
      const { quarter, fy } = tdsQuarterOf(run.month);
      await api.payroll.download24QWorkingPaper(run.client_id, fy, quarter);
    } catch (e) {
      toast({
        title: "Could not build the 24Q working paper",
        description: apiErr(e, "The request failed."),
        variant: "destructive",
      });
    } finally {
      setStatutoryBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      {/* Due Date Checklist */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Statutory Return Deadlines</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">
            Based on today&apos;s date. Mark as filed in your records after submission.
          </p>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {deadlines.map(d => (
              <div
                key={d.id}
                className={`flex items-start justify-between p-3 rounded-lg border ${
                  d.status === "overdue"
                    ? "border-red-200 bg-red-50"
                    : d.status === "due-soon"
                    ? "border-amber-200 bg-amber-50"
                    : "border-[#E2E8F0] bg-white"
                }`}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[#0F172A]">{d.label}</p>
                  <p className="text-xs text-[#64748B] mt-0.5">{d.description}</p>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    Portal: {d.portal} &middot; Due:{" "}
                    {d.dueDate.toLocaleDateString("en-IN", {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })}
                  </p>
                </div>
                <div className="ml-4 flex-shrink-0">
                  <StatusBadge status={d.status} />
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-[#94A3B8] mt-4 border-t pt-3">
            Note: Status is computed from today&apos;s date. This checklist does not auto-track filed
            returns — update your firm records after each submission.
          </p>
        </CardContent>
      </Card>

      {/* Generate Returns for Payroll Runs */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Generate Statutory Return Files</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">
            Download files in the correct format for each portal. Review before uploading.
          </p>
        </CardHeader>
        <CardContent>
          {clients.length > 1 && (
            <div className="mb-4">
              <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
              <ClientLookup
                clients={clients}
                value={selectedClientId}
                onChange={setSelectedClientId}
                ariaLabel="Client"
                placeholder="Select client…"
              />
            </div>
          )}

          {clientRuns.length === 0 ? (
            <p className="text-sm text-[#94A3B8] py-6 text-center">
              No payroll runs for this client. Run a Monthly Payroll first.
            </p>
          ) : (
            <div className="space-y-3">
              {/* CA Review notice */}
              <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <AlertCircle size={15} className="text-amber-600 mt-0.5 flex-shrink-0" />
                <p className="text-xs text-amber-800">
                  <strong>CA Review Required.</strong> These files are generated for review only.
                  Do not upload to any government portal without explicit CA verification and approval.
                  All statutory returns must be authorised by a qualified Chartered Accountant.
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                      <th className="text-left py-3 px-3">Month</th>
                      <th className="text-center py-3 px-3">Employees</th>
                      <th className="text-right py-3 px-3">Total Gross</th>
                      <th className="text-right py-3 px-3">Total TDS</th>
                      <th className="py-3 px-3 text-right">Generate Files</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clientRuns.map(run => {
                      const runSlips = slipsForRun(run.id);
                      const totalGross = runSlips.reduce((sum, s) => sum + s.gross_paise, 0);
                      const totalTds = runSlips.reduce((sum, s) => sum + s.tds_paise, 0);
                      // Whether a slip actually CARRIED the contribution, not
                      // whether a re-derived ceiling test says it should have.
                      // The old ESI test was `gross <= 2100000` for the month,
                      // which drops a member Rule 50 keeps in past the ceiling
                      // until the contribution period ends — so the button read
                      // "no ESI-applicable employees" for people we deducted from.
                      const pfCount = runSlips.filter(s => (s.pf_employee_paise || 0) > 0).length;
                      const esiCount = runSlips.filter(
                        s => (s.esi_employee_paise || 0) > 0 || (s.esi_employer_paise || 0) > 0,
                      ).length;
                      return (
                        <tr key={run.id} className="border-b hover:bg-[#F8FAFC]">
                          <td className="py-3 px-3 font-medium">{run.month}</td>
                          <td className="py-3 px-3 text-center text-[#475569]">{runSlips.length}</td>
                          <td className="py-3 px-3 text-right font-mono">{fmtRs(totalGross)}</td>
                          <td className="py-3 px-3 text-right font-mono text-red-600">{fmtRs(totalTds)}</td>
                          <td className="py-3 px-3">
                            <div className="flex gap-2 justify-end flex-wrap">
                              <Button
                                size="sm"
                                variant="outline"
                                className="flex items-center gap-1 text-xs"
                                onClick={() => handleGeneratePfEcr(run)}
                                disabled={pfCount === 0 || !isFiled(run) || statutoryBusy === `${run.id}:ecr`}
                                title={pfCount === 0 ? "No PF-applicable employees this month"
                                  : !isFiled(run) ? "Finalise the run first — the ECR reports contributions actually made"
                                  : `Generate PF ECR for ${pfCount} employees`}
                              >
                                <Download size={12} />
                                {statutoryBusy === `${run.id}:ecr` ? "…" : "PF ECR"}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="flex items-center gap-1 text-xs"
                                onClick={() => handleGenerateEsiStatement(run)}
                                disabled={esiCount === 0 || !isFiled(run) || statutoryBusy === `${run.id}:esic`}
                                title={esiCount === 0 ? "No ESI-applicable employees this month"
                                  : !isFiled(run) ? "Finalise the run first — the return reports contributions actually made"
                                  : `Generate ESI statement for ${esiCount} employees`}
                              >
                                <Download size={12} />
                                {statutoryBusy === `${run.id}:esic` ? "…" : "ESI"}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="flex items-center gap-1 text-xs"
                                onClick={() => handleGenerate24Q(run)}
                                disabled={runSlips.length === 0}
                                title="Generate TDS 24Q data — CA review required before filing"
                              >
                                <Download size={12} />
                                24Q
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Format notes */}
              <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-[#64748B]">
                <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                  <p className="font-medium text-[#334155] mb-1">PF ECR (.txt)</p>
                  <p>Tilde-separated format for EPFO Unified Portal. Upload via &quot;ECR Upload&quot; on epfindia.gov.in. Due by 15th each month.</p>
                </div>
                <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                  <p className="font-medium text-[#334155] mb-1">ESI Statement (.csv)</p>
                  <p>Employee-wise ESI contribution data for ESIC portal. Half-yearly filing — Apr-Sep by Nov 11, Oct-Mar by May 11.</p>
                </div>
                <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                  <p className="font-medium text-[#334155] mb-1">TDS 24Q (.csv)</p>
                  <p>Quarterly TDS data per IT Act Section 192. Must be filed on the e-filing portal (incometax.gov.in) under the deductor’s TAN. CA review mandatory before submission.</p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────

// ── Salary Disbursement Modal (mark a finalized run paid) ───────────────────
// Records the net-salary payout from a bank account. The chosen bank account
// must be linked to a chart-of-accounts ledger account (bank_accounts.coa_account_id)
// so the disbursement journal (Dr Net Salary Payable / Cr Bank) can post.

export default function PayrollPage() {
  const [loadError, setLoadError] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [slips, setSlips] = useState<PayrollSlip[]>([]);
  const [loading, setLoading] = useState(true);

  // The month the QUEUE is showing. Defaults to the current IST month — the
  // bureau opens this on the 3rd looking at the month just ended, and the
  // control is right there to move it.
  const [queueMonth, setQueueMonth] = useState(() => toLocalISO(new Date()).slice(0, 7));

  const [viewSlip, setViewSlip] = useState<PayrollSlip | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [clientsRes, empRes, runsRes] = await Promise.all([
        api.clients.list() as Promise<ApiResp<{ clients: Client[] }>>,
        // include_inactive: the Employees roster shows resigned/terminated staff
        // too (with a status filter). Payroll generation still uses only active
        // employees — see the runEmployees derivation below.
        api.payroll.listEmployees(undefined, true) as Promise<ApiResp<Employee[]>>,
        api.payroll.listRuns() as Promise<ApiResp<PayrollRun[]>>,
      ]);
      const clientList = clientsRes.data?.clients ?? [];
      const empList = empRes.data ?? [];
      const runList = runsRes.data ?? [];
      setClients(clientList);
      setRuns(runList);

      if (runList.length > 0) {
        const slipLists = await Promise.all(
          runList.map(r => api.payroll.getRunSlips(r.id) as Promise<ApiResp<PayrollSlip[]>>)
        );
        const rawSlips = slipLists.flatMap(res => res.data ?? []);
        const enriched = rawSlips.map(s => ({
          ...s,
          employee: empList.find(e => e.id === s.employee_id),
          run: runList.find(r => r.id === s.run_id),
        }));
        setSlips(enriched);
      } else {
        setSlips([]);
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load payroll data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center"><p className="text-[#64748B]">Loading payroll...</p></div>;
  }

  if (loadError) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle size={18} className="text-red-500" />
              Couldn&apos;t load payroll
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-[#475569] mb-4">{loadError}</p>
            <Button onClick={load}>Retry</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      {viewSlip && <PayslipModal slip={viewSlip} onClose={() => setViewSlip(null)} />}

      <div className="max-w-6xl mx-auto">
        <div className="mb-6 flex items-start justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-2xl font-bold text-[#0F172A]">Payroll</h1>
            <p className="text-sm text-[#64748B] mt-0.5">IT Act Section 192 &middot; EPF Act &middot; ESI Act</p>
          </div>
          <div className="flex items-center gap-2">
            {/* IT Act §192 / Rule 26C — what each employee declared, and what
                their proofs support. Its own page rather than a tab: it is a
                per-client, per-financial-year review, not part of a run. */}
            <Link href="/payroll/people">
              <Button variant="outline" className="flex items-center gap-1.5">
                <Users size={15} />People
              </Button>
            </Link>
            <Link href="/payroll/declarations">
              <Button variant="outline" className="flex items-center gap-1.5">
                <Receipt size={15} />Declarations
              </Button>
            </Link>
            <Link href="/payroll/reports">
              <Button variant="outline" className="flex items-center gap-1.5">
                <BarChart2 size={15} />Reports
              </Button>
            </Link>
          </div>
        </div>

        <Tabs defaultValue="month">
          <TabsList className="mb-6">
            {/* Month is FIRST and default. This page and /clients/[id]/payroll
                had grown into rivals — both able to add an employee, compute a
                run and read payslips, this one behind a client dropdown. The
                client workspace is canonical, because a payroll month is
                COMPLETED for one client; what was missing was the screen that
                says which clients still need one. The tabs after this are the
                firm-grain work that genuinely belongs here. */}
            <TabsTrigger value="month" className="flex items-center gap-1.5"><CalendarDays size={14} />Month</TabsTrigger>
            <TabsTrigger value="statutory-returns" className="flex items-center gap-1.5"><Download size={14} />Statutory Returns</TabsTrigger>
          </TabsList>

          {/* MONTH TAB — the queue, and the way into the client workspace. */}
          <TabsContent value="month">
            <MonthQueueTab month={queueMonth} onMonthChange={setQueueMonth} />
          </TabsContent>

          {/* MONTHLY RUN TAB */}
          {/* Monthly Run, Payslips and Statutory USED TO BE HERE, each behind a
              client dropdown, and each a rival of the client workspace — which
              is where a payroll month is actually completed, against that
              client's ledger, attendance and statutory identity.

              They are removed rather than left beside their replacement,
              because two ways to compute and release a month is how the salary
              register and the ECR each ended up implemented twice, once per
              surface, with only one of them right.

              Nothing was deleted before it had a home. Finalise, record payment
              and reverse now live together in the client month's Release tab;
              the ECR, the ESIC file, the 24Q working paper, the payslip zip and
              the salary register are on its Outputs shelf; the roster, the
              employee form, the bulk import and portal access are on
              /payroll/people. Statutory Returns stays below because the
              deadline checklist genuinely spans the firm. */}
          <TabsContent value="statutory-returns">
            <StatutoryReturnsTab runs={runs} slips={slips} clients={clients} />
          </TabsContent>
        </Tabs>
      </div>

    </div>
  );
}
