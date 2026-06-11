"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { Search, Plus, Pencil, Archive, ArchiveRestore, Building2, User } from "lucide-react";
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

const EMPTY_FORM = {
  account_code: "",
  account_name: "",
  account_type: "Asset" as AccountType,
  account_subtype: "",
};

interface AccountWithSource extends Account {
  _source: "firm" | "client";
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found");
  return data.firm_id as string;
}

export default function ClientCoaPage() {
  const params = useParams<{ id: string }>();
  const clientId = typeof window !== "undefined"
    ? (window.location.pathname.match(/^\/clients\/([^/]+)/)?.[1] ?? params.id)
    : params.id;

  const [accounts, setAccounts] = useState<AccountWithSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<AccountType | "All">("All");
  const [showArchived, setShowArchived] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AccountWithSource | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [firmId, setFirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();

      // Load firm-level accounts (client_id IS NULL) and client-specific accounts
      const { data: firmAccounts, error: e1 } = await sb
        .from("chart_of_accounts")
        .select("*")
        .eq("firm_id", fid)
        .is("client_id", null)
        .order("account_code");
      if (e1) throw new Error(e1.message);

      const { data: clientAccounts, error: e2 } = await sb
        .from("chart_of_accounts")
        .select("*")
        .eq("firm_id", fid)
        .eq("client_id", clientId)
        .order("account_code");
      if (e2) throw new Error(e2.message);

      // Client-specific accounts with same code override firm accounts
      const clientCodes = new Set((clientAccounts ?? []).map((a) => a.account_code));
      const merged: AccountWithSource[] = [
        ...(firmAccounts ?? [])
          .filter((a) => !clientCodes.has(a.account_code))
          .map((a) => ({ ...a, _source: "firm" as const })),
        ...(clientAccounts ?? []).map((a) => ({ ...a, _source: "client" as const })),
      ].sort((a, b) => a.account_code.localeCompare(b.account_code));

      setAccounts(merged);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditTarget(null);
    setForm(EMPTY_FORM);
    setSaveError(null);
    setModalOpen(true);
  }

  function openEdit(acc: AccountWithSource) {
    if (acc._source === "firm") {
      // Editing a firm account from client context creates a client override
      setEditTarget(null);
      setForm({
        account_code: acc.account_code,
        account_name: acc.account_name,
        account_type: acc.account_type as AccountType,
        account_subtype: acc.account_subtype ?? "",
      });
    } else {
      setEditTarget(acc);
      setForm({
        account_code: acc.account_code,
        account_name: acc.account_name,
        account_type: acc.account_type as AccountType,
        account_subtype: acc.account_subtype ?? "",
      });
    }
    setSaveError(null);
    setModalOpen(true);
  }

  async function handleSave() {
    if (!form.account_code.trim() || !form.account_name.trim() || !firmId) return;

    const code = form.account_code.trim().toUpperCase();
    const name = form.account_name.trim().toLowerCase();
    const isDuplicateCode = accounts.some(
      (a) => a.account_code.toUpperCase() === code && a.id !== editTarget?.id && a._source === "client"
    );
    const isDuplicateName = accounts.some(
      (a) => a.account_name.toLowerCase() === name && a.id !== editTarget?.id && a._source === "client"
    );
    if (isDuplicateCode) { setSaveError(`Account code "${code}" already exists for this client`); return; }
    if (isDuplicateName) { setSaveError(`Account name "${form.account_name.trim()}" already exists for this client`); return; }

    setSaving(true);
    setSaveError(null);
    const sb = getSupabaseClient();
    try {
      if (editTarget) {
        const { data, error: err } = await sb
          .from("chart_of_accounts")
          .update({
            account_code: form.account_code.trim(),
            account_name: form.account_name.trim(),
            account_type: form.account_type,
            account_subtype: form.account_subtype || null,
            updated_at: new Date().toISOString(),
          })
          .eq("id", editTarget.id)
          .select()
          .single();
        if (err) throw new Error(err.message);
        setAccounts((prev) =>
          prev.map((a) => a.id === editTarget.id ? { ...data as Account, _source: "client" } : a)
        );
      } else {
        const { error: err } = await sb
          .from("chart_of_accounts")
          .insert({
            firm_id: firmId,
            client_id: clientId,
            account_code: form.account_code.trim(),
            account_name: form.account_name.trim(),
            account_type: form.account_type,
            account_subtype: form.account_subtype || null,
            is_active: true,
          })
          .select()
          .single();
        if (err) {
          if (err.code === "23505") throw new Error("An account with this code already exists");
          throw new Error(err.message);
        }
        // Re-load to get proper merged view
        await load();
        setModalOpen(false);
        return;
      }
      setModalOpen(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function toggleArchive(acc: AccountWithSource) {
    if (acc._source === "firm") return; // Can't archive firm accounts from client view
    const sb = getSupabaseClient();
    const { data, error: err } = await sb
      .from("chart_of_accounts")
      .update({ is_active: !acc.is_active, updated_at: new Date().toISOString() })
      .eq("id", acc.id)
      .select()
      .single();
    if (!err && data)
      setAccounts((prev) => prev.map((a) => a.id === acc.id ? { ...data as Account, _source: "client" } : a));
  }

  if (loading) {
    return (
      <div className="p-6 max-w-5xl space-y-4 animate-pulse">
        {[1, 2, 3].map((i) => <div key={i} className="h-32 bg-[#F1F5F9] rounded-xl" />)}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-5xl">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  const visibleAccounts = accounts.filter((a) => {
    if (!showArchived && !a.is_active) return false;
    if (activeTab !== "All" && a.account_type !== activeTab) return false;
    if (search) {
      const q = search.toLowerCase();
      return a.account_name.toLowerCase().includes(q) || a.account_code.includes(q);
    }
    return true;
  });

  const grouped = ACCOUNT_TYPES.reduce<Record<AccountType, AccountWithSource[]>>((acc, type) => {
    acc[type] = visibleAccounts.filter((a) => a.account_type === type);
    return acc;
  }, { Asset: [], Liability: [], Equity: [], Revenue: [], Expense: [] });

  const tabs: (AccountType | "All")[] = ["All", ...ACCOUNT_TYPES];
  const counts: Record<string, number> = { All: accounts.filter((a) => showArchived || a.is_active).length };
  for (const t of ACCOUNT_TYPES) counts[t] = accounts.filter((a) => a.account_type === t && (showArchived || a.is_active)).length;

  return (
    <div className="p-6 max-w-5xl space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-[#1E293B]">Chart of Accounts</h1>
          <p className="text-xs text-[#94A3B8] mt-0.5">
            {accounts.filter((a) => a.is_active && a._source === "firm").length} firm accounts ·{" "}
            {accounts.filter((a) => a._source === "client").length} client-specific
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowArchived((v) => !v)}
            className="text-xs text-[#64748B] border border-[#E2E8F0] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC]"
          >
            {showArchived ? "Hide Archived" : "Show Archived"}
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
          >
            <Plus size={12} /> Add Account
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-[10px] text-[#64748B]">
        <span className="flex items-center gap-1"><Building2 size={10} /> Firm default (applies to all clients)</span>
        <span className="flex items-center gap-1"><User size={10} /> Client-specific (this client only)</span>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by account name or code…"
          className="w-full pl-8 pr-4 py-2 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === tab
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {tab} <span className="ml-1 text-[#94A3B8]">({counts[tab] ?? 0})</span>
          </button>
        ))}
      </div>

      {/* Account groups */}
      {accounts.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <p className="text-sm text-[#64748B] mb-2">No accounts yet</p>
          <p className="text-xs text-[#94A3B8]">Add accounts in Settings → Chart of Accounts, or add client-specific accounts here.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {ACCOUNT_TYPES.map((type) => {
            const accs = grouped[type];
            if (activeTab !== "All" && activeTab !== type) return null;
            if (accs.length === 0) return null;
            return (
              <div key={type} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
                <div className="px-5 py-3 border-b border-[#F8FAFC] flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[type]}`}>{type}</span>
                  <span className="text-xs text-[#94A3B8]">{accs.length} accounts</span>
                </div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[10px] text-[#94A3B8] border-b border-[#F8FAFC]">
                      <th className="px-5 py-2 text-left font-semibold w-20">Code</th>
                      <th className="px-3 py-2 text-left font-semibold">Name</th>
                      <th className="px-3 py-2 text-left font-semibold">Sub-type</th>
                      <th className="px-3 py-2 text-left font-semibold w-28">Source</th>
                      <th className="px-3 py-2 text-left font-semibold w-20">Status</th>
                      <th className="px-5 py-2 text-right font-semibold w-24">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {accs.map((acc) => (
                      <tr key={acc.id} className={`hover:bg-[#F8FAFC] group ${!acc.is_active ? "opacity-50" : ""}`}>
                        <td className="px-5 py-2.5 font-mono text-[#94A3B8]">{acc.account_code}</td>
                        <td className="px-3 py-2.5 font-medium text-[#0F172A]">{acc.account_name}</td>
                        <td className="px-3 py-2.5 text-[#64748B]">{acc.account_subtype ?? "—"}</td>
                        <td className="px-3 py-2.5">
                          {acc._source === "firm" ? (
                            <span className="flex items-center gap-1 text-[10px] text-[#64748B]">
                              <Building2 size={9} /> Firm default
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-[10px] text-blue-600">
                              <User size={9} /> Client-specific
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2.5">
                          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${acc.is_active ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
                            {acc.is_active ? "Active" : "Archived"}
                          </span>
                        </td>
                        <td className="px-5 py-2.5 text-right">
                          <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={() => openEdit(acc)}
                              className="p-1.5 rounded hover:bg-[#F1F5F9] text-[#94A3B8] hover:text-[#334155]"
                              title={acc._source === "firm" ? "Add client override" : "Edit"}
                            >
                              <Pencil size={11} />
                            </button>
                            {acc._source === "client" && (
                              <button
                                onClick={() => toggleArchive(acc)}
                                className="p-1.5 rounded hover:bg-[#F1F5F9] text-[#94A3B8] hover:text-[#334155]"
                                title={acc.is_active ? "Archive" : "Restore"}
                              >
                                {acc.is_active ? <Archive size={11} /> : <ArchiveRestore size={11} />}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      )}

      {/* Add / Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md">
            <h2 className="text-sm font-semibold text-[#0F172A] mb-1">
              {editTarget ? "Edit Account" : "Add Client Account"}
            </h2>
            <p className="text-[10px] text-[#94A3B8] mb-4">
              {editTarget ? "Updating client-specific account." : "This account will only apply to this client."}
            </p>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Account Code *</label>
                  <input
                    value={form.account_code}
                    onChange={(e) => setForm({ ...form, account_code: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                    placeholder="e.g. 1099"
                  />
                </div>
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Account Type *</label>
                  <select
                    value={form.account_type}
                    onChange={(e) => setForm({ ...form, account_type: e.target.value as AccountType, account_subtype: "" })}
                    className="w-full mt-1 px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs text-[#64748B] font-medium">Account Name *</label>
                <input
                  value={form.account_name}
                  onChange={(e) => setForm({ ...form, account_name: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. GST Input Credit — Capital Goods"
                />
              </div>
              <div>
                <label className="text-xs text-[#64748B] font-medium">Sub-type</label>
                <select
                  value={form.account_subtype}
                  onChange={(e) => setForm({ ...form, account_subtype: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— Select sub-type —</option>
                  {SUBTYPES[form.account_type].map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            {saveError && (
              <p className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-md">{saveError}</p>
            )}
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setModalOpen(false)}
                className="flex-1 text-xs text-[#475569] border border-[#E2E8F0] py-2 rounded-md hover:bg-[#F8FAFC]"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !form.account_code.trim() || !form.account_name.trim()}
                className="flex-1 text-xs bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
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
