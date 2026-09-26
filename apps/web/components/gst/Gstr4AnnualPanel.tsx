"use client";

/**
 * FORM GSTR-4 Annual — a composition dealer's annual return (GST-25, part 3).
 *
 * CGST Act s.44 with Rule 80(3): the annual return under s.10, distinct from
 * the quarterly CMP-08 (`Cmp08Panel`) the same registration also files.
 * Tables 4A-4D are the dealer's own INWARD supplies for the year — a CA
 * records each counterparty's figures below (the same posture `Gstr8Panel`
 * takes for GSTR-8 Table 3: this does not derive them from the books, it
 * CHECKS what is recorded). Table 5 is the opposite — four already-filed
 * CMP-08 statements for the year, summed, with nothing left to type.
 *
 * Prepare-only. Nothing here is transmitted to any portal.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Trash2, Plus, ChevronDown, ChevronRight } from "lucide-react";
import {
  api,
  type Gstr4AnnualWorking,
  type Gstr4AnnualB2BSupply,
  type Gstr4AnnualUrpSupply,
  type Gstr4AnnualImportOfService,
} from "@/lib/api";
import { Callout, GapList, type GapLike } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { objectOrNull, arrayOrEmpty } from "@/lib/api/shape";
import { INDIAN_STATES } from "@/lib/constants/indianStates";
import { financialYearChoicesAround } from "@/lib/dates/periods";

const B2B_RUPEE_FIELDS = [
  ["taxable_value", "Taxable value"],
  ["igst", "IGST"],
  ["cgst", "CGST"],
  ["sgst", "SGST"],
  ["cess", "Cess"],
] as const;

type B2BRupeeKey = (typeof B2B_RUPEE_FIELDS)[number][0];

function emptyB2BForm(): Record<B2BRupeeKey, string> & {
  supplier_gstin: string; place_of_supply: string; rate: string; notes: string;
} {
  return {
    supplier_gstin: "", place_of_supply: "", rate: "", notes: "",
    taxable_value: "", igst: "", cgst: "", sgst: "", cess: "",
  };
}

function emptyUrpForm() {
  return {
    counterparty_pan: "", reverse_charge: false, place_of_supply: "",
    supply_type: "", rate: "", taxable_value: "", igst: "", cgst: "",
    sgst: "", cess: "", notes: "",
  };
}

function emptyImpsForm() {
  return { place_of_supply: "", rate: "", taxable_value: "", igst: "", cess: "" };
}

function Section({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-ps-border rounded-lg">
      <button onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-left">
        <div>
          <h6 className="text-2xs font-semibold text-ps-body">{title}</h6>
          <p className="text-3xs text-ps-hint mt-0.5">{subtitle}</p>
        </div>
        {open ? <ChevronDown size={14} className="text-ps-hint shrink-0" /> : <ChevronRight size={14} className="text-ps-hint shrink-0" />}
      </button>
      {open && <div className="px-3 pb-3 space-y-2">{children}</div>}
    </div>
  );
}

export function Gstr4AnnualPanel({ clientId, gstin }: { clientId: string; gstin: string }) {
  const fyChoices = useMemo(() => financialYearChoicesAround(), []);
  const [financialYear, setFinancialYear] = useState(fyChoices[0] ?? "");

  const [b2b, setB2b] = useState<Gstr4AnnualB2BSupply[]>([]);
  const [b2bRc, setB2bRc] = useState<Gstr4AnnualB2BSupply[]>([]);
  const [urp, setUrp] = useState<Gstr4AnnualUrpSupply[]>([]);
  const [imps, setImps] = useState<Gstr4AnnualImportOfService[]>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);

  const [b2bForm, setB2bForm] = useState(emptyB2BForm());
  const [b2bRcForm, setB2bRcForm] = useState(emptyB2BForm());
  const [urpForm, setUrpForm] = useState(emptyUrpForm());
  const [impsForm, setImpsForm] = useState(emptyImpsForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [statement, setStatement] = useState<Gstr4AnnualWorking | null>(null);
  const [computing, setComputing] = useState(false);
  const [computeError, setComputeError] = useState<string | null>(null);

  const validFY = /^\d{4}-\d{2}$/.test(financialYear);

  const loadRows = useCallback(async () => {
    if (!clientId || !validFY) return;
    setLoadingRows(true);
    setRowsError(null);
    try {
      const [rb2b, rb2brc, rurp, rimps] = await Promise.all([
        api.gstr4Annual.listB2BSupplies(clientId, financialYear, gstin),
        api.gstr4Annual.listB2BRcSupplies(clientId, financialYear, gstin),
        api.gstr4Annual.listUrpSupplies(clientId, financialYear, gstin),
        api.gstr4Annual.listImportOfServices(clientId, financialYear, gstin),
      ]);
      setB2b(arrayOrEmpty<Gstr4AnnualB2BSupply>(rb2b.success ? rb2b.data : null));
      setB2bRc(arrayOrEmpty<Gstr4AnnualB2BSupply>(rb2brc.success ? rb2brc.data : null));
      setUrp(arrayOrEmpty<Gstr4AnnualUrpSupply>(rurp.success ? rurp.data : null));
      setImps(arrayOrEmpty<Gstr4AnnualImportOfService>(rimps.success ? rimps.data : null));
      if (!rb2b.success || !rb2brc.success || !rurp.success || !rimps.success) {
        setRowsError("Couldn't load some recorded supplies.");
      }
    } catch (e) {
      setB2b([]); setB2bRc([]); setUrp([]); setImps([]);
      setRowsError(e instanceof Error ? e.message : "Couldn't load recorded supplies.");
    } finally {
      setLoadingRows(false);
    }
  }, [clientId, gstin, financialYear, validFY]);

  useEffect(() => {
    setStatement(null);
    loadRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [financialYear]);

  const parseB2BBody = (form: ReturnType<typeof emptyB2BForm>): Record<string, unknown> | null => {
    const supplierGstin = form.supplier_gstin.trim().toUpperCase();
    if (!supplierGstin) { setFormError("The supplier's GSTIN is required."); return null; }
    if (!form.place_of_supply) { setFormError("Place of supply is required."); return null; }
    const body: Record<string, unknown> = {
      client_id: clientId, gstin, financial_year: financialYear,
      supplier_gstin: supplierGstin, place_of_supply: form.place_of_supply,
      rate_bps: bpsFromPercentInput(form.rate) ?? 0,
      notes: form.notes || null,
    };
    for (const [key] of B2B_RUPEE_FIELDS) {
      const paise = paiseFromRupeeInput(form[key]);
      if (paise === null) { setFormError(`"${form[key]}" is not an amount.`); return null; }
      body[`${key}_paise`] = paise;
    }
    return body;
  };

  const addB2B = useCallback(async () => {
    setFormError(null);
    const body = parseB2BBody(b2bForm);
    if (!body) return;
    setSaving(true);
    try {
      const res = await api.gstr4Annual.recordB2BSupply(body as Parameters<typeof api.gstr4Annual.recordB2BSupply>[0]);
      if (!res.success) { setFormError(res.error ?? "Couldn't record this supply."); return; }
      setB2bForm(emptyB2BForm());
      setStatement(null);
      await loadRows();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Couldn't record this supply.");
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [b2bForm, clientId, gstin, financialYear, loadRows]);

  const addB2BRc = useCallback(async () => {
    setFormError(null);
    const body = parseB2BBody(b2bRcForm);
    if (!body) return;
    setSaving(true);
    try {
      const res = await api.gstr4Annual.recordB2BRcSupply(body as Parameters<typeof api.gstr4Annual.recordB2BRcSupply>[0]);
      if (!res.success) { setFormError(res.error ?? "Couldn't record this supply."); return; }
      setB2bRcForm(emptyB2BForm());
      setStatement(null);
      await loadRows();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Couldn't record this supply.");
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [b2bRcForm, clientId, gstin, financialYear, loadRows]);

  const addUrp = useCallback(async () => {
    setFormError(null);
    if (!urpForm.place_of_supply) { setFormError("Place of supply is required."); return; }
    if (urpForm.reverse_charge && !urpForm.supply_type) {
      setFormError("Supply type (Intra-State or Inter-State) is required for a reverse-charge row.");
      return;
    }
    const taxable = paiseFromRupeeInput(urpForm.taxable_value);
    const igst = paiseFromRupeeInput(urpForm.igst || "0");
    const cgst = paiseFromRupeeInput(urpForm.cgst || "0");
    const sgst = paiseFromRupeeInput(urpForm.sgst || "0");
    const cess = paiseFromRupeeInput(urpForm.cess || "0");
    if ([taxable, igst, cgst, sgst, cess].some((v) => v === null)) {
      setFormError("Enter valid amounts.");
      return;
    }
    setSaving(true);
    try {
      const res = await api.gstr4Annual.recordUrpSupply({
        client_id: clientId, gstin, financial_year: financialYear,
        counterparty_pan: urpForm.counterparty_pan.trim().toUpperCase() || null,
        reverse_charge: urpForm.reverse_charge,
        place_of_supply: urpForm.place_of_supply,
        supply_type: urpForm.reverse_charge ? (urpForm.supply_type || null) : null,
        rate_bps: urpForm.reverse_charge && urpForm.rate
          ? bpsFromPercentInput(urpForm.rate) : null,
        taxable_value_paise: taxable ?? 0, igst_paise: igst ?? 0,
        cgst_paise: cgst ?? 0, sgst_paise: sgst ?? 0, cess_paise: cess ?? 0,
        notes: urpForm.notes || null,
      });
      if (!res.success) { setFormError(res.error ?? "Couldn't record this supply."); return; }
      setUrpForm(emptyUrpForm());
      setStatement(null);
      await loadRows();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Couldn't record this supply.");
    } finally {
      setSaving(false);
    }
  }, [urpForm, clientId, gstin, financialYear, loadRows]);

  const addImps = useCallback(async () => {
    setFormError(null);
    if (!impsForm.place_of_supply) { setFormError("Place of supply is required."); return; }
    const taxable = paiseFromRupeeInput(impsForm.taxable_value);
    const igst = paiseFromRupeeInput(impsForm.igst || "0");
    const cess = paiseFromRupeeInput(impsForm.cess || "0");
    if ([taxable, igst, cess].some((v) => v === null)) {
      setFormError("Enter valid amounts.");
      return;
    }
    setSaving(true);
    try {
      const res = await api.gstr4Annual.recordImportOfService({
        client_id: clientId, gstin, financial_year: financialYear,
        place_of_supply: impsForm.place_of_supply,
        rate_bps: bpsFromPercentInput(impsForm.rate) ?? 0,
        taxable_value_paise: taxable ?? 0, igst_paise: igst ?? 0, cess_paise: cess ?? 0,
      });
      if (!res.success) { setFormError(res.error ?? "Couldn't record this import."); return; }
      setImpsForm(emptyImpsForm());
      setStatement(null);
      await loadRows();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Couldn't record this import.");
    } finally {
      setSaving(false);
    }
  }, [impsForm, clientId, gstin, financialYear, loadRows]);

  const compute = useCallback(async () => {
    if (!validFY) return;
    setComputing(true);
    setComputeError(null);
    try {
      const res = await api.gstr4Annual.compute(clientId, financialYear, gstin);
      setStatement(objectOrNull<Gstr4AnnualWorking>(res.success ? res.data : null));
      if (!res.success) setComputeError(res.error ?? "Couldn't prepare GSTR-4 Annual.");
    } catch (e) {
      setStatement(null);
      setComputeError(e instanceof Error ? e.message : "Couldn't prepare GSTR-4 Annual.");
    } finally {
      setComputing(false);
    }
  }, [clientId, gstin, financialYear, validFY]);

  const findingGaps: GapLike[] = (statement?.findings ?? []).flatMap((f) =>
    f.problems.map((p) => ({ kind: `${f.table} · ${f.identifier}`, reason: p })));

  return (
    <div className="mt-2 border border-ps-border rounded-lg p-3 space-y-4 bg-ps-bg/40">
      <div>
        <h5 className="text-xs font-semibold text-ps-ink">Prepare FORM GSTR-4 Annual</h5>
        <p className="text-3xs text-ps-hint mt-0.5">
          CGST Act s.44, Rule 80(3) — the annual return a COMPOSITION
          registration files, alongside CMP-08 filed quarterly. Tables 4A-4D
          are the dealer&apos;s own inward supplies for the year; Table 5 is
          the year&apos;s four CMP-08 statements, summed automatically.
        </p>
      </div>

      <label className="text-2xs block w-fit">
        <span className="block text-ps-body font-medium mb-1">Financial year</span>
        <select value={financialYear} onChange={(e) => setFinancialYear(e.target.value)}
          className="px-2 py-1 border border-ps-border rounded w-32 font-mono">
          {fyChoices.map((fy) => <option key={fy} value={fy}>{fy}</option>)}
        </select>
      </label>

      {rowsError && <Callout tone="problem" title="Couldn't load recorded supplies">{rowsError}</Callout>}
      {formError && <Callout tone="problem">{formError}</Callout>}

      <Section title="Table 4A — registered supplier, no reverse charge" subtitle="Informational only: the supplier already charged and remitted this tax.">
        {loadingRows ? <p className="text-2xs text-ps-hint inline-flex items-center gap-1"><Loader2 size={11} className="animate-spin" /> Loading…</p> : (
          <B2BTable rows={b2b} onRemove={async (id) => { setStatement(null); await api.gstr4Annual.deleteB2BSupply(id, clientId); await loadRows(); }} />
        )}
        <B2BForm form={b2bForm} setForm={setB2bForm} onAdd={addB2B} saving={saving} />
      </Section>

      <Section title="Table 4B — registered supplier, reverse charge" subtitle="s.9(3)/(4): the dealer self-assesses this tax, and it feeds the return's liability.">
        {loadingRows ? <p className="text-2xs text-ps-hint inline-flex items-center gap-1"><Loader2 size={11} className="animate-spin" /> Loading…</p> : (
          <B2BTable rows={b2bRc} onRemove={async (id) => { setStatement(null); await api.gstr4Annual.deleteB2BRcSupply(id, clientId); await loadRows(); }} />
        )}
        <B2BForm form={b2bRcForm} setForm={setB2bRcForm} onAdd={addB2BRc} saving={saving} />
      </Section>

      <Section title="Table 4C — unregistered person" subtitle="Reverse charge is a per-row fact — record it only where it applies.">
        {!loadingRows && urp.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-ps-hint text-left border-b border-ps-border">
                  <th className="py-1.5 pr-2 font-semibold">PAN</th>
                  <th className="py-1.5 pr-2 font-semibold">RC</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Taxable value</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Tax</th>
                  <th className="py-1.5 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {urp.map((r) => (
                  <tr key={r.id} className="border-b border-ps-border last:border-0">
                    <td className="py-1.5 pr-2 font-mono">{r.counterparty_pan ?? "—"}</td>
                    <td className="py-1.5 pr-2">{r.reverse_charge ? "Yes" : "No"}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.taxable_value_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.igst_paise + r.cgst_paise + r.sgst_paise + r.cess_paise)}</td>
                    <td className="py-1.5 text-right">
                      <button onClick={async () => { setStatement(null); await api.gstr4Annual.deleteUrpSupply(r.id, clientId); await loadRows(); }} title="Remove" className="text-state-problem hover:opacity-70">
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
          <div className="flex flex-wrap gap-2 items-end">
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Counterparty PAN (optional)</span>
              <input value={urpForm.counterparty_pan} onChange={(e) => setUrpForm((f) => ({ ...f, counterparty_pan: e.target.value.toUpperCase() }))}
                className="px-2 py-1 border border-ps-border rounded w-32 font-mono" maxLength={10} />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Place of supply</span>
              <select value={urpForm.place_of_supply} onChange={(e) => setUrpForm((f) => ({ ...f, place_of_supply: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-40">
                <option value="">—</option>
                {INDIAN_STATES.map((s) => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
              </select>
            </label>
            <label className="text-2xs inline-flex items-center gap-1.5 pb-1.5">
              <input type="checkbox" checked={urpForm.reverse_charge}
                onChange={(e) => setUrpForm((f) => ({ ...f, reverse_charge: e.target.checked }))} />
              Reverse charge
            </label>
            {urpForm.reverse_charge && (
              <>
                <label className="text-2xs">
                  <span className="block text-ps-body font-medium mb-1">Supply type</span>
                  <select value={urpForm.supply_type} onChange={(e) => setUrpForm((f) => ({ ...f, supply_type: e.target.value }))}
                    className="px-2 py-1 border border-ps-border rounded w-32">
                    <option value="">—</option>
                    <option value="Intra-State">Intra-State</option>
                    <option value="Inter-State">Inter-State</option>
                  </select>
                </label>
                <label className="text-2xs">
                  <span className="block text-ps-body font-medium mb-1">Rate (%)</span>
                  <input value={urpForm.rate} inputMode="decimal" placeholder="0"
                    onChange={(e) => setUrpForm((f) => ({ ...f, rate: e.target.value }))}
                    className="px-2 py-1 border border-ps-border rounded w-16" />
                </label>
              </>
            )}
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Taxable value (₹)</span>
              <input value={urpForm.taxable_value} inputMode="decimal" placeholder="0"
                onChange={(e) => setUrpForm((f) => ({ ...f, taxable_value: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-24" />
            </label>
            {urpForm.reverse_charge && (["igst", "cgst", "sgst", "cess"] as const).map((key) => (
              <label key={key} className="text-2xs">
                <span className="block text-ps-body font-medium mb-1">{key.toUpperCase()} (₹)</span>
                <input value={urpForm[key]} inputMode="decimal" placeholder="0"
                  onChange={(e) => setUrpForm((f) => ({ ...f, [key]: e.target.value }))}
                  className="px-2 py-1 border border-ps-border rounded w-20" />
              </label>
            ))}
          </div>
          <button onClick={addUrp} disabled={saving}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {saving ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add supply
          </button>
        </div>
      </Section>

      <Section title="Table 4D — import of services" subtitle="IGST Act s.7(4): always inter-State, so there is no CGST/SGST here at all.">
        {!loadingRows && imps.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-ps-hint text-left border-b border-ps-border">
                  <th className="py-1.5 pr-2 font-semibold">Place of supply</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Taxable value</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">IGST</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Cess</th>
                  <th className="py-1.5 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {imps.map((r) => (
                  <tr key={r.id} className="border-b border-ps-border last:border-0">
                    <td className="py-1.5 pr-2 font-mono">{r.place_of_supply}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.taxable_value_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.igst_paise)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.cess_paise)}</td>
                    <td className="py-1.5 text-right">
                      <button onClick={async () => { setStatement(null); await api.gstr4Annual.deleteImportOfService(r.id, clientId); await loadRows(); }} title="Remove" className="text-state-problem hover:opacity-70">
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
              <span className="block text-ps-body font-medium mb-1">Place of supply</span>
              <select value={impsForm.place_of_supply} onChange={(e) => setImpsForm((f) => ({ ...f, place_of_supply: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-40">
                <option value="">—</option>
                {INDIAN_STATES.map((s) => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
              </select>
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Rate (%)</span>
              <input value={impsForm.rate} inputMode="decimal" placeholder="0"
                onChange={(e) => setImpsForm((f) => ({ ...f, rate: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-16" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Taxable value (₹)</span>
              <input value={impsForm.taxable_value} inputMode="decimal" placeholder="0"
                onChange={(e) => setImpsForm((f) => ({ ...f, taxable_value: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-24" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">IGST (₹)</span>
              <input value={impsForm.igst} inputMode="decimal" placeholder="0"
                onChange={(e) => setImpsForm((f) => ({ ...f, igst: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-20" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Cess (₹)</span>
              <input value={impsForm.cess} inputMode="decimal" placeholder="0"
                onChange={(e) => setImpsForm((f) => ({ ...f, cess: e.target.value }))}
                className="px-2 py-1 border border-ps-border rounded w-20" />
            </label>
          </div>
          <button onClick={addImps} disabled={saving}
            className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
            {saving ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
            Add import
          </button>
        </div>
      </Section>

      {/* ── Compute ──────────────────────────────────────────────────────── */}
      <div className="pt-2 border-t border-ps-border space-y-2">
        <button onClick={compute} disabled={computing || !validFY}
          className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
          {computing && <Loader2 size={11} className="animate-spin" />}
          Compute GSTR-4 Annual
        </button>

        {computeError && <Callout tone="problem" title="Couldn't prepare GSTR-4 Annual">{computeError}</Callout>}

        {statement && (
          <div className="space-y-2">
            <p className="text-2xs text-ps-hint">{statement.financial_year} · {gstin}</p>

            <GapList gaps={findingGaps} tone="attention" title="Rows to review before filing" />
            <GapList gaps={statement.gaps} tone="note" title="What this return does not attempt" />

            <div className="overflow-x-auto">
              <table className="w-full text-2xs">
                <thead>
                  <tr className="text-ps-hint text-left border-b border-ps-border">
                    <th className="py-1.5 pr-3 font-semibold"></th>
                    <th className="py-1.5 font-semibold text-right">Taxable value</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-ps-border">
                    <td className="py-1.5 pr-3 text-ps-body">4A — registered, informational ({statement.b2b_supplies.length})</td>
                    <td className="py-1.5 text-right font-mono">{formatPaise(statement.b2b_total_taxable_paise)}</td>
                  </tr>
                  <tr>
                    <td className="py-1.5 pr-3 text-ps-body font-medium">Total liability (4B + 4C reverse-charge + 4D)</td>
                    <td className="py-1.5 text-right font-mono font-medium">{formatPaise(statement.liability_taxable_paise)}</td>
                  </tr>
                  <tr>
                    <td className="py-1.5 pr-3 text-ps-body">Tax on that liability</td>
                    <td className="py-1.5 text-right font-mono">{formatPaise(statement.liability_tax_paise)}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="pt-2 border-t border-ps-border">
              <h6 className="text-2xs font-semibold text-ps-body mb-1.5">Table 5 — the year&apos;s four CMP-08 statements, summed</h6>
              <div className="overflow-x-auto">
                <table className="w-full text-2xs">
                  <thead>
                    <tr className="text-ps-hint text-left border-b border-ps-border">
                      <th className="py-1.5 pr-3 font-semibold"></th>
                      <th className="py-1.5 pr-3 font-semibold text-right">Taxable value</th>
                      <th className="py-1.5 font-semibold text-right">Tax</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-ps-border">
                      <td className="py-1.5 pr-3 text-ps-body">Outward supplies</td>
                      <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(statement.table_5.outward_taxable_paise)}</td>
                      <td className="py-1.5 text-right font-mono">{formatPaise(statement.table_5.outward_tax_paise)}</td>
                    </tr>
                    <tr className="border-b border-ps-border">
                      <td className="py-1.5 pr-3 text-ps-body">Inward reverse-charge supplies</td>
                      <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(statement.table_5.inward_rcm_taxable_paise)}</td>
                      <td className="py-1.5 text-right font-mono">{formatPaise(statement.table_5.inward_rcm_tax_paise)}</td>
                    </tr>
                    <tr className="border-b border-ps-border">
                      <td className="py-1.5 pr-3 text-ps-body font-medium">Tax paid</td>
                      <td className="py-1.5 pr-3 text-right font-mono"></td>
                      <td className="py-1.5 text-right font-mono font-medium">{formatPaise(statement.table_5.tax_paid_paise)}</td>
                    </tr>
                    <tr>
                      <td className="py-1.5 pr-3 text-ps-body">Interest</td>
                      <td className="py-1.5 pr-3 text-right font-mono"></td>
                      <td className="py-1.5 text-right font-mono">{formatPaise(statement.table_5.interest_paise)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <GapList gaps={statement.table_5.gaps} tone="note" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function B2BTable({ rows, onRemove }: { rows: Gstr4AnnualB2BSupply[]; onRemove: (id: string) => void }) {
  if (rows.length === 0) return <p className="text-2xs text-ps-hint">No supply recorded for this year yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-2xs">
        <thead>
          <tr className="text-ps-hint text-left border-b border-ps-border">
            <th className="py-1.5 pr-2 font-semibold">Supplier GSTIN</th>
            <th className="py-1.5 pr-2 font-semibold">POS</th>
            <th className="py-1.5 pr-2 font-semibold text-right">Rate</th>
            <th className="py-1.5 pr-2 font-semibold text-right">Taxable value</th>
            <th className="py-1.5 pr-2 font-semibold text-right">Tax</th>
            <th className="py-1.5 font-semibold"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-ps-border last:border-0">
              <td className="py-1.5 pr-2 font-mono">{r.supplier_gstin}</td>
              <td className="py-1.5 pr-2 font-mono">{r.place_of_supply}</td>
              <td className="py-1.5 pr-2 text-right font-mono">{(r.rate_bps / 100).toFixed(2)}%</td>
              <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.taxable_value_paise)}</td>
              <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(r.igst_paise + r.cgst_paise + r.sgst_paise + r.cess_paise)}</td>
              <td className="py-1.5 text-right">
                <button onClick={() => onRemove(r.id)} title="Remove" className="text-state-problem hover:opacity-70">
                  <Trash2 size={12} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function B2BForm({ form, setForm, onAdd, saving }: {
  form: ReturnType<typeof emptyB2BForm>;
  setForm: React.Dispatch<React.SetStateAction<ReturnType<typeof emptyB2BForm>>>;
  onAdd: () => void;
  saving: boolean;
}) {
  return (
    <div className="border border-dashed border-ps-border rounded-lg p-2.5 space-y-2">
      <div className="flex flex-wrap gap-2">
        <label className="text-2xs">
          <span className="block text-ps-body font-medium mb-1">Supplier GSTIN</span>
          <input value={form.supplier_gstin}
            onChange={(e) => setForm((f) => ({ ...f, supplier_gstin: e.target.value.toUpperCase() }))}
            className="px-2 py-1 border border-ps-border rounded w-40 font-mono" maxLength={15} />
        </label>
        <label className="text-2xs">
          <span className="block text-ps-body font-medium mb-1">Place of supply</span>
          <select value={form.place_of_supply}
            onChange={(e) => setForm((f) => ({ ...f, place_of_supply: e.target.value }))}
            className="px-2 py-1 border border-ps-border rounded w-40">
            <option value="">—</option>
            {INDIAN_STATES.map((s) => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
          </select>
        </label>
        <label className="text-2xs">
          <span className="block text-ps-body font-medium mb-1">Rate (%)</span>
          <input value={form.rate} inputMode="decimal" placeholder="0"
            onChange={(e) => setForm((f) => ({ ...f, rate: e.target.value }))}
            className="px-2 py-1 border border-ps-border rounded w-16" />
        </label>
        {B2B_RUPEE_FIELDS.map(([key, label]) => (
          <label key={key} className="text-2xs">
            <span className="block text-ps-body font-medium mb-1">{label} (₹)</span>
            <input value={form[key]} inputMode="decimal" placeholder="0"
              onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
              className="px-2 py-1 border border-ps-border rounded w-24" />
          </label>
        ))}
      </div>
      <button onClick={onAdd} disabled={saving}
        className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
        {saving ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
        Add supply
      </button>
    </div>
  );
}
