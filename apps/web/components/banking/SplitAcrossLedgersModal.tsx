"use client";

/**
 * Allocate ONE bank line across several GL accounts (Tier 1.2).
 *
 * WHY IT EXISTS
 *   One debit on a statement is often several things: a ₹47,200 payment to a
 *   landlord is ₹40,000 of rent, ₹5,000 of maintenance and ₹2,200 of parking.
 *   The backend has been able to record that since migration 256 — the table,
 *   an atomic replace RPC, domain validation, a service, both endpoints and a
 *   frontend client method — and nothing in the UI ever called it. There were
 *   zero call sites. This is the screen for it.
 *
 *   The button that said "Split across several" opened a different thing: the
 *   settlement modal, which splits a line across INVOICES or BILLS. Both are
 *   real and both are needed, so the two now sit behind one button with a mode
 *   switch at the top rather than two similarly-named controls.
 *
 * THE ONE INVARIANT, ON SCREEN
 *   The legs must sum EXACTLY to what the bank moved. There is no rounding plug
 *   and no auto-balancing — domain/banking/splits refuses anything else, and
 *   the RPC refuses it again inside the transaction. So the figure this modal
 *   keeps in front of the reader is what is still UNALLOCATED, counting down to
 *   zero, rather than a validation message that appears once they press Save.
 *
 *   Save is disabled until it reaches zero. The server is still the authority —
 *   its refusals are shown verbatim, because they name the shortfall in rupees.
 *
 * RUPEES IN, PAISE OUT
 *   The reader types rupees; every amount crosses the wire as integer paise,
 *   and the running total is computed in paise. Nothing here adds floats.
 */

import * as React from "react";
import { X, Plus, Trash2 } from "lucide-react";
import { AccountLookup, type AccountLike } from "@/components/lookups/AccountLookup";
import { formatPaise } from "@/lib/services/formatting";
import { api } from "@/lib/api";
import {
  rupeesToPaise, filledLegs, unallocatedPaise, splitBlock, takeTheRestPaise,
  type SplitLeg, type SplitBlock,
} from "@/lib/banking/splitLegs";

interface SplitsResponse {
  splits?: { account_id: string; amount_paise: number; narration: string | null }[];
  editable?: boolean;
}

/** The words for a reason. The DECISION is splitBlock's, so the disabled Save
 *  button and the sentence explaining it can never disagree — this only says
 *  it out loud, and is the only place that needs a rupee formatter. */
function reasonText(b: SplitBlock): string {
  switch (b.code) {
    case "no-amount":    return "This line has no amount to split.";
    case "too-few":      return "A split needs at least two ledgers.";
    case "no-ledger":    return "Every line needs a ledger.";
    case "non-positive": return "Every line needs a positive amount — they all move the same way as the bank line.";
    case "short":        return `${formatPaise(b.paise)} still unallocated.`;
    case "over":         return `${formatPaise(b.paise)} more than the bank moved.`;
  }
}

const blankLeg = (n: number): SplitLeg => ({ key: `leg-${n}`, account_id: "", amount: "", narration: "" });

export function SplitAcrossLedgersModal({
  txnId, description, amountPaise, isCredit, accounts, onClose, onDone, modeSwitch,
}: {
  txnId: string;
  description: string;
  amountPaise: number;
  isCredit: boolean;
  accounts: AccountLike[];
  onClose: () => void;
  onDone: () => void;
  /** The across-ledgers / across-invoices switch, owned by the caller so both
   *  modals show the same one. */
  modeSwitch?: React.ReactNode;
}) {
  const [legs, setLegs] = React.useState<SplitLeg[]>([blankLeg(1), blankLeg(2)]);
  const [seq, setSeq] = React.useState(3);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [editable, setEditable] = React.useState(true);
  const [wasSplit, setWasSplit] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Load whatever allocation the line already has, so re-opening it EDITS
  // rather than starting again. Replacing a split silently is the failure this
  // avoids — the endpoint is a PUT over the whole set.
  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = (await api.banking.splits.get(txnId)) as { data?: SplitsResponse };
        if (!alive) return;
        const existing = res?.data?.splits ?? [];
        if (existing.length > 0) {
          setWasSplit(true);
          setLegs(existing.map((s, i) => ({
            key: `leg-${i + 1}`,
            account_id: s.account_id,
            amount: (s.amount_paise / 100).toFixed(2),
            narration: s.narration ?? "",
          })));
          setSeq(existing.length + 1);
        }
        if (res?.data?.editable === false) setEditable(false);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Could not read the current split.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [txnId]);

  const filled = filledLegs(legs);
  const left = unallocatedPaise(filled, amountPaise);
  const block = splitBlock(legs, amountPaise);
  const blocked = block ? reasonText(block) : null;

  const update = (key: string, patch: Partial<SplitLeg>) =>
    setLegs((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  /** Put the rest of the line on this leg. The arithmetic a CA would otherwise
   *  do on the last row, which is where the paise go missing. */
  const takeTheRest = (key: string) => {
    const rest = takeTheRestPaise(legs, key, amountPaise);
    if (rest === null) return;
    update(key, { amount: (rest / 100).toFixed(2) });
  };

  async function save() {
    if (blocked) return;
    setSaving(true);
    setError(null);
    try {
      await api.banking.splits.replace(txnId, filled.map((l) => ({
        account_id: l.account_id,
        amount_paise: rupeesToPaise(l.amount),
        narration: l.narration.trim() || null,
      })));
      onDone();
    } catch (e) {
      // Verbatim: the server's messages name the shortfall in rupees, which is
      // more use than "could not save".
      setError(e instanceof Error ? e.message : "Could not save the split.");
    } finally {
      setSaving(false);
    }
  }

  /** Clear the allocation and return the line to an ordinary one-ledger
   *  posting. An empty list is a legitimate operation, not a delete. */
  async function clearSplit() {
    setSaving(true);
    setError(null);
    try {
      await api.banking.splits.replace(txnId, []);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not clear the split.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[#0F172A]">Split across ledgers</h3>
            <p className="text-xs text-[#64748B] mt-0.5 truncate" title={description}>
              {description} · {formatPaise(amountPaise)} {isCredit ? "received" : "spent"}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
            className="text-[#94A3B8] hover:text-[#475569] shrink-0"><X size={16} /></button>
        </div>

        {modeSwitch && <div className="px-5 pt-3">{modeSwitch}</div>}

        <div className="px-5 py-4 space-y-2 overflow-y-auto flex-1">
          {loading ? (
            <p className="text-xs text-[#94A3B8] py-6 text-center">Loading the current split…</p>
          ) : (
            <>
              {!editable && (
                <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                  This line already has a journal, so its split is frozen. Undo the posting first.
                </p>
              )}
              {legs.map((l, i) => (
                <div key={l.key} className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <AccountLookup
                      accounts={accounts}
                      value={l.account_id}
                      onChange={(id) => update(l.key, { account_id: id })}
                      disabled={!editable || saving}
                      size="sm"
                      ariaLabel={`Ledger for line ${i + 1}`}
                      placeholder="Choose a ledger…"
                    />
                    <input
                      type="text"
                      value={l.narration}
                      disabled={!editable || saving}
                      onChange={(e) => update(l.key, { narration: e.target.value })}
                      placeholder="What this part was for (optional)"
                      aria-label={`Note for line ${i + 1}`}
                      className="mt-1 w-full border border-[#E2E8F0] rounded px-2 py-1 text-[11px]"
                    />
                  </div>
                  <div className="w-32 shrink-0">
                    <input
                      type="number" min="0" step="0.01" inputMode="decimal"
                      value={l.amount}
                      disabled={!editable || saving}
                      onChange={(e) => update(l.key, { amount: e.target.value })}
                      aria-label={`Amount for line ${i + 1}`}
                      className="w-full border border-[#E2E8F0] rounded px-2 py-1.5 text-xs text-right font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => takeTheRest(l.key)}
                      disabled={!editable || saving}
                      className="mt-1 w-full text-[10px] text-[#4338CA] hover:underline disabled:opacity-40">
                      Take the rest
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => setLegs((ls) => (ls.length > 2 ? ls.filter((x) => x.key !== l.key) : ls))}
                    disabled={!editable || saving || legs.length <= 2}
                    aria-label={`Remove line ${i + 1}`}
                    title={legs.length <= 2 ? "A split needs at least two ledgers" : "Remove this line"}
                    className="mt-1.5 text-[#CBD5E1] hover:text-red-600 disabled:opacity-30 shrink-0">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}

              <button
                type="button"
                onClick={() => { setLegs((ls) => [...ls, blankLeg(seq)]); setSeq((n) => n + 1); }}
                disabled={!editable || saving}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569] disabled:opacity-50">
                <Plus size={12} /> Add a ledger
              </button>
            </>
          )}

          {error && <p className="text-[11px] text-red-600">{error}</p>}
        </div>

        <div className="px-5 py-3 border-t border-[#F1F5F9] flex items-center gap-3">
          {/* The figure that has to reach zero, kept in front of the reader
              rather than produced as a validation error on Save. */}
          <p className={`text-xs font-mono ${left === 0 ? "text-[#15803D]" : "text-[#B45309]"}`}>
            {left === 0 ? "Fully allocated" : left > 0
              ? `${formatPaise(left)} unallocated`
              : `${formatPaise(-left)} over`}
          </p>
          {/* Only when the amount is NOT the problem — otherwise the figure to
              its left is already saying the same thing twice. */}
          {left === 0 && blocked && (
            <p className="text-[10px] text-[#94A3B8] truncate">{blocked}</p>
          )}
          <div className="ml-auto flex items-center gap-2">
            {wasSplit && editable && (
              <button onClick={clearSplit} disabled={saving}
                className="text-xs px-3 py-1.5 text-[#B91C1C] hover:underline disabled:opacity-50">
                Clear the split
              </button>
            )}
            <button onClick={onClose} disabled={saving}
              className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]">
              Cancel
            </button>
            <button
              onClick={save}
              disabled={!editable || saving || Boolean(blocked)}
              title={blocked ?? "Save this allocation"}
              className="text-xs px-3 py-1.5 rounded-lg font-medium text-white bg-[#4338CA] hover:bg-[#3730A3] disabled:opacity-40 disabled:cursor-not-allowed">
              {saving ? "Saving…" : "Save the split"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
