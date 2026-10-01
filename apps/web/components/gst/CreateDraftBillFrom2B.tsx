"use client";

/**
 * "CREATE DRAFT BILL" on a GSTR-2B document the books have no bill for (gst-13).
 *
 * For a `missing_in_books` row this screen said "chase the document" and
 * stopped, while holding every figure a bill needs. The server drafts one from
 * its own stored row and the file it kept.
 *
 * WHAT IS SENT IS THE DOCUMENT'S ADDRESS AND NOTHING ELSE. No amount, no date
 * and no rate leaves this component — they are read server-side from what the
 * reconciliation stored, so the screen cannot ask for a bill the portal never
 * carried. The `period` here is the month the SERVER reported for the
 * reconciliation (`result.period`), not one typed: the upload screen has no box
 * to type a month in, deliberately.
 *
 * IT NEVER RECEIVES. The answer is a DRAFT, and the panel says so, links to it,
 * and says what is still the CA's: the HSN, unit and product GSTR-2B does not
 * carry, and the CGST §17(5) decision. Where the books' arithmetic does not
 * reproduce what the supplier filed, the server's own sentences are shown —
 * they are never reworded here and the figures are never adjusted.
 *
 * ONE CLICK, ONE BILL. The button is disabled while the request is in flight
 * and after it has succeeded; a second invoice with the same supplier number
 * would be refused by the server anyway (migration 313's index), but a refusal
 * is the wrong way to learn a double click happened.
 */

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Gstr2bDraftBill } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { documentHref } from "@/lib/accounting/sourceDocument";

export interface DraftableDocument {
  section: string | null;
  document_type: string | null;
  supplier_gstin: string;
  document_number: string | null;
}

export function CreateDraftBillFrom2B({
  clientId, period, document,
}: { clientId: string; period: string; document: DraftableDocument }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Gstr2bDraftBill | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    if (busy || done || !document.section || !document.document_type
        || !document.document_number) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await api.gstWorkspace.createDraftBillFrom2b({
        client_id: clientId,
        period,
        section: document.section,
        document_type: document.document_type,
        supplier_gstin: document.supplier_gstin,
        document_number: document.document_number,
      });
      if (resp.success) {
        setDone(objectWithLists<Gstr2bDraftBill>(resp.data, "differences", "caveats"));
      } else {
        setError(resp.error ?? "The draft could not be created.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "The draft could not be created.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="space-y-1 text-3xs" data-testid="gstr2b-draft-created">
        <p className="text-state-ready font-medium">
          Draft bill created — not received.{" "}
          <Link href={documentHref(clientId, "purchases", "bills", done.bill.id)}
            className="underline">
            Open it
          </Link>
        </p>
        {!done.agrees_with_2b && (
          <div role="alert" className="text-state-attention space-y-0.5">
            <p className="font-medium">
              The books&apos; arithmetic does not reproduce what the supplier filed:
            </p>
            {done.differences.map((d, i) => <p key={i}>{d}</p>)}
          </div>
        )}
        {done.caveats.map((c, i) => (
          <p key={i} className="text-ps-hint">{c}</p>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <button type="button" onClick={() => { void create(); }} disabled={busy}
        className="px-2 py-1 border rounded text-3xs hover:bg-ps-bg disabled:opacity-50">
        {busy ? "Creating…" : "Create draft bill"}
      </button>
      {error && <p role="alert" className="text-3xs text-state-problem">{error}</p>}
    </div>
  );
}
