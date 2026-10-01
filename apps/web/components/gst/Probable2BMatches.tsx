"use client";

/**
 * PROBABLE MATCHES — two rows the 2B reconciliation could not tie together and
 * that may be one invoice (gst-12).
 *
 * A SUGGESTION AND NEVER A LINK. The reconciliation is exact on purpose (the
 * supplier's GSTIN plus the folded number, and the AMOUNT is never fuzzy: a
 * tolerance on the tax is a tolerance on the credit claimed). So a bill booked
 * under a supplier GSTIN with one character wrong comes back as two unrelated
 * rows — "supplier has not filed" for the bill, "no bill in the books" for the
 * document the supplier DID file — and the CA used to be left to notice. This
 * panel says the two may be one, and what to check.
 *
 * It changes nothing and offers no button that does. The bill stays unmatched
 * and its credit stays withheld until the CA corrects the document (the
 * supplier's GSTIN, or the bill number) and runs the reconciliation again —
 * which is the only thing that can turn a suggestion into a match. The server
 * decides which pairs are probable and writes the sentences; this renders them
 * and holds no list of kinds.
 */

import Link from "next/link";
import type { ProbableMatch2B } from "@/lib/api";
import { documentHref } from "@/lib/accounting/sourceDocument";
import { formatPaise } from "@/lib/money/format";

const GRADE_LABEL: Record<ProbableMatch2B["grade"], string> = {
  strong: "Strong",
  possible: "Possible",
};

export function Probable2BMatches({
  clientId, matches,
}: { clientId: string; matches: ProbableMatch2B[] }) {
  if (matches.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="gstr2b-probable">
      <div>
        <p className="text-sm font-medium text-ps-body">
          Probably the same invoice — check before you chase a supplier
        </p>
        <p className="text-xs text-ps-label">
          Each pair below is one of your bills the supplier is not shown to have
          filed, next to a document the supplier DID file that you have no bill
          for. These are suggestions and change nothing: the credit stays
          withheld until the bill is corrected and the reconciliation is run
          again.
        </p>
      </div>
      <ul className="space-y-2">
        {matches.map((p, i) => (
          <li key={`${p.bill_id}-${p.document_number}-${i}`}
            className="border rounded p-3 space-y-1.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className={p.grade === "strong"
                ? "font-medium text-state-attention" : "font-medium text-ps-label"}>
                {GRADE_LABEL[p.grade] ?? p.grade} match
              </span>
              <Link href={documentHref(clientId, "purchases", "bills", p.bill_id)}
                className="underline text-ps-label">
                Open the bill
              </Link>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <p className="text-ps-hint">In your books</p>
                <p>
                  {p.bill_no || "(no number)"} · {p.bill_date ?? "no date"}
                </p>
                <p className="text-3xs text-ps-hint">
                  {p.bill_supplier_gstin || "no GSTIN recorded"} · tax {formatPaise(p.book_tax_paise)}
                </p>
              </div>
              <div>
                <p className="text-ps-hint">On GSTR-2B</p>
                <p>
                  {p.document_number} · {p.document_date ?? "no date"}
                </p>
                <p className="text-3xs text-ps-hint">
                  {p.document_supplier_name ? `${p.document_supplier_name} · ` : ""}
                  {p.document_supplier_gstin} · tax {formatPaise(p.portal_tax_paise)}
                </p>
              </div>
            </div>
            <ul className="list-disc pl-4 text-ps-label">
              {p.evidence.map((e, j) => <li key={j}>{e}</li>)}
            </ul>
            <p className="text-ps-body">{p.action}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
