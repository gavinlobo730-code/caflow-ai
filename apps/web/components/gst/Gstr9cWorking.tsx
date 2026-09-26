"use client";

/**
 * FORM GSTR-9C — the audited-books reconciliation statement (GST-25, part 4).
 *
 * CGST Act s.44, Rule 80(3): a registered person above the notified turnover
 * reconciles GSTR-9 against its own AUDITED FINANCIAL STATEMENTS. Almost
 * every figure here is CA-recorded — the audited books are not this
 * product's own ledger — so this screen is mostly a typed form, not a
 * computed report; `domain/gst/gstr9c.py` derives only a plain sum or a
 * plain subtraction of numbers already known, and reads the "declared" side
 * of every comparison from the GSTR-9 already built above.
 *
 * `threshold_table` and `self_certification_from_fy` are shown as REFERENCE
 * ONLY — this screen never decides whether a client must file this return.
 *
 * Prepare-only. Nothing here is transmitted to any portal.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, Trash2, Plus, ChevronDown, ChevronRight, Calculator } from "lucide-react";
import {
  api,
  type Gstr9cWorking as Working,
  type Gstr9cRateWiseLine,
  type Gstr9cExpenseLine,
} from "@/lib/api";
import { Callout, GapList } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { objectOrNull, arrayOrEmpty } from "@/lib/api/shape";

function money(paise: number | null | undefined): string {
  return paise == null ? "—" : formatPaise(paise);
}

function Section({ title, subtitle, children, defaultOpen }: {
  title: string; subtitle: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
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

type MoneyKey =
  | "turnover_per_audited_fs_paise" | "unbilled_revenue_begin_paise"
  | "unadjusted_advances_end_paise" | "deemed_supply_paise"
  | "credit_notes_issued_post_fy_paise" | "trade_discount_not_permissible_paise"
  | "unbilled_revenue_end_paise" | "unadjusted_advances_begin_paise"
  | "credit_notes_in_fs_not_permissible_paise" | "sez_dta_adjustment_paise"
  | "composition_period_turnover_paise" | "section_15_adjustment_paise"
  | "forex_adjustment_paise" | "other_turnover_adjustment_paise"
  | "turnover_after_adjustments_paise"
  | "exempt_nil_nongst_turnover_paise" | "zero_rated_no_tax_turnover_paise"
  | "reverse_charge_turnover_paise" | "ecommerce_9_5_turnover_paise"
  | "taxable_turnover_after_adjustments_paise"
  | "itc_per_audited_fs_paise" | "itc_booked_earlier_fy_claimed_this_fy_paise"
  | "itc_booked_this_fy_claimed_later_fy_paise"
  | "unreconciled_itc_tax_igst_paise" | "unreconciled_itc_tax_cgst_paise"
  | "unreconciled_itc_tax_sgst_paise" | "unreconciled_itc_tax_cess_paise"
  | "unreconciled_itc_interest_paise" | "unreconciled_itc_penalty_paise";

type ReasonsKey = "turnover_reasons" | "taxable_turnover_reasons" | "itc_reasons" | "itc_reasons_16";

function emptyForm(): Record<MoneyKey, string> & Record<ReasonsKey, string> & { act_name: string } {
  return {
    act_name: "",
    turnover_per_audited_fs_paise: "", unbilled_revenue_begin_paise: "",
    unadjusted_advances_end_paise: "", deemed_supply_paise: "",
    credit_notes_issued_post_fy_paise: "", trade_discount_not_permissible_paise: "",
    unbilled_revenue_end_paise: "", unadjusted_advances_begin_paise: "",
    credit_notes_in_fs_not_permissible_paise: "", sez_dta_adjustment_paise: "",
    composition_period_turnover_paise: "", section_15_adjustment_paise: "",
    forex_adjustment_paise: "", other_turnover_adjustment_paise: "",
    turnover_after_adjustments_paise: "",
    exempt_nil_nongst_turnover_paise: "", zero_rated_no_tax_turnover_paise: "",
    reverse_charge_turnover_paise: "", ecommerce_9_5_turnover_paise: "",
    taxable_turnover_after_adjustments_paise: "",
    itc_per_audited_fs_paise: "", itc_booked_earlier_fy_claimed_this_fy_paise: "",
    itc_booked_this_fy_claimed_later_fy_paise: "",
    unreconciled_itc_tax_igst_paise: "", unreconciled_itc_tax_cgst_paise: "",
    unreconciled_itc_tax_sgst_paise: "", unreconciled_itc_tax_cess_paise: "",
    unreconciled_itc_interest_paise: "", unreconciled_itc_penalty_paise: "",
    turnover_reasons: "", taxable_turnover_reasons: "", itc_reasons: "", itc_reasons_16: "",
  };
}

const TABLE5_FIELDS: [MoneyKey, string][] = [
  ["turnover_per_audited_fs_paise", "5A · Turnover per audited financial statements"],
  ["unbilled_revenue_begin_paise", "5B · Unbilled revenue at the beginning of the year"],
  ["unadjusted_advances_end_paise", "5C · Unadjusted advances at the end of the year"],
  ["deemed_supply_paise", "5D · Deemed supply under Schedule I"],
  ["credit_notes_issued_post_fy_paise", "5E · Credit notes issued after the end of the FY, reflected in the annual return"],
  ["trade_discount_not_permissible_paise", "5F · Trade discounts in the accounts, not permissible under GST"],
  ["unbilled_revenue_end_paise", "5H · Unbilled revenue at the end of the year"],
  ["unadjusted_advances_begin_paise", "5I · Unadjusted advances at the beginning of the year"],
  ["credit_notes_in_fs_not_permissible_paise", "5J · Credit notes in the accounts, not permissible under GST"],
  ["sez_dta_adjustment_paise", "5K · Adjustment on account of supply by SEZ units to DTA units"],
  ["composition_period_turnover_paise", "5L · Turnover for the period under the composition scheme"],
  ["section_15_adjustment_paise", "5M · Adjustments under s.15 and the rules"],
  ["forex_adjustment_paise", "5N · Adjustments due to foreign exchange fluctuations"],
  ["other_turnover_adjustment_paise", "5O · Adjustments due to reasons not listed above"],
];

const TABLE12_FIELDS: [MoneyKey, string][] = [
  ["itc_per_audited_fs_paise", "12A · ITC availed per the audited financial statements"],
  ["itc_booked_earlier_fy_claimed_this_fy_paise", "12B · Booked in earlier years, claimed in this year"],
  ["itc_booked_this_fy_claimed_later_fy_paise", "12C · Booked this year, to be claimed in a later year"],
];

const TABLE16_FIELDS: [MoneyKey, string][] = [
  ["unreconciled_itc_tax_igst_paise", "IGST"],
  ["unreconciled_itc_tax_cgst_paise", "CGST"],
  ["unreconciled_itc_tax_sgst_paise", "SGST"],
  ["unreconciled_itc_tax_cess_paise", "Cess"],
  ["unreconciled_itc_interest_paise", "Interest"],
  ["unreconciled_itc_penalty_paise", "Penalty"],
];

function MoneyRow({ label, value, onChange }: {
  label: string; value: string; onChange: (v: string) => void;
}) {
  return (
    <label className="text-2xs flex items-center justify-between gap-3 py-1">
      <span className="text-ps-body flex-1">{label}</span>
      <input value={value} inputMode="decimal" placeholder="not recorded"
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1 border border-ps-border rounded w-32 text-right" />
    </label>
  );
}

export default function Gstr9cWorking({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [statement, setStatement] = useState<Working | null>(null);
  const [computing, setComputing] = useState(false);
  const [computeError, setComputeError] = useState<string | null>(null);

  const [form, setForm] = useState(emptyForm());
  const [reconciliationId, setReconciliationId] = useState<string | null>(null);
  const [loadingRecon, setLoadingRecon] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [rateWiseLines, setRateWiseLines] = useState<Record<string, Gstr9cRateWiseLine[]>>(
    { "9": [], "11": [], "partv": [] });
  const [expenseLines, setExpenseLines] = useState<Gstr9cExpenseLine[]>([]);

  const loadReconciliation = useCallback(async () => {
    setLoadingRecon(true);
    try {
      const res = await api.gstr9c.getReconciliation(clientId, financialYear);
      const row = objectOrNull<Record<string, unknown>>(res.success ? res.data : null);
      if (row) {
        setReconciliationId(String(row.id));
        setForm({
          act_name: (row.act_name as string) ?? "",
          ...Object.fromEntries(([...TABLE5_FIELDS, ...TABLE12_FIELDS, ...TABLE16_FIELDS,
            ["exempt_nil_nongst_turnover_paise", ""], ["zero_rated_no_tax_turnover_paise", ""],
            ["reverse_charge_turnover_paise", ""], ["ecommerce_9_5_turnover_paise", ""],
            ["turnover_after_adjustments_paise", ""],
            ["taxable_turnover_after_adjustments_paise", ""]] as [MoneyKey, string][])
            .map(([k]) => [k, row[k] != null ? String((row[k] as number) / 100) : ""])),
          turnover_reasons: arrayOrEmpty<string>(row.turnover_reasons).join("\n"),
          taxable_turnover_reasons: arrayOrEmpty<string>(row.taxable_turnover_reasons).join("\n"),
          itc_reasons: arrayOrEmpty<string>(row.itc_reasons).join("\n"),
          itc_reasons_16: arrayOrEmpty<string>(row.itc_reasons_16).join("\n"),
        } as ReturnType<typeof emptyForm>);
        const [t9, t11, tpv] = await Promise.all([
          api.gstr9c.listRateWiseLines(clientId, String(row.id), "9"),
          api.gstr9c.listRateWiseLines(clientId, String(row.id), "11"),
          api.gstr9c.listRateWiseLines(clientId, String(row.id), "partv"),
        ]);
        setRateWiseLines({
          "9": arrayOrEmpty<Gstr9cRateWiseLine>(t9.success ? t9.data : null),
          "11": arrayOrEmpty<Gstr9cRateWiseLine>(t11.success ? t11.data : null),
          "partv": arrayOrEmpty<Gstr9cRateWiseLine>(tpv.success ? tpv.data : null),
        });
        const exp = await api.gstr9c.listExpenseLines(clientId, String(row.id));
        setExpenseLines(arrayOrEmpty<Gstr9cExpenseLine>(exp.success ? exp.data : null));
      } else {
        setReconciliationId(null);
        setForm(emptyForm());
        setRateWiseLines({ "9": [], "11": [], "partv": [] });
        setExpenseLines([]);
      }
    } finally {
      setLoadingRecon(false);
    }
  }, [clientId, financialYear]);

  useEffect(() => {
    setStatement(null);
    loadReconciliation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [financialYear]);

  const save = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const parsed: Record<string, unknown> = {
        client_id: clientId, financial_year: financialYear,
        act_name: form.act_name || null,
        turnover_reasons: form.turnover_reasons.split("\n").map((s) => s.trim()).filter(Boolean),
        taxable_turnover_reasons: form.taxable_turnover_reasons.split("\n").map((s) => s.trim()).filter(Boolean),
        itc_reasons: form.itc_reasons.split("\n").map((s) => s.trim()).filter(Boolean),
        itc_reasons_16: form.itc_reasons_16.split("\n").map((s) => s.trim()).filter(Boolean),
      };
      for (const [key] of [...TABLE5_FIELDS, ...TABLE12_FIELDS, ...TABLE16_FIELDS,
        ["exempt_nil_nongst_turnover_paise"], ["zero_rated_no_tax_turnover_paise"],
        ["reverse_charge_turnover_paise"], ["ecommerce_9_5_turnover_paise"],
        ["turnover_after_adjustments_paise"],
        ["taxable_turnover_after_adjustments_paise"]] as [MoneyKey][]) {
        const raw = form[key];
        if (!raw.trim()) { parsed[key] = null; continue; }
        const paise = paiseFromRupeeInput(raw);
        if (paise === null) { setSaveError(`"${raw}" is not an amount.`); setSaving(false); return; }
        parsed[key] = paise;
      }
      const res = await api.gstr9c.saveReconciliation(parsed as Parameters<typeof api.gstr9c.saveReconciliation>[0]);
      if (!res.success) { setSaveError(res.error ?? "Couldn't save."); return; }
      setReconciliationId(String((res.data as Record<string, unknown>).id));
      setStatement(null);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }, [clientId, financialYear, form]);

  const compute = useCallback(async () => {
    setComputing(true);
    setComputeError(null);
    try {
      const res = await api.gstr9c.compute(clientId, financialYear);
      setStatement(objectOrNull<Working>(res.success ? res.data : null));
      if (!res.success) setComputeError(res.error ?? "Couldn't prepare GSTR-9C.");
    } catch (e) {
      setStatement(null);
      setComputeError(e instanceof Error ? e.message : "Couldn't prepare GSTR-9C.");
    } finally {
      setComputing(false);
    }
  }, [clientId, financialYear]);

  const isEcommerceYear = parseInt(financialYear.slice(0, 4), 10) >= 2024;

  return (
    <div className="mt-2 border border-ps-border rounded-lg p-3 space-y-4 bg-ps-bg/40">
      <div>
        <h5 className="text-xs font-semibold text-ps-ink">Prepare FORM GSTR-9C</h5>
        <p className="text-3xs text-ps-hint mt-0.5">
          CGST Act s.44, Rule 80(3) — the reconciliation between this year&apos;s
          annual return and the client&apos;s own audited financial statements.
          Almost every figure below is yours to record; this screen sums and
          subtracts what it can and reads the declared side from GSTR-9 above.
        </p>
      </div>

      {loadingRecon && <p className="text-2xs text-ps-hint inline-flex items-center gap-1"><Loader2 size={11} className="animate-spin" /> Loading…</p>}
      {saveError && <Callout tone="problem">{saveError}</Callout>}

      <label className="text-2xs block w-fit">
        <span className="block text-ps-body font-medium mb-1">Act under which audited</span>
        <input value={form.act_name} placeholder="e.g. Companies Act, 2013"
          onChange={(e) => setForm((f) => ({ ...f, act_name: e.target.value }))}
          className="px-2 py-1 border border-ps-border rounded w-56" />
      </label>

      <Section title="Table 5 — Reconciliation of Gross Turnover" subtitle="5A-5O are your own figures from the audited accounts; 5P is your own worked total." defaultOpen>
        {TABLE5_FIELDS.map(([key, label]) => (
          <MoneyRow key={key} label={label} value={form[key]}
            onChange={(v) => setForm((f) => ({ ...f, [key]: v }))} />
        ))}
        <div className="border-t border-ps-border pt-1.5 mt-1.5">
          <MoneyRow label="5P · Turnover after adjustments (your own total of 5A-5O)"
            value={form.turnover_after_adjustments_paise}
            onChange={(v) => setForm((f) => ({ ...f, turnover_after_adjustments_paise: v }))} />
        </div>
        <label className="text-2xs block">
          <span className="block text-ps-body font-medium mb-1">Table 6 — reasons for the un-reconciled turnover</span>
          <textarea value={form.turnover_reasons} rows={2}
            onChange={(e) => setForm((f) => ({ ...f, turnover_reasons: e.target.value }))}
            placeholder="One reason per line" className="w-full px-2 py-1 border border-ps-border rounded" />
        </label>
      </Section>

      <Section title="Table 7 — Reconciliation of Taxable Turnover" subtitle="7A is 5P carried forward; 7B-7D and 7E are your own figures.">
        <MoneyRow label="7B · Exempted, nil-rated, non-GST, no-supply turnover"
          value={form.exempt_nil_nongst_turnover_paise}
          onChange={(v) => setForm((f) => ({ ...f, exempt_nil_nongst_turnover_paise: v }))} />
        <MoneyRow label="7C · Zero-rated supplies without payment of tax"
          value={form.zero_rated_no_tax_turnover_paise}
          onChange={(v) => setForm((f) => ({ ...f, zero_rated_no_tax_turnover_paise: v }))} />
        <MoneyRow label="7D · Supplies taxed on reverse charge by the recipient"
          value={form.reverse_charge_turnover_paise}
          onChange={(v) => setForm((f) => ({ ...f, reverse_charge_turnover_paise: v }))} />
        {isEcommerceYear && (
          <MoneyRow label="7D(ecom) · Supplies through an e-commerce operator, s.9(5)"
            value={form.ecommerce_9_5_turnover_paise}
            onChange={(v) => setForm((f) => ({ ...f, ecommerce_9_5_turnover_paise: v }))} />
        )}
        <div className="border-t border-ps-border pt-1.5 mt-1.5">
          <MoneyRow label="7E · Taxable turnover after adjustments (your own total)"
            value={form.taxable_turnover_after_adjustments_paise}
            onChange={(v) => setForm((f) => ({ ...f, taxable_turnover_after_adjustments_paise: v }))} />
        </div>
        <label className="text-2xs block">
          <span className="block text-ps-body font-medium mb-1">Table 8 — reasons for the un-reconciled taxable turnover</span>
          <textarea value={form.taxable_turnover_reasons} rows={2}
            onChange={(e) => setForm((f) => ({ ...f, taxable_turnover_reasons: e.target.value }))}
            placeholder="One reason per line" className="w-full px-2 py-1 border border-ps-border rounded" />
        </label>
      </Section>

      <RateWiseSection title="Table 9 — Reconciliation of Rate-wise Liability" tableRef="9"
        clientId={clientId} reconciliationId={reconciliationId}
        lines={rateWiseLines["9"]} onChange={(rows) => setRateWiseLines((r) => ({ ...r, "9": rows }))} />

      <RateWiseSection title="Table 11 — Additional Amount Payable but Not Paid" tableRef="11"
        clientId={clientId} reconciliationId={reconciliationId}
        lines={rateWiseLines["11"]} onChange={(rows) => setRateWiseLines((r) => ({ ...r, "11": rows }))} />

      <Section title="Table 12 — Reconciliation of Net Input Tax Credit" subtitle="12A-12C are your own figures; 12D, 12E and 12F are computed.">
        {TABLE12_FIELDS.map(([key, label]) => (
          <MoneyRow key={key} label={label} value={form[key]}
            onChange={(v) => setForm((f) => ({ ...f, [key]: v }))} />
        ))}
        <label className="text-2xs block">
          <span className="block text-ps-body font-medium mb-1">Table 13 — reasons for the un-reconciled ITC</span>
          <textarea value={form.itc_reasons} rows={2}
            onChange={(e) => setForm((f) => ({ ...f, itc_reasons: e.target.value }))}
            placeholder="One reason per line" className="w-full px-2 py-1 border border-ps-border rounded" />
        </label>
      </Section>

      <ExpenseSection clientId={clientId} reconciliationId={reconciliationId}
        lines={expenseLines} onChange={setExpenseLines} />

      <Section title="Table 16 — Tax Payable on Un-reconciled ITC" subtitle="One figure per head, plus interest and penalty — all your own.">
        {TABLE16_FIELDS.map(([key, label]) => (
          <MoneyRow key={key} label={label} value={form[key]}
            onChange={(v) => setForm((f) => ({ ...f, [key]: v }))} />
        ))}
        <label className="text-2xs block">
          <span className="block text-ps-body font-medium mb-1">Table 15 — reasons for the un-reconciled ITC (Table 16)</span>
          <textarea value={form.itc_reasons_16} rows={2}
            onChange={(e) => setForm((f) => ({ ...f, itc_reasons_16: e.target.value }))}
            placeholder="One reason per line" className="w-full px-2 py-1 border border-ps-border rounded" />
        </label>
      </Section>

      <RateWiseSection title="Part V — Additional Liability Due to Non-Reconciliation" tableRef="partv"
        clientId={clientId} reconciliationId={reconciliationId}
        lines={rateWiseLines["partv"]} onChange={(rows) => setRateWiseLines((r) => ({ ...r, "partv": rows }))} />

      <div className="flex items-center gap-2">
        <button onClick={save} disabled={saving}
          className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
          {saving && <Loader2 size={11} className="animate-spin" />}
          Save reconciliation
        </button>
        {!reconciliationId && (
          <span className="text-3xs text-ps-hint">
            Save once to record the Table 9/11/14/Part V rows below it.
          </span>
        )}
      </div>

      {/* ── Compute ──────────────────────────────────────────────────────── */}
      <div className="pt-2 border-t border-ps-border space-y-2">
        <button onClick={compute} disabled={computing}
          className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
          {computing ? <Loader2 size={11} className="animate-spin" /> : <Calculator size={11} />}
          Prepare GSTR-9C
        </button>

        {computeError && <Callout tone="problem" title="Couldn't prepare GSTR-9C">{computeError}</Callout>}

        {statement && (
          <div className="space-y-3">
            <p className="text-2xs text-ps-hint">{statement.financial_year} · {statement.gstin}</p>

            <GapList gaps={statement.gaps} tone="withheld" title="What this working does not derive" />

            <div className="overflow-x-auto">
              <table className="w-full text-2xs">
                <thead>
                  <tr className="text-ps-hint text-left border-b border-ps-border">
                    <th className="py-1.5 pr-3 font-semibold"></th>
                    <th className="py-1.5 font-semibold text-right">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">5Q · Turnover declared in the Annual Return (from GSTR-9)</td><td className="py-1.5 text-right font-mono">{money(statement.table5.declared_turnover_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3 font-medium">5R · Un-reconciled turnover (5P − 5Q)</td><td className="py-1.5 text-right font-mono font-medium">{money(statement.table5.unreconciled_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">7F · Taxable turnover declared in the Annual Return (from GSTR-9)</td><td className="py-1.5 text-right font-mono">{money(statement.table7.declared_taxable_turnover_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3 font-medium">7G · Un-reconciled taxable turnover (7E − 7F)</td><td className="py-1.5 text-right font-mono font-medium">{money(statement.table7.unreconciled_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">Table 9 total payable (rate-wise + tail rows)</td><td className="py-1.5 text-right font-mono">{money((statement.table9.total_payable_paise?.igst_paise ?? 0) + (statement.table9.total_payable_paise?.cgst_paise ?? 0) + (statement.table9.total_payable_paise?.sgst_paise ?? 0) + (statement.table9.total_payable_paise?.cess_paise ?? 0))}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">Table 9 · amount paid, as declared (GSTR-9, row 9d)</td><td className="py-1.5 text-right font-mono">{money(statement.table9.declared_tax_paid_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">Table 11 total (additional amount payable but not paid)</td><td className="py-1.5 text-right font-mono">{money((statement.table11.total_paise?.igst_paise ?? 0) + (statement.table11.total_paise?.cgst_paise ?? 0) + (statement.table11.total_paise?.sgst_paise ?? 0) + (statement.table11.total_paise?.cess_paise ?? 0))}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">12D · ITC per audited books, adjusted (12A + 12B − 12C)</td><td className="py-1.5 text-right font-mono">{money(statement.table12.audited_adjusted_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">12E · ITC claimed per Annual Return (GSTR-9 Table 6O)</td><td className="py-1.5 text-right font-mono">{money(statement.table12.itc_claim_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3 text-ps-hint">— alternate: GSTR-9 Table 7J (Net ITC available)</td><td className="py-1.5 text-right font-mono text-ps-hint">{money(statement.table12.itc_claim_alternate_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3 font-medium">12F · Un-reconciled ITC (12D − 12E)</td><td className="py-1.5 text-right font-mono font-medium">{money(statement.table12.unreconciled_paise)}</td></tr>
                  <tr className="border-b border-ps-border"><td className="py-1.5 pr-3">14R · Total eligible ITC availed on expenses (sum of what is recorded)</td><td className="py-1.5 text-right font-mono">{money(statement.table14.total_eligible_itc_availed_paise)}</td></tr>
                  <tr><td className="py-1.5 pr-3 font-medium">14T · Un-reconciled ITC (14R − 14S)</td><td className="py-1.5 text-right font-mono font-medium">{money(statement.table14.unreconciled_paise)}</td></tr>
                </tbody>
              </table>
            </div>

            <details className="text-2xs">
              <summary className="cursor-pointer text-ps-hint">Reference — when this return is required (never decided by this screen)</summary>
              <table className="w-full text-2xs mt-1.5">
                <tbody>
                  {statement.threshold_table.map((t, i) => (
                    <tr key={i} className="border-b border-ps-border last:border-0">
                      <td className="py-1 pr-3">{t.label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-3xs text-ps-hint mt-1">
                Self-certification (no CA/CMA sign-off recorded in the return) applies from
                FY {statement.self_certification_from_fy} onward.
                {!statement.gstr9c_verified && " These figures are not independently verified against a primary source in this environment."}
              </p>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

function RateWiseSection({ title, tableRef, clientId, reconciliationId, lines, onChange }: {
  title: string; tableRef: "9" | "11" | "partv"; clientId: string;
  reconciliationId: string | null; lines: Gstr9cRateWiseLine[];
  onChange: (rows: Gstr9cRateWiseLine[]) => void;
}) {
  const [desc, setDesc] = useState("");
  const [taxable, setTaxable] = useState("");
  const [igst, setIgst] = useState("");
  const [cgst, setCgst] = useState("");
  const [sgst, setSgst] = useState("");
  const [cess, setCess] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = useCallback(async () => {
    if (!reconciliationId) return;
    if (!desc.trim()) { setError("A description is required (e.g. \"5%\", \"Interest\")."); return; }
    const t = paiseFromRupeeInput(taxable || "0");
    const i = paiseFromRupeeInput(igst || "0");
    const c = paiseFromRupeeInput(cgst || "0");
    const s = paiseFromRupeeInput(sgst || "0");
    const cs = paiseFromRupeeInput(cess || "0");
    if ([t, i, c, s, cs].some((v) => v === null)) { setError("Enter valid amounts."); return; }
    setSaving(true);
    setError(null);
    try {
      const res = await api.gstr9c.addRateWiseLine({
        client_id: clientId, reconciliation_id: reconciliationId, table_ref: tableRef,
        rate_description: desc.trim(), taxable_value_paise: t ?? 0, igst_paise: i ?? 0,
        cgst_paise: c ?? 0, sgst_paise: s ?? 0, cess_paise: cs ?? 0,
      });
      if (!res.success) { setError(res.error ?? "Couldn't add this row."); return; }
      onChange([...lines, res.data as Gstr9cRateWiseLine]);
      setDesc(""); setTaxable(""); setIgst(""); setCgst(""); setSgst(""); setCess("");
    } finally {
      setSaving(false);
    }
  }, [reconciliationId, desc, taxable, igst, cgst, sgst, cess, clientId, tableRef, lines, onChange]);

  const remove = useCallback(async (id: string) => {
    await api.gstr9c.deleteRateWiseLine(id, clientId);
    onChange(lines.filter((l) => l.id !== id));
  }, [clientId, lines, onChange]);

  return (
    <Section title={title} subtitle="Rate-wise rows, plus interest/late fee/penalty/other as their own rows.">
      {!reconciliationId ? (
        <p className="text-2xs text-ps-hint">Save the reconciliation above first.</p>
      ) : (
        <>
          {lines.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-2xs">
                <thead>
                  <tr className="text-ps-hint text-left border-b border-ps-border">
                    <th className="py-1.5 pr-2 font-semibold">Description</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">Taxable value</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">IGST</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">CGST</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">SGST</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">Cess</th>
                    <th className="py-1.5 font-semibold"></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l) => (
                    <tr key={l.id} className="border-b border-ps-border last:border-0">
                      <td className="py-1.5 pr-2">{l.rate_description}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.taxable_value_paise)}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.igst_paise)}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.cgst_paise)}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.sgst_paise)}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.cess_paise)}</td>
                      <td className="py-1.5 text-right">
                        <button onClick={() => l.id && remove(l.id)} title="Remove" className="text-state-problem hover:opacity-70">
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {error && <Callout tone="problem">{error}</Callout>}
          <div className="flex flex-wrap gap-2 items-end">
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Description</span>
              <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="5% / Interest / Others"
                className="px-2 py-1 border border-ps-border rounded w-32" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Taxable value (₹)</span>
              <input value={taxable} inputMode="decimal" placeholder="0" onChange={(e) => setTaxable(e.target.value)}
                className="px-2 py-1 border border-ps-border rounded w-24" />
            </label>
            {(["IGST", "CGST", "SGST", "Cess"] as const).map((h, i) => {
              const [v, setV] = [[igst, setIgst], [cgst, setCgst], [sgst, setSgst], [cess, setCess]][i] as [string, (v: string) => void];
              return (
                <label key={h} className="text-2xs">
                  <span className="block text-ps-body font-medium mb-1">{h} (₹)</span>
                  <input value={v} inputMode="decimal" placeholder="0" onChange={(e) => setV(e.target.value)}
                    className="px-2 py-1 border border-ps-border rounded w-20" />
                </label>
              );
            })}
            <button onClick={add} disabled={saving}
              className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
              {saving ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
              Add row
            </button>
          </div>
        </>
      )}
    </Section>
  );
}

function ExpenseSection({ clientId, reconciliationId, lines, onChange }: {
  clientId: string; reconciliationId: string | null; lines: Gstr9cExpenseLine[];
  onChange: (rows: Gstr9cExpenseLine[]) => void;
}) {
  const [head, setHead] = useState("");
  const [value, setValue] = useState("");
  const [totalItc, setTotalItc] = useState("");
  const [eligible, setEligible] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = useCallback(async () => {
    if (!reconciliationId) return;
    if (!head.trim()) { setError("An expense head is required."); return; }
    const v = paiseFromRupeeInput(value || "0");
    const ti = paiseFromRupeeInput(totalItc || "0");
    const e = paiseFromRupeeInput(eligible || "0");
    if ([v, ti, e].some((x) => x === null)) { setError("Enter valid amounts."); return; }
    setSaving(true);
    setError(null);
    try {
      const res = await api.gstr9c.addExpenseLine({
        client_id: clientId, reconciliation_id: reconciliationId, expense_head: head.trim(),
        value_paise: v ?? 0, total_itc_paise: ti ?? 0, eligible_itc_availed_paise: e ?? 0,
      });
      if (!res.success) { setError(res.error ?? "Couldn't add this row."); return; }
      onChange([...lines, res.data as Gstr9cExpenseLine]);
      setHead(""); setValue(""); setTotalItc(""); setEligible("");
    } finally {
      setSaving(false);
    }
  }, [reconciliationId, head, value, totalItc, eligible, clientId, lines, onChange]);

  const remove = useCallback(async (id: string) => {
    await api.gstr9c.deleteExpenseLine(id, clientId);
    onChange(lines.filter((l) => l.id !== id));
  }, [clientId, lines, onChange]);

  return (
    <Section title="Table 14 — ITC on Expenses per Audited Financial Statements"
      subtitle="No auto-fill: this product's chart of accounts does not classify by these expense heads. Record each one directly.">
      {!reconciliationId ? (
        <p className="text-2xs text-ps-hint">Save the reconciliation above first.</p>
      ) : (
        <>
          {lines.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-2xs">
                <thead>
                  <tr className="text-ps-hint text-left border-b border-ps-border">
                    <th className="py-1.5 pr-2 font-semibold">Expense head</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">Value</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">Total ITC</th>
                    <th className="py-1.5 pr-2 font-semibold text-right">Eligible ITC availed</th>
                    <th className="py-1.5 font-semibold"></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l) => (
                    <tr key={l.id} className="border-b border-ps-border last:border-0">
                      <td className="py-1.5 pr-2">{l.expense_head}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.value_paise)}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.total_itc_paise)}</td>
                      <td className="py-1.5 pr-2 text-right font-mono">{formatPaise(l.eligible_itc_availed_paise)}</td>
                      <td className="py-1.5 text-right">
                        <button onClick={() => l.id && remove(l.id)} title="Remove" className="text-state-problem hover:opacity-70">
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {error && <Callout tone="problem">{error}</Callout>}
          <div className="flex flex-wrap gap-2 items-end">
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Expense head</span>
              <input value={head} onChange={(e) => setHead(e.target.value)} placeholder="Purchases / Freight / …"
                className="px-2 py-1 border border-ps-border rounded w-40" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Value (₹)</span>
              <input value={value} inputMode="decimal" placeholder="0" onChange={(e) => setValue(e.target.value)}
                className="px-2 py-1 border border-ps-border rounded w-24" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Total ITC (₹)</span>
              <input value={totalItc} inputMode="decimal" placeholder="0" onChange={(e) => setTotalItc(e.target.value)}
                className="px-2 py-1 border border-ps-border rounded w-24" />
            </label>
            <label className="text-2xs">
              <span className="block text-ps-body font-medium mb-1">Eligible ITC availed (₹)</span>
              <input value={eligible} inputMode="decimal" placeholder="0" onChange={(e) => setEligible(e.target.value)}
                className="px-2 py-1 border border-ps-border rounded w-24" />
            </label>
            <button onClick={add} disabled={saving}
              className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
              {saving ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
              Add row
            </button>
          </div>
        </>
      )}
    </Section>
  );
}
