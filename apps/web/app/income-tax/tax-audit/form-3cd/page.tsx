"use client";

/**
 * Form 3CD — the statement of particulars annexed to a §44AB tax audit
 * report.
 *
 * NOTHING IS COMPUTED HERE. Every derived clause comes from
 * GET /api/income-tax/form-3cd, which reuses domain/income_tax/form_3cd.py
 * and the modules it calls into — §32 block depreciation, §43B(h)/MSMED §16,
 * brought-forward losses, TDS compliance, the GST-registration split. This
 * screen renders the register and lets a CA record the clauses this product
 * does not derive (see the module's own docstring for exactly which those
 * are and why).
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle2, Circle, Save } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Callout } from "@/components/ui/callout";
import { YearPicker } from "@/components/ui/year-picker";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { api, type Form3cdClause, type Form3cdRegister } from "@/lib/api";
import { arrayOrEmpty } from "@/lib/api/shape";

const FY_OPTIONS = financialYearChoicesAround(null);

/** A best-effort, honest rendering of whatever a derived clause returned —
 *  a number, a string, a list or a nested object — without pretending to
 *  know the shape of every one of them. */
function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return JSON.stringify(value, null, 2);
}

function ClauseRow({ clause, manualValue, onManualChange }: {
  clause: Form3cdClause;
  manualValue: string;
  onManualChange: (code: string, value: string) => void;
}) {
  const hasDerivedValue = clause.derived && clause.value !== null && clause.value !== undefined;
  return (
    <tr className="border-b border-ps-border align-top">
      <td className="py-2 pr-3 text-sm font-mono text-ps-label whitespace-nowrap">{clause.code}</td>
      <td className="py-2 pr-3 text-sm text-ps-ink max-w-[26rem]">{clause.heading}</td>
      <td className="py-2 pr-3 text-sm">
        {hasDerivedValue ? (
          <span className="inline-flex items-center gap-1 text-state-ready">
            <CheckCircle2 size={14} /> Derived
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-ps-hint">
            <Circle size={14} /> Manual
          </span>
        )}
      </td>
      <td className="py-2 pr-3 text-sm">
        {hasDerivedValue ? (
          <pre className="whitespace-pre-wrap break-words text-xs bg-ps-muted rounded p-2 max-w-md">
            {renderValue(clause.value)}
          </pre>
        ) : (
          <textarea
            className="w-full min-w-[16rem] text-xs border border-ps-border rounded p-2"
            rows={2}
            placeholder="Record the CA's own answer for this clause…"
            value={manualValue}
            onChange={(e) => onManualChange(clause.code, e.target.value)}
          />
        )}
      </td>
      <td className="py-2 text-xs text-ps-hint max-w-sm">{clause.note}</td>
    </tr>
  );
}

export default function Form3cdPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [nature, setNature] = useState<"business" | "profession" | "">("");
  const [bankRateBps, setBankRateBps] = useState("");
  const [register, setRegister] = useState<Form3cdRegister | null>(null);
  const [manualDrafts, setManualDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { getClients().then(setClients).catch(() => setClients([])); }, []);

  const load = useCallback(async () => {
    if (!clientId) { setRegister(null); return; }
    setLoading(true); setError(null);
    try {
      const rate = bankRateBps.trim() ? Number(bankRateBps) : undefined;
      const j = await api.incomeTax.form3cd(clientId, fy, {
        nature: nature || undefined,
        bankRateBps: Number.isFinite(rate) ? rate : undefined,
      });
      if (!j.success || !j.data) throw new Error(j.error ?? "Could not build the Form 3CD register.");
      setRegister(j.data);
      // Prefill the draft boxes from whatever the CA has already recorded, so
      // reopening this register does not present a blank box over a saved
      // answer. Only string values round-trip into a textarea this way.
      const prefill: Record<string, string> = {};
      for (const c of j.data.clauses) {
        if (!c.derived && typeof c.value === "string") prefill[c.code] = c.value;
      }
      setManualDrafts(prefill);
    } catch (e) {
      setRegister(null);
      setError(e instanceof Error ? e.message : "Could not build the Form 3CD register.");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy, nature, bankRateBps]);

  useEffect(() => { load(); }, [load]);

  async function saveManual() {
    if (!clientId || Object.keys(manualDrafts).length === 0) return;
    setSaving(true); setError(null);
    try {
      const j = await api.incomeTax.saveForm3cdManualClauses(clientId, fy, {
        clauses: manualDrafts,
        status: "draft",
      });
      if (!j.success) throw new Error(j.error ?? "Could not save.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  const clauses = arrayOrEmpty<Form3cdClause>(register?.clauses);

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/income-tax/tax-audit" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-ps-ink">Form 3CD</h1>
          <p className="text-sm text-ps-label mt-0.5">
            The 44-clause statement of particulars annexed to the §44AB audit report.
            Derived clauses are computed from the books; every other clause is the
            CA&apos;s own to record.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-ps-label">Client</label>
          <div className="mt-1 min-w-[220px]">
            <ClientLookup clients={clients} value={clientId} onChange={setClientId}
                          ariaLabel="Client" placeholder="Select client…" />
          </div>
        </div>
        <div>
          <label className="text-xs text-ps-label">Financial year</label>
          <div className="mt-1">
            <YearPicker value={fy} onChange={setFy} className="w-auto" />
          </div>
        </div>
        <div>
          <label className="text-xs text-ps-label">Activity (for clause 8)</label>
          <select
            className="mt-1 border border-ps-border rounded px-2 py-1.5 text-sm"
            value={nature}
            onChange={(e) => setNature(e.target.value as "business" | "profession" | "")}
          >
            <option value="">Not stated</option>
            <option value="business">Business</option>
            <option value="profession">Profession</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-ps-label">RBI Bank Rate, bps (for clause 22)</label>
          <input
            className="mt-1 border border-ps-border rounded px-2 py-1.5 text-sm w-40"
            placeholder="e.g. 675"
            value={bankRateBps}
            onChange={(e) => setBankRateBps(e.target.value)}
          />
        </div>
        {Object.keys(manualDrafts).length > 0 && (
          <Button size="sm" onClick={saveManual} disabled={saving}>
            <Save size={14} className="mr-1" /> {saving ? "Saving…" : "Save recorded clauses"}
          </Button>
        )}
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

      <Card>
        <CardContent className="p-4">
          {loading ? (
            <TableSkeleton rows={8} cols={5} bare />
          ) : !clientId ? (
            <p className="text-sm text-ps-hint py-6 text-center">Select a client to build the register.</p>
          ) : (
            <>
              {register && (
                <p className="text-sm text-ps-label mb-3">
                  {register.derived_count} of {clauses.length} clauses derived from the books;
                  {" "}{register.manual_count} are the CA&apos;s own to record.
                </p>
              )}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-xs text-ps-hint border-b border-ps-border">
                      <th className="py-2 pr-3">Clause</th>
                      <th className="py-2 pr-3">Particulars</th>
                      <th className="py-2 pr-3">Source</th>
                      <th className="py-2 pr-3">Value / CA&apos;s answer</th>
                      <th className="py-2">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clauses.map((c) => (
                      <ClauseRow
                        key={c.code}
                        clause={c}
                        manualValue={manualDrafts[c.code] ?? ""}
                        onManualChange={(code, value) =>
                          setManualDrafts((prev) => ({ ...prev, [code]: value }))}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
