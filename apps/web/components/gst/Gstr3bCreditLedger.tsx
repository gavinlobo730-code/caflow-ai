"use client";

/**
 * The electronic credit ledger a GSTR-3B is set off against (gst-06): what it
 * opened with, where that came from, what the return leaves in it — and the one
 * form a CA uses to key the balance the portal shows.
 *
 * WHAT WAS WRONG
 *     The set-off ran against this return's own Table 4(C) and nothing else, so a
 *     client whose April closed holding Rs 36,54,961.65 of IGST credit opened May
 *     as though April had not happened and was shown a cash payment for tax the
 *     ledger already covered. The server now spends the ledger's opening balance
 *     first (`domain/gst/credit_ledger.py`).
 *
 * THIS SCREEN DECIDES NOTHING. Which balance won, whether it was KNOWN and what is
 * said when it was not are the server's, and every sentence here is one it
 * served. The only thing computed in this file is a typed rupee amount read into
 * paise by `paiseFromRupeeInput`, the one parser.
 *
 * AN ASSUMED NIL IS SAID TO BE ONE. `known: false` means nobody has stated the
 * opening balance and the arithmetic assumed an empty ledger — a different thing
 * from a ledger that was empty — and it is rendered in the attention palette
 * rather than as an ordinary zero.
 *
 * NOTHING IS FILED OR POSTED. A keyed balance is an input to a figure the CA
 * reviews; the portal is not contacted.
 */
import { useState } from "react";
import { Landmark } from "lucide-react";
import { api, type CreditBalanceFigures, type CreditLedgerBlock } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { useSingleFlight } from "@/lib/async/useSingleFlight";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";

const HEADS = [
  { key: "igst_paise", label: "IGST" },
  { key: "cgst_paise", label: "CGST" },
  { key: "sgst_paise", label: "SGST" },
  { key: "cess_paise", label: "Cess" },
] as const;

type Draft = Record<(typeof HEADS)[number]["key"], string>;

function draftFrom(b: CreditBalanceFigures): Draft {
  return {
    igst_paise: rupeeInputFromPaise(b.igst_paise),
    cgst_paise: rupeeInputFromPaise(b.cgst_paise),
    sgst_paise: rupeeInputFromPaise(b.sgst_paise),
    cess_paise: rupeeInputFromPaise(b.cess_paise),
  };
}

function Row({ label, figures }: { label: string; figures: CreditBalanceFigures }) {
  return (
    <tr className="border-t border-ps-border">
      <th scope="row" className="px-3 py-1.5 text-left font-normal text-ps-label">{label}</th>
      {HEADS.map((h) => (
        <td key={h.key} className="px-3 py-1.5 text-right font-mono">{formatPaise(figures[h.key])}</td>
      ))}
      <td className="px-3 py-1.5 text-right font-mono font-medium">{formatPaise(figures.total_paise)}</td>
    </tr>
  );
}

export function Gstr3bCreditLedger({
  clientId, period, gstin, ledger, onChanged,
}: {
  clientId: string;
  /** The return's own period key, as the server resolved it. */
  period: string;
  gstin?: string;
  /** The `credit_ledger` block the compute served. Absent from an older backend,
   *  which renders nothing rather than a ledger nobody consulted. */
  ledger?: CreditLedgerBlock | null;
  /** Called after a balance is saved or removed — the caller computes again. */
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Saving and removing the keyed balance share one guard: both rewrite what the
  // next GSTR-3B opens with, and `busy` alone takes a render to reach the DOM.
  // (Declared before the early return below: a hook may not follow a conditional exit.)
  const { flight } = useSingleFlight();

  if (!ledger || !ledger.opening) return null;
  const { opening, closing } = ledger;

  function openForm() {
    setDraft(draftFrom(opening.balance));
    setNote(opening.recorded?.note ?? "");
    setError(null);
    setEditing(true);
  }

  async function save() {
    if (!draft) return;
    const parsed: Record<string, number> = {};
    for (const h of HEADS) {
      const p = paiseFromRupeeInput(draft[h.key]);
      if (p === null) { setError(`${h.label} is not an amount.`); return; }
      parsed[h.key] = p;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.gstCreditLedger.setOpening({
        client_id: clientId, period, ...(gstin ? { gstin } : {}),
        igst_paise: parsed.igst_paise, cgst_paise: parsed.cgst_paise,
        sgst_paise: parsed.sgst_paise, cess_paise: parsed.cess_paise,
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      if (!res.success) { setError(res.error ?? "Couldn't record the balance."); return; }
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record the balance.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.gstCreditLedger.clearOpening(clientId, period, gstin);
      if (!res.success) { setError(res.error ?? "Couldn't remove the recorded balance."); return; }
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove the recorded balance.");
    } finally {
      setBusy(false);
    }
  }

  const sentences = Array.isArray(opening.sentences) ? opening.sentences : [];

  return (
    <section aria-label="Electronic credit ledger"
             className="rounded-lg border border-ps-border bg-white p-3 space-y-2.5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="flex items-center gap-1.5 text-sm font-semibold text-ps-ink">
            <Landmark className="h-4 w-4" aria-hidden /> Electronic credit ledger
          </h4>
          <p className="text-2xs text-ps-label">
            Opening balance: {opening.label}. Credit in the ledger pays output tax before any
            cash is due (CGST Act s.49(4)).
          </p>
        </div>
        {!editing && (
          <button type="button" onClick={openForm}
                  className="shrink-0 text-xs text-blue-700 hover:underline">
            {opening.source === "recorded" ? "Change the recorded balance" : "Record the portal's balance"}
          </button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-ps-label">
              <th className="px-3 py-1 text-left font-normal"><span className="sr-only">Balance</span></th>
              {HEADS.map((h) => (
                <th key={h.key} scope="col" className="px-3 py-1 text-right font-normal">{h.label}</th>
              ))}
              <th scope="col" className="px-3 py-1 text-right font-normal">Total</th>
            </tr>
          </thead>
          <tbody>
            <Row label={opening.known ? "Opening" : "Opening (assumed nil)"} figures={opening.balance} />
            <Row label="Left after this return" figures={closing} />
          </tbody>
        </table>
      </div>

      {sentences.length > 0 && (
        <Callout tone={opening.known ? "note" : "attention"}>
          <ul className="space-y-1.5">
            {sentences.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </Callout>
      )}

      {editing && draft && (
        <div className="rounded-md border border-ps-border bg-ps-bg p-3 space-y-2">
          <p className="text-xs text-ps-label">
            Enter what the portal&apos;s Electronic Credit Ledger shows for this registration when
            this return&apos;s period opened. Nothing is filed or posted — it changes the figures
            on this return, which you still review.
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {HEADS.map((h) => (
              <div key={h.key}>
                <label htmlFor={`credit-opening-${h.key}`} className="block text-2xs text-ps-label">
                  {h.label} (₹)
                </label>
                <input id={`credit-opening-${h.key}`} name={`credit-opening-${h.key}`} inputMode="decimal"
                       autoComplete="off" value={draft[h.key]}
                       onChange={(e) => setDraft({ ...draft, [h.key]: e.target.value })}
                       className="mt-0.5 w-full rounded border border-ps-border px-2 py-1 text-right font-mono text-sm" />
              </div>
            ))}
          </div>
          <div>
            <label htmlFor="credit-opening-note" className="block text-2xs text-ps-label">
              Where you read it (optional)
            </label>
            <input id="credit-opening-note" name="credit-opening-note" autoComplete="off"
                   maxLength={500} value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder="Electronic Credit Ledger on the portal, 1 May 2026"
                   className="mt-0.5 w-full rounded border border-ps-border px-2 py-1 text-sm" />
          </div>
          {error && <p role="alert" className="text-xs text-state-problem">{error}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="plain" size="none" spinner={false} flight={flight}
                    type="button" onClick={() => save()} disabled={busy}
                    className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50">
              {busy ? "Saving…" : "Save and compute again"}
            </Button>
            <button type="button" onClick={() => setEditing(false)} disabled={busy}
                    className="text-xs text-ps-body hover:underline">
              Cancel
            </button>
            {opening.source === "recorded" && (
              <Button variant="plain" size="none" spinner={false} flight={flight}
                      type="button" onClick={() => remove()} disabled={busy}
                      className="text-xs text-state-problem hover:underline">
                Remove the recorded balance
              </Button>
            )}
          </div>
        </div>
      )}
      {!editing && error && <p role="alert" className="text-xs text-state-problem">{error}</p>}
    </section>
  );
}
