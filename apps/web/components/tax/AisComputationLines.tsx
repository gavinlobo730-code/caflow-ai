"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle, XCircle, AlertTriangle, Loader2 } from "lucide-react";
import { formatPaise } from "@/lib/services/formatting";
import {
  getAisComputationLines, decideAisComputationLine,
  type AisComputationLines,
} from "@/lib/data/income-tax";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { Callout } from "@/components/ui/callout";

/**
 * What the Annual Information Statement says, offered line by line
 * (TDS-INCOME-TAX-10).
 *
 * THIS SCREEN DECIDES NOTHING. The server totals salary, interest and dividend
 * from the uploaded statement, names every payer behind each, records the CA's
 * accept or reject on the figure they were looking at, and says where a figure
 * already typed into a box differs from the statement. An AIS figure is what
 * OTHERS reported about the client, not the client's income — which is why an
 * accepted line fills a box only when that box is EMPTY, and a typed figure that
 * differs is flagged and KEPT.
 *
 * The lines the computation takes no box for — a sale of securities, a property
 * sale, rent, a foreign remittance — are listed with the server's reason for
 * each, so a CA is not left wondering why the statement's largest figure is not
 * offered.
 */
const STATE_LABEL: Record<string, string> = {
  suggested: "Suggested",
  accepted: "Accepted",
  rejected: "Rejected",
  accepted_stale: "Accepted on an earlier figure",
  rejected_stale: "Rejected on an earlier figure",
};

export function AisComputationLinesPanel({
  clientId, fy, typedGrossSalary, typedOtherIncome, onApply,
}: {
  clientId: string;
  fy: string;
  /** What is already in the boxes, in paise — undefined where the box is blank. */
  typedGrossSalary: number | undefined;
  typedOtherIncome: number | undefined;
  /** Fill a computation box. Called only for an EMPTY box. */
  onApply: (target: string, paise: number) => void;
}) {
  const [data, setData] = useState<AisComputationLines | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // What was last put in each box, so a box the CA emptied on purpose is not
  // refilled with the same figure.
  const applied = useRef<Record<string, number>>({});
  // The latest callback, held in a ref so the loader's identity does not change
  // with every render of the parent and refetch on each keystroke.
  const onApplyRef = useRef(onApply);
  onApplyRef.current = onApply;

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder" || !fy) return;
    try {
      const raw = await getAisComputationLines(clientId, fy, {
        ...(typedGrossSalary !== undefined ? { gross_salary_paise: typedGrossSalary } : {}),
        ...(typedOtherIncome !== undefined ? { other_income_paise: typedOtherIncome } : {}),
      });
      const next = objectWithLists<AisComputationLines>(raw, "lines", "targets", "refused", "gaps");
      setData(next);
      setErr(null);
      for (const t of arrayOrEmpty<AisComputationLines["targets"][number]>(next?.targets)) {
        if (t.accept_paise > 0 && t.typed_paise === null && applied.current[t.target] !== t.accept_paise) {
          applied.current[t.target] = t.accept_paise;
          onApplyRef.current(t.target, t.accept_paise);
        }
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read the AIS lines.");
    }
  }, [clientId, fy, typedGrossSalary, typedOtherIncome]);

  // Debounced: the typed figures change on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => { void load(); }, 400);
    return () => clearTimeout(t);
  }, [load]);

  async function decide(lineKey: string, decision: "accepted" | "rejected" | "undecided") {
    setBusy(lineKey); setErr(null);
    try {
      await decideAisComputationLine(clientId, fy, lineKey, decision);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The decision could not be recorded.");
    } finally {
      setBusy(null);
    }
  }

  const lines = arrayOrEmpty<AisComputationLines["lines"][number]>(data?.lines);
  const targets = arrayOrEmpty<AisComputationLines["targets"][number]>(data?.targets);

  return (
    <div className="space-y-3">
      <p className="text-2xs text-ps-label">
        What the department already holds about this client for AY {data?.assessment_year ?? "—"}.
        An accepted line fills its box when the box is empty; a figure you have typed that differs is
        flagged and kept.
      </p>

      {err && <p className="text-xs text-state-problem">{err}</p>}

      {data && !data.has_statement && (
        <Callout tone="note">
          {arrayOrEmpty<string>(data.gaps).map((g, i) => <p key={i}>{g}</p>)}
        </Callout>
      )}

      {lines.map(l => (
        <div key={l.line_key} className="border border-ps-border rounded-lg p-3 space-y-1.5 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <strong>{l.bucket}</strong> — {formatPaise(l.amount_paise)}
              {l.tds_paise > 0 && <span className="text-ps-hint"> (TDS {formatPaise(l.tds_paise)})</span>}
              <span className="text-ps-hint"> → {l.target_label}</span>
            </span>
            <span className={
              l.state === "accepted" ? "inline-flex items-center gap-1 text-state-ready"
                : l.state.endsWith("stale") ? "inline-flex items-center gap-1 text-state-attention"
                : "text-ps-hint"}>
              {l.state === "accepted" && <CheckCircle size={11} />}
              {l.state === "rejected" && <XCircle size={11} />}
              {l.state.endsWith("stale") && <AlertTriangle size={11} />}
              {STATE_LABEL[l.state] ?? l.state}
            </span>
          </div>
          <ul className="text-3xs text-ps-label space-y-0.5">
            {arrayOrEmpty<AisComputationLines["lines"][number]["sources"][number]>(l.sources).map((s, i) => (
              <li key={i}>
                {s.payer || "Unnamed payer"}{s.label ? ` — ${s.label}` : ""}: {formatPaise(s.amount_paise)}
                {s.source === "manual" && <span className="text-state-attention"> (added by hand)</span>}
              </li>
            ))}
          </ul>
          {l.state.endsWith("stale") && l.decided_amount_paise !== null && (
            <p className="text-3xs text-state-attention">
              You decided this when it stood at {formatPaise(l.decided_amount_paise)}; the statement now says{" "}
              {formatPaise(l.amount_paise)}. It is not applied until you decide again.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy === l.line_key || l.state === "accepted"}
              onClick={() => decide(l.line_key, "accepted")}
              className="text-2xs px-2.5 py-1 border border-ps-border rounded hover:bg-ps-bg disabled:opacity-40 inline-flex items-center gap-1">
              {busy === l.line_key && <Loader2 size={10} className="animate-spin" />} Accept
            </button>
            <button type="button" disabled={busy === l.line_key || l.state === "rejected"}
              onClick={() => decide(l.line_key, "rejected")}
              className="text-2xs px-2.5 py-1 border border-ps-border rounded hover:bg-ps-bg disabled:opacity-40">
              Reject
            </button>
            {l.state !== "suggested" && (
              <button type="button" disabled={busy === l.line_key}
                onClick={() => decide(l.line_key, "undecided")}
                className="text-2xs px-2.5 py-1 text-ps-hint hover:underline">
                Take back
              </button>
            )}
          </div>
        </div>
      ))}

      {targets.filter(t => t.differs).map(t => (
        <Callout key={t.target} tone="attention" title={`${t.label} differs from the statement`}>
          <p>
            You typed {formatPaise(t.typed_paise ?? 0)}; the statement says {formatPaise(t.ais_paise ?? 0)}
            {t.difference_paise !== null && ` (${t.difference_paise > 0 ? "above" : "below"} by ${formatPaise(Math.abs(t.difference_paise))})`}.
            Your figure is kept — the statement is what others reported, and you may know something it does not.
          </p>
        </Callout>
      ))}

      {data && arrayOrEmpty<AisComputationLines["refused"][number]>(data.refused).length > 0 && (
        <Callout tone="withheld" title="On the statement, but not offered">
          {arrayOrEmpty<AisComputationLines["refused"][number]>(data.refused).map(r => (
            <p key={r.bucket}><strong>{r.bucket}</strong> ({formatPaise(r.amount_paise)}): {r.reason}</p>
          ))}
        </Callout>
      )}

      {data && data.has_statement && arrayOrEmpty<string>(data.gaps).length > 0 && (
        <Callout tone="attention">
          {arrayOrEmpty<string>(data.gaps).map((g, i) => <p key={i}>{g}</p>)}
        </Callout>
      )}
    </div>
  );
}

export default AisComputationLinesPanel;
