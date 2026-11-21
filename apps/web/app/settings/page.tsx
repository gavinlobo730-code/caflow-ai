"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Building2, Calendar, User } from "lucide-react";
import { FormSkeleton } from "@/components/ui/skeleton";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { ChangePart, ReadOnlyNotice } from "@/components/settings/ChangePart";
import { useScreenAccess } from "@/lib/access/useScreenAccess";
import { SETTINGS_GROUPS, firmProfileShown, groupFromTab, visibleLinks } from "@/lib/settings/groups";
import { api, type FirmProfile } from "@/lib/api";
import { objectOrNull } from "@/lib/api/shape";
import { gstinProblem } from "@/lib/gst/gstin";
import { isValidPan } from "@/lib/identifiers/pan";
import { RefusalText } from "@/components/auth/RefusalText";
import { isMfaRefusal } from "@/lib/auth/mfaRefusal";
import { PageHeader } from "@/components/ui/page-header";
import { istToday } from "@/lib/dateMath";

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
// CGST Act §25, THROUGH THE ONE BROWSER AUTHORITY. This is the PRACTICE's own
// GSTIN, which `domain/firm/identity` puts on every fee invoice the firm
// raises, and the shape regex that used to live here accepts a transposition.
// `PATCH /api/firms/profile` does test the check digit, so a wrong one was
// refused — after the CA had filled in the rest of the form, with a server
// error rather than a message naming the character. Blank stays valid: the
// field is optional and unregistered is not wrong.
//
// THE SENTENCE IS THE AUTHORITY'S, NOT "Invalid GSTIN format" (sweep-settings-
// hub-1-07). The fixed message called a check-digit mismatch a FORMAT error and
// named no character, and it appeared only after Save with no toast saying the
// save had not been sent — so a CA watching the network saw a later PATCH and
// read the flagged value as saved. `gstinProblem` says what is wrong (length,
// shape, state code, or which check digit the first fourteen compute to),
// shown as soon as fifteen characters are typed, and a refused Save says so.

// IT Act Section 139A — PAN format: 5 uppercase letters + 4 digits + 1 uppercase letter
// IT Act §139A, THROUGH THE ONE BROWSER RULE. This tested the RAW field value
// while `core/validators.validate_pan` on the server strips and uppercases
// first — and the shared `Field` below does not uppercase what is typed, so a
// CA entering their firm's own PAN in lower case, or pasting one with a space,
// was refused here and would have been accepted there.
function validatePAN(pan: string): boolean {
  return isValidPan(pan);
}

// ─── Financial year computation ────────────────────────────────────────────
// Indian FY: April 1 to March 31
function getCurrentFinancialYear(): { label: string; start: number; end: number } {
  const now = istToday();
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
      <span><RefusalText message={message} /></span>
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
      <label className="text-xs font-medium text-ps-label block mb-1">
        {label}
        {required && <span className="text-state-problem ml-0.5">*</span>}
      </label>
      <input aria-label={label}
        type={type}
        value={form[field]}
        onChange={(e) => onChange(field, e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        className={`w-full text-sm text-ps-ink border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg ${
          errors[field] ? "border-red-400 bg-state-problem-surface" : "border-ps-border"
        }`}
      />
      {hint && !errors[field] && (
        <p className="text-xs text-ps-hint mt-1">{hint}</p>
      )}
      {errors[field] && (
        <p className="text-xs text-state-problem mt-1">{errors[field]}</p>
      )}
    </div>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────
function SettingsHome() {
  const { user, fullName, refreshUserContext } = useAuth();
  const tab = useSearchParams()?.get("tab") ?? null;
  const supabase = getSupabaseClient();

  const [personalName, setPersonalName] = useState(fullName ?? "");
  const [savingPersonal, setSavingPersonal] = useState(false);

  const [form, setForm] = useState<FirmForm>(EMPTY_FORM);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = saving || savingPersonal;
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const [errors, setErrors] = useState<Partial<Record<keyof FirmForm, string>>>({});
  // mfa_guard refused the profile: a blank form under it invites typing into
  // something that cannot be loaded or saved until an authenticator is set up.
  const profileLocked = isMfaRefusal(loadError);

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

      // Fetch firm details through the API, not PostgREST. `public.firms`
      // carries TWO GSTIN columns and this screen used to read and write
      // `gst_number`, the one no backend reader reads — so the firm's own fee
      // invoice printed no supplier GSTIN and the CGST/SGST-versus-IGST
      // fallback put the whole tax on a LOCAL supply into IGST.
      // domain/firm/identity.py resolves it; the served `gstin` is the answer.
      const firmRes = await api.firm.profile();
      if (!firmRes.success) throw new Error(firmRes.error ?? "Failed to load firm data");
      const firmData = objectOrNull<FirmProfile>(firmRes.data) ?? {};

      setForm({
        name: firmData.name ?? "",
        gstin: firmData.gstin ?? "",
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
    // A complete GSTIN is checked at the keystroke — the reason the browser
    // mirror exists — and a partial one is left alone until Save, because
    // "this one is 9 characters" while still typing is noise.
    if (field === "gstin" && value.trim().length >= 15) {
      setErrors((prev) => ({ ...prev, gstin: gstinProblem(value) ?? undefined }));
      return;
    }
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
    // CGST Act §25 — shape AND check digit, in the authority's own words.
    const gstinIssue = gstinProblem(form.gstin);
    if (gstinIssue) newErrors.gstin = gstinIssue;
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
    if (!validate()) {
      // Say that NOTHING was sent. A red line under one field reads, to a CA
      // who pressed Save, like a warning on something that saved anyway.
      setToast({ message: "Not saved — correct the highlighted field first.", type: "error" });
      return;
    }
    if (!firmId) {
      setToast({ message: "No firm found for your account", type: "error" });
      return;
    }

    setSaving(true);
    try {
      // PATCH /api/firms/profile, so rbac() runs (Partner-only — this is the
      // practice's own legal identity) and the GSTIN's CHECK DIGIT is tested.
      // The column's CHECK constraint is a shape regex and cannot do that, and
      // a transposition here is wrong on every invoice the firm ever raises.
      const res = await api.firm.saveProfile({
        name: form.name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        address_line1: form.address_line1.trim(),
        city: form.city.trim(),
        state: form.state,
        pincode: form.pincode.trim(),
        gstin: form.gstin.trim(),
        pan: form.pan.trim(),
        website: form.website.trim(),
        icai_mrn: form.icai_mrn.trim(),
      });
      if (!res.success) throw new Error(res.error ?? "Failed to save");
      setToast({ message: "Firm profile saved successfully", type: "success" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save";
      setToast({ message: msg, type: "error" });
    } finally {
      setSaving(false);
    }
  }

  // The tab a person is on (PRE-A-023): the groups are lib/settings/groups.ts, and the forms this page saves in
  // place are shown on the tab that holds them, the links on every tab.
  const group = SETTINGS_GROUPS.find((g) => g.id === groupFromTab(tab)) ?? SETTINGS_GROUPS[0];
  const inline = group.inline ?? [];
  const access = useScreenAccess();
  const links = visibleLinks(group, access);

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <PageHeader
        back={{ href: "/", label: "Dashboard" }}
        title={group.label}
        subtitle={group.says}
      />

      {inline.includes("personal-profile") && (
        <>
          {/* ── Personal Profile — all users ──────────────────────────────── */}
          <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
            <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
              <User size={15} className="text-ps-label" />
              <h2 className="text-sm font-semibold text-ps-ink">Personal Profile</h2>
            </div>
            <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-medium text-ps-label block mb-1">
                  Full Name<span className="text-state-problem ml-0.5">*</span>
                </label>
                <input aria-label="Full name"
                  type="text"
                  value={personalName}
                  onChange={(e) => setPersonalName(e.target.value)}
                  placeholder="e.g. CA Ravi Sharma"
                  className="w-full text-sm text-ps-ink border border-ps-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-ps-label block mb-1">Email</label>
                <input aria-label="Email"
                  type="email"
                  value={user?.email ?? ""}
                  disabled
                  className="w-full text-sm text-ps-hint border border-ps-border rounded-lg px-3 py-2 bg-ps-bg cursor-not-allowed"
                />
                <p className="text-xs text-ps-hint mt-1">Email cannot be changed here</p>
              </div>
            </div>
            <div className="px-5 py-3 border-t border-ps-border flex justify-end">
              <button
                onClick={savePersonalProfile}
                disabled={actionInFlight}
                className="px-4 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {savingPersonal ? "Saving…" : "Save Profile"}
              </button>
            </div>
          </div>
        </>
      )}

      {inline.includes("firm-profile") && (
        <>
          {/* ── Firm Profile: shown on `firm` `read`, the pair its read asks; saved on `firm` `write` (POST-A-545) ── */}
          {firmProfileShown(access) && (
          <>
          <ReadOnlyNotice resource="firm" action="write" page="Firm Profile" />
          <ChangePart resource="firm" action="write">
          {/* ── Firm Profile ─────────────────────────────────────────────────── */}
          <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
            <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
              <Building2 size={15} className="text-ps-label" />
              <h2 className="text-sm font-semibold text-ps-ink">Firm Profile</h2>
            </div>

            {profileLocked && !loading && (
              <div className="mx-5 my-4 bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3">
                <p className="text-xs text-state-attention">
                  <RefusalText message={loadError ?? ""} />
                </p>
              </div>
            )}

            {loadError && !profileLocked && !loading && (
              <div className="mx-5 mt-4 flex items-center justify-between gap-3 bg-state-problem-surface border border-red-100 rounded-xl px-4 py-3">
                <p className="text-xs text-state-problem">
                  Couldn&apos;t load your saved firm profile — the form below may not reflect what&apos;s saved. {loadError}
                </p>
                <button onClick={loadFirmData} className="text-xs px-3 py-1.5 border border-state-problem-border rounded-lg hover:bg-state-problem-hover text-state-problem shrink-0">
                  Retry
                </button>
              </div>
            )}

            {loading ? (
              <div className="px-5 py-5"><FormSkeleton fields={6} /></div>
            ) : profileLocked ? null : (
              <div className="px-5 py-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Row 1: Firm name spans full width */}
                  <div className="sm:col-span-2">
                    <Field label="Firm Name" field="name" form={form} onChange={handleChange} errors={errors} placeholder="e.g. Sharma & Associates" required />
                  </div>

                  {/* Row 2: GSTIN + PAN */}
                  <Field
                    label="GSTIN"
                    field="gstin"
                    form={form}
                    onChange={handleChange}
                    errors={errors}
                    placeholder="e.g. 27AABCU9603R1ZN"
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
                    <label className="text-xs font-medium text-ps-label block mb-1">State</label>
                    <select aria-label="State"
                      value={form.state}
                      onChange={(e) => handleChange("state", e.target.value)}
                      className="w-full text-sm text-ps-ink border border-ps-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg"
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

            {!profileLocked && (
            <div className="px-5 py-3 border-t border-ps-border flex justify-end">
              <button
                onClick={handleSave}
                disabled={actionInFlight || loading}
                className="px-4 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? "Saving…" : "Save Changes"}
              </button>
            </div>
            )}
          </div>
          </ChangePart>
          </>
          )}
        </>
      )}

      {inline.includes("financial-year") && (
        <>
          {/* ── Financial Year (display only) ────────────────────────────────── */}
          <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
            <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
              <Calendar size={15} className="text-ps-label" />
              <h2 className="text-sm font-semibold text-ps-ink">Financial Year</h2>
            </div>
            <div className="px-5 py-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-ps-label">Current Financial Year</span>
                <span className="text-sm font-semibold text-ps-ink">{fy.label}</span>
              </div>
              <p className="text-xs text-ps-hint">
                Indian financial year runs April 1 to March 31. This is computed automatically from the current date.
              </p>
            </div>
          </div>
        </>
      )}

      {/* ── The group's screens: each link says what it opens ──────────────── */}
      {links.length > 0 && (
        <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
          <ul className="divide-y divide-ps-border">
            {links.map((l) => (
              <li key={l.href} className="px-5 py-4 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ps-ink">{l.label}</p>
                  <p className="text-xs text-ps-hint mt-0.5">{l.says}</p>
                </div>
                <Link
                  href={l.href}
                  className="px-4 py-1.5 border border-ps-border text-ps-ink text-sm font-medium rounded-lg hover:border-brand hover:bg-ps-bg transition-colors whitespace-nowrap shrink-0"
                >
                  Open →
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// useSearchParams() must sit inside a Suspense boundary or `next build` refuses the static page.
export default function SettingsPage() {
  return (
    <Suspense fallback={<FormSkeleton />}>
      <SettingsHome />
    </Suspense>
  );
}
