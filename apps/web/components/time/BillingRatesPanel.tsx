"use client";

/**
 * What an hour bills at (practice_management-11) — each PERSON's default rate and
 * each ENGAGEMENT's override.
 *
 * The order they are read in is the server's (`domain/billing/time_rate`): the
 * entry's own rate, then the engagement's override, then the person's default,
 * then NOTHING — and the answer is stored on the entry when it is recorded, so
 * changing a rate here does not re-price work already logged. This panel says so
 * and decides nothing else.
 *
 * AN EMPTY BOX IS "NONE" AND A TYPED 0 IS A RATE. `paiseFromRupeeInput` reads a
 * blank as 0 — right for an amount column, wrong here, where a stored 0 would
 * say "these hours bill at nothing" and take them off the "no rate" list — so the
 * box goes through `readRateInput`. This is NOT the cost rate, which is what an
 * hour costs the firm and is never used in a computation.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { api, type FeeEngagement, type StaffBillableRate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { readRateInput } from "@/lib/time/rateInput";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import type { Client } from "@/lib/types";

function show(paise: number | null | undefined): string {
  return paise === null || paise === undefined ? "" : rupeeInputFromPaise(paise);
}

export function BillingRatesPanel({ clients, canEdit }: { clients: Client[]; canEdit: boolean }) {
  const [staff, setStaff] = useState<StaffBillableRate[]>([]);
  const [engagements, setEngagements] = useState<FeeEngagement[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const clientName = new Map(clients.map((c) => [c.id, c.client_name]));

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([api.billing.listBillableRates(), api.engagements.list()]);
      if (!s.success) throw new Error(s.error ?? "Staff billing rates could not be loaded.");
      setStaff(arrayOrEmpty<StaffBillableRate>(objectWithLists<{ staff: StaffBillableRate[] }>(s.data, "staff")?.staff));
      setEngagements(e.success
        ? arrayOrEmpty<FeeEngagement>(objectWithLists<{ engagements: FeeEngagement[] }>(e.data, "engagements")?.engagements)
        : []);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Billing rates could not be loaded.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // The box shows what the person is typing, or — until they type — what is stored.
  const valueOf = (key: string, stored: number | null | undefined) =>
    key in drafts ? drafts[key] : show(stored);

  const save = async (key: string, run: (paise: number | null) => Promise<{ success: boolean; error?: string | null }>) => {
    const typed = readRateInput(drafts[key] ?? "");
    if (typed.kind === "invalid") { setError(typed.message); return; }
    setSavingKey(key);
    try {
      const r = await run(typed.kind === "rate" ? typed.paise : null);
      if (!r.success) throw new Error(r.error ?? "The rate was not saved.");
      setDrafts((d) => { const next = { ...d }; delete next[key]; return next; });
      setError(null);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The rate was not saved.");
    } finally {
      setSavingKey(null);
    }
  };

  if (!loaded) {
    return (
      <div className="flex items-center justify-center py-10 text-ps-hint">
        <Loader2 className="animate-spin mr-2" size={16} /> Loading…
      </div>
    );
  }

  const rateBox = (key: string, stored: number | null | undefined, label: string,
                   run: (paise: number | null) => Promise<{ success: boolean; error?: string | null }>) => (
    <div className="flex items-center gap-2">
      <input
        aria-label={label}
        inputMode="decimal"
        disabled={!canEdit}
        value={valueOf(key, stored)}
        onChange={(ev) => setDrafts((d) => ({ ...d, [key]: ev.target.value }))}
        placeholder="none"
        className="w-28 border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 disabled:bg-ps-bg"
      />
      {canEdit && (
        <Button
          size="sm"
          variant="outline"
          disabled={savingKey === key || !(key in drafts)}
          onClick={() => save(key, run)}
        >
          {savingKey === key ? <Loader2 className="animate-spin" size={13} /> : "Save"}
        </Button>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <p className="text-xs text-ps-label">
        An hour is priced at the rate typed on the entry, else the engagement&apos;s override, else the
        person&apos;s rate, else it has no rate and is listed under Unbilled work. The rate is stored on the
        entry when it is recorded, so changing one here does not re-price time already logged. Leave a box
        empty for none; 0 is a rate (these hours bill at nothing).
      </p>

      {error && (
        <div role="alert" className="flex items-center gap-2 text-sm text-state-problem bg-state-problem-surface border border-state-problem-border rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold">People — rupees per hour</CardTitle>
        </CardHeader>
        <CardContent className="p-0 divide-y">
          {staff.length === 0 && <p className="px-5 py-4 text-sm text-ps-hint">No team members.</p>}
          {staff.map((m) => (
            <div key={m.user_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="flex-1 min-w-[10rem]">
                <p className="text-sm text-gray-800">{m.full_name ?? "Unnamed"}</p>
                <p className="text-2xs text-ps-hint">
                  {m.role ?? ""}{m.is_active === false ? " · inactive" : ""}
                  {m.default_billable_rate_paise === null ? " · no rate" : ""}
                </p>
              </div>
              {rateBox(`user:${m.user_id}`, m.default_billable_rate_paise, `Rate for ${m.full_name ?? "this person"}`,
                (paise) => api.billing.setBillableRate(m.user_id, paise))}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold">Engagements — override, rupees per hour</CardTitle>
        </CardHeader>
        <CardContent className="p-0 divide-y">
          {engagements.length === 0 && <p className="px-5 py-4 text-sm text-ps-hint">No engagements.</p>}
          {engagements.map((e) => (
            <div key={e.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="flex-1 min-w-[10rem]">
                <p className="text-sm text-gray-800">{e.service_type}</p>
                <p className="text-2xs text-ps-hint">
                  {clientName.get(e.client_id) ?? "Unknown client"} · {e.status}
                  {e.billable_rate_paise === null || e.billable_rate_paise === undefined ? " · uses the person's rate" : ""}
                </p>
              </div>
              {rateBox(`eng:${e.id}`, e.billable_rate_paise, `Override for ${e.service_type}`,
                (paise) => api.engagements.setBillableRate(e.id, paise))}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
