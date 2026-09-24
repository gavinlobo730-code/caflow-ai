"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Layers, Plus } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { TableSkeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { Callout } from "@/components/ui/callout";

interface CoaRow {
  id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  account_subtype: string | null;
  parent_group: string | null;
  sub_group: string | null;
  is_active: boolean;
}


// SPELLED THE WAY THE DATABASE SPELLS THEM. chart_of_accounts' CHECK
// (migration 003) allows 'Revenue', not 'Income', and the Schedule III
// classifier tests `typ == "revenue"` — so picking "Income" here posted a
// value Postgres refused, and this screen had NO way to create a revenue
// ledger at all. The backend now folds "Income" to "Revenue" on the way in
// (models/accounting.AccountType._missing_) so an older caller keeps working;
// this list sends the canonical spelling.
const ACCOUNT_TYPES = ["Asset", "Liability", "Equity", "Revenue", "Expense"] as const;

/** ACC-09. chart_of_accounts has carried parent_group and sub_group since
 *  migration 057 and nothing but the CSV import ever wrote them, so this screen
 *  rendered one "Ungrouped → General" block for any normally-seeded firm — it
 *  was not broken, it was being told nothing. And there was no way to add a
 *  ledger or to move one: createAccount and updateAccount existed in lib/api
 *  and were called from nowhere.
 *
 *  Every rule stays on the server. account_type is absent from the edit form
 *  because it decides which side of the trial balance the account falls on and
 *  changing it after a posting silently restates every report — the backend
 *  refuses it, and this form does not offer what the backend will not take. */
function LedgerDialog({ account, onClose, onSaved }:
  { account: CoaRow | null; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name:         account?.account_name ?? "",
    code:         account?.account_code ?? "",
    account_type: account?.account_type ?? "Asset",
    parent_group: account?.parent_group ?? "",
    sub_group:    account?.sub_group ?? "",
    // ACC-11. Only the CSV importer ever set this, so a ledger created here
    // had none — and since the year-end statements derive their Schedule III
    // line from the account, none means the coarse fallback: a bank account
    // presented as Other Current Assets.
    account_subtype: account?.account_subtype ?? "",
    is_active:    account?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setError("");
    if (!form.name.trim()) { setError("A ledger needs a name."); return; }
    if (!form.code.trim()) {
      setError("A ledger needs a code — it is what the chart is ordered and matched by.");
      return;
    }
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        code: form.code.trim(),
        parent_group: form.parent_group.trim(),
        sub_group: form.sub_group.trim(),
        account_subtype: form.account_subtype.trim(),
        is_active: form.is_active,
        ...(account ? {} : { account_type: form.account_type }),
      };
      const res = (account
        ? await api.accounting.updateAccount(account.id, body)
        : await api.accounting.createAccount(body)) as { success: boolean; error?: string | null; detail?: string };
      // Checked, not assumed: this router answers a refusal as HTTP 200 with
      // success:false, so an unchecked call would report "saved" for a request
      // the server declined.
      if (!res.success) throw new Error(res.detail ?? res.error ?? "Could not save the ledger.");
      onSaved(); onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the ledger.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-xl max-w-md w-full p-6 space-y-3" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-ps-ink">
          {account ? `Edit ${account.account_name}` : "Add a ledger"}
        </h3>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-2xs font-medium text-ps-label mb-1">Ledger name</label>
            <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-xs"
                   value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="block text-2xs font-medium text-ps-label mb-1">Code</label>
            <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-xs font-mono"
                   value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} />
          </div>
          <div>
            <label className="block text-2xs font-medium text-ps-label mb-1">Type</label>
            {account ? (
              // Fixed once anything can have been posted — it decides which side
              // of the trial balance this account falls on.
              <p className="text-xs text-ps-label py-2">{account.account_type}</p>
            ) : (
              <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-xs"
                      value={form.account_type}
                      onChange={e => setForm(f => ({ ...f, account_type: e.target.value }))}>
                {ACCOUNT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            )}
          </div>
          <div>
            <label className="block text-2xs font-medium text-ps-label mb-1">Parent group</label>
            <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-xs"
                   placeholder="Current Assets"
                   value={form.parent_group}
                   onChange={e => setForm(f => ({ ...f, parent_group: e.target.value }))} />
          </div>
          <div>
            <label className="block text-2xs font-medium text-ps-label mb-1">Sub group</label>
            <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-xs"
                   placeholder="Sundry Debtors"
                   value={form.sub_group}
                   onChange={e => setForm(f => ({ ...f, sub_group: e.target.value }))} />
          </div>
        </div>

        {/* ACC-11. Parent group and sub group above are how the CA reads their
            own trial balance; THIS is what the statutory statements read. The
            classifier keyword-scans it (domain/reporting/schedule_iii), so
            "Bank Account" reaches Cash & Cash Equivalents and a blank reaches
            the coarse fallback for the account's type. */}
        <div>
          <label className="block text-2xs font-medium text-ps-label mb-1">
            Nature (for the Balance Sheet)
          </label>
          <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-xs"
                 placeholder="Bank Account, Trade Receivables, Plant &amp; Machinery…"
                 value={form.account_subtype}
                 onChange={e => setForm(f => ({ ...f, account_subtype: e.target.value }))} />
          {!form.account_subtype.trim() && (
            <p className="mt-1 text-3xs text-state-attention">
              Without this, the ledger presents under the generic caption for its
              type — an Asset as Other Current Assets — on the Balance Sheet and
              in every year-end schedule. Schedule III Mapping can override it
              afterwards.
            </p>
          )}
        </div>

        {error && <Callout tone="problem">{error}</Callout>}

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 text-xs border border-ps-border rounded-lg py-2 text-ps-body hover:bg-ps-bg">Cancel</button>
          <button onClick={save} disabled={saving}
                  className="flex-1 text-xs bg-blue-600 text-white rounded-lg py-2 hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : account ? "Save changes" : "Add ledger"}
          </button>
        </div>
      </div>
    </div>
  );
}


export default function AccountGroupsPage() {
  const [accounts, setAccounts] = useState<CoaRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<CoaRow | null>(null);
  const [adding, setAdding] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const fid = await getFirmId();
        const sb = getSupabaseClient();
        const { data, error: err } = await sb
          .from("chart_of_accounts")
          .select("id, account_code, account_name, account_type, account_subtype, parent_group, sub_group, is_active")
          .eq("firm_id", fid)
          .is("client_id", null)
          .eq("is_active", true)
          .order("account_code");
        if (err) throw new Error(err.message);
        setAccounts((data ?? []) as CoaRow[]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, [reloadKey]);

  if (loading) return (
    <div className="p-6 max-w-ps-data mx-auto space-y-4">
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
    </div>
  );
  if (error) return <div className="p-6"><div className="bg-state-problem-surface text-state-problem rounded-lg px-5 py-4 text-sm">{error}</div></div>;

  // Group by parent_group → sub_group, DERIVING both where the CA has not said
  // (ACC-24).
  //
  // These two columns have existed since migration 057 and only the CSV import
  // and this screen's own editor ever write them, so every normally-onboarded
  // firm arrived here to a single "Ungrouped → General" block holding all 57
  // seeded accounts. The screen was not broken; it was being told nothing.
  //
  // WHY DERIVE RATHER THAN SEED THEM. The obvious fix is a fifth element on
  // each STANDARD_COA tuple in coa_seed_service.py, plus a backfill migration
  // for the firms already seeded. It was not taken, for two reasons:
  //
  //   * it stores a COPY of account_type and account_subtype in two more
  //     columns. Two columns holding the same fact drift, and this repository
  //     has the scar: account_group_mappings cached a derived classification,
  //     nothing re-derived it, and the year-end statements detached from the
  //     CA's own decisions (see CLAUDE.md, "a row is an OVERRIDE, not the
  //     source"). Same shape, same answer — derive, and treat a stored value
  //     as the override it is;
  //   * a backfill has to decide whether to overwrite a group a CA typed. This
  //     way there is nothing to decide, and firms already seeded are fixed on
  //     the next page load rather than on the next migration.
  //
  // What is derived is a NAVIGATIONAL tree, not a statutory one. Schedule III
  // presentation is decided elsewhere and only elsewhere — schedule_iii_mapping
  // through domain/reporting/schedule_iii.py — and putting its captions here
  // would be the second mapping screen CLAUDE.md says not to build.
  const grouped: Record<string, Record<string, CoaRow[]>> = {};
  const derived = new Set<string>();
  for (const acc of accounts) {
    const pg = acc.parent_group ?? acc.account_type ?? "Ungrouped";
    const sg = acc.sub_group ?? acc.account_subtype ?? "General";
    if (acc.parent_group == null) derived.add(pg);
    if (!grouped[pg]) grouped[pg] = {};
    if (!grouped[pg][sg]) grouped[pg][sg] = [];
    grouped[pg][sg].push(acc);
  }
  const parentGroups = Object.keys(grouped).sort();

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-ps-ink flex items-center gap-2">
            <Layers size={18} className="text-blue-600" /> Account Groups
          </h1>
          <p className="text-xs text-ps-label mt-0.5">
            {parentGroups.length} parent groups · {accounts.length} active accounts
          </p>
        </div>
        <button onClick={() => setAdding(true)}
                className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
          <Plus size={12} /> Add ledger
        </button>
      </div>

      <div className="space-y-5">
        {parentGroups.map(pg => {
          const subGroups = Object.keys(grouped[pg]).sort();
          const total = subGroups.reduce((n, sg) => n + grouped[pg][sg].length, 0);
          return (
            <div key={pg} className="bg-white rounded-xl border border-ps-muted overflow-hidden">
              <div className="px-5 py-3 bg-ps-bg border-b border-ps-muted flex items-center justify-between">
                <span className="text-sm font-semibold text-ps-body">
                  {pg}
                  {derived.has(pg) && (
                    <span className="ml-2 font-normal text-3xs text-ps-hint"
                          title="No group recorded for these ledgers, so they are shown under their account type. Edit a ledger to file it where you want it.">
                      by account type
                    </span>
                  )}
                </span>
                <span className="text-xs text-ps-hint">{total} accounts</span>
              </div>
              {subGroups.map(sg => (
                <div key={sg}>
                  <div className="px-5 py-2 border-b border-ps-bg flex items-center justify-between bg-ps-bg">
                    <span className="text-xs font-medium text-ps-label">{sg}</span>
                    <span className="text-3xs text-ps-hint">{grouped[pg][sg].length}</span>
                  </div>
                  <table className="w-full text-xs">
                    <tbody className="divide-y divide-ps-bg">
                      {grouped[pg][sg].map(acc => (
                        <tr key={acc.id} className="hover:bg-ps-bg">
                          <td className="px-5 py-2 font-mono text-3xs text-ps-hint w-16">{acc.account_code}</td>
                          <td className="px-3 py-2 font-medium text-ps-ink">{acc.account_name}</td>
                          <td className="px-3 py-2 text-ps-label">{acc.account_type}</td>
                          <td className="px-3 py-2 text-ps-hint">{acc.account_subtype ?? "—"}</td>
                          <td className="px-5 py-2 text-right">
                            <button onClick={() => setEditing(acc)} className="text-2xs text-blue-600 hover:underline">Edit</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {(adding || editing) && (
        <LedgerDialog
          account={editing}
          onClose={() => { setAdding(false); setEditing(null); }}
          onSaved={() => setReloadKey(k => k + 1)}
        />
      )}
    </div>
  );
}
