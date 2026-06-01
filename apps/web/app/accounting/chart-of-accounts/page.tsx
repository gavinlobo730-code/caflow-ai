"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Search, Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Account, AccountType, ApiResponse } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TYPE_COLORS: Record<AccountType, string> = {
  Asset: "bg-blue-100 text-blue-700",
  Liability: "bg-red-100 text-red-700",
  Equity: "bg-purple-100 text-purple-700",
  Income: "bg-green-100 text-green-700",
  Expense: "bg-orange-100 text-orange-700",
};

const ACCOUNT_TYPES: AccountType[] = ["Asset", "Liability", "Equity", "Income", "Expense"];

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="h-10 bg-gray-100 rounded" />
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-32 bg-gray-100 rounded-xl" />
      ))}
    </div>
  );
}

export default function ChartOfAccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [newAcc, setNewAcc] = useState({ account_code: "", account_name: "", account_type: "Asset" as AccountType, account_subtype: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${BASE_URL}/api/accounting/accounts`)
      .then((r) => r.json())
      .then((res: ApiResponse<Account[]>) => {
        if (res.success) setAccounts(res.data);
        else setError(res.error ?? "Failed to load accounts");
      })
      .catch(() => setError("Failed to load accounts"))
      .finally(() => setLoading(false));
  }, []);

  async function handleSaveAccount() {
    if (!newAcc.account_code || !newAcc.account_name) return;
    setSaving(true);
    try {
      const res: ApiResponse<Account> = await fetch(`${BASE_URL}/api/accounting/accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newAcc, is_active: true }),
      }).then((r) => r.json());
      if (res.success) {
        setAccounts((prev) => [...prev, res.data]);
        setShowModal(false);
        setNewAcc({ account_code: "", account_name: "", account_type: "Asset", account_subtype: "" });
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  const filtered = accounts.filter(
    (a) =>
      a.account_name.toLowerCase().includes(search.toLowerCase()) ||
      a.account_code.includes(search)
  );

  const grouped = ACCOUNT_TYPES.reduce<Record<AccountType, Account[]>>(
    (acc, type) => {
      acc[type] = filtered.filter((a) => a.account_type === type);
      return acc;
    },
    { Asset: [], Liability: [], Equity: [], Income: [], Expense: [] }
  );

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">Chart of Accounts</h1>
          <p className="text-sm text-gray-500 mt-0.5">{accounts.length} accounts</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700 transition-colors"
        >
          <Plus size={13} /> New Account
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search accounts by name or code…"
          className="w-full pl-8 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Groups */}
      <div className="space-y-4">
        {ACCOUNT_TYPES.map((type) => {
          const accs = grouped[type];
          if (accs.length === 0) return null;
          return (
            <Card key={type}>
              <CardHeader className="pb-2 pt-4">
                <CardTitle className="text-sm flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[type]}`}>{type}</span>
                  <span className="text-gray-400 font-normal text-xs">{accs.length} accounts</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="pb-3">
                <div className="divide-y divide-gray-50">
                  {accs.map((acc) => (
                    <div key={acc.id} className="flex items-center gap-4 py-2.5">
                      <span className="text-xs font-mono text-gray-400 w-12 shrink-0">{acc.account_code}</span>
                      <span className="text-sm text-gray-900 flex-1">{acc.account_name}</span>
                      {acc.account_subtype && (
                        <span className="text-xs text-gray-400">{acc.account_subtype}</span>
                      )}
                      <Badge variant={acc.is_active ? "secondary" : "outline"} className={acc.is_active ? "text-xs bg-green-100 text-green-700" : "text-xs text-gray-400"}>
                        {acc.is_active ? "Active" : "Archived"}
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* New Account Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">New Account</h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500">Account Code</label>
                <input
                  value={newAcc.account_code}
                  onChange={(e) => setNewAcc({ ...newAcc, account_code: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. 1006"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Account Name</label>
                <input
                  value={newAcc.account_name}
                  onChange={(e) => setNewAcc({ ...newAcc, account_name: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. Petty Cash"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">Account Type</label>
                <select
                  value={newAcc.account_type}
                  onChange={(e) => setNewAcc({ ...newAcc, account_type: e.target.value as AccountType })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">Sub-type (optional)</label>
                <input
                  value={newAcc.account_subtype}
                  onChange={(e) => setNewAcc({ ...newAcc, account_subtype: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. Current Asset"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setShowModal(false)}
                className="flex-1 text-sm text-gray-600 border border-gray-200 py-1.5 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveAccount}
                disabled={saving}
                className="flex-1 text-sm bg-blue-600 text-white py-1.5 rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save Account"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
