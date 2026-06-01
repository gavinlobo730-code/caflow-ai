"use client";
export const runtime = "edge";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, Search, Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Account, AccountType } from "@/lib/types";

const MOCK_ACCOUNTS: Account[] = [
  { id: "acc-001", account_code: "1001", account_name: "Cash in Hand", account_type: "Asset", account_subtype: "Current Asset", is_active: true },
  { id: "acc-002", account_code: "1002", account_name: "Bank — HDFC Current Account", account_type: "Asset", account_subtype: "Current Asset", is_active: true },
  { id: "acc-003", account_code: "1003", account_name: "Trade Receivables", account_type: "Asset", account_subtype: "Current Asset", is_active: true },
  { id: "acc-004", account_code: "1004", account_name: "GST Input Tax Credit", account_type: "Asset", account_subtype: "Current Asset", is_active: true },
  { id: "acc-005", account_code: "1005", account_name: "Advance Tax Paid", account_type: "Asset", account_subtype: "Current Asset", is_active: true },
  { id: "acc-006", account_code: "1101", account_name: "Office Equipment", account_type: "Asset", account_subtype: "Fixed Asset", is_active: true },
  { id: "acc-007", account_code: "1102", account_name: "Furniture & Fixtures", account_type: "Asset", account_subtype: "Fixed Asset", is_active: true },
  { id: "acc-008", account_code: "2001", account_name: "Trade Payables", account_type: "Liability", account_subtype: "Current Liability", is_active: true },
  { id: "acc-009", account_code: "2002", account_name: "GST Output Tax Payable", account_type: "Liability", account_subtype: "Current Liability", is_active: true },
  { id: "acc-010", account_code: "2003", account_name: "TDS Payable", account_type: "Liability", account_subtype: "Current Liability", is_active: true },
  { id: "acc-011", account_code: "2004", account_name: "Salary Payable", account_type: "Liability", account_subtype: "Current Liability", is_active: true },
  { id: "acc-012", account_code: "2101", account_name: "Bank Loan — Term Loan", account_type: "Liability", account_subtype: "Long-term Liability", is_active: true },
  { id: "acc-013", account_code: "3001", account_name: "Capital Account", account_type: "Equity", account_subtype: "Owner Equity", is_active: true },
  { id: "acc-014", account_code: "3002", account_name: "Retained Earnings", account_type: "Equity", account_subtype: "Owner Equity", is_active: true },
  { id: "acc-015", account_code: "4001", account_name: "Professional Fees — GST Clients", account_type: "Income", account_subtype: "Revenue", is_active: true },
  { id: "acc-016", account_code: "4002", account_name: "Professional Fees — ITR Clients", account_type: "Income", account_subtype: "Revenue", is_active: true },
  { id: "acc-017", account_code: "4003", account_name: "Audit Fees", account_type: "Income", account_subtype: "Revenue", is_active: true },
  { id: "acc-018", account_code: "5001", account_name: "Salary Expense", account_type: "Expense", account_subtype: "Operating Expense", is_active: true },
  { id: "acc-019", account_code: "5002", account_name: "Office Rent", account_type: "Expense", account_subtype: "Operating Expense", is_active: true },
  { id: "acc-020", account_code: "5003", account_name: "Software Subscriptions", account_type: "Expense", account_subtype: "Operating Expense", is_active: true },
  { id: "acc-021", account_code: "5004", account_name: "Bank Charges", account_type: "Expense", account_subtype: "Operating Expense", is_active: true },
  { id: "acc-022", account_code: "5005", account_name: "Depreciation — Equipment", account_type: "Expense", account_subtype: "Non-cash Expense", is_active: true },
];

const TYPE_COLORS: Record<AccountType, string> = {
  Asset: "bg-blue-100 text-blue-700",
  Liability: "bg-red-100 text-red-700",
  Equity: "bg-purple-100 text-purple-700",
  Income: "bg-green-100 text-green-700",
  Expense: "bg-orange-100 text-orange-700",
};

const ACCOUNT_TYPES: AccountType[] = ["Asset", "Liability", "Equity", "Income", "Expense"];

export default function ChartOfAccountsPage() {
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [newAcc, setNewAcc] = useState({ account_code: "", account_name: "", account_type: "Asset" as AccountType, account_subtype: "" });

  const filtered = MOCK_ACCOUNTS.filter(
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
          <p className="text-sm text-gray-500 mt-0.5">{MOCK_ACCOUNTS.length} accounts</p>
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
          const accounts = grouped[type];
          if (accounts.length === 0) return null;
          return (
            <Card key={type}>
              <CardHeader className="pb-2 pt-4">
                <CardTitle className="text-sm flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[type]}`}>{type}</span>
                  <span className="text-gray-400 font-normal text-xs">{accounts.length} accounts</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="pb-3">
                <div className="divide-y divide-gray-50">
                  {accounts.map((acc) => (
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
                onClick={() => setShowModal(false)}
                className="flex-1 text-sm bg-blue-600 text-white py-1.5 rounded-md hover:bg-blue-700"
              >
                Save Account
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
