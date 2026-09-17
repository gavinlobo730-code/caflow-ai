/**
 * What a computed GSTR-1 leaves out, gets wrong, or is unsure about.
 *
 * ONE COMPONENT, TWO SCREENS (GST-16). `gstr1_from_books` has run the validator
 * and reported `validation_errors`, `validation_warnings` and `payload_gaps`
 * since Phase 5 — and the CLIENT workspace's "Compute from Books" panel
 * rendered the reconciliation banner, the invoice count and two totals and
 * nothing else. So a CA computing a return from inside a client saw a green
 * "Reconciled to the General Ledger" tick on a return carrying a duplicate
 * invoice number, IGST on an intra-state supply, or a document the payload does
 * not carry at all. The firm-level /gst/gstr1 page had the whole panel; the one
 * a CA reaches from the client they are working on did not.
 *
 * Extracted rather than copied, because the copy is the defect this repository
 * keeps finding: two renderings of one answer drift, and the one nobody is
 * looking at is the one that goes stale.
 *
 * THE ORDER IS THE POINT AND IS NOT ALPHABETICAL.
 *
 *   1. NOT DECLARED first. A gap is a document the return does not carry at
 *      all — filing short is found out from the recipient, or from the annual
 *      return, months later. It is the only one of the three a CA cannot see
 *      any other way.
 *   2. ERRORS next, and separately from warnings. These are what the portal
 *      REJECTS: folding them in with the warnings would make a rejection look
 *      like a judgement call.
 *   3. WARNINGS last.
 *
 * It renders NOTHING when all three are empty. A "no problems found" banner
 * would be a claim about checks this component does not run — the reconciliation
 * banner beside it is the one that speaks to whether the build agrees with the
 * ledger.
 */
"use client";

import { AlertTriangle } from "lucide-react";
import type { ValidationError, PayloadGap } from "@/lib/data/gst";

export interface Gstr1FindingsProps {
  errors: ValidationError[];
  warnings: ValidationError[];
  gaps: PayloadGap[];
  /** Tightens the spacing where the panel sits inside a drawer rather than a page. */
  compact?: boolean;
}

export function Gstr1Findings({ errors, warnings, gaps, compact = false }: Gstr1FindingsProps) {
  if (!errors.length && !warnings.length && !gaps.length) return null;
  const block = compact ? "mt-3" : "mt-4";
  return (
    <>
      {gaps.length > 0 && (
        <div className={block}>
          <h4 className="text-xs font-semibold text-red-700 mb-2 flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5" />
            Not declared in this return
          </h4>
          <ul className="space-y-1.5">
            {gaps.map((g, i) => (
              <li key={i} className="text-xs text-red-700">
                <span className="font-mono mr-1">[{g.reference_no}]</span>
                <span className="font-medium mr-1">{g.kind}</span>
                {g.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {errors.length > 0 && (
        <div className={block}>
          <h4 className="text-xs font-semibold text-red-700 mb-2 flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5" />
            Errors — the portal will reject these
          </h4>
          <ul className="space-y-1.5">
            {errors.map((e, i) => (
              <li key={i} className="text-xs text-red-700">
                {e.invoice_ref && <span className="font-mono mr-1">[{e.invoice_ref}]</span>}
                {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {warnings.length > 0 && (
        <div className={block}>
          <h4 className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5" />
            Warnings
          </h4>
          <ul className="space-y-1.5">
            {warnings.map((w, i) => (
              <li key={i} className="text-xs text-amber-700">
                {w.invoice_ref && <span className="font-mono mr-1">[{w.invoice_ref}]</span>}
                {w.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

/** A one-line count for a header strip — "2 errors · 1 not declared". */
export function gstr1FindingCounts(
  errors: ValidationError[], warnings: ValidationError[], gaps: PayloadGap[],
): { label: string; tone: "red" | "amber" } | null {
  const parts: string[] = [];
  if (gaps.length) parts.push(`${gaps.length} not declared`);
  if (errors.length) parts.push(`${errors.length} error${errors.length !== 1 ? "s" : ""}`);
  if (warnings.length) parts.push(`${warnings.length} warning${warnings.length !== 1 ? "s" : ""}`);
  if (!parts.length) return null;
  // A GAP is red as well as an error: the return is short either way, and only
  // the reason differs.
  return { label: parts.join(" · "), tone: (gaps.length || errors.length) ? "red" : "amber" };
}
