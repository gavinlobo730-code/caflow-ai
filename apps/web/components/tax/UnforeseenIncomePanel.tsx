"use client";

import { useState } from "react";
import { Plus, Trash2, CheckCircle, AlertTriangle } from "lucide-react";
import { formatPaise } from "@/lib/services/formatting";
import {
  listUnforeseenIncomeCandidates,
  type UnforeseenIncomeCandidate, type UnforeseenIncomeLine,
} from "@/lib/data/income-tax";
import { arrayOrEmpty } from "@/lib/api/shape";
import { Callout } from "@/components/ui/callout";

/** One income the CA has put forward for §234C(1)'s proviso. The tax is held as
 *  TEXT and parsed with the one money parser by the page that owns the rows. */
export interface UnforeseenRow {
  key: string;
  kind: string;
  arose_on: string;
  tax_rs: string;
  description: string;
  /** Set where the row came from a capital gains register entry, so the same
   *  transfer cannot be included twice. */
  register_id?: string | null;
}

// The redeploy-window FALLBACK for the kinds the server serves with the
// candidates (`kinds`) — the Schedule III caption shape. It is pinned from the
// Python side (tests/test_a_234c_proviso_excuses_the_shortfall_unforeseen_
// income_caused.py) against `UNFORESEEN_KINDS`, which is the authority.
const UNFORESEEN_KINDS_FALLBACK = [
  { key: "capital_gain", label: "Capital gain" },
  { key: "winnings", label: "Winnings" },
  { key: "dividend", label: "Dividend" },
];

let _rowSeq = 0;
export function newUnforeseenRow(over: Partial<UnforeseenRow> = {}): UnforeseenRow {
  _rowSeq += 1;
  return { key: `u${_rowSeq}`, kind: "capital_gain", arose_on: "", tax_rs: "", description: "", ...over };
}

/**
 * Income that arose after an instalment fell due (IT-21).
 *
 * THIS SCREEN DECIDES NOTHING. It collects each income's kind, the date it
 * arose and the tax it adds, sends them, and renders the server's working: for
 * each income whether the proviso's condition was met and, where not, why. The
 * condition is the half that matters — the relief holds only if the income's OWN
 * tax is paid in the instalments that remain, or by 31 March where none does —
 * and it is the engine's, in `advance_tax_interest_engine._apply_proviso`.
 *
 * PREPARE-ONLY, WITH AN ACCEPT AND A REJECT ON EVERY LINE. The capital gains
 * register's transfers are OFFERED, never applied: Include puts a candidate in
 * the list (and its tax, an estimate, is editable), and removing a row rejects
 * it. A candidate nobody includes changes no figure.
 */
export function UnforeseenIncomePanel({
  clientId, fy, rows, onChange, lines, caveats, problem,
}: {
  clientId: string;
  fy: string;
  rows: UnforeseenRow[];
  onChange: (rows: UnforeseenRow[]) => void;
  lines?: UnforeseenIncomeLine[];
  caveats?: string[];
  problem?: string | null;
}) {
  const [candidates, setCandidates] = useState<UnforeseenIncomeCandidate[] | null>(null);
  const [offerCaveats, setOfferCaveats] = useState<string[]>([]);
  const [kinds, setKinds] = useState(UNFORESEEN_KINDS_FALLBACK);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function offer() {
    if (!clientId) { setErr("Choose a client first."); return; }
    setBusy(true); setErr(null);
    try {
      const r = await listUnforeseenIncomeCandidates(clientId, fy);
      setCandidates(arrayOrEmpty<UnforeseenIncomeCandidate>(r.candidates));
      setOfferCaveats(arrayOrEmpty<string>(r.caveats));
      const served = arrayOrEmpty<{ key: string; label: string }>(r.kinds);
      if (served.length > 0) setKinds(served);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read the capital gains register.");
    } finally {
      setBusy(false);
    }
  }

  function include(c: UnforeseenIncomeCandidate) {
    if (rows.some(r => r.register_id && r.register_id === c.register_id)) return;
    onChange([...rows, newUnforeseenRow({
      kind: c.kind, arose_on: c.arose_on, description: c.description,
      tax_rs: (c.tax_paise / 100).toFixed(2), register_id: c.register_id,
    })]);
  }

  const set = (key: string, patch: Partial<UnforeseenRow>) =>
    onChange(rows.map(r => (r.key === key ? { ...r, ...patch } : r)));

  return (
    <div className="space-y-3">
      <p className="text-xs text-ps-label">
        §234C(1)&apos;s proviso: a capital gain, winnings or dividend that arose AFTER an instalment
        fell due is left out of what that instalment is measured against — provided its own tax is
        then paid in the instalments that remain, or by 31 March where none does. Enter each with
        the tax it adds to the year&apos;s tax.
      </p>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={offer} disabled={busy}
          className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg disabled:opacity-40">
          {busy ? "Reading…" : "Offer this year's gains from the capital gains register"}
        </button>
        <button type="button" onClick={() => onChange([...rows, newUnforeseenRow()])}
          className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg inline-flex items-center gap-1">
          <Plus size={12} /> Add an income
        </button>
      </div>

      {err && <p className="text-xs text-state-problem">{err}</p>}

      {candidates !== null && (
        <div className="border border-ps-border rounded-lg p-3 space-y-2 bg-ps-bg">
          {candidates.length === 0 ? (
            <p className="text-xs text-ps-label">
              The register holds no taxable gain realised in FY {fy} for this client.
            </p>
          ) : candidates.map(c => {
            const included = rows.some(r => r.register_id && r.register_id === c.register_id);
            return (
              <div key={c.register_id ?? `${c.arose_on}-${c.description}`}
                   className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span>
                  <strong>{c.description || "Transfer"}</strong> — arose {c.arose_on}, gain{" "}
                  {formatPaise(c.gain_paise)}, tax about {formatPaise(c.tax_paise)}
                  {c.is_estimate && <span className="text-ps-hint"> (estimate)</span>}
                </span>
                <button type="button" disabled={included} onClick={() => include(c)}
                  className="px-2 py-1 border border-ps-border rounded hover:bg-white disabled:opacity-40">
                  {included ? "Included" : "Include"}
                </button>
              </div>
            );
          })}
          {offerCaveats.map((c, i) => <p key={i} className="text-2xs text-ps-hint">{c}</p>)}
        </div>
      )}

      {rows.length > 0 && (
        <div className="space-y-2">
          {rows.map(r => (
            <div key={r.key} className="flex flex-wrap items-end gap-2">
              <select value={r.kind} onChange={e => set(r.key, { kind: e.target.value })}
                aria-label="Kind of income"
                className="border border-ps-border rounded px-2 py-1.5 text-xs bg-white">
                {kinds.map(k => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
              <input type="date" value={r.arose_on} aria-label="Date the income arose"
                onChange={e => set(r.key, { arose_on: e.target.value })}
                className="border border-ps-border rounded px-2 py-1.5 text-xs" />
              <input type="text" inputMode="decimal" value={r.tax_rs} aria-label="Tax on the income (₹)"
                onChange={e => set(r.key, { tax_rs: e.target.value })}
                placeholder="Tax it adds (₹)"
                className="w-32 border border-ps-border rounded px-2 py-1.5 text-xs text-right" />
              <input type="text" value={r.description} aria-label="Description"
                onChange={e => set(r.key, { description: e.target.value })}
                placeholder="Description"
                className="w-48 border border-ps-border rounded px-2 py-1.5 text-xs" />
              <button type="button" aria-label="Remove this income"
                onClick={() => onChange(rows.filter(x => x.key !== r.key))}
                className="p-1.5 text-ps-hint hover:text-state-problem">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {problem && <p className="text-xs text-state-problem">{problem}</p>}

      {arrayOrEmpty<UnforeseenIncomeLine>(lines).length > 0 && (
        <div className="space-y-1.5">
          {arrayOrEmpty<UnforeseenIncomeLine>(lines).map((ln, i) => (
            <div key={`${ln.arose_on}-${i}`} className="flex items-start gap-2 text-xs">
              {ln.relief
                ? <span className="inline-flex items-center gap-1 text-state-ready bg-state-ready-surface px-2 py-0.5 rounded-full shrink-0"><CheckCircle size={11} /> Excused</span>
                : <span className="inline-flex items-center gap-1 text-state-attention bg-state-attention-surface px-2 py-0.5 rounded-full shrink-0"><AlertTriangle size={11} /> Not excused</span>}
              <span className="text-ps-label">
                {ln.description || ln.kind} — {ln.arose_on}, tax {formatPaise(ln.tax_paise)}. {ln.reason}
              </span>
            </div>
          ))}
        </div>
      )}

      {arrayOrEmpty<string>(caveats).length > 0 && (
        <Callout tone="note">
          {arrayOrEmpty<string>(caveats).map((c, i) => <p key={i}>{c}</p>)}
        </Callout>
      )}
    </div>
  );
}

export default UnforeseenIncomePanel;
