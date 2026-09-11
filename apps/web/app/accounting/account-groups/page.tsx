"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Layers, Plus, AlertCircle } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { TableSkeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";

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

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found");
  return data.firm_id as string;
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
        <h3 className="text-sm font-semibold text-[#0F172A]">
          {account ? `Edit ${account.account_name}` : "Add a ledger"}
        </h3>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-[11px] font-medium text-[#64748B] mb-1">Ledger name</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs"
                   value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-[#64748B] mb-1">Code</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs font-mono"
                   value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-[#64748B] mb-1">Type</label>
            {account ? (
              // Fixed once anything can have been posted — it decides which side
              // of the trial balance this account falls on.
              <p className="text-xs text-[#64748B] py-2">{account.account_type}</p>
            ) : (
              <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs"
                      value={form.account_type}
                      onChange={e => setForm(f => ({ ...f, account_type: e.target.value }))}>
                {ACCOUNT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            )}
          </div>
          <div>
            <label className="block text-[11px] font-medium text-[#64748B] mb-1">Parent group</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs"
                   placeholder="Current Assets"
                   value={form.parent_group}
                   onChange={e => setForm(f => ({ ...f, parent_group: e.target.value }))} />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-[#64748B] mb-1">Sub group</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs"
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
          <label className="block text-[11px] font-medium text-[#64748B] mb-1">
            Nature (for the Balance Sheet)
          </label>
          <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs"
                 placeholder="Bank Account, Trade Receivables, Plant &amp; Machinery…"
                 value={form.account_subtype}
                 onChange={e => setForm(f => ({ ...f, account_subtype: e.target.value }))} />
          {!form.account_subtype.trim() && (
            <p className="mt-1 text-[10px] text-amber-700">
              Without this, the ledger presents under the generic caption for its
              type — an Asset as Other Current Assets — on the Balance Sheet and
              in every year-end schedule. Schedule III Mapping can override it
              afterwards.
            </p>
          )}
        </div>

        {error && (
          <div className="flex gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
            <AlertCircle size={13} className="text-red-600 shrink-0 mt-0.5" />
            <p className="text-[11px] text-red-700">{error}</p>
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 text-xs border border-[#E2E8F0] rounded-lg py-2 text-[#334155] hover:bg-[#F8FAFC]">Cancel</button>
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
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
      <TableSkeleton cols={4} rows={4} />
    </div>
  );
  if (error) return <div className="p-6"><div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div></div>;

  // Group by parent_group → sub_group
  const grouped: Record<string, Record<string, CoaRow[]>> = {};
  for (const acc of accounts) {
    const pg = acc.parent_group ?? "Ungrouped";
    const sg = acc.sub_group ?? "General";
    if (!grouped[pg]) grouped[pg] = {};
    if (!grouped[pg][sg]) grouped[pg][sg] = [];
    grouped[pg][sg].push(acc);
  }
  const parentGroups = Object.keys(grouped).sort();

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A] flex items-center gap-2">
            <Layers size={18} className="text-blue-600" /> Account Groups
          </h1>
          <p className="text-xs text-[#64748B] mt-0.5">
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
            <div key={pg} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9] flex items-center justify-between">
                <span className="text-sm font-semibold text-[#334155]">{pg}</span>
                <span className="text-xs text-[#94A3B8]">{total} accounts</span>
              </div>
              {subGroups.map(sg => (
                <div key={sg}>
                  <div className="px-5 py-2 border-b border-[#F8FAFC] flex items-center justify-between bg-[#FAFAFA]">
                    <span className="text-xs font-medium text-[#475569]">{sg}</span>
                    <span className="text-[10px] text-[#94A3B8]">{grouped[pg][sg].length}</span>
                  </div>
                  <table className="w-full text-xs">
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {grouped[pg][sg].map(acc => (
                        <tr key={acc.id} className="hover:bg-[#F8FAFC]">
                          <td className="px-5 py-2 font-mono text-[10px] text-[#94A3B8] w-16">{acc.account_code}</td>
                          <td className="px-3 py-2 font-medium text-[#0F172A]">{acc.account_name}</td>
                          <td className="px-3 py-2 text-[#64748B]">{acc.account_type}</td>
                          <td className="px-3 py-2 text-[#94A3B8]">{acc.account_subtype ?? "—"}</td>
                          <td className="px-5 py-2 text-right">
                            <button onClick={() => setEditing(acc)} className="text-[11px] text-blue-600 hover:underline">Edit</button>
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
