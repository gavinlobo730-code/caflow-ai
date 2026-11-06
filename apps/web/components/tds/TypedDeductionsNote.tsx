"use client";

/**
 * The deductions typed on the TDS screen that this statement leaves out (POST-A-078).
 *
 * A 26Q built from the books carries posted purchase bills and withholding advances only. A deduction a CA typed on the TDS screen is a register row that neither a bill
 * nor an advance wrote, so it is not on the statement, and a statement that says nothing about them reads as a complete one while the register holds tax withheld for the
 * same quarter. This note says how many there are, how much tax they withheld, in the server's own sentence why they are not here, and (folded away) which they are.
 *
 * Nothing is added up here and nothing is added to the statement: every figure is the server's (`lib/tds/excludedTyped.ts` reads it and draws nothing it cannot read
 * whole). An answer that is THERE and cannot be read is said to be unreadable, because silence would read as "none". Both return screens draw this one component, so the
 * sentence cannot be two sentences.
 */
import { readExcludedTyped } from "@/lib/tds/excludedTyped";
import { formatPaise } from "@/lib/money/format";
import { formatDate } from "@/lib/dates/format";

export function TypedDeductionsNote({ raw }: { raw: unknown }) {
  const reading = readExcludedTyped(raw);
  if (reading.kind === "none" || reading.kind === "absent") return null;
  if (reading.kind === "unreadable") {
    return (
      <p className="text-xs text-state-attention bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3">
        The note of the deductions typed on the TDS screen for this quarter could not be read from the server&apos;s answer, so this statement does not say whether it
        leaves any out.
      </p>
    );
  }
  const { typed } = reading;
  const one = typed.count === 1;
  return (
    <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 space-y-2">
      <p className="text-xs text-blue-800">
        <strong>{typed.count} deduction{one ? "" : "s"}</strong> typed on the TDS screen for this quarter, with{" "}
        <strong>{formatPaise(typed.tds_paise)}</strong> of tax withheld, {one ? "is" : "are"} not on this statement.{typed.reason ? ` ${typed.reason}` : ""}
      </p>
      {typed.rows && (
        <details>
          <summary className="text-xs font-medium text-blue-800 cursor-pointer">
            {one ? "Show the deduction" : `Show the ${typed.count} deductions`}
          </summary>
          {/* The list scrolls sideways in its own box on a narrow screen, so the box can be reached from the keyboard and says what it holds. */}
          <div role="region" aria-label="Deductions typed on the TDS screen that are not on this statement" tabIndex={0}
            className="mt-2 overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            <table className="w-full text-xs text-ps-body">
              <caption className="sr-only">Deductions typed on the TDS screen for this quarter that are not on this statement</caption>
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
                  <tr key={row.id ?? i} className="border-t border-blue-100">
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
