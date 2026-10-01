"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2, Loader2 } from "lucide-react";
import { formatPaise } from "@/lib/services/formatting";
import {
  getWorksheet, saveWorksheet,
  type HousePropertyResult, type WorksheetResponse,
} from "@/lib/data/income-tax";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { bpsFromPercentInput, paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { Callout } from "@/components/ui/callout";

// The redeploy-window FALLBACK for the vocabularies `domain/income_tax/
// house_property` owns (USES, PURPOSES) — the Schedule III caption shape. Each
// is pinned from the Python side against the module, because a list asserted
// against its own copy passes whenever both drift together.
const USE_OPTIONS = [
  { key: "let_out", label: "Let out" },
  { key: "self_occupied", label: "Self-occupied" },
  { key: "deemed_let_out", label: "Deemed let-out (a third house)" },
];
const PURPOSE_OPTIONS = [
  { key: "", label: "Not stated" },
  { key: "acquire_construct", label: "To acquire or construct" },
  { key: "repair_renew_reconstruct", label: "To repair, renew or reconstruct" },
];

interface Row {
  key: string; name: string; use: string; sharePct: string;
  municipalValue: string; fairRent: string; standardRent: string;
  rent: string; unrealised: string; rule4: "" | "yes" | "no"; vacant: boolean;
  municipalTax: string; interest: string; preConstruction: string;
  completionFy: string; loanTakenOn: string; completedOn: string; loanPurpose: string;
}

let _seq = 0;
function newRow(over: Partial<Row> = {}): Row {
  _seq += 1;
  return {
    key: `p${Date.now().toString(36)}${_seq}`, name: "", use: "let_out", sharePct: "100",
    municipalValue: "", fairRent: "", standardRent: "", rent: "", unrealised: "",
    rule4: "", vacant: false, municipalTax: "", interest: "", preConstruction: "",
    completionFy: "", loanTakenOn: "", completedOn: "", loanPurpose: "", ...over,
  };
}

/** A saved payload back into the rows the CA edits. Defensive on every field:
 *  a row written before a field existed has no key for it. */
function rowsFrom(payload: unknown): Row[] {
  const p = objectOrNull<{ properties?: unknown }>(payload);
  return arrayOrEmpty<Record<string, unknown>>(p?.properties).map(o => {
    const boxText = (k: string) => (typeof o[k] === "number" ? rupeeInputFromPaise(o[k] as number) : "");
    const str = (k: string) => (typeof o[k] === "string" ? (o[k] as string) : "");
    const bps = typeof o.share_bps === "number" ? o.share_bps : 10000;
    // A spread of `{ key: undefined }` would OVERWRITE the generated key, so the
    // saved one is passed only where there is one.
    const saved = str("key");
    return newRow({
      ...(saved ? { key: saved } : {}), name: str("name"), use: str("use") || "let_out",
      sharePct: rupeeInputFromPaise(bps).replace(/\.00$/, ""),
      municipalValue: boxText("municipal_value_paise"), fairRent: boxText("fair_rent_paise"),
      standardRent: boxText("standard_rent_paise"), rent: boxText("rent_receivable_paise"),
      unrealised: boxText("unrealised_rent_paise"),
      rule4: o.unrealised_rent_rule_4_met === true ? "yes" : o.unrealised_rent_rule_4_met === false ? "no" : "",
      vacant: o.vacant_part_of_year === true,
      municipalTax: boxText("municipal_tax_paid_paise"), interest: boxText("interest_paise"),
      preConstruction: boxText("pre_construction_interest_paise"),
      completionFy: str("completion_fy"), loanTakenOn: str("loan_taken_on"),
      completedOn: str("completed_on"), loanPurpose: str("loan_purpose"),
    } as Partial<Row>);
  });
}

/** The rows into the payload the server validates. Returns the first thing the
 *  CA typed that is not an amount rather than sending a guess. */
function payloadFrom(rows: Row[]): { payload?: Record<string, unknown>; error?: string } {
  const out: Record<string, unknown>[] = [];
  for (const r of rows) {
    const label = r.name || "A property";
    const amount = (text: string, what: string): number | string => {
      const v = paiseFromRupeeInput(text);
      return v === null ? `${label}: ${what} is not an amount.` : v;
    };
    const fields: [string, string, string][] = [
      ["municipal_value_paise", r.municipalValue, "municipal value"],
      ["fair_rent_paise", r.fairRent, "fair rent"],
      ["rent_receivable_paise", r.rent, "rent receivable"],
      ["unrealised_rent_paise", r.unrealised, "unrealised rent"],
      ["municipal_tax_paid_paise", r.municipalTax, "municipal tax paid"],
      ["interest_paise", r.interest, "interest"],
      ["pre_construction_interest_paise", r.preConstruction, "pre-construction interest"],
    ];
    const one: Record<string, unknown> = {
      key: r.key, name: r.name.trim(), use: r.use,
      vacant_part_of_year: r.vacant,
      unrealised_rent_rule_4_met: r.rule4 === "" ? null : r.rule4 === "yes",
      completion_fy: r.completionFy.trim() || null,
      loan_taken_on: r.loanTakenOn || null,
      completed_on: r.completedOn || null,
      loan_purpose: r.loanPurpose || null,
    };
    for (const [field, text, what] of fields) {
      const v = amount(text, what);
      if (typeof v === "string") return { error: v };
      one[field] = v;
    }
    if (r.standardRent.trim() !== "") {
      const v = amount(r.standardRent, "standard rent");
      if (typeof v === "string") return { error: v };
      one.standard_rent_paise = v;
    }
    const share = bpsFromPercentInput(r.sharePct);
    if (share === null || share < 1 || share > 10000) {
      return { error: `${label}: the ownership share must be between 0.01% and 100%.` };
    }
    one.share_bps = share;
    out.push(one);
  }
  return { payload: { properties: out } };
}

/**
 * The house-property worksheet (TDS-INCOME-TAX-14).
 *
 * THIS SCREEN DECIDES NOTHING. It collects each property's figures, sends them,
 * and renders the server's working — the annual value, the municipal tax, the
 * 30%, the interest allowed and what was capped, and the head's income. The
 * rules (§23, §24, the self-occupied cap, the five pre-construction instalments,
 * a co-owner's share) are `domain/income_tax/house_property`'s, and so is the
 * refusal where a third house is marked self-occupied.
 *
 * PREPARE-ONLY. "Use this figure" puts the head's income in the computation's
 * own House Property box and nothing else; it is the CA's click, and the
 * computation still applies §71(3A) or §115BAC(2) to a loss.
 */
export function HousePropertyWorksheet({
  clientId, fy, useNewRegime, onUse,
}: {
  clientId: string;
  fy: string;
  useNewRegime: boolean;
  /** Called with the head's income in paise — negative for a loss. */
  onUse: (headIncomePaise: number) => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [result, setResult] = useState<HousePropertyResult | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const take = useCallback((r: WorksheetResponse<HousePropertyResult>) => {
    setRows(rowsFrom(r.payload));
    setResult(objectOrNull<HousePropertyResult>(r.result));
    setSaved(Boolean(r.saved));
  }, []);

  // The worksheet is recomputed for the regime asked: nothing derived is stored,
  // so flipping the regime on the computation screen changes the answer here.
  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !fy) return;
    let cancelled = false;
    setErr(null);
    getWorksheet<HousePropertyResult>("house_property", clientId, fy, useNewRegime)
      .then(r => { if (!cancelled) take(r); })
      .catch(e => { if (!cancelled) setErr(e instanceof Error ? e.message : "Could not read the worksheet."); });
    return () => { cancelled = true; };
  }, [clientId, fy, useNewRegime, take]);

  async function workOut() {
    const built = payloadFrom(rows);
    if (built.error || !built.payload) { setErr(built.error ?? "Check the figures."); return; }
    setBusy(true); setErr(null);
    try {
      const r = await saveWorksheet<HousePropertyResult>(
        "house_property", clientId, fy, useNewRegime, built.payload);
      setResult(objectOrNull<HousePropertyResult>(r.result));
      setSaved(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the worksheet.");
    } finally {
      setBusy(false);
    }
  }

  const set = (key: string, patch: Partial<Row>) =>
    setRows(rs => rs.map(r => (r.key === key ? { ...r, ...patch } : r)));
  const input = "w-full text-xs px-2 py-1.5 border border-ps-border rounded-lg";
  const lines = arrayOrEmpty<HousePropertyResult["properties"][number]>(result?.properties);

  return (
    <div className="space-y-3">
      <p className="text-2xs text-ps-label">
        §22 to §27: annual value, municipal tax, the standard deduction under §24(a) and the interest under §24(b).
        Enter each property&apos;s figures for the year; the working is the server&apos;s.
      </p>

      {rows.map(r => {
        const own = r.use === "self_occupied";
        return (
          <div key={r.key} className="border border-ps-border rounded-lg p-3 space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <div className="flex-1 min-w-[10rem]">
                <label className="text-3xs text-ps-label block mb-1">Property</label>
                <input className={input} value={r.name} placeholder="e.g. Shop, Andheri"
                  onChange={e => set(r.key, { name: e.target.value })} />
              </div>
              <div>
                <label className="text-3xs text-ps-label block mb-1">Use</label>
                <select className={input} value={r.use} onChange={e => set(r.key, { use: e.target.value })}>
                  {USE_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
                </select>
              </div>
              <div className="w-24">
                <label className="text-3xs text-ps-label block mb-1">Your share %</label>
                <input className={input} inputMode="decimal" value={r.sharePct}
                  onChange={e => set(r.key, { sharePct: e.target.value })} />
              </div>
              <button type="button" aria-label="Remove this property"
                onClick={() => setRows(rs => rs.filter(x => x.key !== r.key))}
                className="p-1.5 text-ps-hint hover:text-state-problem">
                <Trash2 size={14} />
              </button>
            </div>

            {!own && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {([
                  ["Municipal value (₹)", "municipalValue"], ["Fair rent (₹)", "fairRent"],
                  ["Standard rent (₹) — if fixed", "standardRent"],
                  ...(r.use === "deemed_let_out" ? [] : [
                    ["Rent receivable (₹)", "rent"], ["Unrealised rent (₹)", "unrealised"],
                  ] as [string, keyof Row][]),
                  ["Municipal tax paid (₹)", "municipalTax"],
                ] as [string, keyof Row][]).map(([label, field]) => (
                  <div key={field}>
                    <label className="text-3xs text-ps-label block mb-1">{label}</label>
                    <input className={input} inputMode="decimal" value={r[field] as string}
                      onChange={e => set(r.key, { [field]: e.target.value } as Partial<Row>)} />
                  </div>
                ))}
              </div>
            )}
            {!own && r.use === "let_out" && (
              <div className="flex flex-wrap gap-4 items-center">
                <label className="flex items-center gap-1.5 text-2xs text-ps-body">
                  <input type="checkbox" checked={r.vacant}
                    onChange={e => set(r.key, { vacant: e.target.checked })} />
                  Vacant for part of the year
                </label>
                {r.unrealised.trim() !== "" && r.unrealised.trim() !== "0" && (
                  <label className="flex items-center gap-1.5 text-2xs text-ps-body">
                    Rule 4&apos;s conditions for the unrealised rent are met:
                    <select className="text-2xs border border-ps-border rounded px-1 py-0.5" value={r.rule4}
                      onChange={e => set(r.key, { rule4: e.target.value as Row["rule4"] })}>
                      <option value="">Not stated</option>
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  </label>
                )}
              </div>
            )}

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div>
                <label className="text-3xs text-ps-label block mb-1">Interest — your own share (₹)</label>
                <input className={input} inputMode="decimal" value={r.interest}
                  onChange={e => set(r.key, { interest: e.target.value })} />
              </div>
              <div>
                <label className="text-3xs text-ps-label block mb-1">Interest before completion — total (₹)</label>
                <input className={input} inputMode="decimal" value={r.preConstruction}
                  onChange={e => set(r.key, { preConstruction: e.target.value })} />
              </div>
              <div>
                <label className="text-3xs text-ps-label block mb-1">Year of completion (e.g. 2023-24)</label>
                <input className={input} value={r.completionFy} placeholder="2023-24"
                  onChange={e => set(r.key, { completionFy: e.target.value })} />
              </div>
              {own && (
                <>
                  <div>
                    <label className="text-3xs text-ps-label block mb-1">The loan was taken</label>
                    <select className={input} value={r.loanPurpose}
                      onChange={e => set(r.key, { loanPurpose: e.target.value })}>
                      {PURPOSE_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-3xs text-ps-label block mb-1">Loan taken on</label>
                    <input type="date" className={input} value={r.loanTakenOn}
                      onChange={e => set(r.key, { loanTakenOn: e.target.value })} />
                  </div>
                  <div>
                    <label className="text-3xs text-ps-label block mb-1">House completed on</label>
                    <input type="date" className={input} value={r.completedOn}
                      onChange={e => set(r.key, { completedOn: e.target.value })} />
                  </div>
                </>
              )}
            </div>
          </div>
        );
      })}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setRows(rs => [...rs, newRow()])}
          className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg inline-flex items-center gap-1">
          <Plus size={12} /> Add a property
        </button>
        <button type="button" onClick={workOut} disabled={busy}
          className="text-xs px-3 py-1.5 bg-brand text-white rounded-lg disabled:opacity-40 inline-flex items-center gap-1">
          {busy && <Loader2 size={12} className="animate-spin" />}
          Save and work out
        </button>
        {saved && <span className="text-3xs text-ps-hint self-center">Saved for FY {fy}</span>}
      </div>

      {err && <p className="text-xs text-state-problem">{err}</p>}

      {result && lines.length > 0 && (
        <div className="space-y-2">
          {lines.map(l => (
            <div key={l.key} className="bg-ps-bg rounded-lg p-3 text-xs space-y-1">
              <div className="flex justify-between gap-2">
                <strong>{l.name}</strong>
                <span className={l.income_paise < 0 ? "text-state-attention" : ""}>
                  {formatPaise(l.income_paise)}
                </span>
              </div>
              <p className="text-3xs text-ps-label">
                Annual value {formatPaise(l.gross_annual_value_paise)} · municipal tax {formatPaise(l.municipal_tax_paise)}
                {" "}· net {formatPaise(l.net_annual_value_paise)} · §24(a) {formatPaise(l.standard_deduction_paise)}
                {" "}· interest allowed {formatPaise(l.interest_allowed_paise)}
                {l.interest_disallowed_paise > 0 && ` (${formatPaise(l.interest_disallowed_paise)} above the cap)`}
              </p>
              {arrayOrEmpty<string>(l.workings).map((w, i) => <p key={i} className="text-3xs text-ps-hint">{w}</p>)}
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ps-border pt-2">
            <p className="text-xs font-semibold">
              Income from house property: {formatPaise(result.head_income_paise)}
              {result.is_loss && " (a loss)"}
            </p>
            <button type="button" onClick={() => onUse(result.head_income_paise)}
              className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg">
              Use this figure in the computation
            </button>
          </div>
        </div>
      )}

      {arrayOrEmpty<string>(result?.gaps).length > 0 && (
        <Callout tone="withheld" title="What could not be established">
          {arrayOrEmpty<string>(result?.gaps).map((g, i) => <p key={i}>{g}</p>)}
        </Callout>
      )}
      {arrayOrEmpty<string>(result?.caveats).length > 0 && (
        <Callout tone="note">
          {arrayOrEmpty<string>(result?.caveats).map((c, i) => <p key={i}>{c}</p>)}
        </Callout>
      )}
    </div>
  );
}

export default HousePropertyWorksheet;
