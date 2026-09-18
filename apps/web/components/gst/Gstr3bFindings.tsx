"use client";

/**
 * The three parts of a GSTR-3B's face that are not figures, rendered once
 * (GST-22).
 *
 * WHAT WAS WRONG
 *     All three come back from `POST /api/gst/gstr3b/from-books` and were
 *     spelled out inline on the per-client GST tab. The firm-level
 *     `/gst/gstr3b` screen showed NONE of them — `computeGSTR3B` dropped the
 *     keys on the way through — so the two GSTR-3B screens disagreed about how
 *     much of the return they show, and a CA reviewing on the firm screen saw
 *     nothing for Table 5.1, nothing for the rows filed nil because nothing
 *     here can derive them, and nothing for the bank lines they had marked as
 *     carrying GST.
 *
 * EVERY SENTENCE IS THE SERVER'S. Nothing here decides which rows are listed,
 * what the interest is, or whether the late fee can be stated — the engines are
 * `domain/gst/late_filing.py` and `services/gst_return_service._undeclarable_
 * rows`, and this renders what they said. The same arrangement as
 * `Gstr1Findings`.
 */
import type {
  BankLineTotals, GLReconciliation, LateFilingBlock, ReturnPeriodWindow,
  UndeclarableRow,
} from "@/lib/data/gst";

function rupees(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** WHAT PERIOD THIS RETURN COVERS (GST-11).
 *
 *  CGST Rule 61A with the proviso to s.39(1) lets a registered person with up
 *  to Rs 5 crore of preceding-year turnover furnish GSTR-1 and GSTR-3B
 *  QUARTERLY (QRMP). The engine could not express a quarter at all, so a CA
 *  with such a client was quoted the quarterly due date and then had to add
 *  three monthly GSTR-3Bs by hand.
 *
 *  Now that it can, the screen has to SAY which window it computed — a CA who
 *  picked "April" and got April to June, or picked "June" and got a return
 *  keyed on April, has to be able to see why. Rendered only on a quarter: a
 *  monthly filer gets the month they asked for and needs no sentence. Every
 *  word is the server's; the frequency is a fact about the REGISTRATION and
 *  nothing here decides it. */
export function Gstr3bPeriodWindow({
  periodWindow: w, monthsWithout2b = [],
}: { periodWindow?: ReturnPeriodWindow; monthsWithout2b?: string[] }) {
  // NOT named `window` — `apps/web` is a static export and nothing may touch
  // the global during render, so the name is kept away from the component.
  if (!w || w.frequency !== "quarterly") return null;
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm space-y-1">
      <p className="font-medium text-indigo-900">
        Quarterly return (QRMP) — {w.label}
      </p>
      <p className="text-2xs text-indigo-800">
        This registration furnishes quarterly under CGST Rule 61A, so the
        figures above cover {w.start} to {w.end} — {w.months_covered} months,
        not one. It is stored and locked under period {w.key}, the quarter&apos;s
        first month.
      </p>
      {monthsWithout2b.length > 0 && (
        <p className="text-2xs text-indigo-800 border-t border-indigo-200 pt-1">
          No GSTR-2B has been reconciled for {monthsWithout2b.join(", ")}. A
          quarter has one 2B per month and the Rule 36(4) ceiling is built from
          the ones on file, so the credit available above is short by whatever
          those months hold.
        </p>
      )}
    </div>
  );
}

/** TABLE 5.1 — WHAT BEING LATE COSTS (GST-21).
 *
 *  The interest is computed PER HEAD on the CASH payable, not on the gross
 *  output tax: Rule 88B(1) charges only "that portion of the tax which is paid
 *  by debiting the electronic cash ledger", so a head the credit ledger
 *  discharged in full bears none however late the return is. The LATE FEE is a
 *  refusal, and the sentence naming the notification to read is the server's —
 *  §47's notified rates are not held, and a fee written from memory is a number
 *  a CA would pay over. */
export function Gstr3bLateFiling({ lateFiling }: { lateFiling?: LateFilingBlock }) {
  const lf = lateFiling;
  if (!lf) return null;
  if (!lf.available) {
    return <p className="text-xs text-ps-hint border-t pt-2">{lf.reason}</p>;
  }
  const heads = (lf.interest_by_head ?? []).filter((h) => h.base_paise > 0);
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm space-y-1">
      <p className="font-medium text-amber-900">
        Table 5.1 — {lf.days_late} day{lf.days_late === 1 ? "" : "s"} after the
        due date of {lf.due_date}
      </p>
      <div className="flex justify-between text-amber-900">
        <span>§50(1) interest at 18% on the cash payable</span>
        <span className="font-mono">{rupees(lf.interest_total_paise ?? 0)}</span>
      </div>
      {heads.length > 0 && (
        <table className="w-full text-2xs text-amber-800">
          <tbody>
            {heads.map((h) => (
              <tr key={h.head}>
                <td className="uppercase py-0.5">{h.head}</td>
                <td className="py-0.5">{rupees(h.base_paise)} × 18% × {h.days}/365</td>
                <td className="py-0.5 text-right font-mono">{rupees(h.interest_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {lf.late_fee?.refused ? (
        <p className="text-2xs text-amber-800 border-t border-amber-200 pt-1">
          {lf.late_fee.reason}
        </p>
      ) : (
        <div className="flex justify-between text-amber-900 border-t border-amber-200 pt-1">
          <span>§47 late fee</span>
          <span className="font-mono">{rupees(lf.late_fee?.fee_paise ?? 0)}</span>
        </div>
      )}
      {(lf.caveats ?? []).map((c, i) => (
        <p key={i} className="text-2xs text-amber-700">{c}</p>
      ))}
    </div>
  );
}

/** WHAT THE BANK LINES PUT ON THIS RETURN (BANK-24).
 *
 *  A charge the CA marked as carrying GST posts a real Dr GST Input leg, so the
 *  credit was already in the ledger — it just never reached Table 4(A), and the
 *  same rupees came back as an unexplained books-vs-ledger difference every
 *  month. The two sentences underneath are the half that cannot be computed:
 *  §16(2)(aa) wants a supplier document a bank line does not carry, and an
 *  outward supply with no tax invoice will not be in the GSTR-1 the portal
 *  compares this return against. Both come from the server. */
export function Gstr3bBankLines({
  reconciliation, caveats,
}: { reconciliation?: GLReconciliation; caveats?: string[] }) {
  const bank = (reconciliation as Record<string, unknown> | undefined)
    ?.bank_lines as BankLineTotals | undefined;
  const notes = caveats ?? [];
  if (!bank || (!bank.itc_paise && !bank.output_tax_paise)) return null;
  return (
    <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm space-y-1">
      <p className="font-medium text-sky-900">From bank lines you marked as carrying GST</p>
      {(bank.itc_paise ?? 0) > 0 && (
        <div className="flex justify-between text-sky-900">
          <span>
            Input credit in Table 4(A)(5) — {bank.inward_line_count} line
            {bank.inward_line_count === 1 ? "" : "s"}
          </span>
          <span className="font-mono">{rupees(bank.itc_paise ?? 0)}</span>
        </div>
      )}
      {(bank.output_tax_paise ?? 0) > 0 && (
        <div className="flex justify-between text-sky-900">
          <span>
            Output tax in Table 3.1(a) — {bank.outward_line_count} line
            {bank.outward_line_count === 1 ? "" : "s"}
          </span>
          <span className="font-mono">{rupees(bank.output_tax_paise ?? 0)}</span>
        </div>
      )}
      {notes.map((c, i) => (
        <p key={i} className="text-2xs text-sky-800 border-t border-sky-200 pt-1">{c}</p>
      ))}
    </div>
  );
}

/** ROWS THIS RETURN DECLARES NIL AND CANNOT DERIVE.
 *
 *  A nil that means "this client had none" and a nil that means "this product
 *  cannot see it" look identical on a filed return. Each row already carried
 *  its reason in a SOURCE COMMENT next to the literal zero — the right place
 *  for the next programmer and no place at all for the CA about to file. The
 *  server's `undeclarable_rows` is the superset (it CALLS `_table_4a_gaps`
 *  rather than restating it) and this is where it is shown. */
export function Gstr3bUndeclarableRows({ rows = [] }: { rows?: UndeclarableRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm space-y-2">
      <p className="font-medium text-ps-body">
        Nil because this product cannot derive it — {rows.length} row
        {rows.length === 1 ? "" : "s"}
      </p>
      <p className="text-2xs text-ps-label">
        These are filed as nil. That is correct for a client with none, and wrong
        for a client with any — nothing here can tell the two apart, so
        check each on the portal before you file.
      </p>
      <ul className="space-y-1.5">
        {rows.map((g) => (
          <li key={g.row} className="border-t border-slate-200 pt-1.5">
            <span className="font-mono text-xs text-ps-body">Table {g.row}</span>
            <span className="text-xs text-ps-label"> — {g.label}</span>
            <p className="text-2xs text-ps-label mt-0.5">{g.reason}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** In the order the return is reviewed: WHAT PERIOD it covers, then what it
 *  costs to be late, what the bank lines added, then what is nil because
 *  nobody can see it. The window comes first because every figure below it is
 *  a figure for that window. */
export function Gstr3bFindings({
  lateFiling, reconciliation, bankLineCaveats, undeclarableRows,
  periodWindow, monthsWithout2b,
}: {
  lateFiling?: LateFilingBlock;
  reconciliation?: GLReconciliation;
  bankLineCaveats?: string[];
  undeclarableRows?: UndeclarableRow[];
  periodWindow?: ReturnPeriodWindow;
  monthsWithout2b?: string[];
}) {
  return (
    <>
      <Gstr3bPeriodWindow periodWindow={periodWindow}
                          monthsWithout2b={monthsWithout2b} />
      <Gstr3bLateFiling lateFiling={lateFiling} />
      <Gstr3bBankLines reconciliation={reconciliation} caveats={bankLineCaveats} />
      <Gstr3bUndeclarableRows rows={undeclarableRows} />
    </>
  );
}
