"use client";

/**
 * Filing season — every client's income-tax return for a year, by stage (POST-A-068).
 *
 * A stage is a reading of the records (no return and no computation, a saved computation, then the return's own status up to filed),
 * never a claim: documents received and e-verification are not recorded anywhere, so they are not stages and the page says so.
 * "Run saved computations again" re-runs the inputs a computation was saved with, at today's rates and records; it saves a DRAFT
 * version where the figures differ, moves no return and files nothing, and answers each client it could not run in words.
 * The button is offered to someone who holds `income_tax` compute, the route's own pair. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ItrSeasonComputePayload, ItrSeasonPayload } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { PageHeader } from "@/components/ui/page-header";
import { YearPicker } from "@/components/ui/year-picker";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { SectionPlaceholder } from "@/components/ui/page-frame";
import { EmptyState } from "@/components/ui/states";
import { Card, CardContent } from "@/components/ui/card";
import { failureSentence } from "@/lib/api/failureSentence";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { formatPaise } from "@/lib/services/formatting";
import { objectOrNull } from "@/lib/api/shape";

const PAGE = 100;

export default function FilingSeasonPage() {
  const { can } = usePermissions();
  const canCompute = can("income_tax", "compute");
  const [fy, setFy] = useState(financialYearChoicesAround(null)[0]);
  const [stage, setStage] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<ItrSeasonPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<ItrSeasonComputePayload | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.itrSeason.list({ financial_year: fy, stage: stage ?? undefined, limit: PAGE, offset });
      if (!res?.success) throw new Error(res?.error ?? "The season could not be read.");
      setData(objectOrNull<ItrSeasonPayload>(res.data));
      setError(null);
    } catch (e) {
      setError(failureSentence(e, "The filing season could not be read.", "read"));
    }
  }, [fy, stage, offset]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setSelected(new Set()); setRun(null); }, [fy, stage, offset]);

  const max = data?.max_bulk_clients ?? 100;

  async function runAgain() {
    if (selected.size === 0) return;
    setRunning(true); setRunError(null);
    try {
      const res = await api.itrSeason.compute({ financial_year: fy, chosen_clients: Array.from(selected) });
      if (!res?.success) throw new Error(res?.error ?? "The run was refused.");
      setRun(objectOrNull<ItrSeasonComputePayload>(res.data));
      await load();
    } catch (e) {
      setRunError(failureSentence(e, "The computations could not be run.", "write"));
    } finally {
      setRunning(false);
    }
  }

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else if (n.size < max) n.add(id);
      return n;
    });
  }

  return (
    <div className="space-y-4">
      <PageHeader
        back={{ href: "/income-tax", label: "Income Tax" }}
        title="Filing season"
        subtitle="Every client's return for the year by stage, read from what is recorded"
      />
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <label className="text-xs text-ps-label">Financial Year</label>
          <YearPicker value={fy} onChange={(v) => { setFy(v); setStage(null); setOffset(0); }} className="mt-1 w-auto" />
        </div>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}
      {!data && !error && <SectionPlaceholder label="Loading the filing season" shape="dashboard" rows={6} cols={6} />}

      {data && (
        <>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Stage">
            <button type="button" onClick={() => { setStage(null); setOffset(0); }}
              className={`text-xs px-3 py-1.5 rounded-full border ${stage === null ? "bg-brand text-white border-brand" : "bg-white border-ps-border"}`}>
              All ({data.total_clients})
            </button>
            {Object.keys(data.counts).map((k) => (
              <button key={k} type="button" onClick={() => { setStage(k); setOffset(0); }}
                className={`text-xs px-3 py-1.5 rounded-full border ${stage === k ? "bg-brand text-white border-brand" : "bg-white border-ps-border"}`}>
                {data.stage_labels[k] ?? k} ({data.counts[k]})
              </button>
            ))}
          </div>
          <ul className="text-2xs text-ps-hint list-disc pl-5">
            {data.not_tracked.map((t) => <li key={t}>{t}</li>)}
          </ul>

          {canCompute && (
            <div className="flex items-center gap-3 flex-wrap">
              <Button type="button" variant="plain" size="none" disabled={running || selected.size === 0} onClick={runAgain}
                className="text-xs px-3 py-1.5 bg-brand text-white rounded-md disabled:opacity-50">
                {running ? "Running…" : `Run saved computations again (${selected.size})`}
              </Button>
              <span className="text-2xs text-ps-hint">
                Re-runs the inputs saved with each client&apos;s latest computation, at today&apos;s rates and records, up to {max} clients at a time.
                A different result is saved as a new DRAFT version; no return changes status and nothing is filed or sent.
              </span>
            </div>
          )}
          {runError && <Callout tone="problem">{runError}</Callout>}
          {run && (
            <Card>
              <CardContent className="p-4 space-y-2">
                <h2 className="text-sm font-semibold text-ps-ink">What the run did</h2>
                <ul className="divide-y divide-ps-border text-xs">
                  {run.results.map((r) => (
                    <li key={r.client_id} className="py-1.5">
                      <span className="font-medium text-ps-ink">{r.client_name ?? r.client_id}</span>{" "}
                      <span className="text-ps-label">{r.message}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-2xs text-ps-hint">This run did not: {run.did_not.map((d) => d.replace(/\.$/, "").toLowerCase()).join("; ")}.</p>
              </CardContent>
            </Card>
          )}

          {data.rows.length === 0 ? (
            <EmptyState title={stage ? "No client is at this stage" : "No clients to show"}
              description="Clients assigned to you appear here with the stage of their return for the year." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ps-border text-xs text-ps-hint">
                    {canCompute && <th className="px-3 py-2 w-8"><span className="sr-only">Select</span></th>}
                    <th className="px-3 py-2 text-left font-semibold">Client</th>
                    <th className="px-3 py-2 text-left font-semibold">Stage</th>
                    <th className="px-3 py-2 text-left font-semibold">Form</th>
                    <th className="px-3 py-2 text-left font-semibold">Saved computation</th>
                    <th className="px-3 py-2 text-right font-semibold">Net payable / refund</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {data.rows.map((r) => (
                    <tr key={r.client_id} className="hover:bg-ps-bg">
                      {canCompute && (
                        <td className="px-3 py-2">
                          <input type="checkbox" aria-label={`Select ${r.client_name ?? "client"}`} checked={selected.has(r.client_id)}
                            onChange={() => toggle(r.client_id)} className="h-3.5 w-3.5" />
                        </td>
                      )}
                      <td className="px-3 py-2 font-medium text-ps-ink">{r.client_name ?? "—"}</td>
                      <td className="px-3 py-2 text-xs">{r.stage_label}</td>
                      <td className="px-3 py-2 text-xs">{r.itr_form ?? "—"}</td>
                      <td className="px-3 py-2 text-xs">
                        {r.computation_version == null ? "None saved" : `Version ${r.computation_version}, ${r.computation_status ?? "draft"}`}
                      </td>
                      <td className="px-3 py-2 text-xs text-right">
                        {r.net_payable_paise == null ? "—" : `${formatPaise(Math.abs(Number(r.net_payable_paise)))}${r.is_refund ? " refund" : ""}`}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        <Link href={`/clients/${r.client_id}/tax/computation`} className="text-blue-600 hover:underline">Open</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.matching > PAGE && (
            <div className="flex items-center gap-3 text-xs text-ps-label">
              <span>Showing {data.offset + 1}–{Math.min(data.offset + data.rows.length, data.matching)} of {data.matching}</span>
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="underline disabled:opacity-40">Previous</button>
              <button type="button" disabled={offset + PAGE >= data.matching} onClick={() => setOffset(offset + PAGE)} className="underline disabled:opacity-40">Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
