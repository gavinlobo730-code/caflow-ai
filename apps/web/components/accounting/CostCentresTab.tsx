"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Layers, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type {
  CostCentre,
  CostCentreAllocationPayload,
  CostCentreResult,
} from "@/lib/api";
import { objectWithLists, arrayOrEmpty } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";
import { EmptyState, ErrorState } from "@/components/ui/states";

/**
 * Cost centres — the master, and income and expenditure by department (ACC-13).
 *
 * ⚠️ A DIMENSION, NOT A SECOND SET OF BOOKS. Tagging a line changes no figure:
 * the trial balance, the financial statements and every return are unaffected,
 * and a test asserts no statutory engine reads the column. That is why this is
 * a tab of the accounting screen and not a second ledger.
 *
 * ── THE UNALLOCATED ROW IS PART OF THE ANSWER ────────────────────────────
 *
 * It is rendered like any other, at the bottom, with its own sentence — never
 * hidden and never merged. Most lines carry no cost centre BY DESIGN: a bank
 * leg, a GST leg and a TDS leg belong to no department, so the row is expected
 * to be large and its size is information. Dropping it would stop the
 * departments summing to the accounts they came from, which is the one
 * property that makes the table checkable.
 *
 * ── AND THE CENTRES DO NOT SUM TO THE P&L ────────────────────────────────
 *
 * Which is why the column is headed "Result" and not "Profit". A centre's
 * result is before everything that is not divided by department, and adding
 * them up gives the allocated part only. The screen does not print a grand
 * total for exactly that reason — a total no reader could reconcile with the
 * P&L next door is worse than no total.
 *
 * ── RETIRE, NEVER DELETE ─────────────────────────────────────────────────
 *
 * Posted lines point at a centre and migration 251 makes a posted line
 * immutable, so closing a department does not un-spend last year's money. The
 * FK is ON DELETE RESTRICT and this screen offers Retire rather than Delete.
 *
 * Every figure is served. This file computes nothing.
 */
export function CostCentresTab({
  clientId,
  financialYear,
}: {
  clientId: string;
  financialYear: string;
}) {
  const [centres, setCentres] = useState<CostCentre[]>([]);
  const [report, setReport] = useState<CostCentreAllocationPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, alloc] = await Promise.all([
        api.accounting.costCentres(clientId, true),
        api.accounting.costCentreAllocation(clientId, financialYear),
      ]);
      if (!list?.success) throw new Error(list?.error || "Could not load cost centres");
      setCentres(arrayOrEmpty<CostCentre>((list.data as { cost_centres?: unknown })?.cost_centres));
      // The refusal path answers HTTP 200 with success:false, and a frontend
      // ahead of its backend answers a payload without these keys — either
      // would otherwise reach `.map` on undefined. See CLAUDE.md.
      setReport(alloc?.success
        ? objectWithLists<CostCentreAllocationPayload>(
            alloc.data, "centres", "centres_with_no_activity", "notes")
        : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load cost centres");
    } finally {
      setLoading(false);
    }
  }, [clientId, financialYear]);

  useEffect(() => { void load(); }, [load]);

  async function add() {
    setSaveError(null);
    const res = await api.accounting.createCostCentre({
      client_id: clientId, code, name,
    });
    if (!res?.success) {
      setSaveError(res?.error || "Could not create the cost centre");
      return;
    }
    setCode("");
    setName("");
    setAdding(false);
    await load();
  }

  async function retire(centre: CostCentre) {
    const res = await api.accounting.updateCostCentre(centre.id, clientId, {
      is_active: !centre.is_active,
    });
    if (res?.success) await load();
  }

  const rows: CostCentreResult[] = report
    ? [...report.centres, ...(report.unallocated ? [report.unallocated] : [])]
    : [];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Layers size={16} className="text-ps-label" />
          <h2 className="text-sm font-semibold text-ps-ink">Cost centres</h2>
          <span className="text-3xs text-ps-hint">FY {financialYear}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ps-border bg-white px-3 py-1.5 text-sm text-ps-body hover:bg-ps-hover transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
          <button
            onClick={() => setAdding((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 transition-opacity"
          >
            <Plus size={14} />
            New cost centre
          </button>
        </div>
      </header>

      {adding && (
        <div className="bg-white rounded-xl border border-ps-border p-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-3xs uppercase tracking-wide text-ps-hint">Code</span>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                maxLength={24}
                placeholder="FACTORY"
                className="mt-1 w-full rounded-lg border border-ps-border px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-3xs uppercase tracking-wide text-ps-hint">Name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Factory"
                className="mt-1 w-full rounded-lg border border-ps-border px-3 py-2 text-sm"
              />
            </label>
          </div>
          <p className="text-3xs text-ps-hint">
            The code is stored upper-cased, so <code>factory</code> and{" "}
            <code>FACTORY</code> are one centre rather than two that split the
            department&apos;s cost in half.
          </p>
          {saveError && <p className="text-xs text-state-problem">{saveError}</p>}
          <button
            onClick={() => void add()}
            disabled={!code.trim() || !name.trim()}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            Save
          </button>
        </div>
      )}

      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {!error && loading && <p className="text-sm text-ps-hint">Loading…</p>}

      {!error && !loading && centres.length === 0 && (
        <EmptyState
          icon={<Layers size={32} />}
          title="No cost centres yet"
          description={
            "A cost centre is a department, a branch or a project. Tag the " +
            "expense and revenue lines of a voucher with one and this tab " +
            "shows what each part of the business earned and spent. It " +
            "changes no figure in the books."
          }
        />
      )}

      {!error && !loading && centres.length > 0 && (
        <>
          <section className="bg-white rounded-xl border border-ps-border overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px]">
                <thead>
                  <tr className="text-3xs uppercase tracking-wide text-ps-hint">
                    <th className="text-left font-medium py-2 px-4">Code</th>
                    <th className="text-left font-medium py-2 pr-4">Name</th>
                    <th className="text-left font-medium py-2 pr-4">Status</th>
                    <th className="text-right font-medium py-2 pr-4"></th>
                  </tr>
                </thead>
                <tbody>
                  {centres.map((c) => (
                    <tr key={c.id} className="border-t border-ps-border">
                      <td className="py-2 px-4 text-sm font-mono text-ps-body">{c.code}</td>
                      <td className="py-2 pr-4 text-sm text-ps-ink">{c.name}</td>
                      <td className="py-2 pr-4 text-3xs text-ps-hint">
                        {c.is_active ? "Active" : "Retired"}
                      </td>
                      <td className="py-2 pr-4 text-right">
                        <button
                          onClick={() => void retire(c)}
                          className="text-3xs text-ps-label hover:text-ps-ink underline"
                        >
                          {c.is_active ? "Retire" : "Reinstate"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="px-4 py-2 text-3xs text-ps-hint border-t border-ps-border">
              Retired, never deleted — posted lines point at a centre and a
              posted line cannot be rewritten. A retired centre stops being
              offered and keeps its history.
            </p>
          </section>

          {rows.length > 0 && (
            <section className="bg-white rounded-xl border border-ps-border overflow-hidden">
              <h3 className="text-sm font-semibold text-ps-ink px-4 pt-4 pb-2">
                Income and expenditure, FY {financialYear}
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px]">
                  <thead>
                    <tr className="text-3xs uppercase tracking-wide text-ps-hint">
                      <th className="text-left font-medium py-2 px-4">Cost centre</th>
                      <th className="text-right font-medium py-2 pr-4">Income</th>
                      <th className="text-right font-medium py-2 pr-4">Expenditure</th>
                      <th className="text-right font-medium py-2 pr-4">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr
                        key={c.cost_centre_id ?? "unallocated"}
                        className="border-t border-ps-border"
                      >
                        <td className="py-2 px-4 text-sm text-ps-ink">{c.name}</td>
                        <td className="py-2 pr-4 text-sm text-ps-body tabular-nums text-right">
                          {formatPaise(c.income_paise)}
                        </td>
                        <td className="py-2 pr-4 text-sm text-ps-body tabular-nums text-right">
                          {formatPaise(c.expense_paise)}
                        </td>
                        <td className="py-2 pr-4 text-sm font-medium text-ps-ink tabular-nums text-right">
                          {formatPaise(c.result_paise)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 border-t border-ps-border space-y-1">
                {(report?.notes ?? []).map((n) => (
                  <p key={n} className="text-3xs text-ps-hint">{n}</p>
                ))}
                {(report?.centres_with_no_activity ?? []).length > 0 && (
                  <p className="text-3xs text-ps-hint">
                    No entries this year for:{" "}
                    {(report?.centres_with_no_activity ?? []).join(", ")}.
                  </p>
                )}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
