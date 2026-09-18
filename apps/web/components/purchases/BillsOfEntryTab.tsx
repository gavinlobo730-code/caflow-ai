"use client";

/**
 * Bills of Entry — the customs assessment on an import of goods (PUR-18).
 *
 * WHAT WAS MISSING
 *   IGST on imported goods is paid to CUSTOMS against a Bill of Entry, not to
 *   the supplier: IGST Act s.5(1)'s proviso puts the levy under Customs Tariff
 *   Act s.3(7), collected under the Customs Act. It is often the largest single
 *   ITC item of an importer's month, and there was no document that could carry
 *   it. Putting it on the vendor's purchase bill overstates Trade Payables by
 *   the whole of it; leaving it off loses the credit — and GSTR-3B Table
 *   4(A)(1) filed NIL against a GSTR-2B whose own `impg` section shows the
 *   Bill of Entry.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Which figure is input tax and which
 * is cost — CGST Act s.2(62)(a) against AS-2 paragraph 6 — is
 * `domain/gst/bill_of_entry.py`'s answer. Every derived total, every refusal
 * and every caveat below comes off the wire, and the two citations are served
 * by /api/bills-of-entry/authorities rather than written here.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, X, AlertTriangle, Info, Ship, Trash2 } from "lucide-react";
import { api, type BillOfEntry, type BillOfEntryAuthorities } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { AccountLookup, type AccountLike } from "@/components/lookups/AccountLookup";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { todayLocalISO } from "@/lib/dateMath";

type Msg = { type: "ok" | "err"; text: string } | null;

const BLANK = {
  be_number: "",
  be_date: todayLocalISO(),
  port_code: "",
  assessable_value: "",
  basic_customs_duty: "",
  social_welfare_surcharge: "",
  other_duty: "",
  igst: "",
  cess: "",
  ineligible_igst: "",
  ineligible_cess: "",
  is_sez: false,
  payment_account_id: "",
  duty_expense_account_id: "",
  notes: "",
};

export function BillsOfEntryTab({ clientId, openDoc }:
    { clientId: string;
      /** ACC-22 — the bill of entry a ledger drill-through arrived at. */
      openDoc?: string | null }) {
  const [rows, setRows] = useState<BillOfEntry[]>([]);
  const [accounts, setAccounts] = useState<AccountLike[]>([]);
  const [authorities, setAuthorities] = useState<BillOfEntryAuthorities | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [postingId, setPostingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg>(null);

  // One action at a time — every button that starts a write waits for
  // whichever is already running.
  const busy = saving || postingId !== null || deletingId !== null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.billsOfEntry.list({ client_id: clientId });
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't read the register.");
      setRows(res.data);
      setLoadFailed(false);
    } catch {
      // Swallowed, a failed fetch renders as "no bills of entry yet", which on
      // this tab is an invitation to re-enter documents that exist.
      setRows([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    let alive = true;
    api.billsOfEntry.authorities()
      .then((r) => { if (alive && r.success && r.data) setAuthorities(r.data); })
      .catch(() => { /* the citations simply do not render */ });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const supabase = getSupabaseClient();
      const { data } = await selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type, account_subtype, is_active, client_id")
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .eq("is_active", true)
        .order("account_code")
        .order("id"));
      if (alive) setAccounts((data as AccountLike[]) ?? []);
    })();
    return () => { alive = false; };
  }, [clientId]);

  const totals = useMemo(() => rows.reduce((acc, r) => ({
    credit: acc.credit + r.creditable_igst_paise + r.creditable_cess_paise,
    cost: acc.cost + r.non_creditable_duty_paise,
    paid: acc.paid + r.total_paise,
  }), { credit: 0, cost: 0, paid: 0 }), [rows]);

  async function handleSave() {
    if (!form.be_number.trim()) {
      setMsg({ type: "err", text: "The Bill of Entry number is required." });
      return;
    }
    // Every amount through the one parser. `parseFloat("1,25,000")` is 1.
    const fields: [keyof typeof BLANK, string][] = [
      ["assessable_value", "Assessable value"],
      ["basic_customs_duty", "Basic customs duty"],
      ["social_welfare_surcharge", "Social welfare surcharge"],
      ["other_duty", "Other duties"],
      ["igst", "IGST"],
      ["cess", "Compensation cess"],
      ["ineligible_igst", "Blocked IGST"],
      ["ineligible_cess", "Blocked cess"],
    ];
    const paise: Record<string, number> = {};
    for (const [key, label] of fields) {
      const typed = String(form[key] ?? "").trim();
      const p = paiseFromRupeeInput(typed || "0");
      if (p === null) {
        setMsg({ type: "err", text: `${label} must be an amount in rupees, e.g. 125000 or 125000.50 — without commas.` });
        return;
      }
      paise[key] = p;
    }

    setSaving(true);
    setMsg(null);
    try {
      const res = await api.billsOfEntry.create({
        client_id: clientId,
        be_number: form.be_number.trim(),
        be_date: form.be_date,
        port_code: form.port_code.trim() || null,
        assessable_value_paise: paise.assessable_value,
        basic_customs_duty_paise: paise.basic_customs_duty,
        social_welfare_surcharge_paise: paise.social_welfare_surcharge,
        other_duty_paise: paise.other_duty,
        igst_paise: paise.igst,
        cess_paise: paise.cess,
        ineligible_igst_paise: paise.ineligible_igst,
        ineligible_cess_paise: paise.ineligible_cess,
        is_sez: form.is_sez,
        payment_account_id: form.payment_account_id || null,
        duty_expense_account_id: form.duty_expense_account_id || null,
        notes: form.notes.trim() || null,
      });
      if (!res.success) throw new Error(res.error ?? "Couldn't save the Bill of Entry.");
      setShowForm(false);
      setForm(BLANK);
      setMsg({ type: "ok", text: "Bill of Entry saved. Check the figures, then post it." });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't save the Bill of Entry." });
    } finally {
      setSaving(false);
    }
  }

  async function handlePost(r: BillOfEntry) {
    const ok = await confirmDialog({
      title: `Post Bill of Entry ${r.be_number}?`,
      message: "This writes the journal: the creditable tax to input credit, the "
             + "duty to the expense account, and the whole assessment out of the "
             + "account it was paid from. A posted entry cannot be rewritten.",
      confirmLabel: "Post",
    });
    if (!ok) return;
    setPostingId(r.id);
    setMsg(null);
    try {
      const res = await api.billsOfEntry.post(r.id, clientId);
      if (!res.success) throw new Error(res.error ?? "Couldn't post the Bill of Entry.");
      setMsg({ type: "ok", text: `Bill of Entry ${r.be_number} posted.` });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't post the Bill of Entry." });
    } finally {
      setPostingId(null);
    }
  }

  async function handleDelete(r: BillOfEntry) {
    const ok = await confirmDialog({
      title: `Withdraw Bill of Entry ${r.be_number}?`,
      message: "It is removed from the register and from the return. Nothing is posted or unposted.",
      confirmLabel: "Withdraw",
      danger: true,
    });
    if (!ok) return;
    setDeletingId(r.id);
    setMsg(null);
    try {
      const res = await api.billsOfEntry.remove(r.id, clientId);
      if (!res.success) throw new Error(res.error ?? "Couldn't withdraw the Bill of Entry.");
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't withdraw the Bill of Entry." });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink flex items-center gap-2">
            <Ship size={15} className="text-blue-600" /> Bills of Entry
          </h2>
          <p className="text-[11px] text-ps-label mt-1 max-w-2xl">
            The customs assessment on an import of goods. The tax here is paid to
            customs, not to the supplier, so no accounts payable is touched.
            {authorities && (
              <>
                {" "}Integrated tax and cess are input tax ({authorities.credit_authority})
                and reach GSTR-3B Table {authorities.table_4a_row}; basic customs duty and
                the surcharge are recoverable from nobody and are cost ({authorities.cost_authority}).
              </>
            )}
          </p>
        </div>
        <button onClick={() => { setForm(BLANK); setShowForm(true); }}
          disabled={busy}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
          <Plus size={13} /> Record a Bill of Entry
        </button>
      </div>

      {msg && (
        <div className={`rounded-lg px-3 py-2 text-xs ${msg.type === "ok"
          ? "bg-emerald-50 border border-emerald-200 text-emerald-800"
          : "bg-red-50 border border-red-200 text-red-700"}`}>
          {msg.text}
        </div>
      )}

      {loadFailed && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-900 flex gap-2">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          <span>The register could not be read, so this list is not the whole of it. Reload before recording anything.</span>
        </div>
      )}

      {rows.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          {[
            ["Input tax credit", totals.credit, "Table 4(A)(1)"],
            ["Duty in cost", totals.cost, "not input tax"],
            ["Paid to customs", totals.paid, "total assessed"],
          ].map(([label, value, note]) => (
            <div key={String(label)} className="border border-ps-border rounded-lg px-3 py-2">
              <p className="text-[10px] text-ps-hint">{label}</p>
              <p className="text-sm font-semibold text-ps-ink tabular-nums">
                {formatPaise(Number(value))}
              </p>
              <p className="text-[10px] text-ps-hint">{note}</p>
            </div>
          ))}
        </div>
      )}

      {loading ? (
        <p className="text-xs text-ps-hint">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-ps-hint">
          No Bills of Entry recorded. Record one for every import so its IGST reaches the return.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-ps-muted text-ps-hint text-left">
                <th className="py-2 font-semibold">Number</th>
                <th className="py-2 font-semibold">Date</th>
                <th className="py-2 font-semibold">Port</th>
                <th className="py-2 font-semibold text-right">Credit</th>
                <th className="py-2 font-semibold text-right">Duty (cost)</th>
                <th className="py-2 font-semibold text-right">Paid</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ps-bg">
              {rows.map((r) => (
                // ACC-22 — a ledger drill-through rings the document it arrived
                // at. A hand-rolled table rather than DataTable here, so the
                // ring is spelled out; the rule is the same one
                // `highlightRowId` states there.
                <tr key={r.id} className={"align-top" +
                     (openDoc && r.id === openDoc ? " bg-amber-50 ring-2 ring-inset ring-amber-300" : "")}>
                  <td className="py-2 font-mono text-ps-ink">
                    {r.be_number}
                    <span className="ml-1.5 text-[10px] text-ps-hint uppercase">{r.gstr2b_section}</span>
                  </td>
                  <td className="py-2">{String(r.be_date).slice(0, 10)}</td>
                  <td className="py-2 font-mono text-ps-label">{r.port_code || "—"}</td>
                  <td className="py-2 text-right tabular-nums">
                    {formatPaise(r.creditable_igst_paise + r.creditable_cess_paise)}
                  </td>
                  <td className="py-2 text-right tabular-nums">{formatPaise(r.non_creditable_duty_paise)}</td>
                  <td className="py-2 text-right tabular-nums">{formatPaise(r.total_paise)}</td>
                  <td className="py-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] ${r.status === "posted"
                      ? "bg-emerald-50 text-emerald-700" : "bg-ps-muted text-ps-label"}`}>
                      {r.status === "posted" ? "Posted" : "Draft"}
                    </span>
                    {/* A refusal stops a posting; a caveat is true and stops
                        nothing. Rendered apart so a note does not read as a
                        block. */}
                    {r.refusals.length > 0 && (
                      <div className="mt-1 text-[10px] text-red-700 space-y-0.5 max-w-xs">
                        {r.refusals.map((x, i) => <p key={i}>{x}</p>)}
                      </div>
                    )}
                    {r.caveats.length > 0 && (
                      <div className="mt-1 text-[10px] text-amber-800 space-y-0.5 max-w-xs">
                        {r.caveats.map((x, i) => (
                          <p key={i} className="flex gap-1"><Info size={10} className="shrink-0 mt-0.5" />{x}</p>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    {r.status !== "posted" && (
                      <>
                        <button onClick={() => handlePost(r)}
                          disabled={busy || !r.can_post}
                          title={r.can_post ? "" : r.refusals.join(" ")}
                          className="px-2 py-1 text-[11px] border border-ps-border rounded hover:bg-ps-bg disabled:opacity-40">
                          {postingId === r.id ? "Posting…" : "Post"}
                        </button>
                        <button onClick={() => handleDelete(r)} disabled={busy}
                          aria-label={`Withdraw ${r.be_number}`}
                          className="ml-1 px-1.5 py-1 text-ps-hint hover:text-red-600 disabled:opacity-40">
                          <Trash2 size={12} />
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {authorities && authorities.not_modelled.length > 0 && (
        <div className="bg-ps-bg border border-ps-border rounded-lg px-3 py-2 text-[11px] text-ps-label space-y-1">
          <p className="font-semibold">What this document does not say</p>
          {authorities.not_modelled.map((x, i) => <p key={i}>{x}</p>)}
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
          <div className="w-full max-w-xl h-full bg-white shadow-xl flex flex-col">
            <div className="px-5 py-4 border-b border-ps-muted flex items-center justify-between">
              <p className="text-sm font-semibold text-ps-ink">Record a Bill of Entry</p>
              <button onClick={() => setShowForm(false)} aria-label="Close"
                className="p-1 rounded hover:bg-ps-muted text-ps-label"><X size={16} /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs">
                  <span className="block text-ps-body font-medium mb-1">Bill of Entry number *</span>
                  <input value={form.be_number} onChange={(e) => setForm(f => ({ ...f, be_number: e.target.value }))}
                    placeholder="e.g. 1234567"
                    className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg font-mono" />
                </label>
                <label className="text-xs">
                  <span className="block text-ps-body font-medium mb-1">Date *</span>
                  <input type="date" value={form.be_date}
                    onChange={(e) => setForm(f => ({ ...f, be_date: e.target.value }))}
                    className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
                </label>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs">
                  <span className="block text-ps-body font-medium mb-1">Port code</span>
                  <input value={form.port_code}
                    onChange={(e) => setForm(f => ({ ...f, port_code: e.target.value.toUpperCase() }))}
                    placeholder="INNSA1"
                    className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg font-mono" />
                  <span className="block text-[10px] text-ps-hint mt-1 leading-tight">
                    GSTR-2B keys the document on the port and the number together.
                  </span>
                </label>
                <label className="text-xs flex items-end gap-2 pb-1.5">
                  <input type="checkbox" checked={form.is_sez}
                    onChange={(e) => setForm(f => ({ ...f, is_sez: e.target.checked }))}
                    className="rounded" id="boe-sez" />
                  <span className="text-ps-body">From an SEZ unit or developer</span>
                </label>
              </div>

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">Assessable value (₹)</span>
                <input value={form.assessable_value}
                  onChange={(e) => setForm(f => ({ ...f, assessable_value: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
                <span className="block text-[10px] text-ps-hint mt-1 leading-tight">
                  Customs Act s.14 value — not the supplier invoice value. Recorded, never posted.
                </span>
              </label>

              <div className="border-t border-ps-muted pt-3">
                <p className="text-[11px] font-semibold text-ps-body mb-2">
                  Input tax — reaches the return
                </p>
                <div className="grid grid-cols-2 gap-3">
                  {([["igst", "IGST (₹)"], ["cess", "Compensation cess (₹)"],
                     ["ineligible_igst", "of which blocked, s.17(5) (₹)"],
                     ["ineligible_cess", "of which blocked, cess (₹)"]] as const).map(([k, label]) => (
                    <label key={k} className="text-xs">
                      <span className="block text-ps-body mb-1">{label}</span>
                      <input value={String(form[k])}
                        onChange={(e) => setForm(f => ({ ...f, [k]: e.target.value }))}
                        className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
                    </label>
                  ))}
                </div>
              </div>

              <div className="border-t border-ps-muted pt-3">
                <p className="text-[11px] font-semibold text-ps-body mb-2">
                  Duty — cost, not credit
                </p>
                <div className="grid grid-cols-2 gap-3">
                  {([["basic_customs_duty", "Basic customs duty (₹)"],
                     ["social_welfare_surcharge", "Social welfare surcharge (₹)"],
                     ["other_duty", "Other levies (₹)"]] as const).map(([k, label]) => (
                    <label key={k} className="text-xs">
                      <span className="block text-ps-body mb-1">{label}</span>
                      <input value={String(form[k])}
                        onChange={(e) => setForm(f => ({ ...f, [k]: e.target.value }))}
                        className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
                    </label>
                  ))}
                </div>
              </div>

              <div className="border-t border-ps-muted pt-3 space-y-3">
                <div>
                  <label htmlFor="boe-payment-account" className="block text-xs font-medium text-ps-body mb-1">
                    Paid from
                  </label>
                  <AccountLookup accounts={accounts} value={form.payment_account_id}
                    onChange={(id) => setForm(f => ({ ...f, payment_account_id: id }))}
                    id="boe-payment-account" ariaLabel="Account the duty was paid from"
                    placeholder="— Choose account —" />
                </div>
                <div>
                  <label htmlFor="boe-duty-account" className="block text-xs font-medium text-ps-body mb-1">
                    Duty and surcharge to
                  </label>
                  <AccountLookup accounts={accounts} value={form.duty_expense_account_id}
                    onChange={(id) => setForm(f => ({ ...f, duty_expense_account_id: id }))}
                    id="boe-duty-account" ariaLabel="Account the customs duty belongs to"
                    placeholder="— Choose account —" />
                  <p className="text-[10px] text-ps-hint mt-1 leading-tight">
                    &quot;Customs Duty&quot; is seeded for this. It is not apportioned across
                    stock lines — the basis for that is a judgement nothing here holds.
                  </p>
                </div>
              </div>

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">Notes</span>
                <textarea value={form.notes} rows={2}
                  onChange={(e) => setForm(f => ({ ...f, notes: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
              </label>
            </div>

            <div className="px-5 py-3 border-t border-ps-muted flex justify-end gap-2">
              <button onClick={() => setShowForm(false)}
                className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg">
                Cancel
              </button>
              <button onClick={handleSave} disabled={saving}
                className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
