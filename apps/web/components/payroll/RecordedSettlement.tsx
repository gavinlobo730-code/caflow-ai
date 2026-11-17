"use client";

/**
 * A leaver's full-and-final settlement AS IT WAS RECORDED (POST-A-096).
 *
 * The ledger names a settlement's journal by the settlement's own id, and until this nothing could open that id: the leaver's drawer
 * computes a NEW settlement and shows none that was recorded. This reads the stored row (`GET /api/payroll/settlements/{id}`) and
 * shows it whole: what was earned, what was exempt and under which clause, what was recovered, the tax withheld and what was paid.
 * Nothing is recomputed here or on the server, because a settlement is stored so the ledger, Annexure II and 24Q read one figure.
 *
 * A figure the row does not hold is a dash, never a zero, and an employee whose row cannot be read under this client is said to be
 * unknown rather than left blank.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { api, type RecordedSettlement } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/money/format";
import { formatDate } from "@/lib/dates/format";
import { journalEntryHref } from "@/lib/accounting/sourceDocument";
import { LoadingRegion } from "@/components/ui/skeleton";

type Load = { kind: "loading" } | { kind: "ok"; s: RecordedSettlement } | { kind: "failed"; why: string };

export default function RecordedSettlementDialog({ clientId, settlementId, onClose }: {
  clientId: string; settlementId: string; onClose: () => void;
}) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    setLoad({ kind: "loading" });
    api.payroll.getSettlement(settlementId, clientId)
      .then((res) => {
        const s = res?.success ? objectWithLists<RecordedSettlement>(res.data, "components") : null;
        if (!s) throw new Error(res?.error ?? "The settlement could not be read.");
        if (live) setLoad({ kind: "ok", s });
      })
      .catch((e) => {
        if (live) setLoad({ kind: "failed", why: e instanceof Error ? e.message : "The settlement could not be read." });
      });
    return () => { live = false; };
  }, [clientId, settlementId]);

  return (
    <Modal title="Recorded settlement" maxWidthClass="max-w-2xl" onClose={onClose}
      note="As it was recorded. Nothing on this page is recomputed.">
      {load.kind === "loading" && (
        <LoadingRegion label="Reading the settlement" className="text-xs text-ps-label">Reading the settlement…</LoadingRegion>
      )}
      {load.kind === "failed" && (
        <p role="alert" className="text-xs text-state-problem">{load.why}</p>
      )}
      {load.kind === "ok" && <SettlementBody clientId={clientId} s={load.s} />}
    </Modal>
  );
}

function SettlementBody({ clientId, s }: { clientId: string; s: RecordedSettlement }) {
  const earnings = s.components.filter((c) => c.kind === "earning");
  const recoveries = s.components.filter((c) => c.kind === "deduction");
  const who = s.employee
    ? `${s.employee.name ?? "Unnamed employee"}${s.employee.employee_code ? ` (${s.employee.employee_code})` : ""}`
    : "Not known: the employee's record could not be read under this client.";
  return (
    <div className="space-y-4 text-xs text-ps-body">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
        <dt className="text-ps-label">Employee</dt><dd data-testid="settlement-employee">{who}</dd>
        <dt className="text-ps-label">Last working day</dt><dd>{formatDate(s.leaving_date)}</dd>
        <dt className="text-ps-label">Financial year</dt><dd>{s.financial_year || "—"}</dd>
        <dt className="text-ps-label">Recorded</dt>
        <dd>{formatDate(s.recorded_at)}{s.recorded_by ? ` by ${s.recorded_by}` : ", by a member not named on the record"}</dd>
      </dl>

      <section aria-label="What was earned">
        <h3 className="font-semibold text-ps-ink mb-1">What was earned</h3>
        {earnings.length === 0 ? (
          <p className="text-ps-label">No earning is recorded on this settlement.</p>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-left text-ps-label">
                <th className="py-1 font-medium">Component</th>
                <th className="py-1 font-medium">Head</th>
                <th className="py-1 font-medium text-right">Gross</th>
                <th className="py-1 font-medium text-right">Exempt</th>
              </tr>
            </thead>
            <tbody>
              {earnings.map((c, i) => (
                <tr key={`e-${i}`} className="border-t border-ps-border">
                  <td className="py-1">{c.label}</td>
                  <td className="py-1">§{c.tax_head}{c.exempt_section ? `, exempt under ${c.exempt_section}` : ""}</td>
                  <td className="py-1 text-right tabular-nums">{formatPaise(c.gross_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{formatPaise(c.exempt_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {recoveries.length > 0 && (
        <section aria-label="What was recovered">
          <h3 className="font-semibold text-ps-ink mb-1">What was recovered</h3>
          <p className="text-ps-label mb-1">A recovery reduces what was paid. It does not reduce the salary earned.</p>
          <table className="w-full">
            <tbody>
              {recoveries.map((c, i) => (
                <tr key={`d-${i}`} className="border-t border-ps-border">
                  <td className="py-1">{c.label}</td>
                  <td className="py-1 text-right tabular-nums">{formatPaise(c.gross_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section aria-label="Totals">
        <h3 className="font-semibold text-ps-ink mb-1">Totals</h3>
        <dl className="grid grid-cols-[1fr_max-content] gap-x-4 gap-y-1 tabular-nums">
          <dt>Gross</dt><dd className="text-right">{formatPaise(s.gross_paise)}</dd>
          <dt>Exempt</dt><dd className="text-right">{formatPaise(s.exempt_paise)}</dd>
          <dt>Taxable as salary</dt><dd className="text-right">{formatPaise(s.taxable_paise)}</dd>
          <dt>Recovered</dt><dd className="text-right">{formatPaise(s.deductions_paise)}</dd>
          <dt>Tax withheld under section 192</dt><dd className="text-right">{formatPaise(s.tds_paise)}</dd>
          <dt className="font-semibold text-ps-ink">Paid to the employee</dt>
          <dd className="text-right font-semibold text-ps-ink" data-testid="settlement-net-paid">{formatPaise(s.net_paid_paise)}</dd>
        </dl>
      </section>

      <p data-testid="settlement-ledger">
        {s.posted && s.journal_entry_id ? (
          <Link className="text-brand underline" href={journalEntryHref(clientId, s.journal_entry_id)}>Open its ledger entry</Link>
        ) : (
          "No ledger entry is recorded against this settlement."
        )}
      </p>
    </div>
  );
}
