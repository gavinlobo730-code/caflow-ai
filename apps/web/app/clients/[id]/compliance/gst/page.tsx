"use client";

import { useState, useEffect, useCallback } from "react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { Badge } from "@/components/ui/badge";
import { DashboardSkeleton, TableSkeleton } from "@/components/ui/skeleton";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Helpers ────────────────────────────────────────────────────────────────

async function getToken(): Promise<string> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  return session?.access_token ?? "";
}

async function apiFetch(path: string, opts?: RequestInit) {
  const token = await getToken();
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

function rupees(paise: number) {
  return `₹${(paise / 100).toLocaleString("en-IN")}`;
}

type GSTTab = "dashboard" | "gstr1" | "gstr3b" | "gstr2b" | "history" | "gstr9";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#334155]",
  validated: "bg-blue-100 text-blue-700",
  ca_approved: "bg-green-100 text-green-700",
  submitted: "bg-emerald-100 text-emerald-800",
};


/**
 * A walk-through of what filing WILL look like. It files nothing.
 *
 * PracticeSync prepares the return and produces the GSTN JSON; the CA uploads
 * and signs it on gst.gov.in. Real API filing needs GSP registration and does
 * not exist yet. This plays the steps so the flow can be shown before it does.
 *
 * WHY THE WARNINGS ARE UNMISSABLE RATHER THAN TASTEFUL
 *   Whoever is demoing knows it is a mock. The person who glances at the screen
 *   over their shoulder, or opens the same return next week, does not — and a
 *   return believed filed and not filed accrues Rs 50 a day under §47 from its
 *   real due date, with the §37(3)/§39(9) correction window running out
 *   regardless. So the banner is above the steps, the final state says NOT
 *   FILED rather than Filed, and the reference is the server's SIM-NOT-FILED
 *   string verbatim. The endpoint is also off unless ENABLE_FILING_SIMULATION
 *   is set, so this button only appears where somebody switched it on.
 */
function FilingSimulationModal({
  returnId, period, onClose,
}: { returnId: string; period: string; onClose: () => void }) {
  const [steps, setSteps] = useState<{ key: string; label: string }[]>([]);
  const [done, setDone] = useState(-1);
  const [ack, setAck] = useState<string | null>(null);
  const [disclaimer, setDisclaimer] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    (async () => {
      try {
        const r = await apiFetch(`/api/gst-workspace/gstr3b/${returnId}/simulate-filing`, { method: "POST" });
        if (cancelled) return;
        if (!r.success) { setError(r.error ?? "Could not start the demo."); return; }
        const d = r.data as { steps: { key: string; label: string }[]; acknowledgement: string; disclaimer: string };
        setSteps(d.steps);
        setDisclaimer(d.disclaimer);
        // Paced so the sequence is legible, not to imitate a real round trip.
        d.steps.forEach((_, i) => {
          timers.push(setTimeout(() => { if (!cancelled) setDone(i); }, 700 * (i + 1)));
        });
        timers.push(setTimeout(() => { if (!cancelled) setAck(d.acknowledgement); }, 700 * (d.steps.length + 1)));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not start the demo.");
      }
    })();
    return () => { cancelled = true; timers.forEach(clearTimeout); };
  }, [returnId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg overflow-hidden">
        <div className="px-5 py-3 bg-amber-100 border-b-2 border-amber-400">
          <p className="text-sm font-bold text-amber-900">DEMO — nothing is being filed</p>
          <p className="text-xs text-amber-900 mt-0.5">
            This is a preview of a feature that does not exist yet. No data leaves
            PracticeSync and no government system is contacted.
          </p>
        </div>

        <div className="px-5 py-4 space-y-3">
          <p className="text-xs text-[#64748B]">GSTR-3B · period {period}</p>
          {error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : (
            <ul className="space-y-2">
              {steps.map((st, i) => (
                <li key={st.key} className="flex items-center gap-2 text-sm">
                  <span className={`w-4 text-center ${i <= done ? "text-green-600" : "text-[#CBD5E1]"}`}>
                    {i <= done ? "✓" : "○"}
                  </span>
                  <span className={i <= done ? "text-[#334155]" : "text-[#94A3B8]"}>{st.label}</span>
                </li>
              ))}
            </ul>
          )}

          {ack && (
            <div className="rounded border-2 border-amber-400 bg-amber-50 p-3 space-y-1">
              <p className="text-sm font-bold text-amber-900">NOT FILED — this was a demo</p>
              <p className="text-xs font-mono text-amber-900 break-all">{ack}</p>
              <p className="text-xs text-amber-900">{disclaimer}</p>
              <p className="text-xs text-amber-900">
                To file for real: download the JSON and upload it on gst.gov.in, then
                record the ARN here with <strong>Mark Filed</strong>.
              </p>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t flex justify-end">
          <button onClick={onClose}
            className="px-3 py-1.5 text-sm border rounded hover:bg-[#F8FAFC]">Close</button>
        </div>
      </div>
    </div>
  );
}


/**
 * The documents behind one GSTR-3B figure — the detail half of the return.
 *
 * WHY IT SHOWS THE DETAIL'S OWN TOTAL NEXT TO THE SUMMARY'S
 *   A detail report that disagrees with the summary above it is worse than no
 *   detail report: it turns one trusted figure into two untrusted ones. The
 *   endpoint reuses the return's own document fetchers and returns its own
 *   sum, and this prints both side by side. If they ever drift it is visible
 *   here rather than discovered at a notice.
 */
function GSTR3BDetailDrawer({
  clientId, period, line, label, expectedPaise, onClose,
}: {
  clientId: string; period: string; line: string; label: string;
  expectedPaise: number | null; onClose: () => void;
}) {
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [totals, setTotals] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch(
          `/api/gst/gstr3b/detail?client_id=${encodeURIComponent(clientId)}` +
          `&period=${encodeURIComponent(period)}&line=${encodeURIComponent(line)}`);
        if (cancelled) return;
        if (!r.success) { setError(r.error ?? "Couldn't load the detail."); return; }
        const d = r.data as { rows: Record<string, unknown>[]; [k: string]: unknown };
        setRows(d.rows);
        setTotals({
          taxable: Number(d.total_taxable_paise ?? 0),
          igst: Number(d.total_igst_paise ?? 0),
          cgst: Number(d.total_cgst_paise ?? 0),
          sgst: Number(d.total_sgst_paise ?? 0),
          tax: Number(d.total_tax_paise ?? 0),
        });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Couldn't load the detail.");
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, period, line]);

  function exportCsv() {
    if (!rows) return;
    const cols = ["document_date", "kind", "document_no", "party",
                  "taxable_paise", "igst_paise", "cgst_paise", "sgst_paise", "tax_paise"];
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const body = [cols.join(","),
      ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([body], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `gstr3b-${period}-${line}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const matches = expectedPaise === null || totals === null
    ? null
    : totals.tax === expectedPaise;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30">
      <div className="bg-white w-full max-w-4xl h-full overflow-y-auto shadow-xl">
        <div className="sticky top-0 bg-white border-b px-5 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-[#1E293B]">{label}</p>
            <p className="text-xs text-[#64748B]">Period {period} · the documents behind this figure</p>
          </div>
          <div className="flex gap-2">
            <button onClick={exportCsv} disabled={!rows?.length}
              className="text-xs px-3 py-1.5 border rounded hover:bg-[#F8FAFC] disabled:opacity-40">
              Export CSV
            </button>
            <button onClick={onClose}
              className="text-xs px-3 py-1.5 border rounded hover:bg-[#F8FAFC]">Close</button>
          </div>
        </div>

        <div className="p-5 space-y-3">
          {error && <p className="text-sm text-red-600">{error}</p>}

          {totals && (
            <div className={`text-xs px-3 py-2 rounded ${
              matches === false ? "bg-amber-50 text-amber-800" : "bg-green-50 text-green-700"}`}>
              {matches === false
                ? `These documents total ${rupees(totals.tax)}, but the return shows ${rupees(expectedPaise ?? 0)}. They should agree — review before filing.`
                : `${rows?.length ?? 0} document${rows?.length === 1 ? "" : "s"}, totalling ${rupees(totals.tax)} tax — matches the return.`}
            </div>
          )}

          {rows === null && !error && <TableSkeleton rows={6} />}

          {rows && rows.length === 0 && (
            <p className="text-sm text-[#94A3B8]">
              No documents for this line in {period}. That is a real answer, not a failure —
              nothing was posted here.
            </p>
          )}

          {rows && rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-[#F8FAFC] text-[#64748B]">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Date</th>
                    <th className="px-3 py-2 text-left font-medium">Type</th>
                    <th className="px-3 py-2 text-left font-medium">Number</th>
                    <th className="px-3 py-2 text-left font-medium">Party</th>
                    <th className="px-3 py-2 text-right font-medium">Taxable</th>
                    <th className="px-3 py-2 text-right font-medium">IGST</th>
                    <th className="px-3 py-2 text-right font-medium">CGST</th>
                    <th className="px-3 py-2 text-right font-medium">SGST</th>
                    <th className="px-3 py-2 text-right font-medium">Tax</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={String(r.id ?? i)} className="border-t hover:bg-[#F8FAFC]">
                      <td className="px-3 py-1.5">{String(r.document_date ?? "")}</td>
                      <td className="px-3 py-1.5 text-[#64748B]">{String(r.kind ?? "")}</td>
                      <td className="px-3 py-1.5 font-mono">{String(r.document_no ?? "")}</td>
                      <td className="px-3 py-1.5">{String(r.party ?? "")}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{rupees(Number(r.taxable_paise ?? 0))}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{rupees(Number(r.igst_paise ?? 0))}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{rupees(Number(r.cgst_paise ?? 0))}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{rupees(Number(r.sgst_paise ?? 0))}</td>
                      <td className="px-3 py-1.5 text-right font-mono font-semibold">{rupees(Number(r.tax_paise ?? 0))}</td>
                    </tr>
                  ))}
                </tbody>
                {totals && (
                  <tfoot className="bg-[#F8FAFC] font-semibold">
                    <tr className="border-t-2">
                      <td className="px-3 py-2" colSpan={4}>Total</td>
                      <td className="px-3 py-2 text-right font-mono">{rupees(totals.taxable)}</td>
                      <td className="px-3 py-2 text-right font-mono">{rupees(totals.igst)}</td>
                      <td className="px-3 py-2 text-right font-mono">{rupees(totals.cgst)}</td>
                      <td className="px-3 py-2 text-right font-mono">{rupees(totals.sgst)}</td>
                      <td className="px-3 py-2 text-right font-mono">{rupees(totals.tax)}</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Dashboard ──────────────────────────────────────────────────────────────

interface GSTDashboardData {
  gstr1Count: number;
  gstr3bCount: number;
  frequency: "monthly" | "quarterly";
  stateCategory: "X" | "Y" | null;
  gstr1Due: string;
  gstr3bDue: string;
  pmt06Due: string | null;
  iffDue: string | null;
  monthInQuarter: number | null;
  currentPeriod: string;
}

/**
 * WHY THIS NOW ASKS THE SERVER FOR ITS DATES
 *
 * It used to compute them here:
 *
 *     const dueDateOf = (day) => toLocalISO(new Date(nextYear, nextMonth - 1, day));
 *     gstr1Due: dueDateOf(11), gstr3bDue: dueDateOf(20)
 *
 * That was a THIRD copy of CGST §37/§39 — after compliance_engine.py and the
 * adapters in gst_workspace.py — living in the browser, which CLAUDE.md puts
 * off limits for exactly this reason: it could not be corrected in one place.
 *
 * And it was wrong. A QRMP filer (Rule 61A: turnover up to Rs 5 crore, opted
 * in) files GSTR-1 by the 13th of the month after the QUARTER and GSTR-3B by
 * the 22nd or 24th depending on their state, and owes PMT-06 challans monthly
 * that a monthly filer does not. The 11th and the 20th are simply not their
 * dates, and §47 charges Rs 50 a day for filing late.
 *
 * The endpoint reads clients.gst_filing_frequency and clients.state_code and
 * returns the whole regime. This renders it and derives nothing.
 */
function GSTDashboard({ clientId }: { clientId: string }) {
  const [data, setData] = useState<GSTDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await apiFetch(`/api/gst-workspace/?client_id=${encodeURIComponent(clientId)}`);
        if (cancelled) return;
        if (!r.success) { setData(null); return; }
        const d = r.data as {
          gstr1_returns?: unknown[];
          gstr3b_returns?: unknown[];
          regime?: { frequency?: string; state_category?: string | null };
          upcoming_due_dates?: Record<string, string | number | null>;
        };
        const due = d.upcoming_due_dates ?? {};
        setData({
          gstr1Count: (d.gstr1_returns ?? []).length,
          gstr3bCount: (d.gstr3b_returns ?? []).length,
          frequency: d.regime?.frequency === "quarterly" ? "quarterly" : "monthly",
          stateCategory: (d.regime?.state_category as "X" | "Y" | null) ?? null,
          gstr1Due: String(due.gstr1 ?? ""),
          gstr3bDue: String(due.gstr3b ?? ""),
          pmt06Due: due.pmt06 ? String(due.pmt06) : null,
          iffDue: due.iff_optional ? String(due.iff_optional) : null,
          monthInQuarter: due.month_in_quarter == null ? null : Number(due.month_in_quarter),
          currentPeriod: String(due.current_period ?? ""),
        });
      } catch {
        if (!cancelled) setData(null);   // renders "Failed to load GST dashboard."
      } finally {
        // Guarded by `cancelled`: a superseded effect must not lower the flag
        // the effect that replaced it has just raised, or the new load renders
        // its empty state instead of a skeleton.
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  if (loading) return <DashboardSkeleton cards={4} />;
  if (!data) return <p className="text-sm text-red-500">Failed to load GST dashboard.</p>;

  const quarterly = data.frequency === "quarterly";

  return (
    <div className="space-y-4">
      {/* Which regime this client is on, said out loud. The dates below mean
          different things under each, and until now the screen showed monthly
          dates for everyone without ever naming the assumption. */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={`px-2 py-1 rounded-full font-medium ring-1 ${
          quarterly ? "bg-purple-50 text-purple-700 ring-purple-200"
                    : "bg-blue-50 text-blue-700 ring-blue-200"}`}>
          {quarterly ? "QRMP — quarterly returns, monthly payment" : "Monthly filer"}
        </span>
        <span className="text-[#94A3B8]">Period {data.currentPeriod}</span>
        {quarterly && data.monthInQuarter && (
          <span className="text-[#94A3B8]">· month {data.monthInQuarter} of the quarter</span>
        )}
        {quarterly && data.stateCategory === null && (
          <span className="px-2 py-1 rounded-full bg-amber-50 text-amber-800 ring-1 ring-amber-200">
            State not set — GSTR-3B date shown is the earlier of the two (22nd)
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="rounded border p-4 bg-blue-50">
          <p className="text-xs text-[#64748B]">
            GSTR-1 due date{quarterly ? " (quarter)" : ""}
          </p>
          <p className="font-semibold">{data.gstr1Due}</p>
        </div>
        <div className="rounded border p-4 bg-amber-50">
          <p className="text-xs text-[#64748B]">
            GSTR-3B due date{quarterly ? " (quarter)" : ""}
          </p>
          <p className="font-semibold">{data.gstr3bDue}</p>
        </div>
      </div>

      {/* Rule 61A. A QRMP filer still pays every month, by challan, for the
          first two months of the quarter — the single most missed thing about
          the scheme, and previously not mentioned anywhere in this product. */}
      {quarterly && (
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded border p-4 bg-red-50">
            <p className="text-xs text-[#64748B]">PMT-06 challan (tax is still paid monthly)</p>
            <p className="font-semibold">
              {data.pmt06Due ?? "Not due — this month's tax is paid with the quarterly return"}
            </p>
          </div>
          <div className="rounded border p-4">
            <p className="text-xs text-[#64748B]">IFF — optional, B2B only</p>
            <p className="font-semibold">
              {data.iffDue ?? "Not applicable in the last month of a quarter"}
            </p>
            <p className="text-[10px] text-[#94A3B8] mt-1">
              Upload B2B invoices so the customer&apos;s ITC does not wait for the quarter.
              Nothing is due if it is not used.
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="rounded border p-4">
          <p className="font-medium">GSTR-1 returns</p>
          <p className="text-2xl font-bold mt-1">{data.gstr1Count}</p>
        </div>
        <div className="rounded border p-4">
          <p className="font-medium">GSTR-3B returns</p>
          <p className="text-2xl font-bold mt-1">{data.gstr3bCount}</p>
        </div>
      </div>
    </div>
  );
}

// ── GSTR-1 ─────────────────────────────────────────────────────────────────

function GSTR1Tab({ clientId }: { clientId: string }) {
  const [returns, setReturns] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no GSTR-1 returns yet" — a masked
  // failure previously rendered identically to a genuinely empty register.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [period, setPeriod] = useState("");
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);

  const [showCompute, setShowCompute] = useState(false);
  const [computePeriod, setComputePeriod] = useState("");
  const [computing, setComputing] = useState(false);
  const [computeResult, setComputeResult] = useState<Record<string, unknown> | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [savingComputed, setSavingComputed] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/returns?client_id=${clientId}`)
      .then((r) => {
        if (r.success) {
          setReturns((r.data as { gstr1: Record<string, unknown>[] }).gstr1);
          setLoadError(null);
        } else {
          setReturns([]);
          setLoadError(r.error ?? "Couldn't load GSTR-1 returns.");
        }
      })
      .catch(() => {
        setReturns([]);
        setLoadError("Couldn't load GSTR-1 returns. Please try again.");
      })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    setSaving(true);
    try {
      await apiFetch("/api/gst-workspace/gstr1", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, period, gstin }),
      });
      setShowNew(false);
      setPeriod("");
      setGstin("");
      load();
    } catch (e) {
      // Keep the dialog open with what was typed still in it — closing on a
      // failed save loses the period and GSTIN and reads as success.
      setLoadError(e instanceof Error ? e.message : "Couldn't create the GSTR-1 return.");
    } finally {
      setSaving(false);
    }
  }

  async function updateStatus(id: string, status: string) {
    await apiFetch(`/api/gst-workspace/gstr1/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, ca_approved: true }),
    });
    load();
  }

  // CGST Act §37 — GSTR-1 derived ENTIRELY from posted sales invoices + issued
  // credit/debit notes and reconciled to the General Ledger (services/
  // gst_return_service.py::gstr1_from_books). All computation happens server-
  // side; the frontend only displays the result (CLAUDE.md: zero business
  // logic in the frontend).
  async function computeFromBooks() {
    setComputing(true);
    setComputeError(null);
    setComputeResult(null);
    const r = await apiFetch("/api/gst/gstr1/from-books", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, period: computePeriod }),
    });
    if (r.success) setComputeResult(r.data as Record<string, unknown>);
    else setComputeError(r.error ?? "Couldn't compute GSTR-1 from books.");
    setComputing(false);
  }

  async function saveComputed() {
    if (!computeResult) return;
    setSavingComputed(true);
    const d = computeResult;
    await apiFetch("/api/gst-workspace/gstr1", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        period: d.period,
        gstin: d.gstin,
        payload_json: d.payload,
        summary_json: d.summary,
        total_taxable_paise: d.taxable_total_paise,
        total_igst_paise: d.total_igst_paise,
        total_cgst_paise: d.total_cgst_paise,
        total_sgst_paise: d.total_sgst_paise,
        total_cess_paise: d.total_cess_paise,
      }),
    });
    setSavingComputed(false);
    setShowCompute(false);
    setComputeResult(null);
    setComputePeriod("");
    setComputeError(null);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">GSTR-1 Returns</h3>
        <div className="flex gap-2">
          <button onClick={() => setShowCompute(true)}
            className="text-sm px-3 py-1 border border-blue-300 text-blue-700 rounded hover:bg-blue-50">
            Compute from Books
          </button>
          <button onClick={() => setShowNew(true)}
            className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
            + New GSTR-1
          </button>
        </div>
      </div>

      {showCompute && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Compute GSTR-1 from Books</p>
          <p className="text-xs text-[#64748B]">
            Derives GSTR-1 entirely from posted sales invoices and issued credit/debit notes,
            and reconciles the output tax to the General Ledger. No manual entry.
          </p>
          <input placeholder="Period (MMYYYY e.g. 042025)" value={computePeriod}
            onChange={(e) => setComputePeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          {computeError && <p className="text-red-600 text-sm">{computeError}</p>}
          <div className="flex gap-2">
            <button onClick={computeFromBooks} disabled={computing || !computePeriod}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {computing ? "Computing…" : "Compute"}
            </button>
            <button onClick={() => { setShowCompute(false); setComputeResult(null); setComputeError(null); }}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>

          {computeResult && (() => {
            const rec = computeResult.reconciliation as Record<string, unknown>;
            const netOut = rec?.net_output_gst as Record<string, number>;
            const reconciled = Boolean(rec?.reconciled);
            return (
              <div className="border-t pt-3 space-y-2">
                <div className={`text-sm px-3 py-2 rounded ${reconciled ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-800"}`}>
                  {reconciled ? "✓ Reconciled to the General Ledger" : "⚠ Does not reconcile to the General Ledger — review before saving"}
                  {!reconciled && netOut && (
                    <span className="block mt-1 text-xs">
                      Books: {rupees(netOut.books_paise ?? 0)} vs Ledger: {rupees(netOut.ledger_paise ?? 0)}
                      {" "}(diff {rupees(netOut.difference_paise ?? 0)})
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div><p className="text-xs text-[#64748B]">Invoices</p><p className="font-medium">{computeResult.invoice_count as number}</p></div>
                  <div><p className="text-xs text-[#64748B]">Taxable Total</p><p className="font-medium">{rupees(computeResult.taxable_total_paise as number)}</p></div>
                  <div><p className="text-xs text-[#64748B]">Tax Total</p><p className="font-medium">{rupees(computeResult.tax_total_paise as number)}</p></div>
                </div>
                <button onClick={saveComputed} disabled={savingComputed}
                  className="px-3 py-1 bg-green-600 text-white rounded text-sm disabled:opacity-50">
                  {savingComputed ? "Saving…" : "Save as Draft"}
                </button>
              </div>
            );
          })()}
        </div>
      )}

      {showNew && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">New GSTR-1</p>
          <input placeholder="Period (MMYYYY e.g. 042025)" value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <input placeholder="GSTIN" value={gstin}
            onChange={(e) => setGstin(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <div className="flex gap-2">
            <button onClick={saveNew} disabled={saving || !period || !gstin}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {saving ? "Saving…" : "Save Draft"}
            </button>
            <button onClick={() => setShowNew(false)}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={5} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Period</th>
              <th className="px-3 py-2 border-b">GSTIN</th>
              <th className="px-3 py-2 border-b">Taxable</th>
              <th className="px-3 py-2 border-b">Status</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {returns.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2">{r.period as string}</td>
                <td className="px-3 py-2 text-xs">{r.gstin as string}</td>
                <td className="px-3 py-2">{rupees((r.total_taxable_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
                <td className="px-3 py-2 space-x-2">
                  {r.status === "draft" && (
                    <button onClick={() => updateStatus(r.id as string, "validated")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-[#F1F5F9]">Validate</button>
                  )}
                  {r.status === "validated" && (
                    <button onClick={() => updateStatus(r.id as string, "ca_approved")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">CA Approve</button>
                  )}
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : returns.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-[#94A3B8]">No GSTR-1 returns yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── GSTR-3B ────────────────────────────────────────────────────────────────

function GSTR3BTab({ clientId }: { clientId: string }) {
  const [returns, setReturns] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // The filing walk-through. Only reachable on a ca_approved return, and only
  // when the server has ENABLE_FILING_SIMULATION on — it files nothing either
  // way, but the button should not exist where the demo is not wanted.
  const [simulate, setSimulate] = useState<{ id: string; period: string } | null>(null);
  // Whether this BUILD can run the walk-through at all. Only the server knows —
  // it is an env flag on the API. Previously the button rendered
  // unconditionally and errored on click when the flag was off, which is a dead
  // control: the exact fault the health badge was fixed for a day earlier.
  const [canSimulate, setCanSimulate] = useState(false);
  // Which GSTR-3B line the detail drawer is open on, if any.
  const [detail, setDetail] = useState<
    { period: string; line: string; label: string; expected: number | null } | null>(null);
  // Distinguishes "fetch failed" from "no GSTR-3B returns yet".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [period, setPeriod] = useState("");
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);

  const [showCompute, setShowCompute] = useState(false);
  const [computePeriod, setComputePeriod] = useState("");
  const [computing, setComputing] = useState(false);
  const [computeResult, setComputeResult] = useState<Record<string, unknown> | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [savingComputed, setSavingComputed] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/returns?client_id=${clientId}`)
      .then((r) => {
        if (r.success) {
          setReturns((r.data as { gstr3b: Record<string, unknown>[] }).gstr3b);
          setLoadError(null);
        } else {
          setReturns([]);
          setLoadError(r.error ?? "Couldn't load GSTR-3B returns.");
        }
      })
      .catch(() => {
        setReturns([]);
        setLoadError("Couldn't load GSTR-3B returns. Please try again.");
      })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    setSaving(true);
    try {
      await apiFetch("/api/gst-workspace/gstr3b", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, period, gstin }),
      });
      setShowNew(false);
      setPeriod("");
      setGstin("");
      load();
    } catch (e) {
      // Same as GSTR1Tab.saveNew — the dialog stays open with its input.
      setLoadError(e instanceof Error ? e.message : "Couldn't create the GSTR-3B return.");
    } finally {
      setSaving(false);
    }
  }

  async function updateStatus(id: string, status: string) {
    await apiFetch(`/api/gst-workspace/gstr3b/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, ca_approved: true }),
    });
    load();
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch(`/api/gst-workspace/?client_id=${encodeURIComponent(clientId)}`);
        if (cancelled) return;
        const caps = (r.data as { capabilities?: { filing_simulation?: boolean } })?.capabilities;
        setCanSimulate(Boolean(caps?.filing_simulation));
      } catch {
        // A capability that cannot be confirmed is treated as absent. Showing a
        // control on a failed probe is how the dead button happened.
        if (!cancelled) setCanSimulate(false);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  // CGST Act §39 — GSTR-3B derived ENTIRELY from posted sales/purchase
  // documents (incl. issued credit/debit notes on both sides) and reconciled
  // to the General Ledger's GST control accounts (services/
  // gst_return_service.py::gstr3b_from_books). CA REVIEW REQUIRED before
  // filing — this only computes and previews a draft.
  async function computeFromBooks() {
    setComputing(true);
    setComputeError(null);
    setComputeResult(null);
    const r = await apiFetch("/api/gst/gstr3b/from-books", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, period: computePeriod }),
    });
    if (r.success) setComputeResult(r.data as Record<string, unknown>);
    else setComputeError(r.error ?? "Couldn't compute GSTR-3B from books.");
    setComputing(false);
  }

  async function saveComputed() {
    if (!computeResult) return;
    setSavingComputed(true);
    const d = computeResult;
    await apiFetch("/api/gst-workspace/gstr3b", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        period: d.period,
        gstin: d.gstin,
        payload_json: d.payload,
        summary_json: d.working,
        tax_liability_paise: d.tax_liability_paise,
        itc_claimed_paise: d.itc_claimed_paise,
        net_tax_paise: d.net_tax_paise,
        // The carry-forward is NOT sent as its own field: SaveGSTR3BRequest has
        // no such parameter, and Pydantic would drop it without complaint —
        // a value that looks saved and is not. It rides in summary_json, which
        // is `working` and now carries working.itc_utilisation.
      }),
    });
    setSavingComputed(false);
    setShowCompute(false);
    setComputeResult(null);
    setComputePeriod("");
    setComputeError(null);
    load();
  }

  return (
    <div className="space-y-4">
      {detail && (
        <GSTR3BDetailDrawer
          clientId={clientId}
          period={detail.period}
          line={detail.line}
          label={detail.label}
          expectedPaise={detail.expected}
          onClose={() => setDetail(null)}
        />
      )}
      {simulate && (
        <FilingSimulationModal
          returnId={simulate.id}
          period={simulate.period}
          onClose={() => setSimulate(null)}
        />
      )}
      <div className="flex justify-between items-center">
        <h3 className="font-medium">GSTR-3B Returns</h3>
        <div className="flex gap-2">
          <button onClick={() => setShowCompute(true)}
            className="text-sm px-3 py-1 border border-blue-300 text-blue-700 rounded hover:bg-blue-50">
            Compute from Books
          </button>
          <button onClick={() => setShowNew(true)}
            className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
            + New GSTR-3B
          </button>
        </div>
      </div>

      {showCompute && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Compute GSTR-3B from Books</p>
          <p className="text-xs text-[#64748B]">
            Derives GSTR-3B entirely from posted sales/purchase documents (including issued
            credit/debit notes) and reconciles output tax and ITC to the General Ledger.
          </p>
          <input placeholder="Period (MMYYYY e.g. 042025)" value={computePeriod}
            onChange={(e) => setComputePeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          {computeError && <p className="text-red-600 text-sm">{computeError}</p>}
          <div className="flex gap-2">
            <button onClick={computeFromBooks} disabled={computing || !computePeriod}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {computing ? "Computing…" : "Compute"}
            </button>
            <button onClick={() => { setShowCompute(false); setComputeResult(null); setComputeError(null); }}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>

          {computeResult && (() => {
            const rec = computeResult.reconciliation as Record<string, unknown>;
            const output = rec?.output_gst as Record<string, number>;
            const itc = rec?.itc as Record<string, number>;
            const reconciled = Boolean(rec?.reconciled);
            const cf = (computeResult.itc_carried_forward_paise as number) ?? 0;
            return (
              <div className="border-t pt-3 space-y-2">
                <div className={`text-sm px-3 py-2 rounded ${reconciled ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-800"}`}>
                  {reconciled ? "✓ Reconciled to the General Ledger" : "⚠ Does not reconcile to the General Ledger — review before saving"}
                  {!reconciled && (
                    <div className="mt-1 text-xs space-y-0.5">
                      {output && !output.matched && (
                        <p>Output GST — Books: {rupees(output.books_paise ?? 0)} vs Ledger: {rupees(output.ledger_paise ?? 0)}</p>
                      )}
                      {itc && !itc.matched && (
                        <p>ITC — Books: {rupees(itc.books_paise ?? 0)} vs Ledger: {rupees(itc.ledger_paise ?? 0)}</p>
                      )}
                    </div>
                  )}
                </div>
                <div className="grid grid-cols-4 gap-3 text-sm">
                  <div><p className="text-xs text-[#64748B]">Tax Liability</p><p className="font-medium">{rupees(computeResult.tax_liability_paise as number)}</p></div>
                  <div><p className="text-xs text-[#64748B]">ITC Claimed</p><p className="font-medium">{rupees(computeResult.itc_claimed_paise as number)}</p></div>
                  <div><p className="text-xs text-[#64748B]">Net Tax</p><p className="font-medium">{rupees(computeResult.net_tax_paise as number)}</p></div>
                  {/* Net Tax of zero is true both when liability and credit cancel
                      out and when credit exceeds liability by lakhs. Apex's April
                      2026 showed zero over Rs 36,54,961.65 of unused credit, with
                      nothing on screen to tell the two apart. The figure is
                      computed in apps/api as the residual of the same set-off
                      that produced Net Tax, so the two cannot disagree. */}
                  <div>
                    <p className="text-xs text-[#64748B]">Credit Carried Forward</p>
                    <p className={cf > 0 ? "font-medium text-emerald-700" : "font-medium"}>{rupees(cf)}</p>
                  </div>
                </div>
                {cf > 0 && (
                  <p className="text-xs text-[#64748B]">
                    Input credit exceeded this period&apos;s liability, so there is no tax to
                    pay and {rupees(cf)} carries into the next return.
                  </p>
                )}
                {/* THE TABLES, not just the totals.
                    The GSTN offline utility is table by table, and a CA
                    reviewing before filing is checking 3.1 and 4, not a single
                    liability figure. This panel showed four numbers and the
                    only way to see the breakdown was the separate firm-level
                    GSTR-3B screen, which most people never reach from a client.
                    Everything below already came back in `working` — it was
                    fetched and thrown away. */}
                <details className="border rounded">
                  <summary className="px-3 py-2 text-sm font-medium cursor-pointer select-none text-[#334155]">
                    Table-by-table breakdown
                  </summary>
                  {(() => {
                    const w = computeResult.working as Record<string, Record<string, number>> | undefined;
                    if (!w) return <p className="px-3 pb-3 text-xs text-[#94A3B8]">No working available.</p>;
                    const out = w.outward ?? {};
                    const itcW = w.itc ?? {};
                    const revP = (w.itc_reversal as unknown as { permanent_paise?: Record<string, number> })?.permanent_paise ?? {};
                    const revR = (w.itc_reversal as unknown as { reclaimable_paise?: Record<string, number> })?.reclaimable_paise ?? {};
                    const np = w.net_payable ?? {};
                    // A line is clickable only where documents exist behind it.
                    // 4(C) and Table 6 are arithmetic over the lines above, not
                    // things you can list — offering a drill-down that opened
                    // an empty drawer would be the dead-control fault again.
                    const row = (label: string, i?: number, c?: number, sg?: number,
                                 drill?: string) => {
                      const total = (i ?? 0) + (c ?? 0) + (sg ?? 0);
                      return (
                        <tr key={label} className="border-t hover:bg-[#F8FAFC]">
                          <td className="px-3 py-1.5 text-[#475569]">
                            {drill ? (
                              <button
                                onClick={() => setDetail({
                                  period: computeResult.period as string,
                                  line: drill, label, expected: total,
                                })}
                                className="text-blue-700 hover:underline text-left"
                              >
                                {label} →
                              </button>
                            ) : label}
                          </td>
                          <td className="px-3 py-1.5 text-right font-mono">{rupees(i ?? 0)}</td>
                          <td className="px-3 py-1.5 text-right font-mono">{rupees(c ?? 0)}</td>
                          <td className="px-3 py-1.5 text-right font-mono">{rupees(sg ?? 0)}</td>
                        </tr>
                      );
                    };
                    return (
                      <div className="px-3 pb-3 overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead className="text-[#94A3B8]">
                            <tr>
                              <th className="px-3 py-1.5 text-left font-medium">&nbsp;</th>
                              <th className="px-3 py-1.5 text-right font-medium">IGST</th>
                              <th className="px-3 py-1.5 text-right font-medium">CGST</th>
                              <th className="px-3 py-1.5 text-right font-medium">SGST</th>
                            </tr>
                          </thead>
                          <tbody>
                            {row("3.1(a) Outward taxable supplies",
                                 out.taxable_igst_paise, out.taxable_cgst_paise, out.taxable_sgst_paise, "3.1a")}
                            {row("4(A) ITC available (gross)",
                                 itcW.avail_igst_paise, itcW.avail_cgst_paise, itcW.avail_sgst_paise, "4A")}
                            {row("4(B)(1) Reversed — permanent",
                                 revP.igst_paise, revP.cgst_paise, revP.sgst_paise, "4B1")}
                            {row("4(B)(2) Reversed — reclaimable",
                                 revR.igst_paise, revR.cgst_paise, revR.sgst_paise, "4B2")}
                            {row("4(C) Net ITC available",
                                 itcW.net_igst_paise, itcW.net_cgst_paise, itcW.net_sgst_paise)}
                            {row("6 Tax payable after set-off",
                                 np.igst_paise, np.cgst_paise, np.sgst_paise)}
                          </tbody>
                        </table>
                        <p className="text-[10px] text-[#94A3B8] mt-2">
                          Click a blue line to see the documents behind it — the detail
                          report, which sums to the figure beside it. 4(C) and Table 6 are
                          arithmetic over the lines above, so they have no documents of
                          their own. Table 4 follows Notification 14/2022-Central Tax with
                          Circular 170/02/2022-GST: 4(A) is gross, §17(5) sits in 4(B)(1)
                          and is not repeated in 4(D), and Table 6 sets off 4(C) — never 4(A).
                        </p>
                      </div>
                    );
                  })()}
                </details>
                <button onClick={saveComputed} disabled={savingComputed}
                  className="px-3 py-1 bg-green-600 text-white rounded text-sm disabled:opacity-50">
                  {savingComputed ? "Saving…" : "Save as Draft"}
                </button>
              </div>
            );
          })()}
        </div>
      )}

      {showNew && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">New GSTR-3B</p>
          <input placeholder="Period (MMYYYY)" value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <input placeholder="GSTIN" value={gstin}
            onChange={(e) => setGstin(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <div className="flex gap-2">
            <button onClick={saveNew} disabled={saving || !period || !gstin}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {saving ? "Saving…" : "Save Draft"}
            </button>
            <button onClick={() => setShowNew(false)}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={6} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Period</th>
              <th className="px-3 py-2 border-b">Tax Liability</th>
              <th className="px-3 py-2 border-b">ITC Claimed</th>
              <th className="px-3 py-2 border-b">Net Tax</th>
              <th className="px-3 py-2 border-b">Status</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {returns.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2">{r.period as string}</td>
                <td className="px-3 py-2">{rupees((r.tax_liability_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">{rupees((r.itc_claimed_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">{rupees((r.net_tax_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
                <td className="px-3 py-2 space-x-2">
                  {r.status === "draft" && (
                    <button onClick={() => updateStatus(r.id as string, "validated")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-[#F1F5F9]">Validate</button>
                  )}
                  {r.status === "validated" && (
                    <button onClick={() => updateStatus(r.id as string, "ca_approved")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">CA Approve</button>
                  )}
                  {/* Only on an approved return, because that is where real
                      filing would sit — and only where the server says the
                      walk-through exists. A control that always errors is worse
                      than no control. */}
                  {r.status === "ca_approved" && canSimulate && (
                    <button onClick={() => setSimulate({ id: r.id as string, period: r.period as string })}
                      className="text-xs px-2 py-0.5 border border-amber-300 rounded hover:bg-amber-50 text-amber-800">
                      Preview filing (demo)
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : returns.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-[#94A3B8]">No GSTR-3B returns yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── GSTR-2B ────────────────────────────────────────────────────────────────

function GSTR2BTab({ clientId }: { clientId: string }) {
  const [period, setPeriod] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload() {
    setLoading(true);
    setError(null);
    try {
      const raw_data = JSON.parse(jsonText);
      const resp = await apiFetch("/api/gst-workspace/gstr2b/upload", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, period, raw_data }),
      });
      if (resp.success) setResult(resp.data);
      else setError(resp.error ?? "Upload failed");
    } catch {
      setError("Invalid JSON. Please paste valid GSTR-2B JSON.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="font-medium">GSTR-2B Reconciliation</h3>
      <div className="space-y-3">
        <input placeholder="Period (MMYYYY e.g. 042025)" value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="w-full border rounded px-3 py-1.5 text-sm" />
        <textarea placeholder="Paste GSTR-2B JSON here (include book_invoices array for reconciliation)"
          value={jsonText} onChange={(e) => setJsonText(e.target.value)}
          rows={8} className="w-full border rounded px-3 py-2 text-sm font-mono" />
        {error && <p className="text-red-600 text-sm">{error}</p>}
        <button onClick={upload} disabled={loading || !period || !jsonText}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
          {loading ? "Reconciling…" : "Upload & Reconcile"}
        </button>
      </div>

      {result && (
        <div className="border rounded p-4 space-y-3">
          <p className="font-medium text-sm">Reconciliation Result</p>
          {(() => {
            const recon = result.reconciliation_result as Record<string, unknown>;
            const summary = recon?.summary as Record<string, number>;
            const mismatched = recon?.mismatched as unknown[];
            const missing = recon?.missing_in_2b as unknown[];
            return (
              <div className="space-y-2">
                <div className="flex gap-4 text-sm">
                  <span className="text-green-700">✓ Matched: {summary?.matched_count ?? 0}</span>
                  <span className="text-amber-600">⚠ Mismatched: {summary?.mismatch_count ?? 0}</span>
                  <span className="text-red-600">✗ Missing: {summary?.missing_count ?? 0}</span>
                </div>
                {(mismatched?.length ?? 0) > 0 && (
                  <div>
                    <p className="text-sm font-medium text-amber-700">Amount mismatches:</p>
                    {(mismatched as Record<string, unknown>[]).map((m, i) => (
                      <div key={i} className="text-xs text-[#334155] mt-1">
                        {JSON.stringify(m.key)} — Book: {rupees(m.book_paise as number)}, 2B: {rupees(m.gstr2b_paise as number)}
                      </div>
                    ))}
                  </div>
                )}
                {(missing?.length ?? 0) > 0 && (
                  <div>
                    <p className="text-sm font-medium text-red-700">Missing in GSTR-2B:</p>
                    {(missing as Record<string, unknown>[]).map((m, i) => (
                      <div key={i} className="text-xs text-[#334155] mt-1">{JSON.stringify(m.key)}</div>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

// ── Filing History ─────────────────────────────────────────────────────────

function FilingHistoryTab({ clientId }: { clientId: string }) {
  const [data, setData] = useState<{ gstr1_filed: Record<string, unknown>[]; gstr3b_filed: Record<string, unknown>[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/filing-history?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setData(r.data); setLoadError(null); }
        else { setData(null); setLoadError(r.error ?? "Failed to load filing history."); }
      })
      .catch(() => { setData(null); setLoadError("Failed to load filing history. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <TableSkeleton cols={4} bare />;
  if (!data) return (
    <div className="text-center py-6 space-y-2">
      <p className="text-sm text-red-500">{loadError ?? "Failed to load filing history."}</p>
      <button onClick={load} className="text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
    </div>
  );

  const all = ([
    ...(data.gstr1_filed ?? []).map((r) => ({ ...r, type: "GSTR-1" })),
    ...(data.gstr3b_filed ?? []).map((r) => ({ ...r, type: "GSTR-3B" })),
  ] as Record<string, unknown>[]).sort((a, b) =>
    String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""))
  );

  return (
    <div className="space-y-4">
      <h3 className="font-medium">Filing History</h3>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-[#F8FAFC] text-left">
            <th className="px-3 py-2 border-b">Type</th>
            <th className="px-3 py-2 border-b">Period</th>
            <th className="px-3 py-2 border-b">ARN</th>
            <th className="px-3 py-2 border-b">Status</th>
          </tr>
        </thead>
        <tbody>
          {all.map((r) => (
            <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
              <td className="px-3 py-2 font-medium">{r.type as string}</td>
              <td className="px-3 py-2">{r.period as string}</td>
              <td className="px-3 py-2 text-xs">{(r.arn as string) ?? "—"}</td>
              <td className="px-3 py-2">
                <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                  {r.status as string}
                </span>
              </td>
            </tr>
          ))}
          {all.length === 0 && (
            <tr><td colSpan={4} className="px-3 py-4 text-center text-[#94A3B8]">No filed returns yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── GSTR-9 ─────────────────────────────────────────────────────────────────

function GSTR9Tab() {
  return (
    <div className="space-y-4">
      <h3 className="font-medium">GSTR-9 Annual Return</h3>
      <div className="rounded border p-4 bg-amber-50 text-sm text-amber-800">
        <p className="font-medium">⚠ CA Review Required</p>
        <p className="mt-1">GSTR-9 is generated as a read-only draft. The CA must review all data before filing.
          CGST Act §44 — Annual return must be filed by 31st December.</p>
      </div>
      <p className="text-sm text-[#475569]">
        GSTR-9 is auto-computed from your GSTR-1 and GSTR-3B returns for the financial year.
        Navigate to GSTR-1 and GSTR-3B tabs to review monthly returns first.
      </p>
      <p className="text-xs text-[#94A3B8]">Draft generation from filed monthly returns will be available once GSTR-1/3B returns are CA approved.</p>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

// GSTR-9 is intentionally hidden for Closed Beta (Beta-readiness Part 1):
// GSTR9Tab() below has no computation logic behind it (no gstr9_builder in
// apps/api/domain/gst, unlike GSTR-1/GSTR-3B) — it only ever rendered a
// static "not available yet" message. GSTR-9's own due-date obligation is
// still tracked correctly via the Compliance workspace/dashboard; only this
// decorative preparation tab is hidden. Component kept, not deleted, so it
// can be wired to a real builder and re-added to TABS later.
const TABS: { id: GSTTab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "gstr1", label: "GSTR-1" },
  { id: "gstr3b", label: "GSTR-3B" },
  { id: "gstr2b", label: "GSTR-2B Recon" },
  { id: "history", label: "Filing History" },
];

export default function GSTWorkspacePage() {
  const { clientId } = useClientNav();
  const [tab, setTab] = useState<GSTTab>("dashboard");

  if (!clientId || clientId === "_placeholder") {
    return <p className="text-sm text-[#64748B] p-6">Select a client to view GST workspace.</p>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">GST Compliance Workspace</h2>
        <Badge variant="outline" className="text-amber-700 border-amber-300 bg-amber-50 text-xs">
          CA Review Required before filing
        </Badge>
      </div>

      <div className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {tab === "dashboard" && <GSTDashboard clientId={clientId} />}
        {tab === "gstr1" && <GSTR1Tab clientId={clientId} />}
        {tab === "gstr3b" && <GSTR3BTab clientId={clientId} />}
        {tab === "gstr2b" && <GSTR2BTab clientId={clientId} />}
        {tab === "history" && <FilingHistoryTab clientId={clientId} />}
        {tab === "gstr9" && <GSTR9Tab />}
      </div>
    </div>
  );
}
