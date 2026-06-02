"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Building2, AlertTriangle, Calendar, LogOut, ShieldCheck } from "lucide-react";
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

// ─── Main page ──────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const supabase = getSupabaseClient();

  const [form, setForm] = useState<FirmForm>(EMPTY_FORM);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const [errors, setErrors] = useState<Partial<Record<keyof FirmForm, string>>>({});

  const fy = getCurrentFinancialYear();

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
        .select("name, email, phone, address_line1, city, state, pincode, gst_number, icai_mrn")
        .eq("id", userData.firm_id)
        .single();

      if (firmError) throw firmError;

      setForm({
        name: firmData.name ?? "",
        gstin: firmData.gst_number ?? "",
        pan: "", // pan column not yet in schema — UI only for now
        icai_mrn: firmData.icai_mrn ?? "",
        phone: firmData.phone ?? "",
        email: firmData.email ?? "",
        website: "", // website column not yet in schema — UI only for now
        address_line1: firmData.address_line1 ?? "",
        city: firmData.city ?? "",
        state: firmData.state ?? "",
        pincode: firmData.pincode ?? "",
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load firm data";
      setToast({ message: msg, type: "error" });
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
    if (form.pincode && !/^[0-9]{6}$/.test(form.pincode)) {
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

  // ─── Input component ─────────────────────────────────────────────────────
  function Field({
    label,
    field,
    type = "text",
    placeholder,
    hint,
    required,
  }: {
    label: string;
    field: keyof FirmForm;
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
          value={form[field]}
          onChange={(e) => handleChange(field, e.target.value)}
          placeholder={placeholder}
          className={`w-full text-sm text-gray-900 border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50 ${
            errors[field] ? "border-red-400 bg-red-50" : "border-gray-200"
          }`}
        />
        {hint && !errors[field] && (
          <p className="text-xs text-gray-400 mt-1">{hint}</p>
        )}
        {errors[field] && (
          <p className="text-xs text-red-500 mt-1">{errors[field]}</p>
        )}
      </div>
    );
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
        <h1 className="text-xl font-semibold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-0.5">Firm configuration and preferences</p>
      </div>

      {/* ── Firm Profile — Partner only (firm financials) ────────────────── */}
      <RoleGuard allowed={["Partner"]} redirect={false}>
      {/* ── Firm Profile ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Building2 size={15} className="text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-900">Firm Profile</h2>
        </div>

        {loading ? (
          <div className="px-5 py-10 text-center text-sm text-gray-400">Loading…</div>
        ) : (
          <div className="px-5 py-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Row 1: Firm name spans full width */}
              <div className="sm:col-span-2">
                <Field label="Firm Name" field="name" placeholder="e.g. Gavin Lobo & Associates" required />
              </div>

              {/* Row 2: GSTIN + PAN */}
              <Field
                label="GSTIN"
                field="gstin"
                placeholder="e.g. 27AABCU9603R1ZX"
                hint="15-char GST Identification Number (CGST Act §25)"
              />
              <Field
                label="PAN"
                field="pan"
                placeholder="e.g. AABCU9603R"
                hint="10-char Permanent Account Number (IT Act §139A)"
              />

              {/* Row 3: Registration number + Phone */}
              <Field
                label="Registration / ICAI MRN"
                field="icai_mrn"
                placeholder="e.g. ICAI-MRN-123456"
              />
              <Field label="Phone" field="phone" type="tel" placeholder="+91 98765 43210" />

              {/* Row 4: Email + Website */}
              <Field label="Email" field="email" type="email" placeholder="firm@example.com" />
              <Field label="Website" field="website" type="url" placeholder="https://example.com" />

              {/* Row 5: Address line 1 spans full */}
              <div className="sm:col-span-2">
                <Field label="Address Line 1" field="address_line1" placeholder="Street, Building, Suite" />
              </div>

              {/* Row 6: City + State + Pincode */}
              <Field label="City" field="city" placeholder="e.g. Mumbai" />

              <div>
                <label className="text-xs font-medium text-gray-500 block mb-1">State</label>
                <select
                  value={form.state}
                  onChange={(e) => handleChange("state", e.target.value)}
                  className="w-full text-sm text-gray-900 border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50"
                >
                  <option value="">Select state…</option>
                  {INDIAN_STATES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>

              <Field label="Pincode" field="pincode" placeholder="e.g. 400001" hint="6-digit postal code" />
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
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Calendar size={15} className="text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-900">Financial Year</h2>
        </div>
        <div className="px-5 py-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">Current Financial Year</span>
            <span className="text-sm font-semibold text-gray-900">{fy.label}</span>
          </div>
          <p className="text-xs text-gray-400">
            Indian financial year runs April 1 to March 31. This is computed automatically from the current date.
          </p>
        </div>
      </div>

      {/* ── Audit Log — Partner only ─────────────────────────────────────── */}
      <RoleGuard allowed={["Partner"]} redirect={false}>
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
            <ShieldCheck size={15} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-gray-900">Audit Log</h2>
          </div>
          <div className="px-5 py-4 flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-700">View a timeline of all changes made across clients, journals, compliance and accounts.</p>
              <p className="text-xs text-gray-400 mt-0.5">Partner access only.</p>
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

      {/* ── Danger Zone ──────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-red-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-red-50">
          <AlertTriangle size={15} className="text-red-500" />
          <h2 className="text-sm font-semibold text-red-700">Danger Zone</h2>
        </div>
        <div className="px-5 py-4 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-900">Sign Out</p>
            <p className="text-xs text-gray-400 mt-0.5">
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
