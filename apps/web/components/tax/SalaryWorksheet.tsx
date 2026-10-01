"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2, Loader2 } from "lucide-react";
import { formatPaise } from "@/lib/services/formatting";
import {
  getWorksheet, saveWorksheet,
  type SalaryResult, type WorksheetResponse,
} from "@/lib/data/income-tax";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { Callout } from "@/components/ui/callout";

// The redeploy-window FALLBACK for the vocabularies `domain/income_tax/
// schedule_s` owns (PERQUISITE_KINDS, EXEMPTION_KINDS), pinned from the Python
// side. Whether an exemption survives §115BAC(2) is NOT held here: the server
// reports each one it withdrew in the working.
const PERQUISITE_OPTIONS = [
  { key: "accommodation", label: "Rent-free or concessional accommodation" },
  { key: "motor_car", label: "Motor car" },
  { key: "concessional_loan", label: "Interest-free or concessional loan" },
  { key: "meals_gifts_other", label: "Meals, gifts, club and similar" },
  { key: "employer_contribution_above_limit", label: "Employer's contributions above ₹7.5 lakh — §17(2)(vii)/(viia)" },
  { key: "other", label: "Other perquisite" },
];
const EXEMPTION_OPTIONS = [
  { key: "gratuity_10_10", label: "Gratuity — §10(10)" },
  { key: "leave_encashment_10_10aa", label: "Leave encashment on retirement — §10(10AA)" },
  { key: "commuted_pension_10_10a", label: "Commuted pension — §10(10A)" },
  { key: "vrs_10_10c", label: "Voluntary retirement — §10(10C)" },
  { key: "official_duty_allowance_10_14_i", label: "Allowance for expenses of official duty — §10(14)(i)" },
  { key: "lta_10_5", label: "Leave travel concession — §10(5)" },
  { key: "education_hostel_10_14_ii", label: "Children's education and hostel allowance — §10(14)(ii)" },
  { key: "other_10", label: "Another §10 exemption (stated by the CA)" },
];

interface PerqRow { kind: string; amount: string; description: string }
interface EsopRow { description: string; shares: string; fmv: string; price: string }
interface ExemptRow { kind: string; amount: string }
interface Emp {
  key: string; name: string; tan: string; previous: boolean;
  salary: string; profitsInLieu: string; professionalTax: string;
  perqs: PerqRow[]; esop: EsopRow[]; exempts: ExemptRow[];
}
interface HraState { basic: string; received: string; rent: string; metro: boolean }

let _seq = 0;
function newEmp(over: Partial<Emp> = {}): Emp {
  _seq += 1;
  return {
    key: `e${Date.now().toString(36)}${_seq}`, name: "", tan: "", previous: false,
    salary: "", profitsInLieu: "", professionalTax: "",
    perqs: [], esop: [], exempts: [], ...over,
  };
}

function empsFrom(payload: unknown): Emp[] {
  const p = objectOrNull<{ employers?: unknown }>(payload);
  const boxText = (o: Record<string, unknown>, k: string) =>
    (typeof o[k] === "number" ? rupeeInputFromPaise(o[k] as number) : "");
  const str = (o: Record<string, unknown>, k: string) => (typeof o[k] === "string" ? (o[k] as string) : "");
  return arrayOrEmpty<Record<string, unknown>>(p?.employers).map(o => {
    const saved = str(o, "key");
    return newEmp({
      ...(saved ? { key: saved } : {}),
      name: str(o, "name"), tan: str(o, "tan"), previous: o.is_previous_employer === true,
      salary: boxText(o, "salary_17_1_paise"), profitsInLieu: boxText(o, "profits_in_lieu_17_3_paise"),
      professionalTax: boxText(o, "professional_tax_paise"),
      perqs: arrayOrEmpty<Record<string, unknown>>(o.perquisites).map(x => ({
        kind: str(x, "kind") || "other", amount: boxText(x, "amount_paise"), description: str(x, "description"),
      })),
      esop: arrayOrEmpty<Record<string, unknown>>(o.esop_exercises).map(x => ({
        description: str(x, "description"),
        shares: typeof x.shares === "number" ? String(x.shares) : "",
        fmv: boxText(x, "fmv_per_share_paise"), price: boxText(x, "exercise_price_per_share_paise"),
      })),
      exempts: arrayOrEmpty<Record<string, unknown>>(o.exemptions).map(x => ({
        kind: str(x, "kind") || "other_10", amount: boxText(x, "amount_paise"),
      })),
    });
  });
}

function hraFrom(payload: unknown): HraState {
  const p = objectOrNull<{ hra?: Record<string, unknown> }>(payload);
  const h = p?.hra ?? {};
  const boxText = (k: string) => (typeof h[k] === "number" ? rupeeInputFromPaise(h[k] as number) : "");
  return { basic: boxText("basic_salary_paise"), received: boxText("hra_received_paise"),
           rent: boxText("rent_paid_paise"), metro: h.is_metro === true };
}

function payloadFrom(emps: Emp[], hra: HraState): { payload?: Record<string, unknown>; error?: string } {
  const amt = (text: string, what: string): number => {
    const v = paiseFromRupeeInput(text);
    if (v === null) throw new Error(`${what} is not an amount.`);
    return v;
  };
  try {
    const employers = emps.map(e => {
      const who = e.name || "An employer";
      return {
        key: e.key, name: e.name.trim(), tan: e.tan.trim() || null,
        is_previous_employer: e.previous,
        salary_17_1_paise: amt(e.salary, `${who}: salary`),
        profits_in_lieu_17_3_paise: amt(e.profitsInLieu, `${who}: profits in lieu of salary`),
        professional_tax_paise: amt(e.professionalTax, `${who}: professional tax`),
        perquisites: e.perqs.map(x => ({
          kind: x.kind, amount_paise: amt(x.amount, `${who}: a perquisite`), description: x.description,
        })),
        esop_exercises: e.esop.map(x => {
          // A share COUNT, not an amount: whole shares only.
          if (!/^\d*$/.test(x.shares.trim())) throw new Error(`${who}: the number of shares is not a whole number.`);
          return {
            description: x.description,
            shares: x.shares.trim() === "" ? 0 : Number(x.shares),
            fmv_per_share_paise: amt(x.fmv, `${who}: the fair market value per share`),
            exercise_price_per_share_paise: amt(x.price, `${who}: the exercise price per share`),
          };
        }),
        exemptions: e.exempts.map(x => ({ kind: x.kind, amount_paise: amt(x.amount, `${who}: an exemption`) })),
      };
    });
    return {
      payload: {
        employers,
        hra: {
          basic_salary_paise: amt(hra.basic, "HRA: basic salary"),
          hra_received_paise: amt(hra.received, "HRA received"),
          rent_paid_paise: amt(hra.rent, "Rent paid"),
          is_metro: hra.metro,
        },
      },
    };
  } catch (e) {
    return { error: e instanceof Error ? e.message : "Check the figures." };
  }
}

/**
 * The salary worksheet — Schedule S (TDS-INCOME-TAX-15).
 *
 * THIS SCREEN DECIDES NOTHING. It collects each employer's Form 16 figures,
 * sends them, and renders the server's Schedule S: one block per employer,
 * the §10 exemptions the regime allows (and the ones it withdrew, named), the
 * standard deduction taken ONCE, and the income chargeable. ESOP and RSU are
 * valued by the server from the share count and the two prices.
 *
 * PREPARE-ONLY. "Use in the computation" fills the salary box and the HRA
 * boxes the computation already has — the figure the engine takes, which is the
 * gross less the other exemptions and professional tax, NOT the total — and the
 * CA presses it.
 */
export function SalaryWorksheet({
  clientId, fy, useNewRegime, onUse,
}: {
  clientId: string;
  fy: string;
  useNewRegime: boolean;
  onUse: (engineInputs: SalaryResult["engine_inputs"]) => void;
}) {
  const [emps, setEmps] = useState<Emp[]>([]);
  const [hra, setHra] = useState<HraState>({ basic: "", received: "", rent: "", metro: false });
  const [result, setResult] = useState<SalaryResult | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const take = useCallback((r: WorksheetResponse<SalaryResult>) => {
    setEmps(empsFrom(r.payload));
    setHra(hraFrom(r.payload));
    setResult(objectOrNull<SalaryResult>(r.result));
    setSaved(Boolean(r.saved));
  }, []);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder" || !fy) return;
    let cancelled = false;
    setErr(null);
    getWorksheet<SalaryResult>("salary", clientId, fy, useNewRegime)
      .then(r => { if (!cancelled) take(r); })
      .catch(e => { if (!cancelled) setErr(e instanceof Error ? e.message : "Could not read the worksheet."); });
    return () => { cancelled = true; };
  }, [clientId, fy, useNewRegime, take]);

  async function workOut() {
    const built = payloadFrom(emps, hra);
    if (built.error || !built.payload) { setErr(built.error ?? "Check the figures."); return; }
    setBusy(true); setErr(null);
    try {
      const r = await saveWorksheet<SalaryResult>("salary", clientId, fy, useNewRegime, built.payload);
      setResult(objectOrNull<SalaryResult>(r.result));
      setSaved(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the worksheet.");
    } finally {
      setBusy(false);
    }
  }

  const upd = (key: string, patch: Partial<Emp>) =>
    setEmps(es => es.map(e => (e.key === key ? { ...e, ...patch } : e)));
  const input = "w-full text-xs px-2 py-1.5 border border-ps-border rounded-lg";
  const blocks = arrayOrEmpty<SalaryResult["employers"][number]>(result?.employers);

  return (
    <div className="space-y-3">
      <p className="text-2xs text-ps-label">
        Schedule S: one block per employer, from each Form 16. Perquisites are the taxable value the
        employer stated; ESOP and RSU are valued here from the share count and the two prices.
      </p>

      {emps.map(e => (
        <div key={e.key} className="border border-ps-border rounded-lg p-3 space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex-1 min-w-[10rem]">
              <label className="text-3xs text-ps-label block mb-1">Employer</label>
              <input className={input} value={e.name} onChange={ev => upd(e.key, { name: ev.target.value })} />
            </div>
            <div className="w-32">
              <label className="text-3xs text-ps-label block mb-1">TAN</label>
              <input className={input} value={e.tan} maxLength={10}
                onChange={ev => upd(e.key, { tan: ev.target.value.toUpperCase() })} />
            </div>
            <label className="flex items-center gap-1.5 text-2xs text-ps-body pb-1.5">
              <input type="checkbox" checked={e.previous}
                onChange={ev => upd(e.key, { previous: ev.target.checked })} />
              Previous employer
            </label>
            <button type="button" aria-label="Remove this employer"
              onClick={() => setEmps(es => es.filter(x => x.key !== e.key))}
              className="p-1.5 text-ps-hint hover:text-state-problem">
              <Trash2 size={14} />
            </button>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {([["Salary — §17(1) (₹)", "salary"], ["Profits in lieu — §17(3) (₹)", "profitsInLieu"],
               ["Professional tax (₹)", "professionalTax"]] as [string, keyof Emp][]).map(([label, field]) => (
              <div key={field}>
                <label className="text-3xs text-ps-label block mb-1">{label}</label>
                <input className={input} inputMode="decimal" value={e[field] as string}
                  onChange={ev => upd(e.key, { [field]: ev.target.value } as Partial<Emp>)} />
              </div>
            ))}
          </div>

          <div className="space-y-1.5">
            <p className="text-3xs text-ps-label">Perquisites — §17(2), as valued in Form 16</p>
            {e.perqs.map((x, i) => (
              <div key={i} className="flex flex-wrap gap-2">
                <select className="text-xs px-2 py-1.5 border border-ps-border rounded-lg" value={x.kind}
                  onChange={ev => upd(e.key, { perqs: e.perqs.map((y, j) => j === i ? { ...y, kind: ev.target.value } : y) })}>
                  {PERQUISITE_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
                </select>
                <input className="w-32 text-xs px-2 py-1.5 border border-ps-border rounded-lg text-right" inputMode="decimal"
                  placeholder="₹" value={x.amount}
                  onChange={ev => upd(e.key, { perqs: e.perqs.map((y, j) => j === i ? { ...y, amount: ev.target.value } : y) })} />
                <button type="button" aria-label="Remove this perquisite" className="p-1 text-ps-hint hover:text-state-problem"
                  onClick={() => upd(e.key, { perqs: e.perqs.filter((_, j) => j !== i) })}>
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            <button type="button" className="text-2xs text-blue-600 inline-flex items-center gap-1"
              onClick={() => upd(e.key, { perqs: [...e.perqs, { kind: "other", amount: "", description: "" }] })}>
              <Plus size={11} /> Add a perquisite
            </button>
          </div>

          <div className="space-y-1.5">
            <p className="text-3xs text-ps-label">ESOP and RSU exercised — §17(2)(vi)</p>
            {e.esop.map((x, i) => (
              <div key={i} className="flex flex-wrap gap-2 items-center">
                <input className="w-40 text-xs px-2 py-1.5 border border-ps-border rounded-lg" placeholder="Grant"
                  value={x.description}
                  onChange={ev => upd(e.key, { esop: e.esop.map((y, j) => j === i ? { ...y, description: ev.target.value } : y) })} />
                <input className="w-20 text-xs px-2 py-1.5 border border-ps-border rounded-lg text-right" inputMode="numeric"
                  placeholder="Shares" value={x.shares}
                  onChange={ev => upd(e.key, { esop: e.esop.map((y, j) => j === i ? { ...y, shares: ev.target.value } : y) })} />
                <input className="w-28 text-xs px-2 py-1.5 border border-ps-border rounded-lg text-right" inputMode="decimal"
                  placeholder="FMV per share ₹" value={x.fmv}
                  onChange={ev => upd(e.key, { esop: e.esop.map((y, j) => j === i ? { ...y, fmv: ev.target.value } : y) })} />
                <input className="w-28 text-xs px-2 py-1.5 border border-ps-border rounded-lg text-right" inputMode="decimal"
                  placeholder="Price paid ₹ (0 for RSU)" value={x.price}
                  onChange={ev => upd(e.key, { esop: e.esop.map((y, j) => j === i ? { ...y, price: ev.target.value } : y) })} />
                <button type="button" aria-label="Remove this exercise" className="p-1 text-ps-hint hover:text-state-problem"
                  onClick={() => upd(e.key, { esop: e.esop.filter((_, j) => j !== i) })}>
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            <button type="button" className="text-2xs text-blue-600 inline-flex items-center gap-1"
              onClick={() => upd(e.key, { esop: [...e.esop, { description: "", shares: "", fmv: "", price: "" }] })}>
              <Plus size={11} /> Add an exercise
            </button>
          </div>

          <div className="space-y-1.5">
            <p className="text-3xs text-ps-label">Exemptions under §10 — the EXEMPT amount, as Form 16 states it</p>
            {e.exempts.map((x, i) => (
              <div key={i} className="flex flex-wrap gap-2">
                <select className="text-xs px-2 py-1.5 border border-ps-border rounded-lg" value={x.kind}
                  onChange={ev => upd(e.key, { exempts: e.exempts.map((y, j) => j === i ? { ...y, kind: ev.target.value } : y) })}>
                  {EXEMPTION_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
                </select>
                <input className="w-32 text-xs px-2 py-1.5 border border-ps-border rounded-lg text-right" inputMode="decimal"
                  placeholder="₹" value={x.amount}
                  onChange={ev => upd(e.key, { exempts: e.exempts.map((y, j) => j === i ? { ...y, amount: ev.target.value } : y) })} />
                <button type="button" aria-label="Remove this exemption" className="p-1 text-ps-hint hover:text-state-problem"
                  onClick={() => upd(e.key, { exempts: e.exempts.filter((_, j) => j !== i) })}>
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            <button type="button" className="text-2xs text-blue-600 inline-flex items-center gap-1"
              onClick={() => upd(e.key, { exempts: [...e.exempts, { kind: "gratuity_10_10", amount: "" }] })}>
              <Plus size={11} /> Add an exemption
            </button>
          </div>
        </div>
      ))}

      <div className="border border-ps-border rounded-lg p-3 space-y-2">
        <p className="text-2xs font-semibold text-ps-body">House rent allowance — §10(13A), for the year</p>
        <div className="grid grid-cols-3 gap-2">
          {([["Basic + DA (₹)", "basic"], ["HRA received (₹)", "received"],
             ["Rent paid (₹)", "rent"]] as [string, "basic" | "received" | "rent"][]).map(([label, field]) => (
            <div key={field}>
              <label className="text-3xs text-ps-label block mb-1">{label}</label>
              <input className={input} inputMode="decimal" value={hra[field]}
                onChange={ev => setHra(h => ({ ...h, [field]: ev.target.value }))} />
            </div>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-2xs text-ps-body">
          <input type="checkbox" checked={hra.metro} onChange={ev => setHra(h => ({ ...h, metro: ev.target.checked }))} />
          Delhi, Mumbai, Kolkata or Chennai
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setEmps(es => [...es, newEmp()])}
          className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg inline-flex items-center gap-1">
          <Plus size={12} /> Add an employer
        </button>
        <button type="button" onClick={workOut} disabled={busy}
          className="text-xs px-3 py-1.5 bg-brand text-white rounded-lg disabled:opacity-40 inline-flex items-center gap-1">
          {busy && <Loader2 size={12} className="animate-spin" />}
          Save and work out
        </button>
        {saved && <span className="text-3xs text-ps-hint self-center">Saved for FY {fy}</span>}
      </div>

      {err && <p className="text-xs text-state-problem">{err}</p>}

      {result && blocks.length > 0 && (
        <div className="space-y-2">
          {blocks.map(b => (
            <div key={b.key} className="bg-ps-bg rounded-lg p-3 text-xs space-y-1">
              <div className="flex justify-between gap-2">
                <strong>{b.name}{b.is_previous_employer ? " (previous employer)" : ""}{b.tan ? ` · ${b.tan}` : ""}</strong>
                <span>{formatPaise(b.gross_salary_paise)}</span>
              </div>
              <p className="text-3xs text-ps-label">
                §17(1) {formatPaise(b.salary_17_1_paise)} · perquisites {formatPaise(b.perquisites_17_2_paise)}
                {" "}· ESOP/RSU {formatPaise(b.esop_perquisite_paise)} · §17(3) {formatPaise(b.profits_in_lieu_17_3_paise)}
                {" "}· exemptions allowed {formatPaise(b.exemptions_allowed_paise)}
                {" "}· professional tax {formatPaise(b.professional_tax_allowed_paise)}
              </p>
              {arrayOrEmpty<string>(b.workings).map((w, i) => <p key={i} className="text-3xs text-ps-hint">{w}</p>)}
            </div>
          ))}
          <div className="text-xs space-y-0.5 border-t border-ps-border pt-2">
            <p>Gross salary {formatPaise(result.gross_salary_paise)}</p>
            <p>Exemptions {formatPaise(result.exemptions_allowed_paise)} · HRA {formatPaise(result.hra_exemption_paise)}</p>
            <p>Standard deduction, once: {formatPaise(result.standard_deduction_paise)}</p>
            <p className="font-semibold">Income chargeable under Salaries: {formatPaise(result.income_chargeable_paise)}</p>
          </div>
          <div className="flex justify-end">
            <button type="button" onClick={() => onUse(result.engine_inputs)}
              className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg">
              Use in the computation
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

export default SalaryWorksheet;
