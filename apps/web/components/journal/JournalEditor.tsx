"use client";

/**
 * Journal entry editor — create, view and correct, on its own page.
 *
 * It has three shapes, decided entirely by what the backend says about the
 * entry rather than by anything worked out here:
 *
 *   NEW        blank form; Save Draft or Post Entry.
 *   DRAFT      nothing is on the books yet, so everything is editable; Save
 *              Draft or Post Entry.
 *   POSTED     the entry is in the ledger. Whether it may still be corrected
 *              is `editable`/`lock_reason` off the GET, which come from
 *              journal_period_lock_reason — the same database function the
 *              write path enforces with. When it is open the CA gets Save
 *              Correction; when it is not, the form is read-only and the
 *              reason is shown, because "GSTR-3B covering this date was filed
 *              on 18 Jul 2026" tells them what to do next and a disabled
 *              button does not.
 *
 * WHY A POSTED ENTRY IS EDITABLE AT ALL
 *     The proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires
 *     an edit log of each change made in the books of account, which presumes
 *     changes happen. What ends the right is the CA locking the year or a
 *     return being filed for the period. See migration 266.
 *
 * NO BUSINESS LOGIC LIVES HERE. The balance check below is input validation so
 * the CA is not made to round-trip to learn their entry does not balance; the
 * authority is post_journal_atomic and edit_posted_journal, which check again
 * in integer paise and refuse. The same goes for the period lock: this screen
 * only renders what the backend resolved.
 */
import { useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { todayLocalISO } from "@/lib/dateMath";
import type { JournalEntryDetail, JournalLineIO } from "@/lib/api";

export const ENTRY_TYPES = [
  "Journal", "Sales", "Purchase", "Payment", "Receipt", "Contra", "Opening",
] as const;

export interface EditorAccount {
  id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  is_active?: boolean;
}

/**
 * A line as the form holds it. Amounts stay as the TYPED STRING, not a number:
 * parsing on every keystroke would fight the CA mid-entry ("12." is not yet an
 * amount but is on its way to being one), and it is the only way to tell "0.00"
 * apart from text that does not parse at all.
 */
interface FormLine {
  key: string;
  account_id: string;
  debit: string;
  credit: string;
  narration: string;
}

let lineSeq = 0;
const newLine = (): FormLine => ({
  key: `l${lineSeq++}`, account_id: "", debit: "", credit: "", narration: "",
});

function toFormLines(lines: JournalLineIO[] | undefined): FormLine[] {
  const rows = (lines ?? []).map((l) => ({
    key: `l${lineSeq++}`,
    account_id: l.account_id ?? "",
    debit: l.debit_paise ? rupeeInputFromPaise(l.debit_paise) : "",
    credit: l.credit_paise ? rupeeInputFromPaise(l.credit_paise) : "",
    narration: l.narration ?? "",
  }));
  while (rows.length < 2) rows.push(newLine());
  return rows;
}

export type JournalSaveMode = "draft" | "post" | "correct";

export interface JournalEditorProps {
  accounts: EditorAccount[];
  /** null in create mode; otherwise the entry as the backend returned it. */
  existing: JournalEntryDetail | null;
  saving?: boolean;
  /** Server-side failure to show verbatim — its wording is written for the CA. */
  serverError?: string | null;
  onSave: (mode: JournalSaveMode, payload: {
    entry_date: string; entry_type: string; reference_no: string;
    narration: string; lines: JournalLineIO[];
  }) => void;
  onCancel: () => void;
}

export function JournalEditor({
  accounts, existing, saving = false, serverError = null, onSave, onCancel,
}: JournalEditorProps) {
  const isNew = existing === null;
  const isPosted = !!existing?.is_posted;
  // A reversed entry is finished: its correction already exists as the reversal.
  const lockReason = existing?.is_reversed
    ? "This entry has been reversed, so it can no longer be edited."
    : existing?.lock_reason ?? null;
  const readOnly = !isNew && lockReason !== null;

  const [entryDate, setEntryDate] = useState(existing?.entry_date ?? todayLocalISO());
  const [entryType, setEntryType] = useState(existing?.entry_type ?? "Journal");
  const [referenceNo, setReferenceNo] = useState(existing?.reference_no ?? "");
  const [narration, setNarration] = useState(existing?.narration ?? "");
  const [lines, setLines] = useState<FormLine[]>(() =>
    existing ? toFormLines(existing.lines) : [newLine(), newLine()]);
  const [localError, setLocalError] = useState<string | null>(null);

  // Every amount parsed once, exactly, in integer paise. `null` marks a cell
  // whose text is not an amount — surfaced as a per-line error rather than
  // being folded into 0, which would let an unbalanced entry look balanced.
  const parsed = useMemo(() => lines.map((l) => ({
    debit: paiseFromRupeeInput(l.debit),
    credit: paiseFromRupeeInput(l.credit),
  })), [lines]);

  const hasUnparseable = parsed.some((p) => p.debit === null || p.credit === null);
  const totalDebit = parsed.reduce((s, p) => s + (p.debit ?? 0), 0);
  const totalCredit = parsed.reduce((s, p) => s + (p.credit ?? 0), 0);
  const isBalanced = !hasUnparseable && totalDebit > 0 && totalDebit === totalCredit;

  function setLine(idx: number, patch: Partial<FormLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }

  /** A line carries one side or the other, never both — typing in one clears the other. */
  function setAmount(idx: number, side: "debit" | "credit", raw: string) {
    const other = side === "debit" ? "credit" : "debit";
    const paise = paiseFromRupeeInput(raw);
    setLine(idx, { [side]: raw, ...(paise ? { [other]: "" } : {}) } as Partial<FormLine>);
  }

  function buildPayload() {
    const out: JournalLineIO[] = [];
    lines.forEach((l, i) => {
      const debit = parsed[i].debit ?? 0;
      const credit = parsed[i].credit ?? 0;
      if (!l.account_id || (debit === 0 && credit === 0)) return;
      out.push({
        account_id: l.account_id,
        debit_paise: debit,
        credit_paise: credit,
        narration: l.narration.trim() || undefined,
      });
    });
    return {
      entry_date: entryDate,
      entry_type: entryType,
      reference_no: referenceNo.trim(),
      narration: narration.trim(),
      lines: out,
    };
  }

  function handleSave(mode: JournalSaveMode) {
    setLocalError(null);
    if (hasUnparseable) { setLocalError("One of the amounts isn't a number. Check the highlighted cells."); return; }
    if (!narration.trim()) { setLocalError("Narration is required."); return; }
    if (!isBalanced) { setLocalError("Debits must equal credits before saving."); return; }
    const payload = buildPayload();
    if (payload.lines.length < 2) { setLocalError("At least 2 lines with an account and an amount are required."); return; }
    onSave(mode, payload);
  }

  const title = isNew ? "New Journal Entry"
    : isPosted ? `Journal Entry ${existing?.reference_no ?? ""}`.trim()
    : `Draft Journal Entry ${existing?.reference_no ?? ""}`.trim();

  const field = "w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#64748B]";

  return (
    <div className="space-y-5 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-[#0F172A]">{title}</h2>
          {!isNew && (
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
              isPosted ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
              {isPosted ? "Posted" : "Draft"}
            </span>
          )}
        </div>
        <button onClick={onCancel} className="text-xs text-[#64748B] hover:text-[#334155]">
          Back to Journal
        </button>
      </div>

      {/* Why this cannot be changed — the sentence, not a disabled button. */}
      {readOnly && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 space-y-1">
          <p className="text-sm text-amber-900 font-medium">This entry can no longer be edited.</p>
          <p className="text-xs text-amber-800">{lockReason}</p>
          <p className="text-xs text-amber-700">
            Correct it with a reversal, and an amendment in the next return.
          </p>
        </div>
      )}

      {/* Editing something already in the ledger is a different act from typing
          a new one, and the CA should know that before they start, not after. */}
      {isPosted && !readOnly && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
          <p className="text-xs text-blue-900">
            This entry is already posted to the ledger. Saving rewrites it and
            records the change — the previous figures stay in the audit log.
          </p>
        </div>
      )}

      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label htmlFor="je-date" className="block text-xs font-medium text-[#475569] mb-1">Date *</label>
            <input id="je-date" type="date" value={entryDate} disabled={readOnly}
                   onChange={(e) => setEntryDate(e.target.value)} className={field} />
          </div>
          <div>
            <label htmlFor="je-type" className="block text-xs font-medium text-[#475569] mb-1">Type</label>
            <select id="je-type" value={entryType} disabled={readOnly}
                    onChange={(e) => setEntryType(e.target.value)} className={field}>
              {ENTRY_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="je-ref" className="block text-xs font-medium text-[#475569] mb-1">Reference No.</label>
            <input id="je-ref" value={referenceNo} disabled={readOnly} placeholder="INV-001"
                   onChange={(e) => setReferenceNo(e.target.value)} className={field} />
          </div>
        </div>
        <div>
          <label htmlFor="je-narration" className="block text-xs font-medium text-[#475569] mb-1">Narration *</label>
          <input id="je-narration" value={narration} disabled={readOnly}
                 placeholder="Being goods sold to ABC Ltd…"
                 onChange={(e) => setNarration(e.target.value)} className={field} />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                <th className="pb-2 text-left font-semibold">Account</th>
                <th className="pb-2 text-right font-semibold w-28">Debit (₹)</th>
                <th className="pb-2 text-right font-semibold w-28">Credit (₹)</th>
                <th className="pb-2 text-left font-semibold pl-3">Narration</th>
                <th className="pb-2 w-6" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {lines.map((line, idx) => {
                const bad = (side: "debit" | "credit") => parsed[idx][side] === null;
                const amountCls = (side: "debit" | "credit") =>
                  `w-full px-2 py-1 border rounded focus:outline-none focus:ring-1 text-right text-xs disabled:bg-[#F8FAFC] ${
                    bad(side) ? "border-red-400 focus:ring-red-500 bg-red-50" : "border-[#E2E8F0] focus:ring-blue-500"}`;
                return (
                  <tr key={line.key}>
                    <td className="py-1.5 pr-2">
                      <AccountLookup
                        accounts={accounts}
                        value={line.account_id}
                        onChange={(id) => setLine(idx, { account_id: id })}
                        size="sm"
                        disabled={readOnly}
                        placeholder="— Select account —"
                        ariaLabel="Account"
                      />
                    </td>
                    <td className="py-1.5 px-2">
                      <input inputMode="decimal" value={line.debit} disabled={readOnly}
                             aria-invalid={bad("debit")} aria-label="Debit"
                             onChange={(e) => setAmount(idx, "debit", e.target.value)}
                             placeholder="0.00" className={amountCls("debit")} />
                    </td>
                    <td className="py-1.5 px-2">
                      <input inputMode="decimal" value={line.credit} disabled={readOnly}
                             aria-invalid={bad("credit")} aria-label="Credit"
                             onChange={(e) => setAmount(idx, "credit", e.target.value)}
                             placeholder="0.00" className={amountCls("credit")} />
                    </td>
                    <td className="py-1.5 pl-3">
                      <input value={line.narration} disabled={readOnly} placeholder="optional"
                             aria-label="Line narration"
                             onChange={(e) => setLine(idx, { narration: e.target.value })}
                             className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs disabled:bg-[#F8FAFC]" />
                    </td>
                    <td className="py-1.5 pl-1">
                      {!readOnly && lines.length > 2 && (
                        <button onClick={() => setLines((p) => p.filter((_, i) => i !== idx))}
                                aria-label="Remove line"
                                className="text-[#CBD5E1] hover:text-red-600 font-bold">×</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-[#F1F5F9] text-xs font-semibold">
                <td className="pt-2 text-[#64748B]">Total</td>
                <td className="pt-2 text-right text-[#334155] px-2">
                  {totalDebit > 0 ? `₹${rupeeInputFromPaise(totalDebit)}` : "—"}
                </td>
                <td className="pt-2 text-right text-[#334155] px-2">
                  {totalCredit > 0 ? `₹${rupeeInputFromPaise(totalCredit)}` : "—"}
                </td>
                <td colSpan={2} className="pt-2 pl-3">
                  {hasUnparseable && <span className="text-red-500 text-[10px]">Check the highlighted amounts</span>}
                  {!hasUnparseable && totalDebit > 0 && totalDebit !== totalCredit && (
                    <span className="text-red-500 text-[10px]">
                      Difference: ₹{rupeeInputFromPaise(Math.abs(totalDebit - totalCredit))}
                    </span>
                  )}
                  {isBalanced && <span className="text-green-600 text-[10px]">✓ Balanced</span>}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        {!readOnly && (
          <button onClick={() => setLines((p) => [...p, newLine()])}
                  className="text-xs text-blue-600 hover:underline flex items-center gap-1">
            <Plus size={12} /> Add line
          </button>
        )}

        {(localError || serverError) && (
          <p role="alert" className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">
            {localError || serverError}
          </p>
        )}

        {!readOnly && (
          <div className="flex gap-3 justify-end pt-1">
            <button onClick={onCancel}
                    className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">
              Cancel
            </button>
            {isPosted ? (
              <button onClick={() => handleSave("correct")} disabled={saving || !isBalanced}
                      className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
                {saving ? "Saving…" : "Save Correction"}
              </button>
            ) : (
              <>
                <button onClick={() => handleSave("draft")} disabled={saving || !isBalanced}
                        className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-40">
                  Save Draft
                </button>
                <button onClick={() => handleSave("post")} disabled={saving || !isBalanced}
                        className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
                  {saving ? "Saving…" : "Post Entry"}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
