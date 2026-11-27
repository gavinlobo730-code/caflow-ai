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
 * TABLE 4 / 4.1 (POST-A-056) revise a row an EARLIER month's statement declared. They are recorded here against the month they amend and
 * checked by the server as the offline utility checks them; the statement says, in the server's own sentence, that they are NOT netted
 * against what the earlier month filed, which is held on the portal. This screen adds nothing up for them.
 *
 * Prepare-only. Nothing here is transmitted to any portal.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, Trash2, Plus } from "lucide-react";
import {
  api, type Gstr8Working, type Gstr8Supply, type Gstr8UnregisteredSupply,
  type Gstr8Amendment, type Gstr8UnregisteredAmendment,
} from "@/lib/api";
import { Callout, GapList, type GapLike } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { objectOrNull, objectWithLists } from "@/lib/api/shape";
import { failureSentence } from "@/lib/api/failureSentence";
import { INDIAN_STATES } from "@/lib/constants/indianStates";
import { Button } from "@/components/ui/button";
import { istToday } from "@/lib/dateMath";
import { LoadingRegion, SkeletonText } from "@/components/ui/skeleton";

function todayPeriod(): string {
  const d = istToday();
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

type AmendAction = "add" | "delete";

function emptyAmendmentForm(): Record<RupeeKey, string> & {
  original_period: string; original_supplier_gstin: string; original_place_of_supply: string;
  supplier_gstin: string; place_of_supply: string; action: AmendAction;
} {
  return {
    original_period: "", original_supplier_gstin: "", original_place_of_supply: "",
    supplier_gstin: "", place_of_supply: "", action: "add",
    gross_registered: "", returns_registered: "", gross_unregistered: "", returns_unregistered: "",
    igst: "", cgst: "", sgst: "",
  };
}

function emptyUnregisteredAmendmentForm() {
  return { original_period: "", original_enrolment_id: "", enrolment_id: "", gross: "", returns: "", action: "add" as AmendAction };
}

/** "042026" -> "04/2026". Display only. */
function monthLabel(period: string): string {
  return /^\d{6}$/.test(period) ? `${period.slice(0, 2)}/${period.slice(2)}` : period;
}

const ACTION_LABEL: Record<AmendAction, string> = { add: "Add", delete: "Delete" };

export function Gstr8Panel({ clientId, gstin }: { clientId: string; gstin: string }) {
  const [period, setPeriod] = useState(todayPeriod());
  const [registered, setRegistered] = useState<Gstr8Supply[]>([]);
  const [unregistered, setUnregistered] = useState<Gstr8UnregisteredSupply[]>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const [supplyForm, setSupplyForm] = useState(emptySupplyForm());
  const [savingSupply, setSavingSupply] = useState(false);
  const [supplyFormError, setSupplyFormError] = useState<string | null>(null);

  const [enrolmentId, setEnrolmentId] = useState("");
  const [unregGross, setUnregGross] = useState("");
  const [unregReturns, setUnregReturns] = useState("");
  const [savingUnreg, setSavingUnreg] = useState(false);
  const [unregFormError, setUnregFormError] = useState<string | null>(null);

  const [amendments, setAmendments] = useState<Gstr8Amendment[]>([]);
  const [amendForm, setAmendForm] = useState(emptyAmendmentForm());
  const [savingAmend, setSavingAmend] = useState(false);
  const [amendFormError, setAmendFormError] = useState<string | null>(null);

  const [unregAmendments, setUnregAmendments] = useState<Gstr8UnregisteredAmendment[]>([]);
  const [unregAmendForm, setUnregAmendForm] = useState(emptyUnregisteredAmendmentForm());
  const [savingUnregAmend, setSavingUnregAmend] = useState(false);
  const [unregAmendFormError, setUnregAmendFormError] = useState<string | null>(null);

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
      const data = objectWithLists<{
        registered: Gstr8Supply[]; unregistered: Gstr8UnregisteredSupply[];
        amendments: Gstr8Amendment[]; unregistered_amendments: Gstr8UnregisteredAmendment[];
      }>(res.success ? res.data : null, "registered", "unregistered", "amendments", "unregistered_amendments");
      setRegistered(data?.registered ?? []);
      setUnregistered(data?.unregistered ?? []);
      setAmendments(data?.amendments ?? []);
      setUnregAmendments(data?.unregistered_amendments ?? []);
      if (!res.success) setRowsError(res.error ?? "Couldn't load recorded supplies.");
    } catch (e) {
      setRegistered([]);
      setUnregistered([]);
      setAmendments([]);
      setUnregAmendments([]);
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

  // A REFUSED OR FAILED DELETE IS SAID, NEVER IGNORED (POST-A-515). The Remove buttons called the delete with no catch and no look at the
  // answer, so a locked period or a dropped connection left the row where it was and said nothing. The API client throws on a failed
  // request and answers `success: false` for a refusal it chose to word, and both are told here, in the words the server gave.
  const removeRow = useCallback(async (remove: () => Promise<{ success: boolean; error?: string | null }>) => {
    setStatement(null);
    setRemoveError(null);
    try {
      const res = await remove();
      if (!res.success) {
        setRemoveError(res.error ?? "Couldn't remove that row.");
        return;
      }
      await loadRows();
    } catch (e) {
      setRemoveError(failureSentence(e, "Couldn't remove that row.", "write"));
    }
  }, [loadRows]);

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

  const removeSupply = useCallback(
    (id: string) => removeRow(() => api.ecommerceOperator.deleteSupply(id, clientId)),
    [clientId, removeRow]);

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

  const removeUnregistered = useCallback(
    (id: string) => removeRow(() => api.ecommerceOperator.deleteUnregisteredSupply(id, clientId)),
    [clientId, removeRow]);

  // A blank revised GSTIN or place of supply means "unchanged": the request carries the original, so what is sent is explicit.
  const addAmendment = useCallback(async () => {
    const originalGstin = amendForm.original_supplier_gstin.trim().toUpperCase();
    if (!/^\d{6}$/.test(amendForm.original_period)) {
      setAmendFormError("The month being amended is required, as MMYYYY.");
      return;
    }
    if (!originalGstin) {
      setAmendFormError("The GSTIN of the supplier whose row is amended is required.");
      return;
    }
    setSavingAmend(true);
    setAmendFormError(null);
    try {
      const body: Record<string, unknown> = {
        client_id: clientId, gstin, period, original_period: amendForm.original_period,
        original_supplier_gstin: originalGstin,
        original_place_of_supply: amendForm.original_place_of_supply || null,
        supplier_gstin: amendForm.supplier_gstin.trim().toUpperCase() || originalGstin,
        place_of_supply: amendForm.place_of_supply || amendForm.original_place_of_supply || null,
        action: amendForm.action,
      };
      for (const [key] of RUPEE_FIELDS) {
        const paise = paiseFromRupeeInput(amendForm[key]);
        if (paise === null) {
          setAmendFormError(`"${amendForm[key]}" is not an amount.`);
          setSavingAmend(false);
          return;
        }
        body[`${key}_paise`] = paise;
      }
      const res = await api.ecommerceOperator.recordAmendment(body as Parameters<typeof api.ecommerceOperator.recordAmendment>[0]);
      if (!res.success) {
        setAmendFormError(res.error ?? "Couldn't record this amendment.");
        return;
      }
      setAmendForm(emptyAmendmentForm());
      setStatement(null);
      await loadRows();
    } catch (e) {
      setAmendFormError(e instanceof Error ? e.message : "Couldn't record this amendment.");
    } finally {
      setSavingAmend(false);
    }
  }, [clientId, gstin, period, amendForm, loadRows]);

  const removeAmendment = useCallback(
    (id: string) => removeRow(() => api.ecommerceOperator.deleteAmendment(id, clientId)),
    [clientId, removeRow]);

  const addUnregisteredAmendment = useCallback(async () => {
    const originalId = unregAmendForm.original_enrolment_id.trim();
    if (!/^\d{6}$/.test(unregAmendForm.original_period)) {
      setUnregAmendFormError("The month being amended is required, as MMYYYY.");
      return;
    }
    if (!originalId) {
      setUnregAmendFormError("The Enrolment ID of the row being amended is required.");
      return;
    }
    const gross = paiseFromRupeeInput(unregAmendForm.gross);
    const returns = paiseFromRupeeInput(unregAmendForm.returns);
    if (gross === null || returns === null) {
      setUnregAmendFormError("Enter valid amounts.");
      return;
    }
    setSavingUnregAmend(true);
    setUnregAmendFormError(null);
    try {
      const res = await api.ecommerceOperator.recordUnregisteredAmendment({
        client_id: clientId, gstin, period, original_period: unregAmendForm.original_period,
        original_enrolment_id: originalId, enrolment_id: unregAmendForm.enrolment_id.trim() || originalId,
        gross_value_paise: gross, returns_paise: returns, action: unregAmendForm.action,
      });
      if (!res.success) {
        setUnregAmendFormError(res.error ?? "Couldn't record this amendment.");
        return;
      }
      setUnregAmendForm(emptyUnregisteredAmendmentForm());
      setStatement(null);
      await loadRows();
    } catch (e) {
      setUnregAmendFormError(e instanceof Error ? e.message : "Couldn't record this amendment.");
    } finally {
      setSavingUnregAmend(false);
    }
  }, [clientId, gstin, period, unregAmendForm, loadRows]);

  const removeUnregisteredAmendment = useCallback(
    (id: string) => removeRow(() => api.ecommerceOperator.deleteUnregisteredAmendment(id, clientId)),
    [clientId, removeRow]);

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
  const amendmentGaps: GapLike[] = (statement?.amendment_findings ?? []).flatMap((f) =>
    f.problems.map((p) => ({ kind: `Amends ${f.supplier_gstin}`, reason: p })));

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
      {removeError && <Callout tone="problem" title="That row was not removed">{removeError}</Callout>}

      {/* ── Table 3 — registered sellers ────────────────────────────────── */}
      <div className="space-y-2">
        <h6 className="text-2xs font-semibold text-ps-body">Registered sellers (Table 3)</h6>
        {loadingRows ? (
          <LoadingRegion label="Loading the sellers">
            <SkeletonText lines={2} />
          </LoadingRegion>
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
                      <Button variant="plain" size="none" spinner={false} onClick={() => removeSupply(r.id)} title="Remove"
                        className="text-state-problem hover:opacity-70">
                        <Trash2 size={12} />
                      </Button>
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
          <Button variant="plain" size="none" spinner={false} onClick={addSupply} disabled={savingSupply}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {savingSupply ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add seller
          </Button>
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
                      <Button variant="plain" size="none" spinner={false} onClick={() => removeUnregistered(r.id)} title="Remove"
                        className="text-state-problem hover:opacity-70">
                        <Trash2 size={12} />
                      </Button>
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
          <Button variant="plain" size="none" spinner={false} onClick={addUnregistered} disabled={savingUnreg}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {savingUnreg ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add seller
          </Button>
        </div>
      </div>

      {/* ── Table 4 — amendments of an earlier month's registered sellers ─── */}
      <div className="space-y-2">
        <h6 className="text-2xs font-semibold text-ps-body">Amendments to an earlier month&apos;s registered sellers (Table 4)</h6>
        <p className="text-3xs text-ps-hint">
          Revise a row an earlier month&apos;s statement declared. The revised figures are recorded and checked; they are not netted
          against what that month filed, which is held on the portal.
        </p>
        {amendments.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-ps-hint text-left border-b border-ps-border">
                  <th className="py-1.5 pr-2 font-semibold">Amends</th>
                  <th className="py-1.5 pr-2 font-semibold">Revised supplier</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Net liable</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">IGST</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">CGST</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">SGST</th>
                  <th className="py-1.5 pr-2 font-semibold">Action</th>
                  <th className="py-1.5 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {amendments.map((r) => (
                  <tr key={r.id} className="border-b border-ps-border last:border-0">
                    <td className="py-1.5 pr-2 font-mono">{monthLabel(r.original_period)} · {r.original_supplier_gstin}</td>
                    <td className="py-1.5 pr-2 font-mono">{r.supplier_gstin}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.net_liable_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.igst_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.cgst_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.sgst_paise)}</td>
                    <td className="py-1.5 pr-2">{ACTION_LABEL[r.action] ?? r.action}</td>
                    <td className="py-1.5 text-right">
                      <Button variant="plain" size="none" spinner={false} onClick={() => removeAmendment(r.id)} title="Remove"
                        className="text-state-problem hover:opacity-70">
                        <Trash2 size={12} />
                      </Button>
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
              <span className="block text-ps-body font-medium mb-1">Month amended</span>
              <input value={amendForm.original_period} inputMode="numeric" placeholder="MMYYYY"
                onChange={(e) => setAmendForm((f) => ({ ...f, original_period: e.target.value.replace(/\D/g, "").slice(0, 6) }))}
                className="px-2 py-1 border border-ps-border rounded w-24 font-mono" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Supplier GSTIN amended</span>
              <input value={amendForm.original_supplier_gstin}
                onChange={(e) => setAmendForm((f) => ({ ...f, original_supplier_gstin: e.target.value.toUpperCase() }))}
                className="px-2 py-1 border border-ps-border rounded w-40 font-mono" maxLength={15} />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Original place of supply (from FY 2025-26)</span>
              <select value={amendForm.original_place_of_supply}
                onChange={(e) => setAmendForm((f) => ({ ...f, original_place_of_supply: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-44">
                <option value="">—</option>
                {INDIAN_STATES.map((st) => (
                  <option key={st.code} value={st.code}>{st.code} · {st.name}</option>
                ))}
              </select>
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Revised supplier GSTIN (blank = unchanged)</span>
              <input value={amendForm.supplier_gstin}
                onChange={(e) => setAmendForm((f) => ({ ...f, supplier_gstin: e.target.value.toUpperCase() }))}
                className="px-2 py-1 border border-ps-border rounded w-40 font-mono" maxLength={15} />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Revised place of supply (blank = unchanged)</span>
              <select value={amendForm.place_of_supply}
                onChange={(e) => setAmendForm((f) => ({ ...f, place_of_supply: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-44">
                <option value="">—</option>
                {INDIAN_STATES.map((st) => (
                  <option key={st.code} value={st.code}>{st.code} · {st.name}</option>
                ))}
              </select>
            </label>
            {RUPEE_FIELDS.map(([key, label]) => (
              <label key={key} className="text-2xs">
                <span className="block text-ps-body font-medium mb-1">{label}, revised (₹)</span>
                <input value={amendForm[key]} inputMode="decimal" placeholder="0"
                  onChange={(e) => setAmendForm((f) => ({ ...f, [key]: e.target.value }))}
                  className="px-2 py-1 border border-ps-border rounded w-24" />
              </label>
            ))}
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Action</span>
              <select value={amendForm.action}
                onChange={(e) => setAmendForm((f) => ({ ...f, action: e.target.value as AmendAction }))}
                className="px-2 py-1 border border-ps-border rounded w-24">
                <option value="add">Add</option>
                <option value="delete">Delete</option>
              </select>
            </label>
          </div>
          {amendFormError && <Callout tone="problem">{amendFormError}</Callout>}
          <Button variant="plain" size="none" spinner={false} onClick={addAmendment} disabled={savingAmend}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {savingAmend ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add amendment
          </Button>
        </div>
      </div>

      {/* ── Table 4.1 — amendments of an earlier month's Enrolment-ID sellers ─ */}
      <div className="space-y-2">
        <h6 className="text-2xs font-semibold text-ps-body">Amendments to an earlier month&apos;s Enrolment-ID sellers (Table 4.1)</h6>
        {unregAmendments.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-ps-hint text-left border-b border-ps-border">
                  <th className="py-1.5 pr-2 font-semibold">Amends</th>
                  <th className="py-1.5 pr-2 font-semibold">Revised Enrolment ID</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Gross value</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Returns</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Net</th>
                  <th className="py-1.5 pr-2 font-semibold">Action</th>
                  <th className="py-1.5 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {unregAmendments.map((r) => (
                  <tr key={r.id} className="border-b border-ps-border last:border-0">
                    <td className="py-1.5 pr-2 font-mono">{monthLabel(r.original_period)} · {r.original_enrolment_id}</td>
                    <td className="py-1.5 pr-2 font-mono">{r.enrolment_id}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.gross_value_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.returns_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.net_liable_paise)}</td>
                    <td className="py-1.5 pr-2">{ACTION_LABEL[r.action] ?? r.action}</td>
                    <td className="py-1.5 text-right">
                      <Button variant="plain" size="none" spinner={false} onClick={() => removeUnregisteredAmendment(r.id)} title="Remove"
                        className="text-state-problem hover:opacity-70">
                        <Trash2 size={12} />
                      </Button>
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
              <span className="block text-ps-body font-medium mb-1">Month amended</span>
              <input value={unregAmendForm.original_period} inputMode="numeric" placeholder="MMYYYY"
                onChange={(e) => setUnregAmendForm((f) => ({ ...f, original_period: e.target.value.replace(/\D/g, "").slice(0, 6) }))}
                className="px-2 py-1 border border-ps-border rounded w-24 font-mono" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Enrolment ID amended</span>
              <input value={unregAmendForm.original_enrolment_id}
                onChange={(e) => setUnregAmendForm((f) => ({ ...f, original_enrolment_id: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-40 font-mono" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Revised Enrolment ID (blank = unchanged)</span>
              <input value={unregAmendForm.enrolment_id}
                onChange={(e) => setUnregAmendForm((f) => ({ ...f, enrolment_id: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-40 font-mono" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Gross value, revised (₹)</span>
              <input value={unregAmendForm.gross} inputMode="decimal" placeholder="0"
                onChange={(e) => setUnregAmendForm((f) => ({ ...f, gross: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-28" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Returns, revised (₹)</span>
              <input value={unregAmendForm.returns} inputMode="decimal" placeholder="0"
                onChange={(e) => setUnregAmendForm((f) => ({ ...f, returns: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-28" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Action</span>
              <select value={unregAmendForm.action}
                onChange={(e) => setUnregAmendForm((f) => ({ ...f, action: e.target.value as AmendAction }))}
                className="px-2 py-1 border border-ps-border rounded w-24">
                <option value="add">Add</option>
                <option value="delete">Delete</option>
              </select>
            </label>
          </div>
          {unregAmendFormError && <Callout tone="problem">{unregAmendFormError}</Callout>}
          <Button variant="plain" size="none" spinner={false} onClick={addUnregisteredAmendment} disabled={savingUnregAmend}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {savingUnregAmend ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add amendment
          </Button>
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
                validation rather than confirmed against the CBIC portal.
                Check it before relying on this figure.
              </Callout>
            )}

            <GapList gaps={findingGaps} tone="attention" title="Rows to review before filing" />
            <GapList gaps={amendmentGaps} tone="attention" title="Amendments to review before filing" />

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

            {statement.amendment_note && (
              <Callout tone="note" title={`Amendments declared this month: Table 4 (${statement.amendment_count ?? 0}), Table 4.1 (${statement.unregistered_amendment_count ?? 0})`}>
                {statement.amendment_note}
              </Callout>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
