"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Building2, AlertTriangle, Calendar, LogOut, ShieldCheck, ChevronLeft, User, Palette, Hash, FileText, Mail, Globe2, Scale } from "lucide-react";
import { FormSkeleton } from "@/components/ui/skeleton";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { useRouter } from "next/navigation";
import { RoleGuard } from "@/components/RoleGuard";

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

// ─── Validation helpers ────────────────────────────────────────────────────
// CGST Act Section 25 — GSTIN format: 2-digit state code + PAN (10 chars) + 1 entity digit + Z + 1 check digit
function validateGSTIN(gstin: string): boolean {
  if (!gstin) return true; // Optional field
  return /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(gstin);
}

// IT Act Section 139A — PAN format: 5 uppercase letters + 4 digits + 1 uppercase letter
function validatePAN(pan: string): boolean {
  if (!pan) return true; // Optional field
  return /^[A-Z]{5}[0-9]{4}[A-Z]$/.test(pan);
}

// ─── Financial year computation ────────────────────────────────────────────
// Indian FY: April 1 to March 31
function getCurrentFinancialYear(): { label: string; start: number; end: number } {
  const now = new Date();
  const month = now.getMonth(); // 0-based; March = 2, April = 3
  const year = now.getFullYear();
  const fyStart = month >= 3 ? year : year - 1;
  const fyEnd = fyStart + 1;
  return {
    label: `April ${fyStart} – March ${fyEnd}`,
    start: fyStart,
    end: fyEnd,
  };
}

// ─── Form state type ────────────────────────────────────────────────────────
interface FirmForm {
  name: string;
  gstin: string;
  pan: string;
  icai_mrn: string;
  phone: string;
  email: string;
  website: string;
  address_line1: string;
  city: string;
  state: string;
  pincode: string;
}

const EMPTY_FORM: FirmForm = {
  name: "",
  gstin: "",
  pan: "",
  icai_mrn: "",
  phone: "",
  email: "",
  website: "",
  address_line1: "",
  city: "",
  state: "",
  pincode: "",
};

// ─── Toast component ────────────────────────────────────────────────────────
function Toast({
  message,
  type,
  onClose,
}: {
  message: string;
  type: "success" | "error";
  onClose: () => void;
}) {
  useEffect(() => {
    const timer = setTimeout(onClose, 4000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-sm font-medium transition-all ${
        type === "success"
          ? "bg-green-600 text-white"
          : "bg-red-600 text-white"
      }`}
    >
      <span>{message}</span>
      <button onClick={onClose} className="opacity-70 hover:opacity-100 text-lg leading-none">
        ×
      </button>
    </div>
  );
}

// ─── Field component — module scope (MUST NOT be defined inside SettingsPage:
// an inner component gets a new function identity on every render, causing React
// to unmount/remount the <input> on each keystroke and steal focus after one word.)
function Field({
  label,
  field,
  form,
  onChange,
  errors,
  type = "text",
  placeholder,
  hint,
  required,
  maxLength,
}: {
  label: string;
  field: keyof FirmForm;
  form: FirmForm;
  onChange: (field: keyof FirmForm, value: string) => void;
  errors: Partial<Record<keyof FirmForm, string>>;
  type?: string;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  maxLength?: number;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-[#64748B] block mb-1">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type={type}
        value={form[field]}
        onChange={(e) => onChange(field, e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        className={`w-full text-sm text-[#0F172A] border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC] ${
          errors[field] ? "border-red-400 bg-red-50" : "border-[#E2E8F0]"
        }`}
      />
      {hint && !errors[field] && (
        <p className="text-xs text-[#94A3B8] mt-1">{hint}</p>
      )}
      {errors[field] && (
        <p className="text-xs text-red-500 mt-1">{errors[field]}</p>
      )}
    </div>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const { user, signOut, fullName, refreshUserContext } = useAuth();
  const router = useRouter();
  const supabase = getSupabaseClient();

  const [personalName, setPersonalName] = useState(fullName ?? "");
  const [savingPersonal, setSavingPersonal] = useState(false);

  const [form, setForm] = useState<FirmForm>(EMPTY_FORM);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const [errors, setErrors] = useState<Partial<Record<keyof FirmForm, string>>>({});

  const fy = getCurrentFinancialYear();

  // Sync personalName when fullName resolves from AuthContext (may be null on first render)
  useEffect(() => {
    if (fullName !== null) setPersonalName(fullName);
  }, [fullName]);

  // ─── Save personal profile ───────────────────────────────────────────────
  async function savePersonalProfile() {
    if (!personalName.trim()) {
      setToast({ message: "Full name cannot be empty", type: "error" });
      return;
    }
    setSavingPersonal(true);
    try {
      // Was a direct `supabase.from("users").update(...)`, which has failed with
      // "permission denied for table users" since migration 153 revoked UPDATE
      // on `users` from the `authenticated` role. The revoke was correct — a
      // browser should not be able to write user rows — but nothing replaced the
      // write, so saving a name has been impossible. PATCH /api/identity/me does
      // it server-side, addressing the caller's own row from the verified token.
      const { api } = await import("@/lib/api");
      const res = await api.identity.updateMyProfile(personalName.trim());
      if (!res.success) throw new Error(res.error ?? "Failed to save");
      await refreshUserContext();
      setToast({ message: "Personal profile saved", type: "success" });
    } catch (err) {
      setToast({ message: err instanceof Error ? err.message : "Failed to save", type: "error" });
    } finally {
      setSavingPersonal(false);
    }
  }

  // ─── Load firm data on mount ─────────────────────────────────────────────
  const loadFirmData = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      // Get user's firm_id from users table
      const { data: userData, error: userError } = await supabase
        .from("users")
        .select("firm_id")
        .eq("email", user.email)
        .maybeSingle();

      if (userError) throw userError;
      if (!userData?.firm_id) {
        setLoading(false);
        return;
      }

      setFirmId(userData.firm_id);

      // Fetch firm details
      const { data: firmData, error: firmError } = await supabase
        .from("firms")
        .select("name, email, phone, address_line1, city, state, pincode, gst_number, icai_mrn, pan, website")
        .eq("id", userData.firm_id)
        .single();

      if (firmError) throw firmError;

      setForm({
        name: firmData.name ?? "",
        gstin: firmData.gst_number ?? "",
        pan: firmData.pan ?? "",
        icai_mrn: firmData.icai_mrn ?? "",
        phone: firmData.phone ?? "",
        email: firmData.email ?? "",
        website: firmData.website ?? "",
        address_line1: firmData.address_line1 ?? "",
        city: firmData.city ?? "",
        state: firmData.state ?? "",
        pincode: firmData.pincode ?? "",
      });
      setLoadError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load firm data";
      setToast({ message: msg, type: "error" });
      setLoadError(msg);
    } finally {
      setLoading(false);
    }
  }, [user, supabase]);

  useEffect(() => {
    loadFirmData();
  }, [loadFirmData]);

  // ─── Field change handler ────────────────────────────────────────────────
  function handleChange(field: keyof FirmForm, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    // Clear error on change
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  }

  // ─── Validate form ───────────────────────────────────────────────────────
  function validate(): boolean {
    const newErrors: Partial<Record<keyof FirmForm, string>> = {};

    if (!form.name.trim()) {
      newErrors.name = "Firm name is required";
    }
    if (form.gstin && !validateGSTIN(form.gstin)) {
      // CGST Act Section 25 — GSTIN format validation
      newErrors.gstin = "Invalid GSTIN format (e.g. 27AABCU9603R1ZX)";
    }
    if (form.pan && !validatePAN(form.pan)) {
      // IT Act Section 139A — PAN format validation
      newErrors.pan = "Invalid PAN format (e.g. AABCU9603R)";
    }
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      newErrors.email = "Invalid email address";
    }
    if (form.pincode && !/^[1-9][0-9]{5}$/.test(form.pincode)) {
      newErrors.pincode = "Pincode must be 6 digits";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }

  // ─── Save handler ────────────────────────────────────────────────────────
  async function handleSave() {
    if (!validate()) return;
    if (!firmId) {
      setToast({ message: "No firm found for your account", type: "error" });
      return;
    }

    setSaving(true);
    try {
      const { error } = await supabase
        .from("firms")
        .update({
          name: form.name.trim(),
          email: form.email.trim(),
          phone: form.phone.trim() || null,
          address_line1: form.address_line1.trim() || null,
          city: form.city.trim() || null,
          state: form.state || null,
          pincode: form.pincode.trim() || null,
          gst_number: form.gstin.trim() || null,
          pan: form.pan.trim() || null,
          website: form.website.trim() || null,
          icai_mrn: form.icai_mrn.trim() || null,
        })
        .eq("id", firmId);

      if (error) throw error;
      setToast({ message: "Firm profile saved successfully", type: "success" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save";
      setToast({ message: msg, type: "error" });
    } finally {
      setSaving(false);
    }
  }

  // ─── Sign out handler ────────────────────────────────────────────────────
  async function handleSignOut() {
    await signOut();
    router.push("/login");
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-xs text-[#94A3B8] hover:text-[#475569] transition-colors mb-1"
        >
          <ChevronLeft size={13} />
          Dashboard
        </Link>
        <h1 className="text-xl font-semibold text-[#0F172A]">Settings</h1>
        <p className="text-sm text-[#64748B] mt-0.5">Firm configuration and preferences</p>
      </div>

      {/* ── Personal Profile — all users ──────────────────────────────── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <User size={15} className="text-[#64748B]" />
          <h2 className="text-sm font-semibold text-[#0F172A]">Personal Profile</h2>
        </div>
        <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-[#64748B] block mb-1">
              Full Name<span className="text-red-500 ml-0.5">*</span>
            </label>
            <input
              type="text"
              value={personalName}
              onChange={(e) => setPersonalName(e.target.value)}
              placeholder="e.g. CA Gavin Lobo"
              className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-[#64748B] block mb-1">Email</label>
            <input
              type="email"
              value={user?.email ?? ""}
              disabled
              className="w-full text-sm text-[#94A3B8] border border-[#E2E8F0] rounded-lg px-3 py-2 bg-[#F8FAFC] cursor-not-allowed"
            />
            <p className="text-xs text-[#94A3B8] mt-1">Email cannot be changed here</p>
          </div>
        </div>
        <div className="px-5 py-3 border-t border-gray-50 flex justify-end">
          <button
            onClick={savePersonalProfile}
            disabled={savingPersonal}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {savingPersonal ? "Saving…" : "Save Profile"}
          </button>
        </div>
      </div>

      {/* ── Firm Profile — Partner only (firm financials) ────────────────── */}
      <RoleGuard allowed={["Partner"]} redirect={false}>
      {/* ── Firm Profile ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Building2 size={15} className="text-[#64748B]" />
          <h2 className="text-sm font-semibold text-[#0F172A]">Firm Profile</h2>
        </div>

        {loadError && !loading && (
          <div className="mx-5 mt-4 flex items-center justify-between gap-3 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
            <p className="text-xs text-red-700">
              Couldn&apos;t load your saved firm profile — the form below may not reflect what&apos;s saved. {loadError}
            </p>
            <button onClick={loadFirmData} className="text-xs px-3 py-1.5 border border-red-200 rounded-lg hover:bg-red-100 text-red-700 shrink-0">
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <div className="px-5 py-5"><FormSkeleton fields={6} /></div>
        ) : (
          <div className="px-5 py-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Row 1: Firm name spans full width */}
              <div className="sm:col-span-2">
                <Field label="Firm Name" field="name" form={form} onChange={handleChange} errors={errors} placeholder="e.g. Gavin Lobo & Associates" required />
              </div>

              {/* Row 2: GSTIN + PAN */}
              <Field
                label="GSTIN"
                field="gstin"
                form={form}
                onChange={handleChange}
                errors={errors}
                placeholder="e.g. 27AABCU9603R1ZX"
                hint="15-char GST Identification Number (CGST Act §25)"
                maxLength={15}
              />
              <Field
                label="PAN"
                field="pan"
                form={form}
                onChange={handleChange}
                errors={errors}
                placeholder="e.g. AABCU9603R"
                hint="10-char Permanent Account Number (IT Act §139A)"
                maxLength={10}
              />

              {/* Row 3: Registration number + Phone */}
              <Field
                label="Registration / ICAI MRN"
                field="icai_mrn"
                form={form}
                onChange={handleChange}
                errors={errors}
                placeholder="e.g. ICAI-MRN-123456"
              />
              <Field label="Phone" field="phone" form={form} onChange={handleChange} errors={errors} type="tel" placeholder="+91 98765 43210" />

              {/* Row 4: Email + Website */}
              <Field label="Email" field="email" form={form} onChange={handleChange} errors={errors} type="email" placeholder="firm@example.com" />
              <Field label="Website" field="website" form={form} onChange={handleChange} errors={errors} type="url" placeholder="https://example.com" />

              {/* Row 5: Address line 1 spans full */}
              <div className="sm:col-span-2">
                <Field label="Address Line 1" field="address_line1" form={form} onChange={handleChange} errors={errors} placeholder="Street, Building, Suite" />
              </div>

              {/* Row 6: City + State + Pincode */}
              <Field label="City" field="city" form={form} onChange={handleChange} errors={errors} placeholder="e.g. Mumbai" />

              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">State</label>
                <select
                  value={form.state}
                  onChange={(e) => handleChange("state", e.target.value)}
                  className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                >
                  <option value="">Select state…</option>
                  {INDIAN_STATES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>

              <Field label="Pincode" field="pincode" form={form} onChange={handleChange} errors={errors} placeholder="e.g. 400001" hint="6-digit postal code" />
            </div>
          </div>
        )}

        <div className="px-5 py-3 border-t border-gray-50 flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>

      </RoleGuard>

      {/* ── Financial Year (display only) ────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Calendar size={15} className="text-[#64748B]" />
          <h2 className="text-sm font-semibold text-[#0F172A]">Financial Year</h2>
        </div>
        <div className="px-5 py-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-[#475569]">Current Financial Year</span>
            <span className="text-sm font-semibold text-[#0F172A]">{fy.label}</span>
          </div>
          <p className="text-xs text-[#94A3B8]">
            Indian financial year runs April 1 to March 31. This is computed automatically from the current date.
          </p>
        </div>
      </div>

      {/* ── Security / MFA — all users ───────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <ShieldCheck size={15} className="text-blue-600" />
          <h2 className="text-sm font-semibold text-[#0F172A]">Security</h2>
        </div>
        <div className="px-5 py-4 flex items-center justify-between">
          <div>
            <p className="text-sm text-[#334155]">Enable two-factor authentication (authenticator app) for your account.</p>
            <p className="text-xs text-[#94A3B8] mt-0.5">Required for Partner accounts.</p>
          </div>
          <Link
            href="/settings/security"
            className="px-4 py-1.5 border border-blue-200 text-blue-600 text-sm font-medium rounded-lg hover:bg-blue-50 transition-colors whitespace-nowrap"
          >
            Manage 2FA →
          </Link>
        </div>
      </div>

      {/* ── Audit Log — Partner only ─────────────────────────────────────── */}
      <RoleGuard allowed={["Partner"]} redirect={false}>
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
            <ShieldCheck size={15} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-[#0F172A]">Audit Log</h2>
          </div>
          <div className="px-5 py-4 flex items-center justify-between">
            <div>
              <p className="text-sm text-[#334155]">View a timeline of all changes made across clients, journals, compliance and accounts.</p>
              <p className="text-xs text-[#94A3B8] mt-0.5">Partner access only.</p>
            </div>
            <Link
              href="/settings/audit-log"
              className="px-4 py-1.5 border border-blue-300 text-blue-700 text-sm font-medium rounded-lg hover:bg-blue-50 transition-colors"
            >
              View Audit Log →
            </Link>
          </div>
        </div>
      </RoleGuard>

      {/* ── Scheduled Reports ───────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Calendar size={15} className="text-blue-600" />
          <h2 className="text-sm font-semibold text-[#0F172A]">Scheduled Reports</h2>
        </div>
        <div className="px-5 py-4 flex items-center justify-between">
          <div>
            <p className="text-sm text-[#334155]">Automatically email P&L, GST, TDS, and payroll reports to clients on a schedule.</p>
            <p className="text-xs text-[#94A3B8] mt-0.5">Configure frequency, recipients, and delivery day.</p>
          </div>
          <Link
            href="/settings/scheduled-reports"
            className="px-4 py-1.5 border border-blue-200 text-blue-600 text-sm font-medium rounded-lg hover:bg-blue-50 transition-colors whitespace-nowrap"
          >
            Manage Schedules →
          </Link>
        </div>
      </div>

      {/* ── Firm Branding & Document Customization — Partner only ────────── */}
      <RoleGuard allowed={["Partner"]} redirect={false}>
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
            <Palette size={15} className="text-violet-600" />
            <h2 className="text-sm font-semibold text-[#0F172A]">Branding &amp; Document Customization</h2>
          </div>

          <div className="divide-y divide-[#F8FAFC]">
            <div className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-start gap-3">
                <Palette size={15} className="text-violet-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[#0F172A]">Firm Branding</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">Logo, colors, fonts and social links applied to all client documents.</p>
                </div>
              </div>
              <Link
                href="/settings/branding"
                className="px-4 py-1.5 border border-violet-200 text-violet-700 text-sm font-medium rounded-lg hover:bg-violet-50 transition-colors whitespace-nowrap"
              >
                Customize →
              </Link>
            </div>

            <div className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-start gap-3">
                <Hash size={15} className="text-blue-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[#0F172A]">Invoice Settings</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">Invoice numbering format, bank details, UPI, and footer text.</p>
                </div>
              </div>
              <Link
                href="/settings/invoice-settings"
                className="px-4 py-1.5 border border-blue-200 text-blue-600 text-sm font-medium rounded-lg hover:bg-blue-50 transition-colors whitespace-nowrap"
              >
                Configure →
              </Link>
            </div>

            <div className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-start gap-3">
                <FileText size={15} className="text-indigo-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[#0F172A]">Invoice Templates</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">Layout styles: Classic, Modern, Professional CA, Corporate, Minimal.</p>
                </div>
              </div>
              <Link
                href="/settings/invoice-templates"
                className="px-4 py-1.5 border border-indigo-200 text-indigo-700 text-sm font-medium rounded-lg hover:bg-indigo-50 transition-colors whitespace-nowrap"
              >
                Manage →
              </Link>
            </div>

            <div className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-start gap-3">
                <Hash size={15} className="text-violet-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[#0F172A]">Firm HSN/SAC Library</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">The HSN/SAC codes your firm bills against. You own and curate this list — Caflow does not ship or suggest classifications.</p>
                </div>
              </div>
              <Link
                href="/settings/firm-hsn-library"
                className="px-4 py-1.5 border border-violet-200 text-violet-700 text-sm font-medium rounded-lg hover:bg-violet-50 transition-colors whitespace-nowrap"
              >
                Manage →
              </Link>
            </div>

            <div className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-start gap-3">
                <Scale size={15} className="text-indigo-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[#0F172A]">Statutory Values</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">Your firm&apos;s reading of the state professional-tax notifications. Twenty-two states levy it and four are built in; the rest deduct nothing until you record them here, once, for every client.</p>
                </div>
              </div>
              <Link
                href="/settings/statutory-values"
                className="px-4 py-1.5 border border-indigo-200 text-indigo-700 text-sm font-medium rounded-lg hover:bg-indigo-50 transition-colors whitespace-nowrap"
              >
                Manage →
              </Link>
            </div>

            <div className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-start gap-3">
                <Globe2 size={15} className="text-sky-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[#0F172A]">DTAA Treaty Rates</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">Your firm&apos;s reading of the treaty rates it withholds under, per country and nature of income. Ships empty and is never seeded — India has agreements with over ninety countries.</p>
                </div>
              </div>
              <Link
                href="/settings/treaty-rates"
                className="px-4 py-1.5 border border-sky-200 text-sky-700 text-sm font-medium rounded-lg hover:bg-sky-50 transition-colors whitespace-nowrap"
              >
                Manage →
              </Link>
            </div>

            <div className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-start gap-3">
                <Mail size={15} className="text-teal-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-[#0F172A]">Email Templates</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">Customize emails sent for invoices, engagements, documents, and reminders.</p>
                </div>
              </div>
              <Link
                href="/settings/email-templates"
                className="px-4 py-1.5 border border-teal-200 text-teal-700 text-sm font-medium rounded-lg hover:bg-teal-50 transition-colors whitespace-nowrap"
              >
                Edit →
              </Link>
            </div>
          </div>
        </div>
      </RoleGuard>

      {/* ── Danger Zone ──────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-red-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-red-50">
          <AlertTriangle size={15} className="text-red-500" />
          <h2 className="text-sm font-semibold text-red-700">Danger Zone</h2>
        </div>
        <div className="px-5 py-4 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-[#0F172A]">Sign Out</p>
            <p className="text-xs text-[#94A3B8] mt-0.5">
              You will be redirected to the login page.
            </p>
          </div>
          <button
            onClick={handleSignOut}
            className="flex items-center gap-2 px-4 py-1.5 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors"
          >
            <LogOut size={14} />
            Sign Out
          </button>
        </div>
      </div>
    </div>
  );
}
