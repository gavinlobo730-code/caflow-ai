"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Search, Plus, Pencil, Archive, ArchiveRestore, Download } from "lucide-react";
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

const SCHEDULE_III_MAPPINGS = [
  "Fixed Assets", "Capital Work in Progress", "Goodwill & Intangibles",
  "Long-term Investments", "Deferred Tax Asset",
  "Inventories", "Trade Receivables", "Cash & Cash Equivalents",
  "Short-term Loans & Advances", "Other Current Assets",
  "Share Capital", "Reserves & Surplus",
  "Long-term Borrowings", "Deferred Tax Liability", "Long-term Provisions",
  "Short-term Borrowings", "Trade Payables", "Other Current Liabilities", "Short-term Provisions",
  "Revenue from Operations", "Other Income",
  "Cost of Materials Consumed", "Employee Benefits Expense",
  "Finance Costs", "Depreciation & Amortisation",
  "Other Expenses",
];

const TAX_CATEGORIES = [
  "Taxable", "Exempt", "Nil Rated", "Non-GST",
  "RCM (Reverse Charge)", "Input Tax Credit", "Output Tax",
  "TDS Deductible", "TDS Receivable", "Not Applicable",
];

const EMPTY_FORM = {
  account_code: "",
  account_name: "",
  account_type: "Asset" as AccountType,
  account_subtype: "",
  parent_group: "",
  sub_group: "",
  tax_category: "",
  schedule_iii_mapping: "",
};

// Standard Indian CA practice COA default pack
const DEFAULT_PACK: Array<{
  account_code: string; account_name: string; account_type: AccountType;
  account_subtype: string; parent_group: string; sub_group: string;
  tax_category: string; schedule_iii_mapping: string;
}> = [
  { account_code: "1001", account_name: "Cash in Hand",                account_type: "Asset",     account_subtype: "Cash",          parent_group: "Current Assets",  sub_group: "Cash & Bank",            tax_category: "Not Applicable",  schedule_iii_mapping: "Cash & Cash Equivalents" },
  { account_code: "1002", account_name: "Petty Cash",                  account_type: "Asset",     account_subtype: "Cash",          parent_group: "Current Assets",  sub_group: "Cash & Bank",            tax_category: "Not Applicable",  schedule_iii_mapping: "Cash & Cash Equivalents" },
  { account_code: "1101", account_name: "HDFC Bank Current Account",   account_type: "Asset",     account_subtype: "Bank",          parent_group: "Current Assets",  sub_group: "Cash & Bank",            tax_category: "Not Applicable",  schedule_iii_mapping: "Cash & Cash Equivalents" },
  { account_code: "1102", account_name: "SBI Bank Current Account",    account_type: "Asset",     account_subtype: "Bank",          parent_group: "Current Assets",  sub_group: "Cash & Bank",            tax_category: "Not Applicable",  schedule_iii_mapping: "Cash & Cash Equivalents" },
  { account_code: "1201", account_name: "Accounts Receivable",         account_type: "Asset",     account_subtype: "Receivable",    parent_group: "Current Assets",  sub_group: "Trade Receivables",      tax_category: "Not Applicable",  schedule_iii_mapping: "Trade Receivables" },
  { account_code: "1301", account_name: "GST Input Credit - CGST",     account_type: "Asset",     account_subtype: "Tax",           parent_group: "Current Assets",  sub_group: "Tax Assets",             tax_category: "Input Tax Credit", schedule_iii_mapping: "Other Current Assets" },
  { account_code: "1302", account_name: "GST Input Credit - SGST",     account_type: "Asset",     account_subtype: "Tax",           parent_group: "Current Assets",  sub_group: "Tax Assets",             tax_category: "Input Tax Credit", schedule_iii_mapping: "Other Current Assets" },
  { account_code: "1303", account_name: "GST Input Credit - IGST",     account_type: "Asset",     account_subtype: "Tax",           parent_group: "Current Assets",  sub_group: "Tax Assets",             tax_category: "Input Tax Credit", schedule_iii_mapping: "Other Current Assets" },
  { account_code: "1401", account_name: "Advance Tax Paid",            account_type: "Asset",     account_subtype: "Tax",           parent_group: "Current Assets",  sub_group: "Tax Assets",             tax_category: "Not Applicable",  schedule_iii_mapping: "Short-term Loans & Advances" },
  { account_code: "1402", account_name: "TDS Receivable",              account_type: "Asset",     account_subtype: "Tax",           parent_group: "Current Assets",  sub_group: "Tax Assets",             tax_category: "TDS Receivable",  schedule_iii_mapping: "Short-term Loans & Advances" },
  { account_code: "1501", account_name: "Office Equipment",            account_type: "Asset",     account_subtype: "Fixed Asset",   parent_group: "Non-Current Assets", sub_group: "Fixed Assets",        tax_category: "Taxable",         schedule_iii_mapping: "Fixed Assets" },
  { account_code: "1502", account_name: "Computers & Laptops",         account_type: "Asset",     account_subtype: "Fixed Asset",   parent_group: "Non-Current Assets", sub_group: "Fixed Assets",        tax_category: "Taxable",         schedule_iii_mapping: "Fixed Assets" },
  { account_code: "1503", account_name: "Furniture & Fixtures",        account_type: "Asset",     account_subtype: "Fixed Asset",   parent_group: "Non-Current Assets", sub_group: "Fixed Assets",        tax_category: "Taxable",         schedule_iii_mapping: "Fixed Assets" },
  { account_code: "1601", account_name: "Security Deposits",           account_type: "Asset",     account_subtype: "Other",         parent_group: "Non-Current Assets", sub_group: "Long-term Deposits",  tax_category: "Not Applicable",  schedule_iii_mapping: "Long-term Investments" },
  { account_code: "1602", account_name: "Prepaid Expenses",            account_type: "Asset",     account_subtype: "Other",         parent_group: "Current Assets",  sub_group: "Other Current Assets",   tax_category: "Not Applicable",  schedule_iii_mapping: "Other Current Assets" },
  { account_code: "2001", account_name: "Accounts Payable",            account_type: "Liability", account_subtype: "Payable",       parent_group: "Current Liabilities", sub_group: "Trade Payables",     tax_category: "Not Applicable",  schedule_iii_mapping: "Trade Payables" },
  { account_code: "2101", account_name: "GST Payable - CGST",          account_type: "Liability", account_subtype: "Tax",           parent_group: "Current Liabilities", sub_group: "Tax Liabilities",    tax_category: "Output Tax",      schedule_iii_mapping: "Other Current Liabilities" },
  { account_code: "2102", account_name: "GST Payable - SGST",          account_type: "Liability", account_subtype: "Tax",           parent_group: "Current Liabilities", sub_group: "Tax Liabilities",    tax_category: "Output Tax",      schedule_iii_mapping: "Other Current Liabilities" },
  { account_code: "2103", account_name: "GST Payable - IGST",          account_type: "Liability", account_subtype: "Tax",           parent_group: "Current Liabilities", sub_group: "Tax Liabilities",    tax_category: "Output Tax",      schedule_iii_mapping: "Other Current Liabilities" },
  { account_code: "2201", account_name: "TDS Payable",                 account_type: "Liability", account_subtype: "Tax",           parent_group: "Current Liabilities", sub_group: "Tax Liabilities",    tax_category: "TDS Deductible",  schedule_iii_mapping: "Other Current Liabilities" },
  { account_code: "2202", account_name: "Professional Tax Payable",    account_type: "Liability", account_subtype: "Tax",           parent_group: "Current Liabilities", sub_group: "Tax Liabilities",    tax_category: "Not Applicable",  schedule_iii_mapping: "Other Current Liabilities" },
  { account_code: "2301", account_name: "Salary Payable",              account_type: "Liability", account_subtype: "Payable",       parent_group: "Current Liabilities", sub_group: "Employee Liabilities", tax_category: "Not Applicable", schedule_iii_mapping: "Other Current Liabilities" },
  { account_code: "2401", account_name: "Short Term Loan",             account_type: "Liability", account_subtype: "Loan",          parent_group: "Current Liabilities", sub_group: "Borrowings",         tax_category: "Not Applicable",  schedule_iii_mapping: "Short-term Borrowings" },
  { account_code: "3001", account_name: "Partner Capital Account",     account_type: "Equity",    account_subtype: "Capital",       parent_group: "Equity",          sub_group: "Capital",                tax_category: "Not Applicable",  schedule_iii_mapping: "Share Capital" },
  { account_code: "3002", account_name: "Retained Earnings",           account_type: "Equity",    account_subtype: "Retained",      parent_group: "Equity",          sub_group: "Reserves",               tax_category: "Not Applicable",  schedule_iii_mapping: "Reserves & Surplus" },
  { account_code: "3003", account_name: "Current Year Profit",         account_type: "Equity",    account_subtype: "Retained",      parent_group: "Equity",          sub_group: "Reserves",               tax_category: "Not Applicable",  schedule_iii_mapping: "Reserves & Surplus" },
  { account_code: "4001", account_name: "Audit Fees",                  account_type: "Revenue",   account_subtype: "Professional Fees", parent_group: "Operating Revenue", sub_group: "Professional Fees", tax_category: "Taxable",        schedule_iii_mapping: "Revenue from Operations" },
  { account_code: "4002", account_name: "GST Consultancy Fees",        account_type: "Revenue",   account_subtype: "Professional Fees", parent_group: "Operating Revenue", sub_group: "Professional Fees", tax_category: "Taxable",        schedule_iii_mapping: "Revenue from Operations" },
  { account_code: "4003", account_name: "Income Tax Fees",             account_type: "Revenue",   account_subtype: "Professional Fees", parent_group: "Operating Revenue", sub_group: "Professional Fees", tax_category: "Exempt",         schedule_iii_mapping: "Revenue from Operations" },
  { account_code: "4004", account_name: "MCA/ROC Filing Fees",         account_type: "Revenue",   account_subtype: "Professional Fees", parent_group: "Operating Revenue", sub_group: "Professional Fees", tax_category: "Exempt",         schedule_iii_mapping: "Revenue from Operations" },
  { account_code: "4005", account_name: "Accounting & Bookkeeping Fees", account_type: "Revenue", account_subtype: "Professional Fees", parent_group: "Operating Revenue", sub_group: "Professional Fees", tax_category: "Taxable",        schedule_iii_mapping: "Revenue from Operations" },
  { account_code: "4006", account_name: "TDS Consultancy Fees",        account_type: "Revenue",   account_subtype: "Professional Fees", parent_group: "Operating Revenue", sub_group: "Professional Fees", tax_category: "Exempt",         schedule_iii_mapping: "Revenue from Operations" },
  { account_code: "4007", account_name: "Other Professional Fees",     account_type: "Revenue",   account_subtype: "Professional Fees", parent_group: "Operating Revenue", sub_group: "Professional Fees", tax_category: "Taxable",        schedule_iii_mapping: "Revenue from Operations" },
  { account_code: "4101", account_name: "Interest Income",             account_type: "Revenue",   account_subtype: "Other Income",  parent_group: "Other Income",    sub_group: "Finance Income",         tax_category: "Taxable",         schedule_iii_mapping: "Other Income" },
  { account_code: "4102", account_name: "Miscellaneous Income",        account_type: "Revenue",   account_subtype: "Other Income",  parent_group: "Other Income",    sub_group: "Other Income",           tax_category: "Taxable",         schedule_iii_mapping: "Other Income" },
  { account_code: "5001", account_name: "Staff Salaries",              account_type: "Expense",   account_subtype: "Personnel",     parent_group: "Operating Expenses", sub_group: "Employee Costs",      tax_category: "Not Applicable",  schedule_iii_mapping: "Employee Benefits Expense" },
  { account_code: "5002", account_name: "Staff Bonus",                 account_type: "Expense",   account_subtype: "Personnel",     parent_group: "Operating Expenses", sub_group: "Employee Costs",      tax_category: "Not Applicable",  schedule_iii_mapping: "Employee Benefits Expense" },
  { account_code: "5003", account_name: "Office Rent",                 account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Establishment Costs", tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5004", account_name: "Electricity & Utilities",     account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Establishment Costs", tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5005", account_name: "Internet & Telephone",        account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Establishment Costs", tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5006", account_name: "Office Supplies & Stationery", account_type: "Expense",  account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Establishment Costs", tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5007", account_name: "Software Subscriptions",      account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Technology Costs",    tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5008", account_name: "Professional Development & CPE", account_type: "Expense", account_subtype: "Overhead",     parent_group: "Operating Expenses", sub_group: "Training Costs",      tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5009", account_name: "Travel & Conveyance",         account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Travel Costs",        tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5010", account_name: "Postage & Courier",           account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Establishment Costs", tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5011", account_name: "Bank Charges",                account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Finance Costs",       tax_category: "Exempt",          schedule_iii_mapping: "Finance Costs" },
  { account_code: "5012", account_name: "Professional Fees Paid",      account_type: "Expense",   account_subtype: "Professional",  parent_group: "Operating Expenses", sub_group: "Outsourcing Costs",   tax_category: "TDS Deductible",  schedule_iii_mapping: "Other Expenses" },
  { account_code: "5013", account_name: "Depreciation",                account_type: "Expense",   account_subtype: "Depreciation",  parent_group: "Operating Expenses", sub_group: "Depreciation",        tax_category: "Not Applicable",  schedule_iii_mapping: "Depreciation & Amortisation" },
  { account_code: "5014", account_name: "GST on Expenses",             account_type: "Expense",   account_subtype: "Tax",           parent_group: "Operating Expenses", sub_group: "Tax Expenses",        tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
  { account_code: "5015", account_name: "Miscellaneous Expenses",      account_type: "Expense",   account_subtype: "Overhead",      parent_group: "Operating Expenses", sub_group: "Other Expenses",      tax_category: "Taxable",         schedule_iii_mapping: "Other Expenses" },
];

type CoaRow = Account & { parent_group?: string; sub_group?: string; tax_category?: string; schedule_iii_mapping?: string };

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding");
  return data.firm_id as string;
}

export default function ChartOfAccountsPage() {
  const [accounts, setAccounts] = useState<CoaRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<AccountType | "All">("All");
  const [showArchived, setShowArchived] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<CoaRow | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [loadingPack, setLoadingPack] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();
      const { data, error: err } = await sb
        .from("chart_of_accounts")
        .select("*")
        .eq("firm_id", fid)
        .is("client_id", null)
        .order("account_code");
      if (err) throw new Error(err.message);
      setAccounts((data ?? []) as CoaRow[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function loadDefaultPack() {
    if (!firmId) return;
    if (!confirm("This will load the standard Indian CA practice Chart of Accounts for any missing account codes. Existing accounts will not be changed. Continue?")) return;
    setLoadingPack(true);
    try {
      const sb = getSupabaseClient();
      const existingCodes = new Set(accounts.map(a => a.account_code));
      const toInsert = DEFAULT_PACK.filter(a => !existingCodes.has(a.account_code)).map(a => ({
        ...a,
        firm_id: firmId,
        client_id: null,
        is_active: true,
      }));
      if (toInsert.length === 0) {
        alert("All default accounts are already present.");
        return;
      }
      const { error: err } = await sb.from("chart_of_accounts").insert(toInsert);
      if (err) throw new Error(err.message);
      await load();
      alert(`Loaded ${toInsert.length} default accounts successfully.`);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to load default pack");
    } finally {
      setLoadingPack(false);
    }
  }

  function openCreate() {
    setEditTarget(null);
    setForm(EMPTY_FORM);
    setSaveError(null);
    setModalOpen(true);
  }

  function openEdit(acc: CoaRow) {
    setEditTarget(acc);
    setForm({
      account_code: acc.account_code,
      account_name: acc.account_name,
      account_type: acc.account_type as AccountType,
      account_subtype: acc.account_subtype ?? "",
      parent_group: acc.parent_group ?? "",
      sub_group: acc.sub_group ?? "",
      tax_category: acc.tax_category ?? "",
      schedule_iii_mapping: acc.schedule_iii_mapping ?? "",
    });
    setSaveError(null);
    setModalOpen(true);
  }

  async function handleSave() {
    if (!form.account_code.trim() || !form.account_name.trim() || !firmId) return;

    const code = form.account_code.trim().toUpperCase();
    const name = form.account_name.trim().toLowerCase();
    const isDupCode = accounts.some(a => a.account_code.toUpperCase() === code && a.id !== editTarget?.id);
    const isDupName = accounts.some(a => a.account_name.toLowerCase() === name && a.id !== editTarget?.id);
    if (isDupCode) { setSaveError(`Account code "${code}" already exists`); return; }
    if (isDupName) { setSaveError(`Account name "${form.account_name.trim()}" already exists`); return; }

    setSaving(true);
    setSaveError(null);
    const sb = getSupabaseClient();
    const payload = {
      account_code: form.account_code.trim(),
      account_name: form.account_name.trim(),
      account_type: form.account_type,
      account_subtype: form.account_subtype || null,
      parent_group: form.parent_group || null,
      sub_group: form.sub_group || null,
      tax_category: form.tax_category || null,
      schedule_iii_mapping: form.schedule_iii_mapping || null,
      updated_at: new Date().toISOString(),
    };
    try {
      if (editTarget) {
        const { data, error: err } = await sb
          .from("chart_of_accounts")
          .update(payload)
          .eq("id", editTarget.id)
          .select()
          .single();
        if (err) throw new Error(err.message);
        setAccounts(prev => prev.map(a => a.id === editTarget.id ? data as CoaRow : a));
      } else {
        const { data, error: err } = await sb
          .from("chart_of_accounts")
          .insert({ ...payload, firm_id: firmId, client_id: null, is_active: true })
          .select()
          .single();
        if (err) {
          if (err.code === "23505") throw new Error("An account with this code or name already exists");
          throw new Error(err.message);
        }
        setAccounts(prev => [...prev, data as CoaRow].sort((a, b) => a.account_code.localeCompare(b.account_code)));
      }
      setModalOpen(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function toggleArchive(acc: CoaRow) {
    const sb = getSupabaseClient();
    const { data, error: err } = await sb
      .from("chart_of_accounts")
      .update({ is_active: !acc.is_active, updated_at: new Date().toISOString() })
      .eq("id", acc.id)
      .select()
      .single();
    if (!err && data) setAccounts(prev => prev.map(a => a.id === acc.id ? data as CoaRow : a));
  }

  if (loading) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-4 animate-pulse">
        <div className="h-6 bg-white/[0.08] rounded w-48" />
        {[1,2,3].map(i => <div key={i} className="h-32 bg-[#F1F5F9] rounded-xl" />)}
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

  const activeAccounts = accounts.filter(a => a.is_active);
  const visibleAccounts = accounts.filter(a => {
    if (!showArchived && !a.is_active) return false;
    if (activeTab !== "All" && a.account_type !== activeTab) return false;
    if (search) {
      const q = search.toLowerCase();
      return a.account_name.toLowerCase().includes(q) || a.account_code.includes(q)
        || (a.parent_group ?? "").toLowerCase().includes(q)
        || (a.schedule_iii_mapping ?? "").toLowerCase().includes(q);
    }
    return true;
  });

  const grouped = ACCOUNT_TYPES.reduce<Record<AccountType, CoaRow[]>>((acc, type) => {
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
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Chart of Accounts</h1>
          <p className="text-xs text-[#64748B] mt-0.5">
            Firm master COA — {activeAccounts.length} active accounts · shared across all clients · balances isolated per client
          </p>
        </div>
        <button
          onClick={() => setShowArchived(v => !v)}
          className="text-xs text-[#64748B] border border-[#E2E8F0] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC]"
        >
          {showArchived ? "Hide Archived" : "Show Archived"}
        </button>
        {activeAccounts.length === 0 && (
          <button
            onClick={loadDefaultPack}
            disabled={loadingPack}
            className="flex items-center gap-1.5 text-xs border border-blue-300 text-blue-700 px-3 py-1.5 rounded-md hover:bg-blue-50 disabled:opacity-50"
          >
            <Download size={12} /> {loadingPack ? "Loading…" : "Load Default Pack"}
          </button>
        )}
        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          <Plus size={13} /> New Account
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by code, name, group or Schedule III mapping…"
          className="w-full pl-8 pr-4 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {tabs.map(tab => (
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
        <div className="text-center py-16 space-y-3">
          <p className="text-sm text-[#64748B]">No accounts yet</p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={loadDefaultPack}
              disabled={loadingPack}
              className="flex items-center gap-1.5 text-sm border border-blue-300 text-blue-700 px-4 py-2 rounded-md hover:bg-blue-50 disabled:opacity-50"
            >
              <Download size={13} /> {loadingPack ? "Loading…" : "Load Default Pack"}
            </button>
            <button onClick={openCreate} className="text-sm bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700">
              Add First Account
            </button>
          </div>
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
                  <span className="text-xs text-[#94A3B8]">{accs.length} accounts</span>
                </div>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-[#94A3B8] border-b border-gray-50">
                        <th className="px-5 py-2 text-left font-medium w-16">Code</th>
                        <th className="px-3 py-2 text-left font-medium">Name</th>
                        <th className="px-3 py-2 text-left font-medium">Group</th>
                        <th className="px-3 py-2 text-left font-medium">Schedule III</th>
                        <th className="px-3 py-2 text-left font-medium">Tax</th>
                        <th className="px-3 py-2 text-left font-medium w-16">Status</th>
                        <th className="px-5 py-2 text-right font-medium w-20">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {accs.map(acc => (
                        <tr key={acc.id} className={`hover:bg-[#F8FAFC] group ${!acc.is_active ? "opacity-50" : ""}`}>
                          <td className="px-5 py-2.5 font-mono text-xs text-[#94A3B8]">{acc.account_code}</td>
                          <td className="px-3 py-2.5 text-sm font-medium text-[#0F172A]">
                            {acc.account_name}
                            {acc.account_subtype && (
                              <span className="ml-1.5 text-[10px] text-[#94A3B8]">{acc.account_subtype}</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-xs text-[#64748B]">
                            {acc.parent_group ? (
                              <span>
                                {acc.parent_group}
                                {acc.sub_group && <span className="text-[#94A3B8]"> › {acc.sub_group}</span>}
                              </span>
                            ) : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-xs text-[#64748B]">{acc.schedule_iii_mapping ?? "—"}</td>
                          <td className="px-3 py-2.5 text-xs text-[#64748B]">{acc.tax_category ?? "—"}</td>
                          <td className="px-3 py-2.5">
                            <Badge className={`text-xs ${acc.is_active ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
                              {acc.is_active ? "Active" : "Archived"}
                            </Badge>
                          </td>
                          <td className="px-5 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button onClick={() => openEdit(acc)} className="p-1.5 rounded hover:bg-white/[0.08] text-[#94A3B8] hover:text-[#334155]" title="Edit">
                                <Pencil size={12} />
                              </button>
                              <button onClick={() => toggleArchive(acc)} className="p-1.5 rounded hover:bg-white/[0.08] text-[#94A3B8] hover:text-[#334155]" title={acc.is_active ? "Archive" : "Restore"}>
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
        <div className="fixed inset-0 bg-[#0F172A]/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-sm font-semibold text-[#0F172A] mb-4">
              {editTarget ? "Edit Account" : "New Account"}
            </h2>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Account Code *</label>
                  <input
                    value={form.account_code}
                    onChange={e => setForm({ ...form, account_code: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                    placeholder="e.g. 1006"
                  />
                </div>
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Account Type *</label>
                  <select
                    value={form.account_type}
                    onChange={e => setForm({ ...form, account_type: e.target.value as AccountType, account_subtype: "" })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {ACCOUNT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
              </div>

              <div>
                <label className="text-xs text-[#64748B] font-medium">Account Name *</label>
                <input
                  value={form.account_name}
                  onChange={e => setForm({ ...form, account_name: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. ICICI Bank Savings Account"
                />
              </div>

              <div>
                <label className="text-xs text-[#64748B] font-medium">Sub-type</label>
                <select
                  value={form.account_subtype}
                  onChange={e => setForm({ ...form, account_subtype: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— Select sub-type —</option>
                  {SUBTYPES[form.account_type].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Parent Group</label>
                  <input
                    value={form.parent_group}
                    onChange={e => setForm({ ...form, parent_group: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g. Current Assets"
                  />
                </div>
                <div>
                  <label className="text-xs text-[#64748B] font-medium">Sub Group</label>
                  <input
                    value={form.sub_group}
                    onChange={e => setForm({ ...form, sub_group: e.target.value })}
                    className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g. Cash & Bank"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-[#64748B] font-medium">Tax Category</label>
                <select
                  value={form.tax_category}
                  onChange={e => setForm({ ...form, tax_category: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— Select tax category —</option>
                  {TAX_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>

              <div>
                <label className="text-xs text-[#64748B] font-medium">Schedule III Mapping</label>
                <select
                  value={form.schedule_iii_mapping}
                  onChange={e => setForm({ ...form, schedule_iii_mapping: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— Select Schedule III line —</option>
                  {SCHEDULE_III_MAPPINGS.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
            </div>

            {saveError && (
              <p className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-md">{saveError}</p>
            )}
            <div className="flex gap-2 mt-5">
              <button onClick={() => setModalOpen(false)} className="flex-1 text-sm text-[#475569] border border-[#E2E8F0] py-2 rounded-md hover:bg-[#F8FAFC]">
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
