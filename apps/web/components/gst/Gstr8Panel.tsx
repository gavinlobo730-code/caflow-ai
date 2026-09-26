"use client";

/**
 * FORM GSTR-8 — a s.52 e-commerce operator's monthly TCS statement (GST-25).
 *
 * WHY IT LIVES ON THE REGISTRATION ROW AND NOWHERE ELSE
 *
 *   A TCS_COLLECTOR registration files GSTR-8 monthly and never GSTR-1 or
 *   GSTR-3B (`other_return_form` already says so on this same row) — the same
 *   reasoning `Cmp08Panel` records for a composition dealer.
 *
 * UNLIKE CMP-08, THIS RECORDS NEW FACTS RATHER THAN REUSING THE BOOKS.
 * GSTR-8 declares what OTHER SELLERS supplied through this operator's
 * platform — data that never touches this client's own ledger, so a CA types
 * each seller's figures here (`/api/ecommerce-operator/supplies`) before the
 * statement can be computed at all. `domain/gst/gstr8.py` does not derive the
 * IGST/CGST/SGST split — it CHECKS what was typed against the statutory rate
 * band, the same posture the GSTN offline utility itself takes.
 *
 * `place_of_supply` is asked only from FY 2025-26 (`pos_required` on the
 * computed statement says which periods) — the offline utility's own Table 3
 * schema carries the field from that year on, not before.
 *
 * Prepare-only. Nothing here is transmitted to any portal.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, Trash2, Plus } from "lucide-react";
import { api, type Gstr8Working, type Gstr8Supply, type Gstr8UnregisteredSupply } from "@/lib/api";
import { Callout, GapList, type GapLike } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { objectOrNull, objectWithLists } from "@/lib/api/shape";
import { INDIAN_STATES } from "@/lib/constants/indianStates";

function todayPeriod(): string {
  const d = new Date();
  return `${String(d.getMonth() + 1).padStart(2, "0")}${d.getFullYear()}`;
}

const RUPEE_FIELDS = [
  ["gross_registered", "Gross value — registered"],
  ["returns_registered", "Returns — registered"],
  ["gross_unregistered", "Gross value — unregistered"],
  ["returns_unregistered", "Returns — unregistered"],
  ["igst", "IGST"],
  ["cgst", "CGST"],
  ["sgst", "SGST"],
] as const;

type RupeeKey = (typeof RUPEE_FIELDS)[number][0];

function emptySupplyForm(): Record<RupeeKey, string> & { supplier_gstin: string; place_of_supply: string; notes: string } {
  return {
    supplier_gstin: "", place_of_supply: "", notes: "",
    gross_registered: "", returns_registered: "",
    gross_unregistered: "", returns_unregistered: "",
    igst: "", cgst: "", sgst: "",
  };
}

export function Gstr8Panel({ clientId, gstin }: { clientId: string; gstin: string }) {
  const [period, setPeriod] = useState(todayPeriod());
  const [registered, setRegistered] = useState<Gstr8Supply[]>([]);
  const [unregistered, setUnregistered] = useState<Gstr8UnregisteredSupply[]>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);

  const [supplyForm, setSupplyForm] = useState(emptySupplyForm());
  const [savingSupply, setSavingSupply] = useState(false);
  const [supplyFormError, setSupplyFormError] = useState<string | null>(null);

  const [enrolmentId, setEnrolmentId] = useState("");
  const [unregGross, setUnregGross] = useState("");
  const [unregReturns, setUnregReturns] = useState("");
  const [savingUnreg, setSavingUnreg] = useState(false);
  const [unregFormError, setUnregFormError] = useState<string | null>(null);

  const [statement, setStatement] = useState<Gstr8Working | null>(null);
  const [computing, setComputing] = useState(false);
  const [computeError, setComputeError] = useState<string | null>(null);

  const validPeriod = /^\d{6}$/.test(period);

  const loadRows = useCallback(async () => {
    if (!clientId || !validPeriod) return;
    setLoadingRows(true);
    setRowsError(null);
    try {
      const res = await api.ecommerceOperator.listSupplies(clientId, period, gstin);
      const data = objectWithLists<{ registered: Gstr8Supply[]; unregistered: Gstr8UnregisteredSupply[] }>(
        res.success ? res.data : null, "registered", "unregistered");
      setRegistered(data?.registered ?? []);
      setUnregistered(data?.unregistered ?? []);
      if (!res.success) setRowsError(res.error ?? "Couldn't load recorded supplies.");
    } catch (e) {
      setRegistered([]);
      setUnregistered([]);
      setRowsError(e instanceof Error ? e.message : "Couldn't load recorded supplies.");
    } finally {
      setLoadingRows(false);
    }
  }, [clientId, gstin, period, validPeriod]);

  useEffect(() => {
    setStatement(null);
    loadRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  const addSupply = useCallback(async () => {
    const supplierGstin = supplyForm.supplier_gstin.trim().toUpperCase();
    if (!supplierGstin) {
      setSupplyFormError("The supplier's GSTIN is required.");
      return;
    }
    setSavingSupply(true);
    setSupplyFormError(null);
    try {
      const body: Record<string, unknown> = {
        client_id: clientId, gstin, period, supplier_gstin: supplierGstin,
        place_of_supply: supplyForm.place_of_supply || null,
        notes: supplyForm.notes || null,
      };
      for (const [key] of RUPEE_FIELDS) {
        const paise = paiseFromRupeeInput(supplyForm[key]);
        if (paise === null) {
          setSupplyFormError(`"${supplyForm[key]}" is not an amount.`);
          setSavingSupply(false);
          return;
        }
        body[`${key}_paise`] = paise;
      }
      const res = await api.ecommerceOperator.recordSupply(body as Parameters<typeof api.ecommerceOperator.recordSupply>[0]);
      if (!res.success) {
        setSupplyFormError(res.error ?? "Couldn't record this seller's figures.");
        return;
      }
      setSupplyForm(emptySupplyForm());
      setStatement(null);
      await loadRows();
    } catch (e) {
      setSupplyFormError(e instanceof Error ? e.message : "Couldn't record this seller's figures.");
    } finally {
      setSavingSupply(false);
    }
  }, [clientId, gstin, period, supplyForm, loadRows]);

  const removeSupply = useCallback(async (id: string) => {
    setStatement(null);
    await api.ecommerceOperator.deleteSupply(id, clientId);
    await loadRows();
  }, [clientId, loadRows]);

  const addUnregistered = useCallback(async () => {
    const eid = enrolmentId.trim();
    if (!eid) {
      setUnregFormError("The Enrolment ID is required.");
      return;
    }
    const gross = paiseFromRupeeInput(unregGross);
    const returns = paiseFromRupeeInput(unregReturns);
    if (gross === null || returns === null) {
      setUnregFormError("Enter valid amounts.");
      return;
    }
    setSavingUnreg(true);
    setUnregFormError(null);
    try {
      const res = await api.ecommerceOperator.recordUnregisteredSupply({
        client_id: clientId, gstin, period, enrolment_id: eid,
        gross_value_paise: gross, returns_paise: returns,
      });
      if (!res.success) {
        setUnregFormError(res.error ?? "Couldn't record this seller's figures.");
        return;
      }
      setEnrolmentId(""); setUnregGross(""); setUnregReturns("");
      setStatement(null);
      await loadRows();
    } catch (e) {
      setUnregFormError(e instanceof Error ? e.message : "Couldn't record this seller's figures.");
    } finally {
      setSavingUnreg(false);
    }
  }, [clientId, gstin, period, enrolmentId, unregGross, unregReturns, loadRows]);

  const removeUnregistered = useCallback(async (id: string) => {
    setStatement(null);
    await api.ecommerceOperator.deleteUnregisteredSupply(id, clientId);
    await loadRows();
  }, [clientId, loadRows]);

  const compute = useCallback(async () => {
    if (!validPeriod) return;
    setComputing(true);
    setComputeError(null);
    try {
      const res = await api.gstr8.compute(clientId, period, gstin);
      setStatement(objectOrNull<Gstr8Working>(res.success ? res.data : null));
      if (!res.success) setComputeError(res.error ?? "Couldn't prepare GSTR-8.");
    } catch (e) {
      setStatement(null);
      setComputeError(e instanceof Error ? e.message : "Couldn't prepare GSTR-8.");
    } finally {
      setComputing(false);
    }
  }, [clientId, gstin, period, validPeriod]);

  const findingGaps: GapLike[] = (statement?.findings ?? []).flatMap((f) =>
    f.problems.map((p) => ({ kind: f.supplier_gstin, reason: p })));

  return (
    <div className="mt-2 border border-ps-border rounded-lg p-3 space-y-4 bg-ps-bg/40">
      <div>
        <h5 className="text-xs font-semibold text-ps-ink">Prepare FORM GSTR-8</h5>
        <p className="text-3xs text-ps-hint mt-0.5">
          CGST Act s.52, Rule 67(1) — the monthly TCS statement an e-commerce
          operator files for what OTHER sellers supplied through its platform.
          Record each seller&apos;s figures below, then compute the statement.
        </p>
      </div>

      <label className="text-2xs block w-fit">
        <span className="block text-ps-body font-medium mb-1">Month</span>
        <input value={period} inputMode="numeric" placeholder="MMYYYY"
          onChange={(e) => setPeriod(e.target.value.replace(/\D/g, "").slice(0, 6))}
          className="px-2 py-1 border border-ps-border rounded w-24 font-mono" />
      </label>

      {rowsError && <Callout tone="problem" title="Couldn't load recorded supplies">{rowsError}</Callout>}

      {/* ── Table 3 — registered sellers ────────────────────────────────── */}
      <div className="space-y-2">
        <h6 className="text-2xs font-semibold text-ps-body">Registered sellers (Table 3)</h6>
        {loadingRows ? (
          <p className="text-2xs text-ps-hint inline-flex items-center gap-1"><Loader2 size={11} className="animate-spin" /> Loading…</p>
        ) : registered.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-ps-hint text-left border-b border-ps-border">
                  <th className="py-1.5 pr-2 font-semibold">Supplier GSTIN</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Net liable</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">IGST</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">CGST</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">SGST</th>
                  <th className="py-1.5 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {registered.map((r) => (
                  <tr key={r.id} className="border-b border-ps-border last:border-0">
                    <td className="py-1.5 pr-2 font-mono">{r.supplier_gstin}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">
                      {formatPaise(r.gross_registered_paise + r.gross_unregistered_paise
                        - r.returns_registered_paise - r.returns_unregistered_paise)}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.igst_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.cgst_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.sgst_paise)}</td>
                    <td className="py-1.5 text-right">
                      <button onClick={() => removeSupply(r.id)} title="Remove"
                        className="text-state-problem hover:opacity-70">
                        <Trash2 size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-2xs text-ps-hint">No registered seller recorded for this month yet.</p>
        )}

        <div className="border border-dashed border-ps-border rounded-lg p-2.5 space-y-2">
          <div className="flex flex-wrap gap-2">
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Supplier GSTIN</span>
              <input value={supplyForm.supplier_gstin}
                onChange={(e) => setSupplyForm((f) => ({ ...f, supplier_gstin: e.target.value.toUpperCase() }))}
                className="px-2 py-1 border border-ps-border rounded w-40 font-mono" maxLength={15} />
            </label>
            {statement?.pos_required && (
              <label className="text-2xs">
                <span className="block text-ps-body font-medium mb-1">Place of supply</span>
                <select value={supplyForm.place_of_supply}
                  onChange={(e) => setSupplyForm((f) => ({ ...f, place_of_supply: e.target.value }))}
                  className="px-2 py-1 border border-ps-border rounded w-40">
                  <option value="">—</option>
                  {INDIAN_STATES.map((s) => (
                    <option key={s.code} value={s.code}>{s.code} · {s.name}</option>
                  ))}
                </select>
              </label>
            )}
            {RUPEE_FIELDS.map(([key, label]) => (
              <label key={key} className="text-2xs">
                <span className="block text-ps-body font-medium mb-1">{label} (₹)</span>
                <input value={supplyForm[key]} inputMode="decimal" placeholder="0"
                  onChange={(e) => setSupplyForm((f) => ({ ...f, [key]: e.target.value }))}
                  className="px-2 py-1 border border-ps-border rounded w-24" />
              </label>
            ))}
          </div>
          {supplyFormError && <Callout tone="problem">{supplyFormError}</Callout>}
          <button onClick={addSupply} disabled={savingSupply}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {savingSupply ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add seller
          </button>
        </div>
      </div>

      {/* ── Table 3.1 — Enrolment-ID sellers ─────────────────────────────── */}
      <div className="space-y-2">
        <h6 className="text-2xs font-semibold text-ps-body">Unregistered sellers, Rule 12(1A) Enrolment ID (Table 3.1)</h6>
        {unregistered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-ps-hint text-left border-b border-ps-border">
                  <th className="py-1.5 pr-2 font-semibold">Enrolment ID</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Gross value</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Returns</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Net</th>
                  <th className="py-1.5 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {unregistered.map((r) => (
                  <tr key={r.id} className="border-b border-ps-border last:border-0">
                    <td className="py-1.5 pr-2 font-mono">{r.enrolment_id}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.gross_value_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.returns_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.gross_value_paise - r.returns_paise)}</td>
                    <td className="py-1.5 text-right">
                      <button onClick={() => removeUnregistered(r.id)} title="Remove"
                        className="text-state-problem hover:opacity-70">
                        <Trash2 size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="border border-dashed border-ps-border rounded-lg p-2.5 space-y-2">
          <div className="flex flex-wrap gap-2">
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Enrolment ID</span>
              <input value={enrolmentId} onChange={(e) => setEnrolmentId(e.target.value)}
                className="px-2 py-1 border border-ps-border rounded w-40 font-mono" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Gross value (₹)</span>
              <input value={unregGross} inputMode="decimal" placeholder="0"
                onChange={(e) => setUnregGross(e.target.value)}
                className="px-2 py-1 border border-ps-border rounded w-28" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Returns (₹)</span>
              <input value={unregReturns} inputMode="decimal" placeholder="0"
                onChange={(e) => setUnregReturns(e.target.value)}
                className="px-2 py-1 border border-ps-border rounded w-28" />
            </label>
          </div>
          {unregFormError && <Callout tone="problem">{unregFormError}</Callout>}
          <button onClick={addUnregistered} disabled={savingUnreg}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {savingUnreg ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add seller
          </button>
        </div>
      </div>

      {/* ── Compute ──────────────────────────────────────────────────────── */}
      <div className="pt-2 border-t border-ps-border space-y-2">
        <button onClick={compute} disabled={computing || !validPeriod}
          className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
          {computing && <Loader2 size={11} className="animate-spin" />}
          Compute GSTR-8
        </button>

        {computeError && <Callout tone="problem" title="Couldn't prepare GSTR-8">{computeError}</Callout>}

        {statement && (
          <div className="space-y-2">
            <p className="text-2xs text-ps-hint">
              {statement.financial_year} · {gstin}
            </p>

            {!statement.gstr8_rates_verified && (
              <Callout tone="note" title="Rate band not independently verified">
                The s.52 TCS rate applied here is recorded from the Finance
                (No. 2) Act 2024 and the GSTN offline utility&apos;s own
                validation rather than confirmed against the CBIC portal in
                this environment. Check it before relying on this figure.
              </Callout>
            )}

            <GapList gaps={findingGaps} tone="attention" title="Rows to review before filing" />

            <div className="overflow-x-auto">
              <table className="w-full text-2xs">
                <thead>
                  <tr className="text-ps-hint text-left border-b border-ps-border">
                    <th className="py-1.5 pr-3 font-semibold"></th>
                    <th className="py-1.5 pr-3 font-semibold text-right">Net liable</th>
                    <th className="py-1.5 pr-3 font-semibold text-right">IGST</th>
                    <th className="py-1.5 pr-3 font-semibold text-right">CGST</th>
                    <th className="py-1.5 font-semibold text-right">SGST</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-ps-border">
                    <td className="py-1.5 pr-3 text-ps-body">
                      Registered sellers ({statement.supplier_count})
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(statement.total_net_liable_paise)}</td>
                    <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(statement.total_igst_paise)}</td>
                    <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(statement.total_cgst_paise)}</td>
                    <td className="py-1.5 text-right font-mono">{formatPaise(statement.total_sgst_paise)}</td>
                  </tr>
                  <tr>
                    <td className="py-1.5 pr-3 text-ps-body">
                      Unregistered sellers ({statement.unregistered_supplier_count})
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(statement.total_unregistered_net_paise)}</td>
                    <td className="py-1.5 pr-3 text-right font-mono">—</td>
                    <td className="py-1.5 pr-3 text-right font-mono">—</td>
                    <td className="py-1.5 text-right font-mono">—</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
