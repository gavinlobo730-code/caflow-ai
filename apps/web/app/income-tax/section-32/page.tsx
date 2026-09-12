"use client";

/**
 * IT Act §32 — depreciation on a BLOCK OF ASSETS.
 *
 * WHY THIS SCREEN EXISTS
 *
 * Depreciation is charged twice in every Indian business's books, on two
 * systems that are not two rates for one calculation:
 *
 *     Companies Act 2013, Schedule II — per ASSET, over its useful LIFE. That
 *     is the fixed-asset register, and it is what the accounts carry.
 *
 *     IT Act 1961, §32 — per BLOCK, at the block's RATE, on the block's
 *     written-down value. Assets lose their identity inside the block.
 *
 * The difference between them is usually the largest single line in the
 * book-to-tax bridge. Until migration 357 there was no §32 computation in this
 * product at all, and the bridge marked itself incomplete for every client.
 *
 * NOTHING IS COMPUTED HERE. Every figure comes from GET /api/income-tax/
 * section-32, which runs domain/income_tax/section_32.py — CLAUDE.md, "zero
 * business logic in the frontend". What this page does is collect the facts
 * only a CA holds, and show what is still missing.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Info, AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { request } from "@/lib/api";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { financialYearChoicesAround } from "@/lib/dates/periods";

// FROM THE CLOCK, NOT A LITERAL. This list ended at a year that is now in the
// past, so the current financial year could not be selected at all — broken on
// 1 April with nothing saying so. `financialYearChoicesAround` is the one
// helper (lib/dates/periods.ts); see
// scripts/a-financial-year-choice-comes-from-the-clock.test.ts.
const FY_OPTIONS = financialYearChoicesAround(null);

interface ApiEnvelope<T = unknown> { success: boolean; data?: T; error?: string | null }

/** One block as the engine reports it. Every figure is server-computed. */
interface BlockRow {
  block_key: string;
  rate_percent: number;
  opening_wdv_paise: number;
  additions_full_rate_paise: number;
  additions_half_rate_paise: number;
  additions_not_put_to_use_paise: number;
  deletions_paise: number;
  wdv_before_depreciation_paise: number;
  depreciation_paise: number;
  additional_depreciation_paise: number;
  closing_wdv_paise: number;
  /** §50: positive is a short-term capital GAIN, negative a LOSS. */
  short_term_capital_gain_paise: number;
  gaps: string[];
}

interface Section32Answer {
  financial_year: string;
  period_start: string;
  period_end: string;
  blocks: BlockRow[];
  depreciation_paise: number;
  additional_depreciation_paise: number;
  allowance_paise: number;
  short_term_capital_gain_paise: number;
  unclassified_assets: {
    asset_id: string; asset_code: string | null; asset_name: string | null;
    asset_category: string | null; purchase_cost_paise: number;
  }[];
  blocks_without_opening_wdv: string[];
  statutory_gaps: string[];
  /** The field to read before using the figure in a return. */
  is_complete: boolean;
}

export default function Section32Page() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [answer, setAnswer] = useState<Section32Answer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => { getClients().then(setClients).catch(() => setClients([])); }, []);

  const load = useCallback(async () => {
    if (!clientId) { setAnswer(null); return; }
    setLoading(true); setError(null);
    try {
      const j = await request<ApiEnvelope<Section32Answer>>(
        `/api/income-tax/section-32?client_id=${encodeURIComponent(clientId)}&fy=${fy}`);
      if (!j.success || !j.data) throw new Error(j.error ?? "Could not compute §32 depreciation.");
      setAnswer(j.data);
    } catch (e) {
      setAnswer(null);
      setError(e instanceof Error ? e.message : "Could not compute §32 depreciation.");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-[#94A3B8] hover:text-[#475569]"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Depreciation under §32</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            IT Act 1961 §32 — per block of assets, at the block&apos;s rate. Separate from
            the Companies Act Schedule II charge the accounts carry.
          </p>
        </div>
        <Button size="sm" onClick={() => setShowAdd(true)} disabled={!clientId}>
          <Plus size={14} className="mr-1" /> Add block
        </Button>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-[#64748B]">Client</label>
          <div className="mt-1 min-w-[220px]">
            <ClientLookup clients={clients} value={clientId} onChange={setClientId}
                          ariaLabel="Client" placeholder="Select client…" />
          </div>
        </div>
        <div>
          <label className="text-xs text-[#64748B]">Previous year</label>
          <select value={fy} onChange={e => setFy(e.target.value)}
            className="block mt-1 border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
            {FY_OPTIONS.map(f => <option key={f} value={f}>FY {f}</option>)}
          </select>
        </div>
      </div>

      {error && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-3 text-sm">{error}</div>}

      {!clientId ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <p className="text-sm text-[#94A3B8]">Select a client to see its blocks.</p>
        </div>
      ) : loading ? (
        <TableSkeleton cols={7} rows={3} />
      ) : answer ? (
        <>
          {/* WHETHER THE FIGURE IS SAFE TO USE comes first, not last. An
              incomplete §32 computation looks exactly like a complete one if
              the total is all you show. */}
          {!answer.is_complete && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 space-y-2">
              <p className="text-sm font-medium text-amber-900 flex items-center gap-2">
                <AlertTriangle size={15} /> This computation is not complete.
              </p>
              <ul className="list-disc pl-5 space-y-1">
                {answer.statutory_gaps.map((g, i) => (
                  <li key={i} className="text-xs text-amber-800">{g}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Depreciation u/s 32", value: formatPaise(answer.depreciation_paise), red: false },
              { label: "Additional u/s 32(1)(iia)", value: formatPaise(answer.additional_depreciation_paise), red: false },
              { label: "Allowable in the bridge", value: formatPaise(answer.allowance_paise), red: false },
              { label: "Short-term capital gain u/s 50",
                value: formatPaise(answer.short_term_capital_gain_paise),
                red: answer.short_term_capital_gain_paise !== 0 },
            ].map(s => (
              <Card key={s.label}>
                <CardContent className="pt-4 pb-3">
                  <p className={`text-lg font-bold tabular-nums ${s.red ? "text-amber-700" : "text-[#0F172A]"}`}>{s.value}</p>
                  <p className="text-xs text-[#64748B] mt-0.5">{s.label}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* §50 is NOT netted into the allowance, and the screen says so —
              it belongs in the capital-gains schedule, and §74 does not let a
              capital loss relieve business income anyway. */}
          {answer.short_term_capital_gain_paise !== 0 && (
            <p className="text-xs text-[#64748B] flex items-start gap-1.5">
              <Info size={13} className="shrink-0 mt-0.5" />
              The §50 figure is not part of the depreciation allowance. It is a capital
              gain or loss and belongs in the capital-gains schedule.
            </p>
          )}

          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F8FAFC] text-[#64748B]">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold">Block</th>
                  <th className="px-3 py-3 text-right font-semibold">Rate</th>
                  <th className="px-3 py-3 text-right font-semibold">Opening WDV</th>
                  <th className="px-3 py-3 text-right font-semibold">Additions (full)</th>
                  <th className="px-3 py-3 text-right font-semibold">Additions (half)</th>
                  <th className="px-3 py-3 text-right font-semibold">Moneys payable</th>
                  <th className="px-3 py-3 text-right font-semibold">Depreciation</th>
                  <th className="px-4 py-3 text-right font-semibold">Closing WDV</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {answer.blocks.length === 0 ? (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-[#94A3B8]">
                    No blocks recorded for FY {fy}. Add one with its opening written-down
                    value from last year&apos;s return.
                  </td></tr>
                ) : answer.blocks.map(b => (
                  <tr key={b.block_key} className="align-top">
                    <td className="px-4 py-3">
                      <p className="font-medium text-[#1E293B]">{b.block_key}</p>
                      {b.gaps.map((g, i) => (
                        <p key={i} className="text-[10px] text-amber-700 mt-0.5">{g}</p>
                      ))}
                      {b.short_term_capital_gain_paise !== 0 && (
                        <p className="text-[10px] text-amber-800 mt-0.5">
                          §50: {b.short_term_capital_gain_paise > 0 ? "short-term capital gain" : "short-term capital loss"}{" "}
                          {formatPaise(Math.abs(b.short_term_capital_gain_paise))} — no depreciation this year.
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">{b.rate_percent}%</td>
                    <td className="px-3 py-3 text-right tabular-nums">{formatPaise(b.opening_wdv_paise)}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{formatPaise(b.additions_full_rate_paise)}</td>
                    <td className="px-3 py-3 text-right tabular-nums">
                      {formatPaise(b.additions_half_rate_paise)}
                      {b.additions_not_put_to_use_paise > 0 && (
                        <span className="block text-[10px] text-[#94A3B8]">
                          {formatPaise(b.additions_not_put_to_use_paise)} not yet put to use
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">{formatPaise(b.deletions_paise)}</td>
                    <td className="px-3 py-3 text-right tabular-nums font-medium">
                      {formatPaise(b.depreciation_paise)}
                      {b.additional_depreciation_paise > 0 && (
                        <span className="block text-[10px] text-[#94A3B8]">
                          + {formatPaise(b.additional_depreciation_paise)} u/s 32(1)(iia)
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium">{formatPaise(b.closing_wdv_paise)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {answer.unclassified_assets.length > 0 && (
            /* Named, not placed. There is no safe default: the wrong block
               charges the wrong rate on the wrong base for the life of the
               asset, and no block silently drops its cost. */
            <div className="bg-white rounded-xl border border-amber-200 px-5 py-4 space-y-2">
              <p className="text-sm font-medium text-[#1E293B]">
                Assets not assigned to a §32 block
              </p>
              <p className="text-xs text-[#64748B]">
                §2(11) groups by nature <em>and</em> rate, so the Schedule II category does
                not decide it. Set the block on each asset in the fixed-asset register.
              </p>
              <ul className="space-y-1">
                {answer.unclassified_assets.map(a => (
                  <li key={a.asset_id} className="text-xs text-[#475569]">
                    <span className="font-medium">{a.asset_code ?? a.asset_name}</span>
                    {a.asset_category ? ` · ${a.asset_category}` : ""} · {formatPaise(a.purchase_cost_paise)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : null}

      {showAdd && (
        <AddBlockDialog clientId={clientId} fy={fy}
                        onClose={() => setShowAdd(false)}
                        onSaved={() => { setShowAdd(false); load(); }} />
      )}
    </div>
  );
}

/** The facts only a CA holds. Everything else about a block — its additions and
 *  its deletions — is derived from the fixed-asset register. */
function AddBlockDialog({ clientId, fy, onClose, onSaved }: {
  clientId: string; fy: string; onClose: () => void; onSaved: () => void;
}) {
  const [blockKey, setBlockKey] = useState("");
  const [rate, setRate] = useState("15");
  const [openingRs, setOpeningRs] = useState("");
  const [assetsRemain, setAssetsRemain] = useState<"yes" | "no" | "unknown">("yes");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    const opening = paiseFromRupeeInput(openingRs || "0");
    if (!blockKey.trim()) { setError("Give the block a name, e.g. Plant & Machinery 15%."); return; }
    if (opening === null) {
      setError("Enter the opening written-down value in rupees, e.g. 1250000 — without commas.");
      return;
    }
    const ratePercent = Number(rate);
    if (!Number.isInteger(ratePercent) || ratePercent < 0 || ratePercent > 100) {
      setError("The rate is a whole per cent from Appendix I — 15 for plant and machinery, 40 for computers.");
      return;
    }
    setSaving(true); setError("");
    try {
      const j = await request<ApiEnvelope>("/api/income-tax/section-32/blocks", {
        method: "PUT",
        body: JSON.stringify({
          client_id: clientId, financial_year: fy, block_key: blockKey.trim(),
          rate_percent: ratePercent, opening_wdv_paise: opening,
          assets_remain: assetsRemain === "unknown" ? null : assetsRemain === "yes",
          notes: notes.trim() || null,
        }),
      });
      if (!j.success) throw new Error(j.error ?? "Could not save the block.");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the block.");
    } finally {
      setSaving(false);
    }
  }

  const input = "w-full mt-1 px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl max-w-lg w-full p-6 space-y-4" onClick={e => e.stopPropagation()}>
        <div>
          <h3 className="text-sm font-semibold text-[#0F172A]">Add a §32 block — FY {fy}</h3>
          <p className="text-[11px] text-[#64748B] mt-1">
            A block is a group of assets of the same nature carrying the same rate (§2(11)),
            so its name and its rate are one decision. Its opening written-down value comes
            off last year&apos;s return.
          </p>
        </div>

        <label className="block text-xs font-medium text-[#475569]">
          Block
          <input className={input} value={blockKey} onChange={e => setBlockKey(e.target.value)}
                 placeholder="Plant &amp; Machinery 15%" />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs font-medium text-[#475569]">
            Rate (%)
            <input className={input} type="number" min={0} max={100} step={1}
                   value={rate} onChange={e => setRate(e.target.value)} />
            <span className="block text-[10px] text-[#94A3B8] mt-1">
              From Appendix I to the Income-tax Rules.
            </span>
          </label>
          <label className="block text-xs font-medium text-[#475569]">
            Opening WDV (₹)
            <input className={input} value={openingRs} onChange={e => setOpeningRs(e.target.value)}
                   placeholder="1250000" />
            <span className="block text-[10px] text-[#94A3B8] mt-1">
              Off last year&apos;s return. A zero allows no depreciation at all.
            </span>
          </label>
        </div>

        <label className="block text-xs font-medium text-[#475569]">
          Does any asset of this block remain at 31 March?
          <select className={input} value={assetsRemain}
                  onChange={e => setAssetsRemain(e.target.value as "yes" | "no" | "unknown")}>
            <option value="yes">Yes</option>
            <option value="no">No — every asset has gone</option>
            <option value="unknown">Not established</option>
          </select>
          <span className="block text-[10px] text-[#94A3B8] mt-1">
            §50 turns an emptied block into a short-term capital loss and allows no
            depreciation on it. A positive written-down value does not settle it.
          </span>
        </label>

        <label className="block text-xs font-medium text-[#475569]">
          Notes
          <input className={input} value={notes} onChange={e => setNotes(e.target.value)}
                 placeholder="Optional" />
        </label>

        {error && <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded px-3 py-2">{error}</p>}

        <div className="flex gap-2 justify-end pt-1">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <Button size="sm" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save block"}</Button>
        </div>
      </div>
    </div>
  );
}
