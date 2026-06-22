"use client";
import { LogoIcon } from "@/components/LogoIcon";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Building2, CheckCircle, ChevronRight, ChevronLeft, KeyRound, Eye, EyeOff } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { setPasswordWithReauthNonce, isInvalidNonceError } from "@/lib/auth/reauth";
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

// ─── Diagnostic trace for the password / reauthentication flow ──────────────
// Captures each step's method, payload metadata and the raw provider response so
// the OTP flow can be traced end-to-end. The raw one-time code is only logged
// outside production to avoid leaking a live nonce into production logs.
function otpTrace(step: string, detail: Record<string, unknown> = {}) {
  const safe = process.env.NODE_ENV === "production" ? { ...detail, token: undefined } : detail;
  // eslint-disable-next-line no-console
  console.info(`[onboarding:otp] ${step}`, safe);
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
  maxLength,
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
        value={form[field] as string}
        onChange={(e) => setForm((prev) => ({ ...prev, [field]: e.target.value }))}
        placeholder={placeholder}
        maxLength={maxLength}
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
      if (firmData?.name) {
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
    router.replace("/?welcome=1");
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
      // Step 1 & 2 — try to set the password directly.
      otpTrace("step 1: updateUser({ password }) — direct set attempt", { email: user?.email });
      const { error: upErr } = await supabase.auth.updateUser({ password: pw });
      if (upErr) {
        otpTrace("step 1 response: updateUser returned error", {
          code: upErr.code, status: upErr.status, message: upErr.message,
        });
        // "Secure password change" is enabled, so a magic-link session that isn't
        // "recently signed in" must reauthenticate first. reauthenticate() emails a
        // nonce that is later consumed by updateUser({ password, nonce }).
        if (upErr.message.toLowerCase().includes("reauthentication")) {
          otpTrace("step 2: reauthenticate() — emailing nonce", { email: user?.email });
          const { error: raErr } = await supabase.auth.reauthenticate();
          if (raErr) {
            otpTrace("step 2 response: reauthenticate error", {
              code: raErr.code, status: raErr.status, message: raErr.message,
            });
            throw new Error("Could not send verification code. Please try again.");
          }
          otpTrace("step 2 response: reauthenticate OK — verification code emailed");
          setNeedsReauth(true);
          return;
        }
        throw new Error(upErr.message);
      }
      otpTrace("step 1 response: password set without reauthentication");
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
    // The reauthentication code is sent verbatim — no truncation/parseInt/slice.
    const nonce = reauthOtp.trim();
    try {
      // ── ROOT-CAUSE FIX ─────────────────────────────────────────────────────
      // The code emailed by reauthenticate() is a REAUTHENTICATION NONCE, not an
      // email OTP. The Supabase SDK is explicit: "After receiving the OTP, include
      // it as the `nonce` in your updateUser() call to finalize the password
      // change." The nonce is NOT a verifyOtp() token — EmailOtpType has no
      // 'reauthentication' member ('signup'|'invite'|'magiclink'|'recovery'|
      // 'email_change'|'email'), so the previous verifyOtp({ type: "email" }) call
      // could never match the nonce and rejected every correct code as "invalid".
      // Correct flow: reauthenticate() → updateUser({ password, nonce }).
      otpTrace("step 3: OTP entered by user", { email: user.email, tokenLength: nonce.length, token: nonce });
      otpTrace("steps 4-7: updateUser({ password, nonce }) — verify nonce + set password", {
        method: "auth.updateUser", email: user.email, tokenLength: nonce.length, token: nonce,
      });
      const { error: upErr } = await setPasswordWithReauthNonce(supabase.auth, pw, nonce);
      if (upErr) {
        otpTrace("verify response: updateUser returned error", {
          code: upErr.code, status: upErr.status, message: upErr.message,
        });
        // Surface the real reason so the user knows whether to request a new code.
        throw new Error(
          isInvalidNonceError(upErr)
            ? "That code is incorrect or has expired. Request a new code and try again."
            : upErr.message,
        );
      }
      otpTrace("verify response: password updated — reauthentication accepted");
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

  // Re-send a fresh reauthentication nonce (e.g. the previous code expired).
  async function resendReauthCode() {
    setReauthError(null);
    setReauthSending(true);
    try {
      otpTrace("resend: reauthenticate() — emailing a fresh nonce", { email: user?.email });
      const { error: raErr } = await supabase.auth.reauthenticate();
      if (raErr) {
        otpTrace("resend response: reauthenticate error", {
          code: raErr.code, status: raErr.status, message: raErr.message,
        });
        throw new Error("Could not resend the code. Please try again in a moment.");
      }
      setReauthOtp("");
      setReauthError("A new code has been sent to your email.");
    } catch (err) {
      setReauthError(err instanceof Error ? err.message : "Could not resend the code.");
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
    if (firmForm.pincode && !/^[1-9][0-9]{5}$/.test(firmForm.pincode)) errs.pincode = "Pincode must be 6 digits starting with a non-zero digit";
    setFirmErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function saveFirmProfile() {
    if (!validateFirm()) return;
    setSaving(true);
    setError(null);
    try {
      if (!firmId) {
        // No firm yet — create it server-side (firm + Partner user + standard CoA).
        // Backend seeds the full Chart of Accounts automatically; no onboarding step needed.
        const id = await ensureFirmExists({
          pan: firmForm.pan.trim() || undefined,
          gstin: firmForm.gstin.trim() || undefined,
          phone: firmForm.phone.trim() || undefined,
          address: firmForm.address.trim() || undefined,
          city: firmForm.city.trim() || undefined,
          state: firmForm.state || undefined,
        });
        if (!id) { setError("Could not create your firm. Please check the firm name and try again."); return; }
        await finish();
        return;
      }
      // Firm exists — update its profile fields (permitted by RLS for the firm owner).
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
      // Idempotent CoA seed — covers the edge case where firm exists but CoA was
      // never seeded (e.g. partial onboarding). Non-blocking; failure is not fatal.
      api.account.seedCoa().catch(() => {});
      // Provision the internal practice client now that a PAN may be set (non-fatal).
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
      await finish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save firm profile");
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
                    We sent an 8-digit code to <span className="font-medium">{user?.email}</span>. Enter it below to set your password.
                  </p>
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={8}
                    value={reauthOtp}
                    onChange={(e) => { setReauthError(null); setReauthOtp(e.target.value.replace(/\D/g, "")); }}
                    placeholder="8-digit code"
                    autoComplete="one-time-code"
                    className="w-full text-sm border border-blue-300 rounded-lg px-3 py-2 tracking-widest text-center focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  />
                  {reauthError && <p className="text-xs text-red-500">{reauthError}</p>}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={verifyAndSetPassword}
                      disabled={reauthSending || reauthOtp.length < 8}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                    >
                      {reauthSending ? "Verifying…" : "Verify & Set Password"}
                      {!reauthSending && <ChevronRight size={14} />}
                    </button>
                    <button
                      type="button"
                      onClick={resendReauthCode}
                      disabled={reauthSending}
                      className="text-sm text-blue-700 hover:text-blue-900 hover:underline disabled:opacity-50"
                    >
                      Resend code
                    </button>
                  </div>
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
                maxLength={10}
              />
              <Field
                label="GSTIN (optional)"
                field="gstin"
                form={firmForm}
                setForm={setFirmForm}
                errors={firmErrors}
                placeholder="e.g. 27AABCU9603R1ZX"
                hint="CGST Act §25 — 15-char GSTIN"
                maxLength={15}
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
                {saving ? "Setting up your workspace…" : "Complete Setup"}
                {!saving && <ChevronRight size={16} />}
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
