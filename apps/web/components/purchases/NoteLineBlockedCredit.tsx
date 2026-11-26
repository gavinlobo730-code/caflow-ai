"use client";

/**
 * The CGST Act s.17(5) mark under a purchase note line's description (POST-A-459), the control the bill editor has: one checkbox, and
 * the clause list only once a line is marked. A note against a blocked bill line marks the same line, so the note moves the credit
 * ledgers by the creditable tax only. Nothing is inferred and no figure is computed here.
 */
import { BLOCKED_CREDIT_REASONS } from "@/lib/purchases/billEditor";
import { noteLineIsBlocked, type NoteLineBlockedCredit } from "@/lib/purchases/noteBlockedCredit";

export function NoteLineBlockedCredit({ index, line, disabled, onChange }: {
  index: number;
  line: NoteLineBlockedCredit;
  disabled?: boolean;
  onChange: (patch: NoteLineBlockedCredit) => void;
}) {
  const blocked = noteLineIsBlocked(line);
  const reason = BLOCKED_CREDIT_REASONS.find((r) => r.code === line.blocked_credit_reason);
  return (
    <>
      <label className="mt-1 flex items-center gap-1.5 text-3xs text-ps-label">
        <input type="checkbox" checked={blocked} disabled={disabled}
          aria-label={`Line ${index + 1} ITC blocked under section 17(5)`}
          onChange={(e) => onChange(e.target.checked
            ? { itc_eligible: false, blocked_credit_reason: line.blocked_credit_reason || "" }
            // Unmarking clears the clause too: a stale reason on an eligible line contradicts the flag beside it.
            : { itc_eligible: true, blocked_credit_reason: "" })} />
        ITC blocked (§17(5)), as on the bill
      </label>
      {blocked && (
        <>
          <select value={line.blocked_credit_reason ?? ""} disabled={disabled}
            aria-label={`Line ${index + 1} section 17(5) clause`}
            onChange={(e) => onChange({ blocked_credit_reason: e.target.value })}
            className={`mt-1 w-full px-1 py-1 border rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand text-3xs ${
              (line.blocked_credit_reason ?? "").trim() === "" ? "border-state-problem" : "border-ps-border"}`}>
            <option value="">— which clause? —</option>
            {BLOCKED_CREDIT_REASONS.map((r) => (
              <option key={r.code} value={r.code}>{r.clause} · {r.label}</option>
            ))}
          </select>
          {reason?.note && <p className="mt-0.5 text-3xs text-ps-hint">{reason.note}</p>}
          <p className="mt-0.5 text-3xs text-ps-hint">The tax on this line goes to the cost, not to the input credit ledgers.</p>
        </>
      )}
    </>
  );
}
