"use client";

/**
 * IT Act §43B(h) — a sum payable to a micro or small enterprise, paid late.
 *
 * WHAT THIS SCREEN USED TO BE (PUR-15)
 *     It asked the CA to type every bill in again — supplier, invoice number,
 *     invoice date, amount, whether the agreement was written, payment date —
 *     into `msme_payments` over PostgREST, and then computed the whole
 *     statutory rule in TypeScript. Three defects in one screen: the figure
 *     was a re-keying of data the books already hold and drifted the moment a
 *     bill was corrected; `rbac()` never ran on the write; and a §43B(h)
 *     disallowance was being decided in the browser.
 *
 *     Its rule was wrong in the direction that matters, too. It read the
 *     agreement type per ROW and defaulted the limit to 15 or 45 off that,
 *     but nothing anywhere recorded which suppliers actually have a written
 *     agreement — so the number depended on what somebody picked in a dropdown
 *     for that one invoice.
 *
 * WHAT IT IS NOW
 *     A rendering of GET /api/income-tax/msme-43bh, which derives the working
 *     from `purchase_bills`, their payment allocations and
 *     `vendors.msme_status`. This file computes nothing: no due dates, no
 *     limits, no disallowance. `domain/income_tax/section_43b_h.py` is the
 *     rule and says what it refuses to decide.
 *
 *     `msme_payments` is no longer read or written. Dropping the table is a
 *     migration and an owner decision; not reading it is neither.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle, Info, Download } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/services/formatting";
import { getClients } from "@/lib/data/clients";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { api, type MSME43BHWorking, type MSMEDInterest } from "@/lib/api";
import * as XLSX from "xlsx";
import type { Client } from "@/lib/types";
import { Callout } from "@/components/ui/callout";
import { YearPicker } from "@/components/ui/year-picker";
import { buildWorkbook, moneyCell } from "@/lib/export/xlsx";

export default function MSME43BHPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  // Derived from the clock, never listed — a hardcoded year list is a control
  // that goes stale on 1 April and then offers a year already past.
  const fyChoices = useMemo(() => financialYearChoicesAround(), []);
  const [fy, setFy] = useState(fyChoices[0]);
  const [working, setWorking] = useState<MSME43BHWorking | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // MSMED §16 charges THREE TIMES the RBI Bank Rate, and nothing in this
  // product holds that rate: it moves by notification partway through a year,
  // so a delay spanning a change is governed by more than one. It is the CA's
  // own figure, typed here — the shape the DTAA treaty rates use. Empty means
  // the server refuses the charge and names what to look up, which is a
  // different thing from a nil charge.
  const [bankRate, setBankRate] = useState("");

  useEffect(() => { getClients().then(setClients).catch(() => setClients([])); }, []);

  const load = useCallback(async () => {
    if (!clientId || !fy) { setWorking(null); return; }
    setLoading(true);
    setError(null);
    try {
      // bpsFromPercentInput is the one parser for a typed percentage; a bare
      // parseFloat here is the money-parser defect wearing a rate's clothes.
      const bps = bankRate.trim() === "" ? undefined : bpsFromPercentInput(bankRate);
      const r = await api.incomeTax.msme43bh(clientId, fy, bps ?? undefined);
      if (!r.success) { setWorking(null); setError(r.error ?? "Could not compute the §43B(h) working"); return; }
      setWorking(r.data);
    } catch (e) {
      setWorking(null);
      setError(e instanceof Error ? e.message : "Could not compute the §43B(h) working");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy, bankRate]);

  useEffect(() => { load(); }, [load]);

  const rows = working?.bills ?? [];

  function exportExcel() {
    if (!working) return;
    const sheet = working.bills.map(b => ({
      Supplier: b.vendor_name,
      "Bill No": b.bill_no ?? "",
      "Bill Date": b.bill_date ?? "",
      "MSMED s.15 limit (days)": b.limit_days ?? "",
      "Due by": b.due_by ?? "",
      "Invoice total (Rs)": moneyCell(b.total_paise),
      "Deduction claimed (Rs)": moneyCell(b.deductible_paise),
      "Paid in time (Rs)": moneyCell(b.paid_in_time_paise),
      "Paid late (Rs)": moneyCell(b.paid_late_paise),
      "Still unpaid (Rs)": moneyCell(b.unpaid_paise),
      "Disallowed this year (Rs)": moneyCell(b.disallowed_paise),
      Basis: b.reason,
    }));
    const wb = buildWorkbook(XLSX, {
      rows: sheet,
      moneyColumns: ["Invoice total (Rs)", "Deduction claimed (Rs)", "Paid in time (Rs)",
                     "Paid late (Rs)", "Still unpaid (Rs)", "Disallowed this year (Rs)"],
      sheetName: "43B(h)",
    });
    XLSX.writeFile(wb, `msme_43bh_${working.financial_year}.xlsx`);
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-ps-hint hover:text-ps-label"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-ps-ink">MSME §43B(h)</h1>
          <p className="text-sm text-ps-label mt-0.5">
            Sums payable to micro and small enterprises beyond the MSMED §15 limit,
            read from the purchase ledger
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={exportExcel} disabled={rows.length === 0}>
          <Download size={14} className="mr-1" /> Export
        </Button>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="min-w-[240px]">
          <ClientLookup
            clients={clients}
            value={clientId}
            onChange={(id) => setClientId(id)}
            ariaLabel="Client"
            placeholder="Select a client"
          />
        </div>
        <YearPicker value={fy} onChange={setFy} className="w-auto" />
        <div className="flex items-center gap-2">
          <label htmlFor="bank-rate" className="text-xs text-ps-label whitespace-nowrap">
            RBI Bank Rate
          </label>
          <input
            id="bank-rate"
            inputMode="decimal"
            placeholder="6.75"
            title="MSMED §16 charges three times this. Not the repo rate and not a lending rate."
            className="w-[90px] border border-ps-border rounded-lg px-3 py-2 text-sm tabular-nums outline-none focus:border-blue-500"
            value={bankRate}
            onChange={e => setBankRate(e.target.value)}
          />
          <span className="text-xs text-ps-hint">%</span>
        </div>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

      {!clientId && (
        <div className="bg-ps-bg border border-ps-border rounded-xl px-5 py-4 text-sm text-ps-label">
          §43B(h) is a figure in one client&apos;s tax computation. Pick a client.
        </div>
      )}

      {working && !working.applicable && (
        <div className="bg-ps-bg border border-ps-border rounded-xl px-5 py-4 text-sm text-ps-label">
          {working.caveats[0]}
        </div>
      )}

      {working?.applicable && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className={`rounded-xl px-5 py-4 border ${working.disallowed_paise > 0
              ? "bg-state-problem-surface border-state-problem-border" : "bg-ps-bg border-ps-border"}`}>
              <p className="text-xs text-ps-label">Added back to taxable income, FY {working.financial_year}</p>
              <p className={`text-2xl font-bold tabular-nums mt-1 ${working.disallowed_paise > 0
                ? "text-state-problem" : "text-ps-ink"}`}>
                {formatPaise(working.disallowed_paise)}
              </p>
              <p className="text-xs text-ps-label mt-1">
                Bills that accrued this year and were not paid within their own MSMED §15 limit.
              </p>
            </div>
            <div className="rounded-xl px-5 py-4 border bg-ps-bg border-ps-border">
              <p className="text-xs text-ps-label">Allowed back this year, on payment</p>
              <p className="text-2xl font-bold tabular-nums mt-1 text-ps-ink">
                {formatPaise(working.allowed_on_payment_paise)}
              </p>
              <p className="text-xs text-ps-label mt-1">
                Earlier years&apos; bills that were disallowed then and were actually paid during
                this year.
              </p>
            </div>
          </div>

          {/* MSMED §16 — A DEBT, NOT A DEFERRAL, and the second number this screen
              exists to show. §43B(h) above moves a deduction between years;
              §16 makes the client liable to the SUPPLIER for compound interest
              at three times the Bank Rate, and §23 then disallows that
              interest outright, so paying it never releases it. */}
          <MsmedInterestPanel interest={working.msmed_interest} />

          {working.gaps.length > 0 && (
            <Callout tone="attention"
                     title={`${working.gaps.length} supplier${working.gaps.length !== 1 ? "s are" : " is"} not in this working, and should be`}>
              <ul className="space-y-1">
                {working.gaps.map((g, i) => <li key={i}>{g}</li>)}
              </ul>
              <p className="pt-1.5">
                Record it on the client&apos;s Schedule III ageing screen, then recompute.
              </p>
            </Callout>
          )}

          <div className="bg-ps-bg border border-ps-border rounded-xl px-5 py-4 space-y-1.5">
            <div className="flex items-start gap-2">
              <Info size={15} className="text-ps-hint shrink-0 mt-0.5" />
              <div className="space-y-1.5">
                {working.caveats.map((c, i) => (
                  <p key={i} className="text-xs text-ps-label">{c}</p>
                ))}
                <p className="text-2xs text-ps-hint">{working.source}</p>
              </div>
            </div>
          </div>

          <Card>
            {loading ? (
              <TableSkeleton cols={8} bare />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[980px]">
                  <thead>
                    <tr className="border-b border-ps-muted text-xs text-ps-hint">
                      <th className="px-5 py-3 text-left">Supplier</th>
                      <th className="px-3 py-3 text-left">Bill</th>
                      <th className="px-3 py-3 text-left">Bill date</th>
                      <th className="px-3 py-3 text-left">§15 limit</th>
                      <th className="px-3 py-3 text-left">Due by</th>
                      <th className="px-3 py-3 text-right">Deduction</th>
                      <th className="px-3 py-3 text-right">Unpaid</th>
                      <th className="px-5 py-3 text-right">Disallowed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ps-bg">
                    {rows.length === 0 && (
                      <tr><td colSpan={8} className="text-center text-ps-hint py-8 text-sm">
                        No purchase bills for this client.
                      </td></tr>
                    )}
                    {rows.map(b => (
                      <tr key={b.bill_id} className={b.disallowed_paise > 0 ? "bg-state-problem-surface/40" : ""}>
                        <td className="px-5 py-3 text-sm font-medium text-ps-ink">{b.vendor_name}</td>
                        <td className="px-3 py-3 text-xs font-mono text-ps-label">{b.bill_no ?? "—"}</td>
                        <td className="px-3 py-3 text-xs text-ps-label">{b.bill_date ?? "—"}</td>
                        <td className="px-3 py-3 text-xs text-ps-label" title={b.limit_source}>
                          {b.limit_days == null ? "—" : `${b.limit_days} days`}
                        </td>
                        <td className="px-3 py-3 text-xs text-ps-label">{b.due_by ?? "—"}</td>
                        <td className="px-3 py-3 text-sm tabular-nums text-right">{formatPaise(b.deductible_paise)}</td>
                        <td className="px-3 py-3 text-sm tabular-nums text-right">{formatPaise(b.unpaid_paise)}</td>
                        <td className="px-5 py-3 text-sm tabular-nums text-right font-medium">
                          {b.disallowed_paise > 0
                            ? <span className="text-state-problem">{formatPaise(b.disallowed_paise)}</span>
                            : <span className="inline-flex items-center gap-1 text-ps-hint" title={b.reason}>
                                <CheckCircle size={12} /> —
                              </span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * MSMED §16 — the DEBT a late payment creates.
 *
 * This is deliberately a SECOND panel and not another tile beside the §43B(h)
 * figures, because it is a different KIND of number and netting them would be
 * wrong twice over:
 *
 *   §43B(h)  moves a DEDUCTION into the year the sum is actually paid. The
 *            money is the client's own tax, and paying the supplier releases
 *            it.
 *   §16      makes the client LIABLE TO THE SUPPLIER for compound interest
 *            with monthly rests at three times the RBI Bank Rate, and §23
 *            then disallows that interest outright — so paying it never
 *            releases it, and it is owed to somebody else entirely.
 *
 * THE CHARGE IS NULL WHERE NO BANK RATE WAS GIVEN, AND A NULL IS NOT A NIL.
 * Nothing in this product holds the Bank Rate: it moves by RBI notification
 * partway through a year, so a delay spanning a change is governed by more
 * than one. The working still renders — which bills are accruing, since when,
 * over how many rests — because that is useful before anybody looks a rate up,
 * and a panel that shows nothing until a figure is typed reads as broken.
 */
function MsmedInterestPanel({ interest }: { interest: MSMEDInterest }) {
  const rows = interest.amounts;
  const charged = interest.charged_rate_bps;
  const unknownRate = interest.interest_paise === null;

  if (rows.length === 0) {
    return (
      <div className="bg-ps-bg border border-ps-border rounded-xl px-5 py-4">
        <p className="text-sm font-semibold text-ps-ink">MSMED §16 interest</p>
        <p className="text-xs text-ps-label mt-1">
          No amount has missed its MSMED §15 limit, so §16 charges nothing.
        </p>
      </div>
    );
  }

  return (
    <div className={`rounded-xl border ${unknownRate
      ? "bg-state-attention-surface border-state-attention-border" : "bg-ps-surface border-ps-border"}`}>
      <div className="px-5 py-4 border-b border-ps-border">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-ps-ink">
              MSMED §16 — interest owed to the supplier
            </p>
            <p className="text-xs text-ps-label mt-0.5">
              Compound interest with monthly rests, at three times the RBI Bank Rate.
              {charged !== null && (
                <> Charged at <strong className="tabular-nums">
                  {(charged / 100).toFixed(2)}%
                </strong> a year.</>
              )}
            </p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-xs text-ps-label">As at {interest.as_at ?? "—"}</p>
            <p className="text-2xl font-bold tabular-nums mt-0.5 text-ps-ink">
              {unknownRate ? "—" : formatPaise(interest.interest_paise ?? 0)}
            </p>
          </div>
        </div>
      </div>

      {interest.gaps.length > 0 && (
        <div className="px-5 py-3 bg-state-attention-surface/60 border-b border-state-attention-border/60 space-y-1">
          {interest.gaps.map((g, i) => (
            <p key={i} className="text-xs text-state-attention">{g}</p>
          ))}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[820px]">
          <thead>
            <tr className="border-b border-ps-border bg-ps-bg">
              <th className="px-3 py-2 text-left text-2xs font-semibold text-ps-label uppercase">Supplier</th>
              <th className="px-3 py-2 text-left text-2xs font-semibold text-ps-label uppercase">Bill</th>
              <th className="px-3 py-2 text-right text-2xs font-semibold text-ps-label uppercase">Amount</th>
              <th className="px-3 py-2 text-left text-2xs font-semibold text-ps-label uppercase">Interest from</th>
              <th className="px-3 py-2 text-left text-2xs font-semibold text-ps-label uppercase">To</th>
              <th className="px-3 py-2 text-right text-2xs font-semibold text-ps-label uppercase">Rests</th>
              <th className="px-3 py-2 text-right text-2xs font-semibold text-ps-label uppercase">Interest</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a, i) => (
              <tr key={`${a.bill_id}-${i}`} className="border-b border-ps-muted last:border-0">
                <td className="px-3 py-2.5 text-ps-ink">{a.vendor_name}</td>
                <td className="px-3 py-2.5 text-ps-label">{a.bill_no ?? "—"}</td>
                <td className="px-3 py-2.5 tabular-nums text-right">{formatPaise(a.principal_paise)}</td>
                <td className="px-3 py-2.5 text-ps-label tabular-nums">{a.from_date ?? "—"}</td>
                <td className="px-3 py-2.5 text-ps-label tabular-nums">
                  {a.to_date ?? "—"}
                  {a.still_running && (
                    <span className="ml-1.5 text-3xs text-state-attention">still accruing</span>
                  )}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-right" title={a.reason}>
                  {a.months}
                  {a.part_days > 0 && (
                    /* A part month is a rest that has not fallen due, so it is
                       reported and NOT charged — shown so the figure below can
                       be reconciled rather than looking arbitrary. */
                    <span className="text-3xs text-ps-hint"> +{a.part_days}d</span>
                  )}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-right font-medium">
                  {a.interest_paise === null
                    ? <span className="text-ps-hint">—</span>
                    : formatPaise(a.interest_paise)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 border-t border-ps-border space-y-1.5 bg-ps-bg">
        {interest.caveats.map((c, i) => (
          <p key={i} className="text-xs text-ps-label">{c}</p>
        ))}
      </div>
    </div>
  );
}
