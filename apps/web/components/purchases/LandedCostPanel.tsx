"use client";

/**
 * What else the goods cost to get here — freight inward, insurance in transit,
 * a clearing agent's fee, non-creditable customs duty (INV-05, migration 396).
 *
 * WHY THIS SCREEN EXISTS
 *   AS-2 paragraph 6 puts "freight inwards and other expenditure directly
 *   attributable to the acquisition" in the cost of purchase. The receipt used
 *   to cost a line at its taxable value plus its §17(5)-blocked tax and nothing
 *   else, so a consignment that cost money to bring in was carried at less than
 *   it cost — and because the cost formula runs off the same figure, every
 *   later COGS was wrong with it.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). The basis in force, the split, what
 * is refused and why, the sentence on a charge recorded after the receipt — all
 * of it is `domain/inventory/landed_cost.py`'s answer served by
 * GET /api/purchase-bills/{id}/landed-costs. In particular the browser does NOT
 * know that value is the basis when nobody recorded one, does not compute a
 * share, and does not hold the two basis labels: a second copy of any of those
 * is a second place for them to be wrong.
 *
 * THE PREVIEW IS THE POINT. A posted journal cannot be rewritten (migration
 * 251), so the split has to be visible BEFORE the bill is received. The server
 * runs the same `apportion_many` the receipt runs, over the same goods lines.
 */
import { useCallback, useEffect, useState } from "react";
import { X, Truck, Trash2, Lock } from "lucide-react";
import { apiGet, apiCall, getAuthToken, fmt } from "@/lib/invoices/shared";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { Callout, GapList } from "@/components/ui/callout";

interface Charge {
  id: string;
  description: string;
  amount_paise: number;
  expense_account_id: string | null;
  source: string;
  bill_of_entry_id: string | null;
  applied_at: string | null;
  notes: string | null;
  is_applied: boolean;
  why_not_in_cost: string | null;
}

interface SplitLine {
  line_id: string;
  item_name: string;
  own_cost_paise: number;
  quantity: string;
  landed_cost_paise: number;
  total_cost_paise: number;
}

interface LandedCosts {
  found: boolean;
  bill_no?: string | null;
  bill_status?: string | null;
  basis: string;
  basis_label: string;
  client_basis: string | null;
  bill_basis: string | null;
  basis_is_recorded: boolean;
  bases: { value: string; label: string }[];
  charges: Charge[];
  lines: SplitLine[];
  total_paise: number;
  unapportioned_paise: number;
  gaps: string[];
  notes: string[];
  weight_and_volume_refused: string;
  freight_outward_is_not_cost: string;
}

export function LandedCostPanel({
  clientId, billId, onClose, onChanged,
}: {
  clientId: string;
  billId: string;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const [data, setData] = useState<LandedCosts | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const token = await getAuthToken();
      const res = await apiGet(
        `/api/purchase-bills/${billId}/landed-costs?client_id=${encodeURIComponent(clientId)}`,
        token);
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't read the charges.");
      setData(res.data as LandedCosts);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't read the charges.");
    } finally {
      setBusy(false);
    }
  }, [billId, clientId]);

  useEffect(() => { load(); }, [load]);

  async function add() {
    // One parser for a typed rupee amount (lib/money/rupeeInput) — null for
    // anything that is not an amount, so "1,25,000" is not one rupee.
    const paise = paiseFromRupeeInput(amount);
    if (!description.trim() || paise === null || paise <= 0) {
      setError("Say what the charge is and what it came to.");
      return;
    }
    setSaving(true); setError("");
    try {
      const token = await getAuthToken();
      const res = await apiCall(`/api/purchase-bills/${billId}/landed-costs`, "POST", {
        client_id: clientId, description: description.trim(), amount_paise: paise,
      }, token);
      if (!res.success) throw new Error(res.error ?? "Couldn't record the charge.");
      setDescription(""); setAmount("");
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record the charge.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(charge: Charge) {
    setSaving(true); setError("");
    try {
      const token = await getAuthToken();
      const res = await apiCall(
        `/api/purchase-bills/${billId}/landed-costs/${charge.id}?client_id=${encodeURIComponent(clientId)}`,
        "DELETE", undefined, token);
      if (!res.success) throw new Error(res.error ?? "Couldn't remove the charge.");
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove the charge.");
    } finally {
      setSaving(false);
    }
  }

  /** `scope` says which row is being written: the client's accounting policy,
   *  or this one consignment. An empty basis clears the BILL override only —
   *  the server refuses to un-record a client policy, and says why. */
  async function setBasis(basis: string, scope: "client" | "bill") {
    setSaving(true); setError("");
    try {
      const token = await getAuthToken();
      const res = await apiCall(`/api/purchase-bills/landed-cost-basis`, "PUT", {
        client_id: clientId,
        basis: basis || null,
        bill_id: scope === "bill" ? billId : null,
      }, token);
      if (!res.success) throw new Error(res.error ?? "Couldn't record the basis.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record the basis.");
    } finally {
      setSaving(false);
    }
  }

  const received = data?.bill_status === "received"
    || data?.bill_status === "partially_paid" || data?.bill_status === "paid";

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
      <div className="w-full max-w-2xl h-full bg-white shadow-xl flex flex-col">
        <div className="px-5 py-4 border-b border-ps-muted flex items-start justify-between">
          <div>
            <p className="text-sm font-semibold text-ps-ink flex items-center gap-2">
              <Truck size={15} className="text-blue-600" />
              Landed costs
            </p>
            <p className="text-2xs text-ps-hint mt-0.5">
              AS-2 par. 6 · {data?.bill_no ? `Bill ${data.bill_no}` : "This bill"}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
            className="p-1 rounded hover:bg-ps-muted text-ps-label">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {error && <Callout tone="problem">{error}</Callout>}

          {busy && !data && <p className="text-xs text-ps-hint">Loading…</p>}

          {data && (
            <>
              {/* THE BASIS. Two rows, because they are two different
                  statements: the client's accounting policy, applied
                  consistently, and an override for this one consignment. */}
              <div className="border border-ps-border rounded-lg p-3 space-y-3">
                <p className="text-xs font-semibold text-ps-body">
                  How the charges are split — {data.basis_label}
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-xs">
                    <span className="block text-ps-hint mb-1">This client&apos;s policy</span>
                    <select value={data.client_basis ?? ""}
                      onChange={(e) => setBasis(e.target.value, "client")}
                      disabled={saving}
                      className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg text-xs bg-white">
                      <option value="">Not recorded</option>
                      {data.bases.map((b) => (
                        <option key={b.value} value={b.value}>{b.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs">
                    <span className="block text-ps-hint mb-1">This bill only</span>
                    <select value={data.bill_basis ?? ""}
                      onChange={(e) => setBasis(e.target.value, "bill")}
                      disabled={saving}
                      className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg text-xs bg-white">
                      <option value="">Follow the client&apos;s policy</option>
                      {data.bases.map((b) => (
                        <option key={b.value} value={b.value}>{b.label}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <p className="text-2xs text-ps-hint">{data.weight_and_volume_refused}</p>
              </div>

              {/* WHAT COULD NOT BE DECIDED — actionable, so it is separated
                  from the notes below the same way the RCM panel separates
                  gaps from settled reasons. */}
              <GapList gaps={data.gaps} tone="attention" title="Not decided yet" />

              {/* The charges. */}
              <div>
                <p className="text-xs font-semibold text-ps-body mb-2">Charges on this consignment</p>
                {data.charges.length === 0 ? (
                  <p className="text-xs text-ps-hint">
                    Nothing recorded. {data.freight_outward_is_not_cost}
                  </p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-ps-muted text-ps-hint">
                        <th className="py-1.5 text-left font-semibold">Charge</th>
                        <th className="py-1.5 text-right font-semibold">Amount</th>
                        <th className="py-1.5 text-right font-semibold w-16"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ps-bg">
                      {data.charges.map((c) => (
                        <tr key={c.id}>
                          <td className="py-1.5 text-ps-ink">
                            {c.description}
                            {c.source === "bill_of_entry" && (
                              <span className="ml-1.5 text-3xs text-ps-label">
                                from the bill of entry
                              </span>
                            )}
                            {c.why_not_in_cost && (
                              <p className="text-2xs text-state-attention mt-0.5">{c.why_not_in_cost}</p>
                            )}
                          </td>
                          <td className="py-1.5 text-right tabular-nums">{fmt(c.amount_paise)}</td>
                          <td className="py-1.5 text-right">
                            {c.is_applied ? (
                              <span title="Already in the cost of the stock"
                                className="inline-flex text-ps-hint"><Lock size={12} /></span>
                            ) : (
                              <button onClick={() => remove(c)} disabled={saving}
                                aria-label={`Remove ${c.description}`}
                                className="p-1 rounded hover:bg-state-problem-surface text-red-600 disabled:opacity-40">
                                <Trash2 size={12} />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Recording one is allowed AFTER the receipt too — the charge is
                  a fact, and the row's own sentence says it is not in the cost. */}
              <div className="border border-ps-border rounded-lg p-3 space-y-2">
                <p className="text-xs font-semibold text-ps-body">Add a charge</p>
                <div className="grid grid-cols-[1fr_140px_auto] gap-2 items-end">
                  <label className="text-xs">
                    <span className="block text-ps-hint mb-1">What it is</span>
                    <input value={description} onChange={(e) => setDescription(e.target.value)}
                      placeholder="Freight inward"
                      className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg text-xs" />
                  </label>
                  <label className="text-xs">
                    <span className="block text-ps-hint mb-1">Amount (₹)</span>
                    <input value={amount} onChange={(e) => setAmount(e.target.value)}
                      inputMode="decimal"
                      className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg text-xs text-right tabular-nums" />
                  </label>
                  <button onClick={add} disabled={saving}
                    className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs disabled:opacity-40">
                    Add
                  </button>
                </div>
                {received && (
                  <p className="text-2xs text-ps-hint">
                    This bill is already received. A charge added now is recorded but
                    does not enter the cost of the stock — the receipt journal is posted.
                  </p>
                )}
              </div>

              {/* THE PREVIEW — what each line will carry. */}
              {data.lines.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-ps-body mb-2">
                    {received ? "What each line carries" : "What each line will carry"}
                  </p>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-ps-muted text-ps-hint">
                        <th className="py-1.5 text-left font-semibold">Item</th>
                        <th className="py-1.5 text-right font-semibold">Qty</th>
                        <th className="py-1.5 text-right font-semibold">Own cost</th>
                        <th className="py-1.5 text-right font-semibold">+ Landed</th>
                        <th className="py-1.5 text-right font-semibold">Cost of stock</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ps-bg">
                      {data.lines.map((l) => (
                        <tr key={l.line_id}>
                          <td className="py-1.5 text-ps-ink">{l.item_name || "—"}</td>
                          <td className="py-1.5 text-right tabular-nums text-ps-label">{l.quantity}</td>
                          <td className="py-1.5 text-right tabular-nums">{fmt(l.own_cost_paise)}</td>
                          <td className="py-1.5 text-right tabular-nums text-blue-700">
                            {fmt(l.landed_cost_paise)}
                          </td>
                          <td className="py-1.5 text-right tabular-nums font-medium">
                            {fmt(l.total_cost_paise)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {data.unapportioned_paise > 0 && (
                    <p className="text-2xs text-state-attention mt-1.5">
                      {fmt(data.unapportioned_paise)} could not be apportioned.
                    </p>
                  )}
                </div>
              )}

              {/* SETTLED NOTES — why the answer is what it is. */}
              {data.notes.length > 0 && (
                <div className="bg-ps-bg border border-ps-border rounded-lg px-3 py-2 text-xs text-ps-body space-y-1">
                  {data.notes.map((n, i) => <p key={i}>{n}</p>)}
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-ps-muted flex justify-end">
          <button onClick={onClose}
            className="px-3 py-1.5 rounded-lg border border-ps-border text-xs text-ps-label hover:bg-ps-bg">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
