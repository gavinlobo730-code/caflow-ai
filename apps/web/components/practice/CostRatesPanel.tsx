"use client";

/**
 * What an hour of each person's time costs the practice (POST-B-321).
 *
 * Profitability prices every hour a member recorded at THIS rate, so a client's cost is the hours spent on it at what
 * those hours cost the practice (a salary and its overheads over the hours a person works), and not at the rate the
 * hour bills at, which is the Time screen's. The rate is one number per person as it stands today: it prices the
 * hours recorded before it was set as well, and the screen says so.
 *
 * AN EMPTY BOX IS "NONE" AND A TYPED 0 IS A RATE, for the reason `BillingRatesPanel` states: `paiseFromRupeeInput`
 * reads a blank as 0, which would say "these hours cost nothing" and take them off the list of hours with no cost
 * rate, where somebody was going to set one. The box goes through `readRateInput`, which keeps the two apart and reads
 * the digits with the one parser. An hour with no rate is left out of the cost and named on the screen above, never
 * counted as free.
 *
 * ONLY SOMEBODY WHO MAY SET A RATE IS SHOWN THIS PANEL. A rate is derived from a person's pay and overheads, so the
 * server's list asks `billing:write`, the permission that sets one, and the page mounts the panel for that permission
 * alone: a member who was granted the fee figures to read sees the figures, and who has hours with no rate, and not
 * every colleague's rate.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { api, type StaffCostRate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { readRateInput } from "@/lib/time/rateInput";
import { arrayOrEmpty } from "@/lib/api/shape";

/** Said when a typed rate is not an amount. The shared message talks about what an hour BILLS at; this is a cost. */
export const COST_RATE_HINT =
  "A cost rate is an amount in rupees per hour, e.g. 600 or 450.50, without commas. " +
  "Leave it empty for none; 0 means these hours cost nothing.";

function show(paise: number | null | undefined): string {
  return paise === null || paise === undefined ? "" : rupeeInputFromPaise(paise);
}

export function CostRatesPanel({ onSaved }: { onSaved?: () => void }) {
  const [staff, setStaff] = useState<StaffCostRate[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  /** What went wrong with the list or a save: the server's sentence, at the top. */
  const [error, setError] = useState<string | null>(null);
  /** A typed box that is not an amount, on ITS row: which person's box, and cleared when that box is changed. */
  const [rowError, setRowError] = useState<Record<string, string>>({});
  /** "Saved …", said to a screen reader as well as drawn. */
  const [saved, setSaved] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  /** The member whose box takes focus once their save has ended: a disabled box cannot take it, and the box is disabled
   *  for as long as its own save is out. */
  const refocus = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.billing.listCostRates();
      if (!r.success) throw new Error(r.error ?? "The cost rates could not be loaded.");
      setStaff(arrayOrEmpty<StaffCostRate>(r.data));
      setError(null);
      setLoadFailed(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The cost rates could not be loaded.");
      setLoadFailed(true);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (savingKey === null && refocus.current) {
      inputs.current[refocus.current]?.focus();
      refocus.current = null;
    }
  }, [savingKey]);

  // The box shows what the person is typing, or, until they type, what is stored.
  const valueOf = (userId: string, stored: number | null | undefined) =>
    userId in drafts ? drafts[userId] : show(stored);

  const edit = (userId: string, text: string) => {
    setDrafts((d) => ({ ...d, [userId]: text }));
    setRowError((e) => { const next = { ...e }; delete next[userId]; return next; });
    setSaved(null);
  };

  const save = async (m: StaffCostRate) => {
    const userId = m.id;
    const typed = readRateInput(drafts[userId] ?? "");
    if (typed.kind === "invalid") { setRowError((e) => ({ ...e, [userId]: COST_RATE_HINT })); return; }
    setSavingKey(userId);
    try {
      const r = await api.billing.setCostRate(userId, typed.kind === "rate" ? typed.paise : null);
      if (!r.success) throw new Error(r.error ?? "The cost rate was not saved.");
      setDrafts((d) => { const next = { ...d }; delete next[userId]; return next; });
      setError(null);
      setSaved(`Saved the cost per hour for ${m.full_name ?? "this person"}.`);
      await load();
      // The Save button the person just used is disabled now that there is nothing to save: put them back in the box,
      // as soon as the box is enabled again (the effect above).
      refocus.current = userId;
      onSaved?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The cost rate was not saved.");
    } finally {
      setSavingKey(null);
    }
  };

  // Members with no rate first, since those are the hours the figures above leave out; then by name.
  const ordered = [...staff].sort((a, b) =>
    Number(a.cost_rate_paise !== null) - Number(b.cost_rate_paise !== null)
    || (a.full_name ?? "").localeCompare(b.full_name ?? ""));

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="px-4 py-3 border-b border-ps-border bg-ps-bg space-y-1">
        <h2 className="text-sm font-semibold text-ps-ink">What an hour costs the practice</h2>
        <p className="text-3xs text-ps-hint leading-relaxed">
          Each person&apos;s cost per hour, in rupees: their pay and overheads divided by the hours they work. The cost
          above is the hours they recorded at this rate, including hours recorded before you set it. A person with no
          rate is left out of the cost, and is listed first here, never counted as nothing.
        </p>
      </div>

      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-state-problem bg-state-problem-surface border-b border-state-problem-border px-4 py-3">
          <AlertCircle size={14} className="shrink-0" />
          <span className="flex-1 min-w-[10rem]">{error}</span>
          {loadFailed && (
            <Button size="sm" variant="outline" onClick={() => { setLoaded(false); void load(); }}>Try again</Button>
          )}
        </div>
      )}

      {saved && <p role="status" className="px-4 py-2 text-3xs text-ps-hint border-b border-ps-border">{saved}</p>}

      {!loaded && (
        <div className="flex items-center justify-center py-8 text-ps-hint">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading…
        </div>
      )}

      {loaded && ordered.length === 0 && !error && (
        <p className="px-4 py-4 text-xs text-ps-hint">No team members.</p>
      )}

      {loaded && ordered.length > 0 && (
        <div className="divide-y divide-ps-border">
          {ordered.map((m) => {
            const name = m.full_name ?? "this person";
            const problem = rowError[m.id];
            const changed = m.id in drafts && drafts[m.id] !== show(m.cost_rate_paise);
            return (
              <div key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="flex-1 min-w-[10rem]">
                  <p className="text-xs font-medium text-ps-ink">{m.full_name ?? "Unnamed"}</p>
                  <p className="text-3xs text-ps-hint">
                    {m.role ?? ""}{m.is_active === false ? " · inactive" : ""}
                    {m.cost_rate_paise === null ? " · no cost rate" : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    ref={(el) => { inputs.current[m.id] = el; }}
                    aria-label={`Cost per hour for ${name}`}
                    aria-invalid={problem ? true : undefined}
                    aria-describedby={problem ? `cost-rate-problem-${m.id}` : undefined}
                    inputMode="decimal"
                    disabled={savingKey === m.id}
                    value={valueOf(m.id, m.cost_rate_paise)}
                    onChange={(ev) => edit(m.id, ev.target.value)}
                    placeholder="none"
                    className="w-28 border border-ps-border rounded-lg px-3 py-1.5 text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-brand/30 disabled:bg-ps-bg"
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={`Save cost per hour for ${name}`}
                    disabled={savingKey === m.id || !changed}
                    onClick={() => save(m)}
                  >
                    {savingKey === m.id ? <><Loader2 className="animate-spin mr-1" size={13} /> Saving…</> : "Save"}
                  </Button>
                </div>
                {problem && (
                  <p id={`cost-rate-problem-${m.id}`} role="alert" className="basis-full text-3xs text-state-problem">
                    {problem}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
