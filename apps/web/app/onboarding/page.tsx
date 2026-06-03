"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Building2, BookOpen, Users, CheckCircle, ChevronRight, ChevronLeft } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";

// ─── Indian states list ────────────────────────────────────────────────────
const INDIAN_STATES = [
  "Andhra Pradesh",
  "Arunachal Pradesh",
  "Assam",
  "Bihar",
  "Chhattisgarh",
  "Goa",
  "Gujarat",
  "Haryana",
  "Himachal Pradesh",
  "Jharkhand",
  "Karnataka",
  "Kerala",
  "Madhya Pradesh",
  "Maharashtra",
  "Manipur",
  "Meghalaya",
  "Mizoram",
  "Nagaland",
  "Odisha",
  "Punjab",
  "Rajasthan",
  "Sikkim",
  "Tamil Nadu",
  "Telangana",
  "Tripura",
  "Uttar Pradesh",
  "Uttarakhand",
  "West Bengal",
  "Delhi",
  "Jammu & Kashmir",
  "Ladakh",
  "Chandigarh",
  "Puducherry",
];

const ENTITY_TYPES = [
  "Individual",
  "Partnership",
  "LLP",
  "Private Limited",
  "Public Limited",
  "Trust",
  "HUF",
];

// ─── CoA accounts to seed (migration 011) ─────────────────────────────────
// Grouped by account type; account_code is the canonical identifier.
const COA_ACCOUNTS: { account_code: string; account_name: string; account_type: string }[] = [
  // Assets (1xxx)
  { account_code: "1001", account_name: "Cash in Hand", account_type: "Asset" },
  { account_code: "1002", account_name: "Petty Cash", account_type: "Asset" },
  { account_code: "1010", account_name: "Bank Account - Current", account_type: "Asset" },
  { account_code: "1011", account_name: "Bank Account - Savings", account_type: "Asset" },
  { account_code: "1020", account_name: "Fixed Deposits", account_type: "Asset" },
  { account_code: "1100", account_name: "Accounts Receivable", account_type: "Asset" },
  { account_code: "1110", account_name: "Advance to Staff", account_type: "Asset" },
  { account_code: "1120", account_name: "TDS Receivable", account_type: "Asset" },
  { account_code: "1130", account_name: "GST Input Credit", account_type: "Asset" },
  { account_code: "1140", account_name: "Prepaid Expenses", account_type: "Asset" },
  { account_code: "1200", account_name: "Stock in Trade", account_type: "Asset" },
  { account_code: "1300", account_name: "Land & Building", account_type: "Asset" },
  { account_code: "1310", account_name: "Plant & Machinery", account_type: "Asset" },
  { account_code: "1320", account_name: "Furniture & Fixtures", account_type: "Asset" },
  { account_code: "1330", account_name: "Computers & Software", account_type: "Asset" },
  { account_code: "1340", account_name: "Vehicles", account_type: "Asset" },
  { account_code: "1350", account_name: "Accumulated Depreciation", account_type: "Asset" },
  // Liabilities (2xxx)
  { account_code: "2001", account_name: "Accounts Payable", account_type: "Liability" },
  { account_code: "2010", account_name: "Outstanding Expenses", account_type: "Liability" },
  { account_code: "2020", account_name: "Advance from Customers", account_type: "Liability" },
  { account_code: "2100", account_name: "TDS Payable", account_type: "Liability" },
  { account_code: "2110", account_name: "GST Output Tax", account_type: "Liability" },
  { account_code: "2120", account_name: "GST TDS Payable", account_type: "Liability" },
  { account_code: "2130", account_name: "Income Tax Payable", account_type: "Liability" },
  { account_code: "2140", account_name: "Provident Fund Payable", account_type: "Liability" },
  { account_code: "2150", account_name: "ESI Payable", account_type: "Liability" },
  { account_code: "2200", account_name: "Short Term Loans", account_type: "Liability" },
  { account_code: "2210", account_name: "Bank Overdraft", account_type: "Liability" },
  { account_code: "2300", account_name: "Long Term Loans", account_type: "Liability" },
  { account_code: "2310", account_name: "Deferred Tax Liability", account_type: "Liability" },
  // Equity (3xxx)
  { account_code: "3001", account_name: "Capital Account", account_type: "Equity" },
  { account_code: "3010", account_name: "Partners Capital", account_type: "Equity" },
  { account_code: "3020", account_name: "Retained Earnings", account_type: "Equity" },
  { account_code: "3030", account_name: "Current Year Profit", account_type: "Equity" },
  { account_code: "3040", account_name: "Drawings Account", account_type: "Equity" },
  // Revenue (4xxx)
  { account_code: "4001", account_name: "Professional Fees", account_type: "Revenue" },
  { account_code: "4010", account_name: "Audit Fees", account_type: "Revenue" },
  { account_code: "4020", account_name: "Tax Consultancy Fees", account_type: "Revenue" },
  { account_code: "4030", account_name: "GST Consultancy Fees", account_type: "Revenue" },
  { account_code: "4040", account_name: "ROC Filing Fees", account_type: "Revenue" },
  { account_code: "4100", account_name: "Interest Income", account_type: "Revenue" },
  { account_code: "4110", account_name: "Dividend Income", account_type: "Revenue" },
  { account_code: "4200", account_name: "Other Income", account_type: "Revenue" },
  // Expenses (5xxx)
  { account_code: "5001", account_name: "Salaries & Wages", account_type: "Expense" },
  { account_code: "5010", account_name: "Staff Welfare", account_type: "Expense" },
  { account_code: "5100", account_name: "Rent", account_type: "Expense" },
  { account_code: "5110", account_name: "Electricity", account_type: "Expense" },
  { account_code: "5120", account_name: "Internet & Phone", account_type: "Expense" },
  { account_code: "5130", account_name: "Office Supplies", account_type: "Expense" },
  { account_code: "5200", account_name: "Professional Fees Paid", account_type: "Expense" },
  { account_code: "5210", account_name: "Software Subscriptions", account_type: "Expense" },
  { account_code: "5300", account_name: "Travel & Conveyance", account_type: "Expense" },
  { account_code: "5310", account_name: "Marketing & Advertising", account_type: "Expense" },
  { account_code: "5400", account_name: "Bank Charges", account_type: "Expense" },
  { account_code: "5410", account_name: "Interest on Loans", account_type: "Expense" },
  { account_code: "5500", account_name: "Depreciation", account_type: "Expense" },
  { account_code: "5600", account_name: "Audit Fees Paid", account_type: "Expense" },
  { account_code: "5900", account_name: "Miscellaneous Expenses", account_type: "Expense" },
];

const COA_GROUPS: { label: string; type: string; color: string }[] = [
  { label: "Assets", type: "Asset", color: "text-blue-700 bg-blue-50" },
  { label: "Liabilities", type: "Liability", color: "text-red-700 bg-red-50" },
  { label: "Equity", type: "Equity", color: "text-purple-700 bg-purple-50" },
  { label: "Revenue", type: "Revenue", color: "text-green-700 bg-green-50" },
  { label: "Expenses", type: "Expense", color: "text-orange-700 bg-orange-50" },
];

// ─── Validation helpers ────────────────────────────────────────────────────
// CGST Act Section 25 — GSTIN format: 2-digit state code + PAN (10 chars) + 1 entity digit + Z + 1 check digit
function validateGSTIN(gstin: string): boolean {
  if (!gstin) return true;
  return /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(gstin);
}

// IT Act Section 139A — PAN format: 5 uppercase letters + 4 digits + 1 uppercase letter
function validatePAN(pan: string): boolean {
  if (!pan) return true;
  return /^[A-Z]{5}[0-9]{4}[A-Z]$/.test(pan);
}

// ─── Types ─────────────────────────────────────────────────────────────────
interface FirmForm {
  name: string;
  pan: string;
  gstin: string;
  phone: string;
  address: string;
  city: string;
  state: string;
  pincode: string;
  [key: string]: string;
}

interface ClientForm {
  [key: string]: string;
  name: string;
  entity_type: string;
  pan: string;
  gstin: string;
  email: string;
  phone: string;
}

const EMPTY_FIRM: FirmForm = {
  name: "",
  pan: "",
  gstin: "",
  phone: "",
  address: "",
  city: "",
  state: "",
  pincode: "",
};

const EMPTY_CLIENT: ClientForm = {
  name: "",
  entity_type: "Individual",
  pan: "",
  gstin: "",
  email: "",
  phone: "",
};

// ─── Step labels ───────────────────────────────────────────────────────────
const STEPS = [
  { label: "Firm Profile", icon: Building2 },
  { label: "Chart of Accounts", icon: BookOpen },
  { label: "First Client", icon: Users },
];

// ─── Main page ─────────────────────────────────────────────────────────────
export default function OnboardingPage() {
  const { user } = useAuth();
  const router = useRouter();
  const supabase = getSupabaseClient();

  const [step, setStep] = useState(1);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [firmForm, setFirmForm] = useState<FirmForm>(EMPTY_FIRM);
  const [clientForm, setClientForm] = useState<ClientForm>(EMPTY_CLIENT);
  const [firmErrors, setFirmErrors] = useState<Partial<Record<keyof FirmForm, string>>>({});
  const [clientErrors, setClientErrors] = useState<Partial<Record<keyof ClientForm, string>>>({});
  const [coaSeeded, setCoaSeeded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ─── Auto-create firm+user from Partner signup localStorage data ──────
  useEffect(() => {
    if (!user) return;
    const currentUser = user; // capture non-null reference
    async function autoCreateFirmFromSignup() {
      const raw = typeof window !== "undefined" ? localStorage.getItem("practicesync_signup") : null;
      if (!raw) return;
      let signupData: { firmName?: string; fullName?: string } = {};
      try { signupData = JSON.parse(raw); } catch { return; }
      if (!signupData.firmName) return;

      // Check if user already has a row
      const { data: existingUser } = await supabase
        .from("users")
        .select("id, firm_id")
        .eq("auth_user_id", currentUser.id)
        .maybeSingle();
      if (existingUser?.firm_id) {
        // Already onboarded — clear storage
        localStorage.removeItem("practicesync_signup");
        setFirmId(existingUser.firm_id);
        return;
      }

      // Create firm row
      const { data: newFirm, error: firmErr } = await supabase
        .from("firms")
        .insert({ name: signupData.firmName.trim(), email: currentUser.email })
        .select("id")
        .single();
      if (firmErr) { console.error("autoCreateFirm firmErr:", firmErr); return; }

      // Create user row
      const { error: userErr } = await supabase.from("users").insert({
        auth_user_id: currentUser.id,
        firm_id: newFirm.id,
        full_name: signupData.fullName?.trim() ?? currentUser.email,
        email: currentUser.email,
        role: "Partner",
        is_active: true,
      });
      if (userErr) { console.error("autoCreateFirm userErr:", userErr); return; }

      localStorage.removeItem("practicesync_signup");
      setFirmId(newFirm.id);
      // Pre-fill firm name in form
      setFirmForm((f) => ({ ...f, name: signupData.firmName ?? f.name }));
    }
    autoCreateFirmFromSignup();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // ─── Load firm_id on mount ────────────────────────────────────────────
  const loadFirmId = useCallback(async () => {
    if (!user) return;
    const { data } = await supabase
      .from("users")
      .select("firm_id")
      .eq("auth_user_id", user.id)
      .maybeSingle();
    if (data?.firm_id) setFirmId(data.firm_id);
  }, [user, supabase]);

  useEffect(() => {
    loadFirmId();
  }, [loadFirmId]);

  // ─── Redirect away if onboarding not needed ────────────────────────────
  useEffect(() => {
    if (!user || !firmId) return;
    async function checkAlreadyOnboarded() {
      const { data: firmData } = await supabase
        .from("firms")
        .select("name")
        .eq("id", firmId)
        .maybeSingle();
      const { count } = await supabase
        .from("chart_of_accounts")
        .select("id", { count: "exact", head: true })
        .eq("firm_id", firmId);
      if (firmData?.name && count && count > 0) {
        router.replace("/");
      }
    }
    checkAlreadyOnboarded();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firmId]);

  // ─── Navigation ───────────────────────────────────────────────────────
  function goNext() { setStep((s) => Math.min(s + 1, 3)); }
  function goBack() { setStep((s) => Math.max(s - 1, 1)); }
  function finish() { router.replace("/"); }

  // ─── Step 1: Save firm profile ────────────────────────────────────────
  function validateFirm(): boolean {
    const errs: Partial<Record<keyof FirmForm, string>> = {};
    if (!firmForm.name.trim()) errs.name = "Firm name is required";
    // IT Act Section 139A — PAN validation
    if (firmForm.pan && !validatePAN(firmForm.pan)) errs.pan = "Invalid PAN (e.g. AABCU9603R)";
    // CGST Act Section 25 — GSTIN validation
    if (firmForm.gstin && !validateGSTIN(firmForm.gstin)) errs.gstin = "Invalid GSTIN (e.g. 27AABCU9603R1ZX)";
    if (firmForm.pincode && !/^[0-9]{6}$/.test(firmForm.pincode)) errs.pincode = "Pincode must be 6 digits";
    setFirmErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function saveFirmProfile() {
    if (!validateFirm()) return;
    if (!firmId) { setError("No firm found for your account"); return; }
    setSaving(true);
    setError(null);
    try {
      const { error: updateError } = await supabase
        .from("firms")
        .update({
          name: firmForm.name.trim(),
          pan: firmForm.pan.trim() || null,
          gst_number: firmForm.gstin.trim() || null,
          phone: firmForm.phone.trim() || null,
          address_line1: firmForm.address.trim() || null,
          city: firmForm.city.trim() || null,
          state: firmForm.state || null,
          pincode: firmForm.pincode.trim() || null,
        })
        .eq("id", firmId);
      if (updateError) throw updateError;
      goNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save firm profile");
    } finally {
      setSaving(false);
    }
  }

  // ─── Step 2: Seed Chart of Accounts ──────────────────────────────────
  async function seedCoA() {
    if (!firmId) { setError("No firm found for your account"); return; }
    setSaving(true);
    setError(null);
    try {
      const rows = COA_ACCOUNTS.map((acc) => ({
        firm_id: firmId,
        account_code: acc.account_code,
        account_name: acc.account_name,
        account_type: acc.account_type,
        is_active: true,
      }));
      // ON CONFLICT (firm_id, account_code) DO NOTHING — use ignoreDuplicates
      const { error: insertError } = await supabase
        .from("chart_of_accounts")
        .insert(rows, { count: "exact" });
      // Ignore duplicate-key errors (23505) — they mean it's already seeded
      if (insertError && !insertError.message.includes("duplicate") && insertError.code !== "23505") {
        throw insertError;
      }
      setCoaSeeded(true);
      goNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to seed chart of accounts");
    } finally {
      setSaving(false);
    }
  }

  // ─── Step 3: Add first client ─────────────────────────────────────────
  function validateClient(): boolean {
    const errs: Partial<Record<keyof ClientForm, string>> = {};
    if (!clientForm.name.trim()) errs.name = "Client name is required";
    if (!clientForm.entity_type) errs.entity_type = "Entity type is required";
    // IT Act Section 139A — PAN validation
    if (clientForm.pan && !validatePAN(clientForm.pan)) errs.pan = "Invalid PAN (e.g. AABCU9603R)";
    // CGST Act Section 25 — GSTIN validation
    if (clientForm.gstin && !validateGSTIN(clientForm.gstin)) errs.gstin = "Invalid GSTIN (e.g. 27AABCU9603R1ZX)";
    if (clientForm.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientForm.email))
      errs.email = "Invalid email address";
    setClientErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function saveClient() {
    if (!validateClient()) return;
    if (!firmId) { setError("No firm found for your account"); return; }
    setSaving(true);
    setError(null);
    try {
      const { error: insertError } = await supabase.from("clients").insert({
        firm_id: firmId,
        name: clientForm.name.trim(),
        entity_type: clientForm.entity_type,
        pan: clientForm.pan.trim() || null,
        gstin: clientForm.gstin.trim() || null,
        email: clientForm.email.trim() || null,
        phone: clientForm.phone.trim() || null,
      });
      if (insertError) throw insertError;
      finish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add client");
    } finally {
      setSaving(false);
    }
  }

  // ─── Reusable field component ─────────────────────────────────────────
  function Field<T extends Record<string, string>>({
    label,
    field,
    form,
    setForm,
    errors,
    type = "text",
    placeholder,
    hint,
    required,
  }: {
    label: string;
    field: keyof T;
    form: T;
    setForm: React.Dispatch<React.SetStateAction<T>>;
    errors: Partial<Record<keyof T, string>>;
    type?: string;
    placeholder?: string;
    hint?: string;
    required?: boolean;
  }) {
    return (
      <div>
        <label className="text-xs font-medium text-gray-500 block mb-1">
          {label}
          {required && <span className="text-red-500 ml-0.5">*</span>}
        </label>
        <input
          type={type}
          value={form[field] as string}
          onChange={(e) => {
            setForm((prev) => ({ ...prev, [field]: e.target.value }));
            if (errors[field]) {
              // clear error on change — handled by re-validate on submit
            }
          }}
          placeholder={placeholder}
          className={`w-full text-sm text-gray-900 border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50 ${
            errors[field] ? "border-red-400 bg-red-50" : "border-gray-200"
          }`}
        />
        {hint && !errors[field] && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
        {errors[field] && <p className="text-xs text-red-500 mt-1">{errors[field] as string}</p>}
      </div>
    );
  }

  // ─── Progress bar ─────────────────────────────────────────────────────
  function ProgressBar() {
    return (
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          {STEPS.map((s, i) => {
            const n = i + 1;
            const done = step > n;
            const active = step === n;
            return (
              <div key={s.label} className="flex items-center flex-1">
                <div className="flex items-center gap-2 shrink-0">
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
                      done
                        ? "bg-blue-600 text-white"
                        : active
                        ? "bg-blue-600 text-white ring-4 ring-blue-100"
                        : "bg-gray-100 text-gray-400"
                    }`}
                  >
                    {done ? <CheckCircle size={16} /> : n}
                  </div>
                  <span
                    className={`text-sm font-medium hidden sm:block ${
                      active ? "text-blue-700" : done ? "text-gray-700" : "text-gray-400"
                    }`}
                  >
                    {s.label}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className={`flex-1 h-0.5 mx-3 transition-colors ${
                      step > n ? "bg-blue-600" : "bg-gray-200"
                    }`}
                  />
                )}
              </div>
            );
          })}
        </div>
        <p className="text-xs text-gray-400 text-right">Step {step} of {STEPS.length}</p>
      </div>
    );
  }

  // ─── Render ────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-white rounded-2xl shadow-sm border border-gray-100 p-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white text-xs font-bold">CA</span>
            </div>
            <span className="text-sm font-semibold text-gray-700">PracticeSync AI</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mt-4">Welcome! Let&apos;s set up your firm</h1>
          <p className="text-sm text-gray-500 mt-1">This takes about 2 minutes. You can always update these later in Settings.</p>
        </div>

        <ProgressBar />

        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}

        {/* ── Step 1: Firm Profile ────────────────────────────────────────── */}
        {step === 1 && (
          <div>
            <div className="flex items-center gap-2 mb-5">
              <Building2 size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-gray-900">Firm Profile</h2>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="sm:col-span-2">
                <Field
                  label="Firm Name"
                  field="name"
                  form={firmForm}
                  setForm={setFirmForm}
                  errors={firmErrors}
                  placeholder="e.g. Sharma & Associates"
                  required
                />
              </div>
              <Field
                label="PAN"
                field="pan"
                form={firmForm}
                setForm={setFirmForm}
                errors={firmErrors}
                placeholder="e.g. AABCU9603R"
                hint="IT Act §139A — 10-char PAN"
              />
              <Field
                label="GSTIN (optional)"
                field="gstin"
                form={firmForm}
                setForm={setFirmForm}
                errors={firmErrors}
                placeholder="e.g. 27AABCU9603R1ZX"
                hint="CGST Act §25 — 15-char GSTIN"
              />
              <Field
                label="Phone"
                field="phone"
                form={firmForm}
                setForm={setFirmForm}
                errors={firmErrors}
                type="tel"
                placeholder="+91 98765 43210"
              />
              <div className="sm:col-span-2">
                <Field
                  label="Address"
                  field="address"
                  form={firmForm}
                  setForm={setFirmForm}
                  errors={firmErrors}
                  placeholder="Street, Building, Suite"
                />
              </div>
              <Field
                label="City"
                field="city"
                form={firmForm}
                setForm={setFirmForm}
                errors={firmErrors}
                placeholder="e.g. Mumbai"
              />
              <div>
                <label className="text-xs font-medium text-gray-500 block mb-1">State</label>
                <select
                  value={firmForm.state}
                  onChange={(e) => setFirmForm((p) => ({ ...p, state: e.target.value }))}
                  className="w-full text-sm text-gray-900 border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50"
                >
                  <option value="">Select state…</option>
                  {INDIAN_STATES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <Field
                label="Pincode"
                field="pincode"
                form={firmForm}
                setForm={setFirmForm}
                errors={firmErrors}
                placeholder="e.g. 400001"
                hint="6-digit postal code"
              />
            </div>

            <div className="flex items-center justify-between mt-8 pt-5 border-t border-gray-50">
              <button
                onClick={finish}
                className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
              >
                Skip for now
              </button>
              <button
                onClick={saveFirmProfile}
                disabled={saving}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save & Continue"}
                {!saving && <ChevronRight size={16} />}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Chart of Accounts ───────────────────────────────────── */}
        {step === 2 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <BookOpen size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-gray-900">Chart of Accounts</h2>
            </div>
            <p className="text-sm text-gray-500 mb-5">
              We&apos;ll seed your ledger with {COA_ACCOUNTS.length} standard Indian accounts. You can add, rename or delete them later.
            </p>

            <div className="border border-gray-100 rounded-xl overflow-hidden divide-y divide-gray-50 max-h-80 overflow-y-auto">
              {COA_GROUPS.map((group) => {
                const accounts = COA_ACCOUNTS.filter((a) => a.account_type === group.type);
                return (
                  <div key={group.type}>
                    <div className={`px-4 py-2 flex items-center justify-between ${group.color}`}>
                      <span className="text-xs font-semibold uppercase tracking-wide">{group.label}</span>
                      <span className="text-xs font-medium">{accounts.length} accounts</span>
                    </div>
                    {accounts.map((acc) => (
                      <div key={acc.account_code} className="flex items-center justify-between px-4 py-2 hover:bg-gray-50">
                        <span className="text-sm text-gray-800">{acc.account_name}</span>
                        <span className="text-xs text-gray-400 font-mono">{acc.account_code}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>

            {coaSeeded && (
              <div className="mt-3 flex items-center gap-2 text-sm text-green-700">
                <CheckCircle size={15} />
                Chart of Accounts set up successfully
              </div>
            )}

            <div className="flex items-center justify-between mt-8 pt-5 border-t border-gray-50">
              <div className="flex items-center gap-4">
                <button
                  onClick={goBack}
                  className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <ChevronLeft size={16} /> Back
                </button>
                <button
                  onClick={goNext}
                  className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Skip for now
                </button>
              </div>
              <button
                onClick={seedCoA}
                disabled={saving || coaSeeded}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving ? "Setting up…" : coaSeeded ? "Done" : "Set Up Chart of Accounts"}
                {!saving && !coaSeeded && <ChevronRight size={16} />}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: First Client ────────────────────────────────────────── */}
        {step === 3 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Users size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-gray-900">Add Your First Client</h2>
            </div>
            <p className="text-sm text-gray-500 mb-5">
              Add a client to get started. You can add more from the Clients section.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="sm:col-span-2">
                <Field
                  label="Client Name"
                  field="name"
                  form={clientForm}
                  setForm={setClientForm}
                  errors={clientErrors}
                  placeholder="e.g. Ramesh Kumar or ABC Pvt Ltd"
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 block mb-1">
                  Entity Type<span className="text-red-500 ml-0.5">*</span>
                </label>
                <select
                  value={clientForm.entity_type}
                  onChange={(e) => setClientForm((p) => ({ ...p, entity_type: e.target.value }))}
                  className={`w-full text-sm text-gray-900 border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50 ${
                    clientErrors.entity_type ? "border-red-400 bg-red-50" : "border-gray-200"
                  }`}
                >
                  {ENTITY_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                {clientErrors.entity_type && (
                  <p className="text-xs text-red-500 mt-1">{clientErrors.entity_type}</p>
                )}
              </div>
              <Field
                label="PAN"
                field="pan"
                form={clientForm}
                setForm={setClientForm}
                errors={clientErrors}
                placeholder="e.g. AABCU9603R"
                hint="IT Act §139A — 10-char PAN"
              />
              <Field
                label="GSTIN (optional)"
                field="gstin"
                form={clientForm}
                setForm={setClientForm}
                errors={clientErrors}
                placeholder="e.g. 27AABCU9603R1ZX"
                hint="CGST Act §25 — 15-char GSTIN"
              />
              <Field
                label="Email"
                field="email"
                form={clientForm}
                setForm={setClientForm}
                errors={clientErrors}
                type="email"
                placeholder="client@example.com"
              />
              <Field
                label="Phone"
                field="phone"
                form={clientForm}
                setForm={setClientForm}
                errors={clientErrors}
                type="tel"
                placeholder="+91 98765 43210"
              />
            </div>

            <div className="flex items-center justify-between mt-8 pt-5 border-t border-gray-50">
              <div className="flex items-center gap-4">
                <button
                  onClick={goBack}
                  className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <ChevronLeft size={16} /> Back
                </button>
                <button
                  onClick={finish}
                  className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Skip for now
                </button>
              </div>
              <button
                onClick={saveClient}
                disabled={saving}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving ? "Adding…" : "Add Client & Finish"}
                {!saving && <ChevronRight size={16} />}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
