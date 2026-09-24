"use client";

/**
 * Which cost formula this client's books are kept on — AS-2 paragraph 14
 * (INV-02).
 *
 * DECIDES NOTHING. The two permitted formulas, what an unrecorded client is
 * on, why standard cost is not offered, whether a change may take effect from
 * a given date and every sentence explaining a refusal come from
 * `apps/api/domain/inventory/costing.py` through
 * `GET/PUT /api/inventory/costing-policy`. This renders them.
 *
 * The one thing worth reading before changing it: a change of cost formula is
 * a change in ACCOUNTING POLICY (AS-5 paragraph 29) and is prospective —
 * nothing already priced is re-costed. So the date is required, the server
 * refuses one stock has already moved on or after, and the panel shows which
 * formula actually priced which period off the ledger's own stamps rather
 * than from anything stored.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, Scale } from "lucide-react";
import { api } from "@/lib/api";
import type { InventoryCostingPolicy } from "@/lib/api";
import { Callout } from "@/components/ui/callout";

export function CostFormulaPanel({ clientId }: { clientId: string }) {
  const [policy, setPolicy] = useState<InventoryCostingPolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [saving, setSaving] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.inventory.costingPolicy({ client_id: clientId });
      setPolicy(res.success ? (res.data ?? null) : null);
    } catch {
      setPolicy(null);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { void load(); }, [load]);

  function begin() {
    if (!policy) return;
    setMethod(policy.method);
    // The server's own suggestion — the day after the last recorded movement.
    // Only ever a pre-fill: the refusal is the server's, computed against the
    // ledger as it stands when the change is submitted.
    setEffectiveFrom(policy.earliest_date_a_change_can_take_effect ?? "");
    setRefusal(null);
    setOpen(true);
  }

  async function save() {
    setSaving(true);
    setRefusal(null);
    try {
      const res = await api.inventory.setCostingPolicy({
        client_id: clientId, method, effective_from: effectiveFrom || null,
      });
      if (!res.success) {
        setRefusal(res.error || "The change could not be recorded.");
        return;
      }
      setOpen(false);
      await load();
    } catch (e) {
      setRefusal(e instanceof Error ? e.message : "The change could not be recorded.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-ps-hint">
        <Loader2 size={12} className="animate-spin" /> Cost formula…
      </div>
    );
  }
  if (!policy) return null;

  return (
    <div className="border border-ps-border rounded-lg bg-white">
      <div className="px-4 py-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Scale size={13} className="text-ps-label" />
            <p className="text-xs font-semibold text-ps-ink">Cost formula</p>
            {!policy.is_recorded && (
              <span className="px-1.5 py-0.5 rounded text-3xs bg-state-attention-surface text-state-attention border border-state-attention-border">
                Not recorded
              </span>
            )}
          </div>
          <p className="text-xs text-ps-label mt-1">{policy.label}</p>
          {policy.unrecorded_means && (
            <p className="text-2xs text-ps-label mt-1.5 leading-relaxed">
              {policy.unrecorded_means}
            </p>
          )}
          {policy.methods_used.length > 1 && (
            <div className="mt-2 text-2xs text-ps-label leading-relaxed">
              <p className="font-medium text-ps-body">What actually priced the ledger</p>
              <ul className="mt-0.5 space-y-0.5">
                {policy.methods_used.map((s) => (
                  <li key={s.method}>
                    {s.label} — {s.first_movement} to {s.last_movement}
                  </li>
                ))}
              </ul>
              <p className="mt-1">{policy.as5_disclosure}</p>
            </div>
          )}
        </div>
        <button onClick={begin}
                className="flex-shrink-0 px-2.5 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">
          {policy.is_recorded ? "Change" : "Record"}
        </button>
      </div>

      {open && (
        <div className="border-t border-ps-border px-4 py-3 space-y-3">
          <div>
            <label htmlFor="cost-formula" className="block text-3xs font-medium text-ps-hint mb-1">
              Cost formula (AS-2 paragraph 14)
            </label>
            <select id="cost-formula" value={method} onChange={(e) => setMethod(e.target.value)}
                    className="w-full px-2.5 py-[7px] text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand">
              {policy.methods.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cost-formula-from" className="block text-3xs font-medium text-ps-hint mb-1">
              Takes effect from
            </label>
            <input id="cost-formula-from" type="date" value={effectiveFrom}
                   onChange={(e) => setEffectiveFrom(e.target.value)}
                   className="w-full px-2.5 py-[7px] text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
            <p className="text-2xs text-ps-label mt-1 leading-relaxed">
              A change is prospective. Nothing already priced is re-costed, so
              the date has to be after the last recorded movement — the start
              of the next period is the usual answer.
            </p>
          </div>
          <p className="text-2xs text-ps-label leading-relaxed">{policy.standard_cost_refused}</p>
          {refusal && <Callout tone="problem">{refusal}</Callout>}
          <div className="flex justify-end gap-2">
            <button onClick={() => setOpen(false)}
                    className="px-2.5 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">
              Cancel
            </button>
            <button onClick={save} disabled={saving || !method}
                    className="px-2.5 py-1.5 text-xs bg-brand-dark text-white rounded-lg hover:bg-brand disabled:opacity-50">
              {saving ? "Saving…" : "Record"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
