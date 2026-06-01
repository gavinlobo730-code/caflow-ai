"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Search, Plus, Pencil, Archive, ArchiveRestore } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Account, AccountType } from "@/lib/types";

const TYPE_COLORS: Record<AccountType, string> = {
  Asset:     "bg-blue-100 text-blue-700",
  Liability: "bg-red-100 text-red-700",
  Equity:    "bg-purple-100 text-purple-700",
  Revenue:   "bg-green-100 text-green-700",
  Expense:   "bg-orange-100 text-orange-700",
};

const ACCOUNT_TYPES: AccountType[] = ["Asset", "Liability", "Equity", "Revenue", "Expense"];

const SUBTYPES: Record<AccountType, string[]> = {
  Asset:     ["Cash", "Bank", "Receivable", "Fixed Asset", "Tax", "Investment", "Other"],
  Liability: ["Payable", "Tax", "Loan", "Credit Card", "Other"],
  Equity:    ["Capital", "Retained", "Drawings", "Other"],
  Revenue:   ["Professional Fees", "Other Income"],
  Expense:   ["Personnel", "Overhead", "Professional", "Depreciation", "Tax", "Other"],
};

const EMPTY_FORM = { account_code: "", account_name: "", account_type: "Asset" as AccountType, account_subtype: "" };

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).single();
  if (!data) throw new Error("User not found");
  return data.firm_id as string;
}

export default function ChartOfAccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<AccountType | "All">("All");
  const [showArchived, setShowArchived] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Account | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [firmId, setFirmId] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();
      const { data, error: err } = await sb
        .from("accounts")
        .select("*")
        .eq("firm_id", fid)
        .order("account_code");
      if (err) throw new Error(err.message);
      setAccounts((data ?? []) as Account[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setEditTarget(null);
    setForm(EMPTY_FORM);
    setSaveError(null);
    setModalOpen(true);
  }

  function openEdit(acc: Account) {
    setEditTarget(acc);
    setForm({
      account_code: acc.account_code,
      account_name: acc.account_name,
      account_type: acc.account_type as AccountType,
      account_subtype: acc.account_subtype ?? "",
    });
    setSaveError(null);
    setModalOpen(true);
  }

  async function handleSave() {
    if (!form.account_code.trim() || !form.account_name.trim() || !firmId) return;
    setSaving(true);
    setSaveError(null);
    const sb = getSupabaseClient();
    try {
      if (editTarget) {
        const { data, error: err } = await sb
          .from("chart_of_accounts")
          .update({
            account_code: form.account_code,
            account_name: form.account_name,
            account_type: form.account_type,
            account_subtype: form.account_subtype || null,
            updated_at: new Date().toISOString(),
          })
          .eq("id", editTarget.id)
          .select()
          .single();
        if (err) throw new Error(err.message);
        setAccounts(prev => prev.map(a => a.id === editTarget.id ? data as Account : a));
      } else {
        const { data, error: err } = await sb
          .from("chart_of_accounts")
          .insert({
            firm_id: firmId,
            account_code: form.account_code,
            account_name: form.account_name,
            account_type: form.account_type,
            account_subtype: form.account_subtype || null,
            is_active: true,
          })
          .select()
          .single();
        if (err) throw new Error(err.message);
        setAccounts(prev => [...prev, data as Account].sort((a, b) => a.account_code.localeCompare(b.account_code)));
      }
      setModalOpen(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function toggleArchive(acc: Account) {
    const sb = getSupabaseClient();
    const { data, error: err } = await sb
      .from("chart_of_accounts")
      .update({ is_active: !acc.is_active, updated_at: new Date().toISOString() })
      .eq("id", acc.id)
      .select()
      .single();
    if (!err && data) setAccounts(prev => prev.map(a => a.id === acc.id ? data as Account : a));
  }

  if (loading) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-4 animate-pulse">
        <div className="h-6 bg-gray-200 rounded w-48" />
        {[1,2,3].map(i => <div key={i} className="h-32 bg-gray-100 rounded-xl" />)}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  const visibleAccounts = accounts.filter(a => {
    if (!showArchived && !a.is_active) return false;
    if (activeTab !== "All" && a.account_type !== activeTab) return false;
    if (search) {
      const q = search.toLowerCase();
      return a.account_name.toLowerCase().includes(q) || a.account_code.includes(q);
    }
    return true;
  });

  const grouped = ACCOUNT_TYPES.reduce<Record<AccountType, Account[]>>((acc, type) => {
    acc[type] = visibleAccounts.filter(a => a.account_type === type);
    return acc;
  }, { Asset: [], Liability: [], Equity: [], Revenue: [], Expense: [] });

  const tabs: (AccountType | "All")[] = ["All", ...ACCOUNT_TYPES];
  const counts: Record<string, number> = { All: accounts.filter(a => showArchived || a.is_active).length };
  for (const t of ACCOUNT_TYPES) counts[t] = accounts.filter(a => a.account_type === t && (showArchived || a.is_active)).length;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">Chart of Accounts</h1>
          <p className="text-sm text-gray-500 mt-0.5">{accounts.filter(a => a.is_active).length} active accounts</p>
        </div>
        <button
          onClick={() => setShowArchived(v => !v)}
          className="text-xs text-gray-500 border border-gray-200 px-3 py-1.5 rounded-md hover:bg-gray-50"
        >
          {showArchived ? "Hide Archived" : "Show Archived"}
        </button>
        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          <Plus size={13} /> New Account
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by account name or code…"
          className="w-full pl-8 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {tabs.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === tab
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab} <span className="ml-1 text-gray-400">({counts[tab] ?? 0})</span>
          </button>
        ))}
      </div>

      {/* Account groups */}
      {accounts.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-sm text-gray-500 mb-3">No accounts yet</p>
          <button onClick={openCreate} className="text-sm bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700">
            Add First Account
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {ACCOUNT_TYPES.map(type => {
            const accs = grouped[type];
            if (activeTab !== "All" && activeTab !== type) return null;
            if (accs.length === 0) return null;
            return (
              <Card key={type}>
                <div className="px-5 py-3 border-b border-gray-50 flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[type]}`}>{type}</span>
                  <span className="text-xs text-gray-400">{accs.length} accounts</span>
                </div>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-gray-400 border-b border-gray-50">
                        <th className="px-5 py-2 text-left font-medium w-20">Code</th>
                        <th className="px-3 py-2 text-left font-medium">Name</th>
                        <th className="px-3 py-2 text-left font-medium">Sub-type</th>
                        <th className="px-3 py-2 text-left font-medium w-20">Status</th>
                        <th className="px-5 py-2 text-right font-medium w-24">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {accs.map(acc => (
                        <tr key={acc.id} className={`hover:bg-gray-50 group ${!acc.is_active ? "opacity-50" : ""}`}>
                          <td className="px-5 py-2.5 font-mono text-xs text-gray-400">{acc.account_code}</td>
                          <td className="px-3 py-2.5 text-sm font-medium text-gray-900">{acc.account_name}</td>
                          <td className="px-3 py-2.5 text-xs text-gray-500">{acc.account_subtype ?? "—"}</td>
                          <td className="px-3 py-2.5">
                            <Badge className={`text-xs ${acc.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                              {acc.is_active ? "Active" : "Archived"}
                            </Badge>
                          </td>
                          <td className="px-5 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={() => openEdit(acc)}
                                className="p-1.5 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-700"
                                title="Edit"
                              >
                                <Pencil size={12} />
                              </button>
                              <button
                                onClick={() => toggleArchive(acc)}
                                className="p-1.5 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-700"
                                title={acc.is_active ? "Archive" : "Restore"}
                              >
                                {acc.is_active ? <Archive size={12} /> : <ArchiveRestore size={12} />}
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Add / Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">
              {editTarget ? "Edit Account" : "New Account"}
            </h2>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 font-medium">Account Code *</label>
                  <input
                    value={form.account_code}
                    onChange={e => setForm({ ...form, account_code: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                    placeholder="e.g. 1006"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 font-medium">Account Type *</label>
                  <select
                    value={form.account_type}
                    onChange={e => setForm({ ...form, account_type: e.target.value as AccountType, account_subtype: "" })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {ACCOUNT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 font-medium">Account Name *</label>
                <input
                  value={form.account_name}
                  onChange={e => setForm({ ...form, account_name: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. ICICI Bank Savings Account"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 font-medium">Sub-type</label>
                <select
                  value={form.account_subtype}
                  onChange={e => setForm({ ...form, account_subtype: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— Select sub-type —</option>
                  {SUBTYPES[form.account_type].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            {saveError && (
              <p className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-md">{saveError}</p>
            )}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setModalOpen(false)}
                className="flex-1 text-sm text-gray-600 border border-gray-200 py-2 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !form.account_code.trim() || !form.account_name.trim()}
                className="flex-1 text-sm bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Saving…" : editTarget ? "Save Changes" : "Add Account"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
