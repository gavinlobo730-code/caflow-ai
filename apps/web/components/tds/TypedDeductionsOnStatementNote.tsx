"use client";

/**
 * The deductions typed on the TDS screen that this statement CARRIES (POST-A-078).
 *
 * A 26Q built from the books carries the deductions typed on the TDS screen beside the purchase bills and advances, each as a deductee row under the challan that
 * paid it. Nothing records which journal, if any, carries a typed deduction, so the statement's tie-out with the TDS Payable account compares the bills and advances alone: a screen that
 * says "reconciled to the General Ledger" over a total that holds typed tax would read as a claim about all of it. This note says how many typed deductions the
 * statement carries, how much tax they withheld, and, in the server's own sentence, that they are outside the tie-out (and, where it applies, which name no supplier,
 * whose payee's residence is not recorded, or which look like a bill on the statement), and (folded away) which they are.
 *
 * Nothing is added up here: every figure is the server's (`lib/tds/excludedTyped.ts` reads it; the shape is the same as the note of what the statement leaves out). An
 * answer that is THERE and cannot be read is said to be unreadable, because silence would read as "none". Both return screens draw this one component, as they draw
 * `TypedDeductionsNote` for the rows the statement leaves out.
 */
import { readExcludedTyped } from "@/lib/tds/excludedTyped";
import { formatPaise } from "@/lib/money/format";
import { formatDate } from "@/lib/dates/format";

export function TypedDeductionsOnStatementNote({ raw }: { raw: unknown }) {
  const reading = readExcludedTyped(raw);
  if (reading.kind === "none" || reading.kind === "absent") return null;
  if (reading.kind === "unreadable") {
    return (
      <p className="text-xs text-state-attention bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3">
        The note of the deductions typed on the TDS screen that this statement carries could not be read from the server&apos;s answer, so it does not say which of
        its deductee rows have no journal behind them.
      </p>
    );
  }
  const { typed } = reading;
  const one = typed.count === 1;
  return (
    <div className="bg-ps-bg border border-ps-border rounded-xl px-4 py-3 space-y-2">
      <p className="text-xs text-ps-body">
        <strong>{typed.count} deduction{one ? "" : "s"}</strong> typed on the TDS screen for this quarter, with{" "}
        <strong>{formatPaise(typed.tds_paise)}</strong> of tax withheld, {one ? "is" : "are"} on this statement.{typed.reason ? ` ${typed.reason}` : ""}
      </p>
      {typed.rows && (
        <details>
          <summary className="text-xs font-medium text-ps-body cursor-pointer">
            {one ? "Show the deduction" : `Show the ${typed.count} deductions`}
          </summary>
          {/* The list scrolls sideways in its own box on a narrow screen, so the box can be reached from the keyboard and says what it holds. */}
          <div role="region" aria-label="Deductions typed on the TDS screen that are on this statement" tabIndex={0}
            className="mt-2 overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            <table className="w-full text-xs text-ps-body">
              <caption className="sr-only">Deductions typed on the TDS screen for this quarter that are on this statement</caption>
              <thead>
                <tr className="text-left text-ps-label">
                  <th scope="col" className="pr-3 py-1 font-medium">Date</th>
                  <th scope="col" className="pr-3 py-1 font-medium">Payee</th>
                  <th scope="col" className="pr-3 py-1 font-medium text-right">Tax withheld</th>
                  <th scope="col" className="pr-3 py-1 font-medium text-right">Payment</th>
                  <th scope="col" className="pr-3 py-1 font-medium">Section</th>
                  <th scope="col" className="py-1 font-medium">PAN</th>
                </tr>
              </thead>
              <tbody>
                {typed.rows.map((row, i) => (
                  <tr key={row.id ?? i} className="border-t border-ps-border">
                    <td className="pr-3 py-1 whitespace-nowrap">{formatDate(row.transaction_date)}</td>
                    <td className="pr-3 py-1">{row.deductee_name || "—"}</td>
                    <td className="pr-3 py-1 text-right whitespace-nowrap">{formatPaise(row.tds_paise)}</td>
                    <td className="pr-3 py-1 text-right whitespace-nowrap">{formatPaise(row.payment_amount_paise)}</td>
                    <td className="pr-3 py-1 whitespace-nowrap">
                      {row.section || "—"}
                      {row.section_1961 && row.section_1961 !== row.section ? ` (${row.section_1961})` : ""}
                    </td>
                    <td className="py-1 font-mono whitespace-nowrap">{row.deductee_pan || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
