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
 *   2. FILED AS RECORDED next. The other kind of gap: the row IS in the
 *      payload and something about it is being reported — the HSN digits, the
 *      unit quantity code, a caveat about the return itself. These used to be
 *      rendered under heading 1, which says the opposite of what their own
 *      reasons say ("Table 12 files the code exactly as recorded"), so a CA
 *      read them as documents missing from a return that carries them. The
 *      server decides which group a gap is in (`PayloadGap.withheld`); this
 *      component holds no list of kinds.
 *
 *      AND THE TWO GROUPS NOW WEAR DIFFERENT TONES, WHICH IS THE POINT.
 *      "Not declared" used to render RED and "filed as recorded" AMBER — the
 *      same two colours as the errors and the warnings below, so four
 *      different things read as two. `Callout`'s `withheld` tone is slate: it
 *      is a statement about what this product could not SEE, not about the
 *      client's tax position, and giving it a warning colour made a CA read
 *      a product limitation as a defect in their own return.
 *   3. ERRORS next, and separately from warnings. These are what the portal
 *      REJECTS: folding them in with the warnings would make a rejection look
 *      like a judgement call.
 *   4. WARNINGS last.
 *
 * It renders NOTHING when all of them are empty. A "no problems found" banner
 * would be a claim about checks this component does not run — the reconciliation
 * banner beside it is the one that speaks to whether the build agrees with the
 * ledger.
 */
"use client";

import { Callout, GapList } from "@/components/ui/callout";
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
  // TWO KINDS OF GAP, AND THE SERVER SAYS WHICH. A gap is either a document
  // the payload does not carry or a report about a row it does — the second
  // kind's own reasons say "Table 12 files the code exactly as recorded",
  // which the heading "Not declared in this return" contradicted. An absent
  // `withheld` reads as withheld, so a backend that has not redeployed yet
  // renders exactly as before.
  const withheld = gaps.filter((g) => g.withheld !== false);
  const reported = gaps.filter((g) => g.withheld === false);
  return (
    <>
      <GapList
        className={block}
        gaps={withheld}
        tone="withheld"
        title="Not declared in this return"
      />
      <GapList
        className={block}
        gaps={reported}
        tone="attention"
        title="Filed as recorded — check before submitting"
      />
      {errors.length > 0 && (
        <Callout
          className={block}
          tone="problem"
          title="Errors — the portal will reject these"
        >
          <ul className="space-y-1.5">
            {errors.map((e, i) => (
              <li key={i}>
                {e.invoice_ref && <span className="mr-1 font-mono">[{e.invoice_ref}]</span>}
                {e.message}
              </li>
            ))}
          </ul>
        </Callout>
      )}
      {warnings.length > 0 && (
        <Callout className={block} tone="attention" title="Warnings">
          <ul className="space-y-1.5">
            {warnings.map((w, i) => (
              <li key={i}>
                {w.invoice_ref && <span className="mr-1 font-mono">[{w.invoice_ref}]</span>}
                {w.message}
              </li>
            ))}
          </ul>
        </Callout>
      )}
    </>
  );
}
