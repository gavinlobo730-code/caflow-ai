/**
 * What the GSTR-1 build did about the amendment tables (gst-33).
 *
 * CGST Act §37: a filed GSTR-1 can never be revised, so a correction to an
 * earlier period is declared in a LATER return's amendment tables — 9A for
 * invoices, 9C for credit and debit notes, 10 for B2C-others. Those used to come
 * from a SECOND route and a SECOND file, downloaded from the Amendments tab, so
 * a CA had to know which of two files carried the month's corrections; the one
 * the GSTR-1 screen built was the one without them.
 *
 * The main build carries them now, by default. This panel is the visible half of
 * that: it says how many were added, so a file never has amendments in it that
 * nobody was told about, and it says so when a build was asked to leave them out.
 *
 * ONE COMPONENT, TWO SCREENS — the firm-level /gst/gstr1 page and the client
 * workspace's "Compute from Books" panel — for `Gstr1Findings`' reason: two
 * renderings of one answer drift.
 *
 * NOTHING IS DECIDED HERE. Which table a correction goes in, whether its window
 * is still open and whether an earlier return already declared it are the
 * server's; this renders the counts it was served. An ABSENT block (a frontend
 * redeployed ahead of the backend) renders NOTHING, because "the server did not
 * say" is not "nothing was added", and an absent count is never shown as 0.
 */
import * as React from "react";
import { Callout } from "@/components/ui/callout";
import { arrayOrEmpty } from "@/lib/api/shape";
import type { GSTR1AmendmentsBlock } from "@/lib/data/gst";

/** A count the server sent, or null. Never 0 for "absent". */
function served(n: unknown): number | null {
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

export function Gstr1Amendments({ block }: { block?: GSTR1AmendmentsBlock | null }) {
  if (!block || typeof block !== "object" || typeof block.included !== "boolean") return null;

  if (!block.included) {
    return (
      <Callout tone="attention" title="This file carries no amendment tables">
        It was built without the corrections earlier returns may still be owed.
        Build it again with amendments included to add the ones this period has to
        declare (CGST Act §37) — otherwise check the Amendments tab before filing.
      </Callout>
    );
  }

  const added = served(block.counts?.amendments);
  const decisions = served(block.counts?.needs_decision);
  const already = served(block.counts?.already_declared);
  const sections = arrayOrEmpty<string>(block.sections);
  const sources = arrayOrEmpty<string>(block.source_periods);

  // A server that answered `included: true` with no count at all has said
  // nothing about how many — show nothing rather than a figure it did not give.
  if (added === null) return null;

  return (
    <div className="space-y-2" data-testid="gstr1-amendments">
      <Callout
        tone={added > 0 ? "attention" : "note"}
        title={added > 0
          ? `${added} amendment${added === 1 ? "" : "s"} added to this return`
          : "No amendments to add to this return"}
      >
        {added > 0 ? (
          <>
            Corrections to returns already filed, declared here because a filed
            GSTR-1 cannot be revised (CGST Act §37).
            {sections.length > 0 && <> Tables: <strong>{sections.join(", ")}</strong>.</>}
            {sources.length > 0 && <> From: <strong>{sources.join(", ")}</strong>.</>}
            {" "}Review them before you upload — untick “include amendments” and
            build again to leave them out.
          </>
        ) : (
          <>No earlier filed return has a correction still to declare in this one.</>
        )}
      </Callout>
      {already !== null && already > 0 && (
        <Callout tone="note">
          {already} earlier correction{already === 1 ? " was" : "s were"} already
          declared in a later return and {already === 1 ? "is" : "are"} not
          repeated here.
        </Callout>
      )}
      {decisions !== null && decisions > 0 && (
        <Callout tone="attention" title={`${decisions} document${decisions === 1 ? "" : "s"} need your decision`}>
          A document cancelled after filing has no single right correction (amend
          it to nil, or raise a credit note). It is listed on the Amendments tab
          and is NOT in this file.
        </Callout>
      )}
    </div>
  );
}
