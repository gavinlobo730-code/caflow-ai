"use client";

/**
 * The book-to-tax bridge — profit per the accounts, down to taxable income.
 *
 * WHY THIS SCREEN EXISTS (FA-06 ≡ IT-09)
 *
 * Every Indian tax computation a CA hands a client starts with the profit in
 * the financial statements and works down to the figure the return is filed
 * on, one named adjustment at a time. It is the document the client actually
 * reads and the document an assessing officer asks for.
 *
 * `domain/income_tax/book_to_tax_bridge.py` has computed it since it was
 * written and `POST /api/income-tax/book-to-tax-bridge` has served it, and
 * grepping `apps/web` for either name returned TWO COMMENTS AND NO CALLER. So
 * §32 block depreciation could be computed and recorded, and nothing in the
 * product showed the two systems reconciled.
 *
 * NOTHING IS COMPUTED HERE. Every line, the taxable income, `foots` and
 * `is_complete` come off the response — CLAUDE.md, "zero business logic in the
 * frontend". What this page does is collect the one figure the books cannot
 * hold and show what the engine could not read.
 *
 * THREE OF THE FOUR INPUTS ARE LEFT BLANK ON PURPOSE. Book profit, the
 * depreciation charged in the accounts and the §43B(h) add-back are figures
 * these books already hold, so an empty box means "derive it" and the answer
 * says where each came from. Typing one overrides it — a CA may be bridging a
 * client whose accounts were prepared elsewhere — and the line then reads
 * "entered" rather than naming a source.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft, Info, AlertTriangle, CheckCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { request } from "@/lib/api";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { YearPicker } from "@/components/ui/year-picker";

interface BridgeLine {
  label: string;
  amount_paise: number;
  direction: "add" | "deduct";
  reference: string;
  derived: boolean;
  note: string;
}

interface DerivedInput {
  value_paise: number | null;
  source: string;
  derived: boolean;
}

interface Bridge {
  book_profit_paise: number;
  lines: BridgeLine[];
  taxable_income_paise: number;
  is_complete: boolean;
  missing: string[];
  reasons: string[];
  foots: boolean;
  inputs: Record<string, DerivedInput>;
  section_32: { is_complete: boolean; allowance_paise: number } | null;
}

/** The three figures that are derived when left blank, in the order they
 *  appear in the bridge. The fourth — brought-forward losses — is never
 *  derived, because §72/§73(4)/§74/§71B each let a loss reach only certain
 *  HEADS of income and the bridge holds one figure for the whole computation. */
const DERIVED_BOXES = [
  { key: "book_profit", field: "book_profit_paise",
    label: "Profit per the accounts",
    hint: "Blank derives it from this year's Profit & Loss" },
  { key: "disallowances", field: "disallowances_paise",
    label: "Disallowances",
    hint: "Blank derives the §43B(h) add-back only; add your own on top" },
  { key: "depreciation_per_books", field: "depreciation_per_books_paise",
    label: "Depreciation per the accounts",
    hint: "Blank reads what was posted to Depreciation Expense" },
] as const;

export default function BookToTaxBridgePage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const fyChoices = useMemo(() => financialYearChoicesAround(), []);
  const [fy, setFy] = useState(fyChoices[0]);
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [bfLoss, setBfLoss] = useState("");
  const [bridge, setBridge] = useState<Bridge | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { getClients().then(setClients).catch(() => setClients([])); }, []);

  const load = useCallback(async () => {
    if (!clientId || !fy) { setBridge(null); return; }
    setLoading(true);
    setError(null);
    try {
      // An EMPTY box sends nothing, which is what tells the server to derive.
      // Sending 0 would be a figure, and a figure suppresses the derivation —
      // the difference between "nobody said" and "it is nil".
      const body: Record<string, unknown> = { client_id: clientId, fy };
      for (const box of DERIVED_BOXES) {
        const raw = (typed[box.key] ?? "").trim();
        if (raw !== "") body[box.field] = paiseFromRupeeInput(raw);
      }
      body.brought_forward_loss_set_off_paise =
        bfLoss.trim() === "" ? 0 : paiseFromRupeeInput(bfLoss);

      const r = await request<{ success: boolean; data: Bridge; error: string | null }>(
        "/api/income-tax/book-to-tax-bridge", { method: "POST", body: JSON.stringify(body) });
      if (!r.success) { setBridge(null); setError(r.error ?? "Could not build the bridge"); return; }
      setBridge(r.data);
    } catch (e) {
      setBridge(null);
      setError(e instanceof Error ? e.message : "Could not build the bridge");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy, typed, bfLoss]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-ps-hint hover:text-ps-body"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-ps-ink">Book-to-tax bridge</h1>
          <p className="text-sm text-ps-label mt-0.5">
            Profit per the accounts, down to taxable income, one named adjustment at a time
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="min-w-[240px]">
          <ClientLookup clients={clients} value={clientId}
            onChange={(id) => setClientId(id)} ariaLabel="Client"
            placeholder="Select a client" />
        </div>
        <YearPicker value={fy} onChange={setFy} className="w-auto" />
      </div>

      {error && <div role="alert" className="bg-state-problem-surface text-state-problem rounded-lg px-5 py-4 text-sm">{error}</div>}

      {!clientId && (
        <div className="bg-ps-bg border border-ps-border rounded-xl px-5 py-4 text-sm text-ps-label">
          A bridge is one client&apos;s computation. Pick a client.
        </div>
      )}

      {clientId && (
        <Card>
          <div className="px-5 py-4 border-b border-ps-border">
            <p className="text-sm font-semibold text-ps-ink">Inputs</p>
            <p className="text-xs text-ps-label mt-0.5">
              Leave a box blank to take the figure from these books. Type one to
              override it — useful where the accounts were prepared elsewhere.
            </p>
          </div>
          <div className="px-5 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            {DERIVED_BOXES.map(box => (
              <div key={box.key}>
                <label htmlFor={box.key} className="text-xs font-medium text-ps-body">{box.label}</label>
                <input id={box.key} inputMode="decimal" placeholder="derived"
                  value={typed[box.key] ?? ""}
                  onChange={e => setTyped(t => ({ ...t, [box.key]: e.target.value }))}
                  className="mt-1 w-full border border-ps-border rounded-lg px-3 py-2 text-sm tabular-nums outline-none focus:border-brand" />
                <p className="text-2xs text-ps-hint mt-1">{box.hint}</p>
              </div>
            ))}
            <div>
              <label htmlFor="bf-loss" className="text-xs font-medium text-ps-body">
                Brought-forward loss set off
              </label>
              <input id="bf-loss" inputMode="decimal" placeholder="0"
                value={bfLoss} onChange={e => setBfLoss(e.target.value)}
                className="mt-1 w-full border border-ps-border rounded-lg px-3 py-2 text-sm tabular-nums outline-none focus:border-brand" />
              <p className="text-2xs text-ps-hint mt-1">
                Never derived — each head has its own section and its own set-off rules
              </p>
            </div>
          </div>
        </Card>
      )}

      {loading && <TableSkeleton cols={4} />}

      {bridge && !loading && (
        <>
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  <tr className="border-b border-ps-border bg-ps-bg">
                    <td className="px-4 py-3 font-medium text-ps-ink">Profit per the accounts</td>
                    <td className="px-4 py-3 text-xs text-ps-label">
                      {bridge.inputs?.book_profit?.source}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums font-semibold text-ps-ink">
                      {formatPaise(bridge.book_profit_paise)}
                    </td>
                  </tr>
                  {bridge.lines.map((l, i) => (
                    <tr key={i} className="border-b border-ps-muted">
                      <td className="px-4 py-3 text-ps-ink">
                        {l.label}
                        <span className="ml-2 text-3xs text-ps-hint">{l.reference}</span>
                        {/* `derived` is the engine's own field: true where the
                            figure came from these books, false where a human
                            supplied it. A reader checking a bridge needs to
                            know which, and the two look identical otherwise. */}
                        {!l.derived && (
                          <span className="ml-2 text-3xs text-state-attention">entered</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-ps-label">{l.note}</td>
                      <td className={`px-4 py-3 text-right tabular-nums ${
                        l.direction === "add" ? "text-ps-ink" : "text-ps-body"}`}>
                        {l.direction === "add" ? "+" : "−"} {formatPaise(l.amount_paise)}
                      </td>
                    </tr>
                  ))}
                  <tr className="bg-ps-muted">
                    <td className="px-4 py-3 font-semibold text-ps-ink">Taxable income</td>
                    <td className="px-4 py-3" />
                    <td className="px-4 py-3 text-right tabular-nums text-base font-bold text-ps-ink">
                      {formatPaise(bridge.taxable_income_paise)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          {/* FOOTS AND COMPLETE ARE TWO DIFFERENT PROPERTIES, and the bridge
              module's docstring is emphatic about it: "A bridge that
              reconciles and lies is worse than one that refuses to
              reconcile." Rendering only the arithmetic would show a green tick
              on a bridge whose largest line was never computed. */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className={`rounded-xl px-5 py-4 border ${bridge.foots
              ? "bg-state-ready-surface border-state-ready-border"
              : "bg-state-problem-surface border-state-problem-border"}`}>
              <p className="text-xs font-semibold flex items-center gap-1.5">
                {bridge.foots
                  ? <><CheckCircle size={13} className="text-state-ready" /><span className="text-state-ready">The arithmetic foots</span></>
                  : <><AlertTriangle size={13} className="text-state-problem" /><span className="text-state-problem">The lines do not add up</span></>}
              </p>
              <p className="text-xs text-ps-label mt-1">
                Book profit plus every adjustment equals the taxable income shown.
              </p>
            </div>
            <div className={`rounded-xl px-5 py-4 border ${bridge.is_complete
              ? "bg-state-ready-surface border-state-ready-border"
              : "bg-state-attention-surface border-state-attention-border"}`}>
              <p className="text-xs font-semibold flex items-center gap-1.5">
                {bridge.is_complete
                  ? <><CheckCircle size={13} className="text-state-ready" /><span className="text-state-ready">Every adjustment is accounted for</span></>
                  : <><AlertTriangle size={13} className="text-state-attention" /><span className="text-state-attention">Incomplete — an adjustment is missing</span></>}
              </p>
              <p className="text-xs text-ps-label mt-1">
                A bridge that foots is not the same as a bridge that is complete.
              </p>
            </div>
          </div>

          {bridge.missing.length > 0 && (
            <div className="bg-state-attention-surface border border-state-attention-border rounded-xl px-5 py-4">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="text-state-attention shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-state-attention">
                    Missing from this bridge
                  </p>
                  {bridge.missing.map((m, i) => (
                    <p key={i} className="text-xs text-state-attention">• {m}</p>
                  ))}
                </div>
              </div>
            </div>
          )}

          {bridge.reasons.length > 0 && (
            <div className="bg-ps-bg border border-ps-border rounded-xl px-5 py-4">
              <div className="flex items-start gap-2">
                <Info size={15} className="text-ps-hint shrink-0 mt-0.5" />
                <div className="space-y-1.5">
                  {bridge.reasons.map((r, i) => (
                    <p key={i} className="text-xs text-ps-label">{r}</p>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
