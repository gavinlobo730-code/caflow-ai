"use client";

/**
 * FilingEffortPanel: how long one filing of each obligation type takes in THIS practice (POST-A-212, migration 671).
 *
 * The capacity forecast above counts an obligation that is worked as a task by that task's own estimate. An obligation that is not
 * worked as a task has none, so it was dated and weightless. The forecast reads the filing calendar (`compliance_calendar`), not the
 * obligation store Deadlines lists (`compliance_records`), and both sentences on this panel say so, so a firm whose obligations are
 * all in the store is not told its calendar is empty of work. The practice states a figure per kind of filing here; nothing is
 * defaulted or suggested, a kind with no figure stays an unknown and the forecast says how many items carry none, and clearing a
 * figure makes the kind unknown again, never zero. The figure is whole minutes for ONE filing and changes the forecast only: no due
 * date, filing or client figure moves. The box is offered to someone who holds `workload` write, the route's own pair.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { objectOrNull, arrayOrEmpty } from "@/lib/api/shape";
import { failureSentence } from "@/lib/api/failureSentence";
import { LoadingRegion } from "@/components/ui/skeleton";

interface Estimate { compliance_type: string; estimated_minutes: number }

export function FilingEffortPanel({ onChanged }: { onChanged?: () => void }) {
  const { can } = usePermissions();
  const canWrite = can("workload", "write");
  const [estimates, setEstimates] = useState<Estimate[] | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [maxMinutes, setMaxMinutes] = useState(525600);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.workload.obligationEstimates();
      if (!res?.success) throw new Error(res?.error ?? "The figures could not be read.");
      const d = objectOrNull<Record<string, unknown>>(res.data) ?? {};
      setEstimates(arrayOrEmpty<Estimate>(d.estimates));
      setMissing(arrayOrEmpty<string>(d.types_without_an_estimate));
      if (typeof d.max_minutes === "number") setMaxMinutes(d.max_minutes);
      setLoadError(null);
    } catch (e) {
      setLoadError(failureSentence(e, "The filing times could not be read.", "read"));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save(kind: string) {
    const text = (draft[kind] ?? "").trim();
    if (!/^[0-9]+$/.test(text) || Number(text) < 1 || Number(text) > maxMinutes) {
      setError(`Enter whole minutes for one ${kind} filing, from 1 to ${maxMinutes.toLocaleString("en-IN")}.`);
      return;
    }
    setBusy(kind); setError(null);
    try {
      const res = await api.workload.setObligationEstimate({ compliance_type: kind, estimated_minutes: Number(text) });
      if (!res?.success) throw new Error(res?.error ?? "Not saved.");
      setDraft((d) => { const n = { ...d }; delete n[kind]; return n; });
      await load();
      onChanged?.();
    } catch (e) {
      setError(failureSentence(e, "Could not save that figure.", "write"));
    } finally { setBusy(null); }
  }

  async function clear(kind: string) {
    setBusy(kind); setError(null);
    try {
      const res = await api.workload.clearObligationEstimate(kind);
      if (!res?.success) throw new Error(res?.error ?? "Not cleared.");
      await load();
      onChanged?.();
    } catch (e) {
      setError(failureSentence(e, "Could not clear that figure.", "write"));
    } finally { setBusy(null); }
  }

  const rows: { kind: string; minutes: number | null }[] = [
    ...(estimates ?? []).map((e) => ({ kind: e.compliance_type, minutes: e.estimated_minutes })),
    ...missing.map((kind) => ({ kind, minutes: null })),
  ];

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">How long one filing takes</h2>
          <p className="text-xs text-ps-label mt-0.5">
            Your own figure, in whole minutes for one filing of each kind. It feeds the forecast above for the obligations in the
            filing calendar that are not worked as tasks. A kind with no figure counts as an item with no estimate; nothing is assumed for it.
            The obligations listed on Deadlines are kept in a second list the forecast does not read yet, so a figure here does not reach
            them.
          </p>
        </div>
        {loadError && <p role="alert" className="text-xs text-state-problem">{loadError}</p>}
        {estimates === null && !loadError && <LoadingRegion label="Reading the filing-effort figures" className="text-xs text-ps-hint">Reading the figures…</LoadingRegion>}
        {estimates !== null && rows.length === 0 && (
          <p className="text-xs text-ps-label">
            The filing calendar the forecast reads holds no obligations yet, so there is no kind of filing to give a figure for here.
          </p>
        )}
        {rows.length > 0 && (
          <ul className="divide-y divide-ps-border">
            {rows.map((r) => (
              <li key={r.kind} className="flex items-center gap-3 py-2 text-xs">
                <span className="w-40 font-medium text-ps-ink">{r.kind}</span>
                <span className="w-32 text-ps-label">{r.minutes === null ? "No figure recorded" : `${r.minutes} min`}</span>
                {canWrite && (
                  <span className="flex items-center gap-2">
                    <input
                      inputMode="numeric"
                      aria-label={`Minutes for one ${r.kind} filing`}
                      value={draft[r.kind] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [r.kind]: e.target.value }))}
                      placeholder="Minutes"
                      className="w-24 px-2 py-1 border border-ps-border rounded-md bg-white"
                    />
                    <Button type="button" variant="plain" size="none" disabled={busy === r.kind || !(draft[r.kind] ?? "").trim()}
                      onClick={() => save(r.kind)} className="px-2 py-1 border border-ps-border rounded-md hover:bg-ps-muted bg-white">
                      {r.minutes === null ? "Save" : "Change"}
                    </Button>
                    {r.minutes !== null && (
                      <Button type="button" variant="plain" size="none" disabled={busy === r.kind}
                        onClick={() => clear(r.kind)} className="px-2 py-1 text-ps-label hover:underline">
                        Clear
                      </Button>
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {error && <p role="alert" className="text-xs text-state-problem">{error}</p>}
      </CardContent>
    </Card>
  );
}
