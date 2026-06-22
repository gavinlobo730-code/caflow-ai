"use client";
import { LogoIcon } from "@/components/LogoIcon";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Building2, BookOpen, CheckCircle, ChevronRight, ChevronLeft, KeyRound, Eye, EyeOff } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { api, type ApiResp } from "@/lib/api";

interface SignupStash { firmName?: string; fullName?: string }
function readSignupStash(): SignupStash {
  if (typeof window === "undefined") return {};
  try { return JSON.parse(localStorage.getItem("practicesync_signup") || "{}"); } catch { return {}; }
}

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

// Phase 3.3A, Part E: the chart of accounts is intentionally NOT defined in the
// browser anymore. The single canonical source is the backend
// (services/coa_seed_service.STANDARD_COA), seeded via POST /api/onboarding/seed-coa.
// Step 3 shows category descriptions only and triggers the server-side seed.

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

// ─── Step labels ───────────────────────────────────────────────────────────
const STEPS = [
  { label: "Create Password", icon: KeyRound },
  { label: "Firm Profile", icon: Building2 },
  { label: "Chart of Accounts", icon: BookOpen },
];

// ─── Reusable field component ──────────────────────────────────────────────
// MUST live at module scope (not inside the page component): a component defined
// inside another component is a NEW function identity on every render, so React
// unmounts/remounts its <input> on each keystroke — which steals focus after a
// single character. Hoisting it keeps the input mounted and focused.
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
      <label className="text-xs font-medium text-[#64748B] block mb-1">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type={type}
        value={form[field] as string}
        onChange={(e) => setForm((prev) => ({ ...prev, [field]: e.target.value }))}
        placeholder={placeholder}
        className={`w-full text-sm text-[#0F172A] border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC] ${
          errors[field] ? "border-red-400 bg-red-50" : "border-[#E2E8F0]"
        }`}
      />
      {hint && !errors[field] && <p className="text-xs text-[#94A3B8] mt-1">{hint}</p>}
      {errors[field] && <p className="text-xs text-red-500 mt-1">{errors[field] as string}</p>}
    </div>
  );
}

// ─── Progress bar ──────────────────────────────────────────────────────────
function ProgressBar({ step }: { step: number }) {
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
                      : "bg-[#F1F5F9] text-[#94A3B8]"
                  }`}
                >
                  {done ? <CheckCircle size={16} /> : n}
                </div>
                <span
                  className={`text-sm font-medium hidden sm:block ${
                    active ? "text-blue-700" : done ? "text-[#334155]" : "text-[#94A3B8]"
                  }`}
                >
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`flex-1 h-0.5 mx-3 transition-colors ${
                    step > n ? "bg-blue-600" : "bg-white/[0.08]"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
      <p className="text-xs text-[#94A3B8] text-right">Step {step} of {STEPS.length}</p>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────
export default function OnboardingPage() {
  const { user, refreshUserContext } = useAuth();
  const router = useRouter();
  const supabase = getSupabaseClient();

  const [step, setStep] = useState(1);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [firmForm, setFirmForm] = useState<FirmForm>(EMPTY_FIRM);
  const [firmErrors, setFirmErrors] = useState<Partial<Record<keyof FirmForm, string>>>({});
  const [coaSeeded, setCoaSeeded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Non-blocking provisioning status for the firm's internal practice client (A2):
  // surfaced instead of being silently swallowed.
  const [provisionNote, setProvisionNote] = useState<string | null>(null);

  // Step 1 — password
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSet, setPwSet] = useState(false);

  // ─── Pre-fill the firm name from the signup stash ─────────────────────
  useEffect(() => {
    const { firmName } = readSignupStash();
    if (firmName) setFirmForm((f) => (f.name ? f : { ...f, name: firmName }));
  }, []);

  // ─── Create the firm + first Partner via the server-side bootstrap ────
  // Runs server-side (service-role) so it is NOT blocked by the firm-isolation
  // RLS that forbids a firm-less user from inserting a firms row. Single
  // entrypoint (called from Save and Skip) so there is no create race.
  const ensureFirmExists = useCallback(
    async (extra?: { pan?: string; gstin?: string; phone?: string; address?: string; city?: string; state?: string }): Promise<string | null> => {
      if (firmId) return firmId;
      if (!user?.email) return null;
      const stash = readSignupStash();
      const name = firmForm.name.trim() || stash.firmName || "";
      if (!name) return null;
      const partner = stash.fullName?.trim() || user.email;
      try {
        const resp = await api.account.createFirm({
          firm_name: name,
          firm_email: user.email,
          partner_name: partner,
          ...extra,
        });
        const newId = resp?.data?.firm?.id ?? null;
        if (!newId) return null;
        if (typeof window !== "undefined") localStorage.removeItem("practicesync_signup");
        setFirmId(newId);
        await refreshUserContext();
        return newId;
      } catch (e) {
        console.error("createFirm failed:", e);
        return null;
      }
    },
    [firmId, user, firmForm.name, refreshUserContext],
  );

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
  function goNext() { setStep((s) => Math.min(s + 1, STEPS.length)); }
  function goBack() { setStep((s) => Math.max(s - 1, 1)); }
  async function finish() {
    // A firm must exist before entering the app, or AuthGuard will bounce the
    // (firm-less) user straight back to onboarding.
    const id = firmId ?? (await ensureFirmExists());
    if (!id) {
      setError("Please enter your firm name (Step 2) before continuing.");
      setStep(2);
      return;
    }
    await refreshUserContext();
    router.replace("/");
  }

  // ─── Step 1: Set a password ───────────────────────────────────────────
  // The account was created via a magic link (passwordless), so we set a real
  // password here — otherwise the email+password login page would be unusable.
  //
  // Supabase requires reauthentication before updateUser({ password }) when the
  // session was established via OTP/magic link. If that error fires, send a
  // one-time verification code and show the OTP input below.
  const [needsReauth, setNeedsReauth] = useState(false);
  const [reauthOtp, setReauthOtp] = useState("");
  const [reauthError, setReauthError] = useState<string | null>(null);
  const [reauthSending, setReauthSending] = useState(false);

  async function savePassword() {
    setError(null);
    setPwError(null);
    if (pw.length < 10) { setPwError("Use at least 10 characters."); return; }
    if (pw !== pw2) { setPwError("Passwords do not match."); return; }
    setSaving(true);
    try {
      const { error: upErr } = await supabase.auth.updateUser({ password: pw });
      if (upErr) {
        if (upErr.message.toLowerCase().includes("reauthentication")) {
          const { error: raErr } = await supabase.auth.reauthenticate();
          if (raErr) throw new Error("Could not send verification code. Please try again.");
          setNeedsReauth(true);
          return;
        }
        throw new Error(upErr.message);
      }
      setPwSet(true);
      // Clear the in-memory password values once set.
      setPw(""); setPw2("");
      goNext();
    } catch (err) {
      setPwError(err instanceof Error ? err.message : "Could not set your password. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function verifyAndSetPassword() {
    if (!user?.email) return;
    setReauthError(null);
    setReauthSending(true);
    try {
      const { error: otpErr } = await supabase.auth.verifyOtp({
        email: user.email,
        token: reauthOtp,
        type: "email",
      });
      if (otpErr) throw new Error("Invalid verification code. Please try again.");
      const { error: upErr } = await supabase.auth.updateUser({ password: pw });
      if (upErr) throw new Error(upErr.message);
      setNeedsReauth(false);
      setReauthOtp("");
      setPwSet(true);
      setPw(""); setPw2("");
      goNext();
    } catch (err) {
      setReauthError(err instanceof Error ? err.message : "Verification failed. Please try again.");
    } finally {
      setReauthSending(false);
    }
  }

  // ─── Step 2: Save firm profile ────────────────────────────────────────
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
    setSaving(true);
    setError(null);
    try {
      if (!firmId) {
        // No firm yet — create it now (server-side: firm + Partner user + master
        // CoA, and the internal client when a PAN is supplied).
        const id = await ensureFirmExists({
          pan: firmForm.pan.trim() || undefined,
          gstin: firmForm.gstin.trim() || undefined,
          phone: firmForm.phone.trim() || undefined,
          address: firmForm.address.trim() || undefined,
          city: firmForm.city.trim() || undefined,
          state: firmForm.state || undefined,
        });
        if (!id) { setError("Could not create your firm. Please check the firm name and try again."); return; }
        goNext();
        return;
      }
      // Firm exists — update its profile fields (anon client; now permitted by RLS).
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
      // Provision the internal practice client now that a PAN may be set
      // (idempotent + non-fatal — onboarding must not fail on this). A2: surface
      // the outcome instead of swallowing it; the backend audit-logs the result.
      if (firmForm.pan.trim()) {
        try {
          const res = await api.practice.provision() as ApiResp<{ provisioned: boolean; message?: string | null }>;
          if (!res?.success || !res.data?.provisioned) {
            setProvisionNote(res?.data?.message || res?.error ||
              "Your practice books could not be set up automatically. You can set them up later from the Practice section.");
          } else {
            setProvisionNote(null);
          }
        } catch {
          setProvisionNote("Your practice books will be set up later — you can trigger it from the Practice section.");
        }
      }
      goNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save firm profile");
    } finally {
      setSaving(false);
    }
  }

  // ─── Step 3: Seed Chart of Accounts (idempotent — server already seeds on
  // firm creation; this is a safety net + the review screen) ───────────────
  async function seedCoA() {
    if (!firmId) { setError("No firm found for your account"); return; }
    setSaving(true);
    setError(null);
    try {
      // CoA seeding is server-side from the single canonical source
      // (coa_seed_service.STANDARD_COA). Idempotent — safe even though firm
      // creation already seeds it. No accounting data is written from the browser.
      const res = await api.account.seedCoa() as ApiResp<{ seeded: number; skipped: boolean }>;
      if (!res?.success) throw new Error(res?.error || "Failed to set up chart of accounts");
      setCoaSeeded(true);
      await finish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set up chart of accounts");
    } finally {
      setSaving(false);
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-white rounded-2xl shadow-sm border border-[#F1F5F9] p-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <LogoIcon size="sm" />
            <span className="text-sm font-semibold text-[#334155]">PracticeSync AI</span>
          </div>
          <h1 className="text-2xl font-bold text-[#0F172A] mt-4">Welcome! Let&apos;s set up your firm</h1>
          <p className="text-sm text-[#64748B] mt-1">This takes about 2 minutes. You can always update these later in Settings.</p>
        </div>

        <ProgressBar step={step} />

        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}

        {provisionNote && (
          <div className="mb-4 px-4 py-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
            {provisionNote}
          </div>
        )}

        {/* ── Step 1: Create Password ──────────────────────────────────────── */}
        {step === 1 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <KeyRound size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-[#0F172A]">Create your password</h2>
            </div>
            <p className="text-sm text-[#64748B] mb-5">
              Your email is verified. Set a password so you can sign in any time — you signed up with <span className="font-medium text-[#334155]">{user?.email}</span>.
            </p>

            <div className="space-y-4 max-w-md">
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">Password<span className="text-red-500 ml-0.5">*</span></label>
                <div className="relative">
                  <input
                    type={showPw ? "text" : "password"}
                    value={pw}
                    onChange={(e) => setPw(e.target.value)}
                    placeholder="At least 10 characters"
                    autoComplete="new-password"
                    className={`w-full text-sm text-[#0F172A] border rounded-lg px-3 py-2 pr-10 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC] ${pwError ? "border-red-400 bg-red-50" : "border-[#E2E8F0]"}`}
                  />
                  <button type="button" onClick={() => setShowPw((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8] hover:text-[#475569]">
                    {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-[#64748B] block mb-1">Confirm password<span className="text-red-500 ml-0.5">*</span></label>
                <input
                  type={showPw ? "text" : "password"}
                  value={pw2}
                  onChange={(e) => setPw2(e.target.value)}
                  placeholder="Re-enter your password"
                  autoComplete="new-password"
                  className={`w-full text-sm text-[#0F172A] border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC] ${pwError ? "border-red-400 bg-red-50" : "border-[#E2E8F0]"}`}
                />
              </div>
              {pwError && <p className="text-xs text-red-500">{pwError}</p>}
              {pwSet && (
                <div className="flex items-center gap-2 text-sm text-green-700"><CheckCircle size={15} /> Password set</div>
              )}

              {needsReauth && (
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg space-y-3">
                  <p className="text-sm font-medium text-blue-900">Check your email for a verification code</p>
                  <p className="text-sm text-blue-700">
                    We sent a 6-digit code to <span className="font-medium">{user?.email}</span>. Enter it below to set your password.
                  </p>
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={reauthOtp}
                    onChange={(e) => { setReauthError(null); setReauthOtp(e.target.value.replace(/\D/g, "")); }}
                    placeholder="6-digit code"
                    autoComplete="one-time-code"
                    className="w-full text-sm border border-blue-300 rounded-lg px-3 py-2 tracking-widest text-center focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  />
                  {reauthError && <p className="text-xs text-red-500">{reauthError}</p>}
                  <button
                    onClick={verifyAndSetPassword}
                    disabled={reauthSending || reauthOtp.length < 6}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                  >
                    {reauthSending ? "Verifying…" : "Verify & Set Password"}
                    {!reauthSending && <ChevronRight size={14} />}
                  </button>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end mt-8 pt-5 border-t border-gray-50">
              <button
                onClick={savePassword}
                disabled={saving || !pw || !pw2 || needsReauth}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving ? "Saving…" : "Set Password & Continue"}
                {!saving && <ChevronRight size={16} />}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Firm Profile ────────────────────────────────────────── */}
        {step === 2 && (
          <div>
            <div className="flex items-center gap-2 mb-5">
              <Building2 size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-[#0F172A]">Firm Profile</h2>
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
                <label className="text-xs font-medium text-[#64748B] block mb-1">State</label>
                <select
                  value={firmForm.state}
                  onChange={(e) => setFirmForm((p) => ({ ...p, state: e.target.value }))}
                  className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
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
                onClick={goBack}
                className="flex items-center gap-1 text-sm text-[#64748B] hover:text-[#334155] transition-colors"
              >
                <ChevronLeft size={16} /> Back
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

        {/* ── Step 3: Chart of Accounts ───────────────────────────────────── */}
        {step === 3 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <BookOpen size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-[#0F172A]">Chart of Accounts</h2>
            </div>
            <p className="text-sm text-[#64748B] mb-5">
              We&apos;ll set up a standard Schedule III chart of accounts for your firm — pre-mapped for GST, TDS, payroll and fixed assets. You can add, rename or delete accounts later from Accounting.
            </p>

            {/* Categories only — the authoritative account list is seeded server-side
                from the single canonical source (no chart of accounts is defined in
                the browser). */}
            <div className="border border-[#F1F5F9] rounded-xl overflow-hidden divide-y divide-[#F8FAFC]">
              {[
                { label: "Assets", color: "text-blue-700 bg-blue-50", desc: "Cash, bank, receivables, GST input, fixed assets" },
                { label: "Liabilities", color: "text-red-700 bg-red-50", desc: "Payables, GST output, TDS, loans" },
                { label: "Equity", color: "text-purple-700 bg-purple-50", desc: "Capital, drawings, retained earnings" },
                { label: "Revenue", color: "text-green-700 bg-green-50", desc: "Professional, audit, GST & tax consultancy fees" },
                { label: "Expenses", color: "text-orange-700 bg-orange-50", desc: "Salaries, rent, software, depreciation" },
              ].map((group) => (
                <div key={group.label} className="flex items-center justify-between px-4 py-3">
                  <span className={`text-xs font-semibold uppercase tracking-wide px-2 py-0.5 rounded ${group.color}`}>{group.label}</span>
                  <span className="text-xs text-[#94A3B8]">{group.desc}</span>
                </div>
              ))}
            </div>

            {coaSeeded && (
              <div className="mt-3 flex items-center gap-2 text-sm text-green-700">
                <CheckCircle size={15} />
                Chart of Accounts ready
              </div>
            )}

            <div className="flex items-center justify-between mt-8 pt-5 border-t border-gray-50">
              <button
                onClick={goBack}
                className="flex items-center gap-1 text-sm text-[#64748B] hover:text-[#334155] transition-colors"
              >
                <ChevronLeft size={16} /> Back
              </button>
              <button
                onClick={seedCoA}
                disabled={saving}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving ? "Finishing…" : "Finish & Go to Dashboard"}
                {!saving && <ChevronRight size={16} />}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
