"use client";
import { LogoIcon } from "@/components/LogoIcon";

import { useState, useEffect, useCallback, useRef, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Building2, CheckCircle, ChevronRight, ChevronLeft, KeyRound, Eye, EyeOff, Hash, Plus, Upload, ExternalLink } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import {
  setPasswordWithReauthNonce,
  isInvalidNonceError,
  isSessionMissingError,
  isSamePasswordError,
  SESSION_EXPIRED_MESSAGE,
} from "@/lib/auth/reauth";
import { mayRenderOnboardingWizard } from "@/lib/auth/guardDecision";
import { onboardingCompletionTarget } from "@/lib/auth/mfaEnrolment";
import { authErrorMessage, knownAuthErrorMessage } from "@/lib/auth/authErrorMessage";
import { passwordProblem } from "@/lib/auth/passwordRules";
import { passwordStepButtonEnabled, passwordStepMode } from "@/lib/auth/passwordStep";
import { onboardingProgress, progressFor, restoredStep } from "@/lib/auth/onboardingProgress";
import { PasswordRules } from "@/components/auth/PasswordRules";
import { clearSignupStash, newFirmSignupStarted, readSignupStash as readStash } from "@/lib/auth/signupStash";
import { canAskAgain } from "@/lib/auth/signupContinue";
import { requestSignupLink } from "@/lib/auth/requestSignupLink";
import { signedInAsSentence, signupLanding } from "@/lib/auth/signupLanding";
import { api, type ApiResp } from "@/lib/api";
import CsvImportModal from "@/components/LazyCsvImportModal";
import type { ImportRow, ImportResult } from "@/components/CsvImportModal";
import { FirmHsnLibraryQuickAddModal } from "@/components/lookups/FirmHsnLibraryQuickAddModal";
import { Callout } from "@/components/ui/callout";
import { gstinProblem } from "@/lib/gst/gstin";
import { isValidPan } from "@/lib/identifiers/pan";
import { Button } from "@/components/ui/button";
import { hasChanges, useUnsavedChanges } from "@/lib/invoices/dirtyState";
import { confirmDialog } from "@/components/ui/confirm-dialog";

// The sign-up page's hand-over across the emailed link: lib/auth/signupStash (it now keeps the address too).
function browserStorage(): Storage | null {
  try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; }
}
function readSignupStash() { return readStash(browserStorage()); }

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
// CGST Act §25, THROUGH THE ONE BROWSER AUTHORITY — see the same function in
// app/settings/page.tsx. This is where a firm first types its own GSTIN, so
// getting it wrong here is the value every later screen reads back. Blank
// stays valid: unregistered is not wrong. The message is `gstinProblem`'s own
// sentence rather than "Invalid GSTIN", which called a check-digit mismatch a
// format error and named no character (sweep-settings-hub-1-07).

// IT Act Section 139A — PAN format: 5 uppercase letters + 4 digits + 1 uppercase letter
// IT Act §139A, THROUGH THE ONE BROWSER RULE — see the same function in
// app/settings/page.tsx. This is where a firm first types its own PAN, and the
// `Field` it is typed into does not uppercase, so the raw-value test refused a
// PAN the server accepts.
function validatePAN(pan: string): boolean {
  return isValidPan(pan);
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
  { label: "HSN/SAC Library", icon: Hash },
];

// ─── Step 3: Import Firm HSN/SAC Library ───────────────────────────────────
// Caflow ships no HSN/SAC data of its own (see docs/HSN_SAC_REDESIGN.md).
// The template below has Caflow-authored COLUMN HEADERS only — no code
// content — so there is nothing here to redistribute or license: the CA
// fills it in from whatever source they choose (their own downloaded GST
// portal file, Tally export, or manual knowledge) and it becomes THEIR
// library. Import reuses the exact same POST /api/firm-hsn-library/ endpoint
// manual add uses (Sales-Invoice-import pattern) — one create path.
//
// This plain outbound link is not a redistribution of government data — it
// sends the CA to the GST portal's own official HSN search/download page
// (verified official source, see docs/FIRM_HSN_LIBRARY.md's research
// citation). Caflow hosts none of that content itself.
const GST_PORTAL_HSN_SEARCH_URL = "https://services.gst.gov.in/services/searchhsnsac";

const HSN_LIBRARY_IMPORT_COLUMNS = [
  { key: "hsn_code", label: "HSN/SAC Code", required: true, hint: "2-8 digits, e.g. 998221" },
  { key: "description", label: "Description", required: true, hint: "e.g. Financial auditing services" },
  { key: "hsn_type", label: "Type", required: true, hint: "goods or services" },
  { key: "gst_rate_pct", label: "GST Rate %", required: false, hint: "e.g. 18 (leave blank if it varies)" },
  { key: "uqc", label: "Unit", required: false, hint: "e.g. NOS, OTH" },
];

function validateHsnLibraryImportRow(row: ImportRow): string[] {
  const errors: string[] = [];
  if (row.hsn_code && !/^\d{2,8}$/.test(row.hsn_code.trim())) errors.push("Code must be 2-8 digits");
  const type = (row.hsn_type || "").trim().toLowerCase();
  if (type && type !== "goods" && type !== "services") errors.push('Type must be "goods" or "services"');
  if (row.gst_rate_pct) {
    const n = parseFloat(row.gst_rate_pct);
    if (!Number.isFinite(n) || n < 0 || n > 100) errors.push("GST Rate % must be between 0 and 100");
  }
  return errors;
}

async function importHsnLibraryRows(rows: ImportRow[]): Promise<ImportResult> {
  let imported = 0;
  let skipped = 0;
  const errors: string[] = [];
  for (const row of rows) {
    try {
      const res = (await api.firmHsnLibrary.add({
        hsn_code: row.hsn_code.trim(),
        description: row.description.trim(),
        hsn_type: (row.hsn_type || "services").trim().toLowerCase(),
        gst_rate_pct: row.gst_rate_pct ? parseFloat(row.gst_rate_pct) : null,
        uqc: row.uqc?.trim() || undefined,
        source: "import",
      })) as ApiResp<{ duplicate?: boolean }>;
      if (!res.success) { errors.push(`${row.hsn_code}: ${res.error ?? "import failed"}`); continue; }
      if (res.data?.duplicate) skipped++; else imported++;
    } catch (e) {
      errors.push(`${row.hsn_code}: ${e instanceof Error ? e.message : "import failed"}`);
    }
  }
  return { imported, skipped, errors };
}

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
      <label className="text-xs font-medium text-ps-label block mb-1">
        {label}
        {required && <span className="text-state-problem ml-0.5">*</span>}
      </label>
      <input aria-label={label}
        type={type}
        value={form[field] as string}
        onChange={(e) => setForm((prev) => ({ ...prev, [field]: e.target.value }))}
        placeholder={placeholder}
        maxLength={maxLength}
        className={`w-full text-sm text-ps-ink border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg ${
          errors[field] ? "border-red-400 bg-state-problem-surface" : "border-ps-border"
        }`}
      />
      {hint && !errors[field] && <p className="text-xs text-ps-hint mt-1">{hint}</p>}
      {errors[field] && <p className="text-xs text-state-problem mt-1">{errors[field] as string}</p>}
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
                      ? "bg-brand text-white"
                      : active
                      ? "bg-brand text-white ring-4 ring-brand-light"
                      : "bg-ps-muted text-ps-hint"
                  }`}
                >
                  {done ? <CheckCircle size={16} /> : n}
                </div>
                <span
                  className={`text-sm font-medium hidden sm:block ${
                    active ? "text-blue-700" : done ? "text-ps-body" : "text-ps-hint"
                  }`}
                >
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`flex-1 h-0.5 mx-3 transition-colors ${
                    step > n ? "bg-brand" : "bg-white/[0.08]"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
      <p className="text-xs text-ps-hint text-right">Step {step} of {STEPS.length}</p>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────
export default function OnboardingPage() {
  const { user, session, loading: authLoading, refreshUserContext, resolveEnrolmentRequired, hasFirm, fullName: memberName, userRole, signOut } = useAuth();
  const router = useRouter();
  const supabase = getSupabaseClient();

  // Seeded from what the wizard remembers, so a remount paints the restored step at once and not step 1 for a frame.
  const [step, setStep] = useState<number>(() => restoredStep({
    progress: onboardingProgress.get(), userId: user?.id, ownerName: readSignupStash().fullName ?? "",
  }));
  // THE ADDRESS ALREADY HAS A PRACTICE (POST-A-480). A new-firm sign-up was started in this browser (the stash is
  // there) and the person the link signed in is already a member of a practice: say so, never open that practice
  // as if it were the new one. `createdHere` is true once THIS wizard made the firm, when having one is expected.
  const [signupStarted] = useState(() => newFirmSignupStarted(readSignupStash()));
  const [createdHere, setCreatedHere] = useState(false);
  const [existingFirmName, setExistingFirmName] = useState<string | null>(null);
  const landing = signupLanding({ hasSession: !!session, hasFirm, signupStarted, createdHere });

  // NOBODY IS SIGNED IN HERE (POST-A-479, 485). A sign-up link lands on /signup/continue and works until it expires or the practice is
  // created, so a person reaches this page without a session by opening the address of an older emailed link that has been used
  // (those worked once), by a bookmark, or after signing out. With the address and names the sign-up page kept, they can have a new
  // link sent by the server instead of starting again.
  const stashedEmail = readSignupStash().email ?? null;
  const canEmailNewLink = canAskAgain(readSignupStash());
  const [linkSending, setLinkSending] = useState(false);
  const [linkWait, setLinkWait] = useState(0);
  const [linkNote, setLinkNote] = useState<{ tone: "ok" | "problem"; text: string } | null>(null);
  useEffect(() => {
    if (linkWait <= 0) return;
    const timer = setTimeout(() => setLinkWait((n) => n - 1), 1000);
    return () => clearTimeout(timer);
  }, [linkWait]);
  async function emailNewLink() {
    const stash = readSignupStash();
    if (!canAskAgain(stash) || linkSending || linkWait > 0) return;
    setLinkSending(true);
    setLinkNote(null);
    try {
      // The SERVER keeps and mails the link (POST-A-485), and says in its own sentence when it will not or could not.
      const sent = await requestSignupLink({ email: stash.email ?? "", firmName: stash.firmName ?? "", fullName: stash.fullName ?? "" });
      setLinkNote({ tone: "ok", text: `A new link is on its way to ${stash.email}. It works until ${sent.validUntil}, and you can open it more than once.` });
      setLinkWait(sent.waitSeconds);
    } catch (e) {
      setLinkNote({ tone: "problem", text: e instanceof Error && e.message ? e.message : "Could not send a new link. Please try again." });
    } finally {
      setLinkSending(false);
    }
  }
  const [ownerName, setOwnerName] = useState(() => readSignupStash().fullName?.trim() ?? "");
  const [firmId, setFirmId] = useState<string | null>(null);
  const [firmForm, setFirmForm] = useState<FirmForm>(EMPTY_FIRM);
  const [firmErrors, setFirmErrors] = useState<Partial<Record<keyof FirmForm, string>>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Non-blocking provisioning status for the firm's internal practice client (A2):
  // surfaced instead of being silently swallowed.
  const [provisionNote, setProvisionNote] = useState<string | null>(null);

  // Step 3 — Import Firm HSN/SAC Library
  const [hsnImportOpen, setHsnImportOpen] = useState(false);
  const [hsnQuickAddOpen, setHsnQuickAddOpen] = useState(false);
  const [hsnAddedCount, setHsnAddedCount] = useState(0);

  // Step 1 — password
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSet, setPwSet] = useState(false);
  // THE PASSWORD STEP'S MEMORY LIVES OUTSIDE THIS COMPONENT (POST-A-478). Saving
  // a password makes AuthGuard unmount this page for a round trip (the sign-in
  // assurance is re-read, and unresolved is not permission), so it mounted again
  // at step 1 with "password set" forgotten and the boxes empty — and typing the
  // same password again is refused as the same password. lib/auth/onboardingProgress
  // holds the fact in a module and in session storage, keyed on the person.
  const progress = useSyncExternalStore(onboardingProgress.subscribe, onboardingProgress.get, () => null);
  const mine = progressFor(progress, user?.id);
  // True once THIS mount has moved the wizard on itself, so the restore below
  // does not move it a second time.
  const advancedHere = useRef(false);
  // The name typed on step 1, readable by the restore without making it re-run on every keystroke.
  const ownerNameNow = useRef(ownerName);
  ownerNameNow.current = ownerName;
  useEffect(() => {
    if (!mine || advancedHere.current) return;
    advancedHere.current = true;
    if (mine.passwordSet) setPwSet(true);
    // A verification code was emailed and the person went to read it: bring its box back (the password itself is
    // never kept, so it is typed again above).
    if (mine.reauthPending) setNeedsReauth(true);
    // A mount that finds the step done is the one that lost its place. Step 2 only when the name is known; step 3
    // once the firm exists (restoredStep).
    const target = restoredStep({ progress: mine, userId: user?.id, ownerName: ownerNameNow.current });
    setStep((s) => (s === 1 ? target : s));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mine]);
  function rememberPasswordSet() {
    advancedHere.current = true;
    if (user?.id) onboardingProgress.markPasswordSet(user.id);
    setPwSet(true);
    setNeedsReauth(false);
    setPw(""); setPw2("");
  }

  // UNSAVED TYPING (frontend_ux-23). A reload in the middle of the wizard drops
  // the owner back at step 1 with everything typed gone, and this is the one
  // form every new firm fills in. Warn (the browser's own prompt, which is all
  // this page can do — it has no in-app exit) while the firm is NOT yet created
  // and there is something the person typed: the firm name beyond the one the
  // signup page handed over, any other firm field, their own name, or a password
  // not yet set. Once `firmId` exists the firm is saved and step 3 holds nothing
  // typed that is not already on the server.
  const [stashedFirmName] = useState(() => readSignupStash().firmName ?? "");
  const [stashedOwnerName] = useState(ownerName);
  const hasUnsavedTyping = !firmId && (
    hasChanges({ ...EMPTY_FIRM, name: stashedFirmName }, firmForm)
    || ownerName !== stashedOwnerName
    || ((pw !== "" || pw2 !== "") && !pwSet));
  useUnsavedChanges(hasUnsavedTyping && !saving, undefined, confirmDialog);

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
      const partner = ownerName.trim() || stash.firmName || user.email;
      const resp = await api.account.createFirm({
        firm_name: name,
        firm_email: user.email,
        partner_name: partner,
        ...extra,
      });
      const newId = resp?.data?.firm?.id ?? null;
      if (!newId) throw new Error(resp?.error ?? "Firm creation did not return a firm ID.");
      clearSignupStash(browserStorage());
      setCreatedHere(true);
      // Remembered: a remount after this goes on to step 3, never back to a blank step 2 whose save would overwrite
      // the profile just entered.
      advancedHere.current = true;
      if (user?.id) onboardingProgress.markFirmCreated(user.id);
      setFirmId(newId);
      await refreshUserContext();
      return newId;
    },
    [firmId, user, firmForm.name, ownerName, refreshUserContext],
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
  // Only applies to a FRESH page load sitting at Step 1 (e.g. an already-
  // onboarded user who navigated back to /onboarding by URL). Once the user
  // has progressed past Step 1 in this session, `firmId` legitimately
  // changes as a side effect of THEIR OWN step-2 submit (a new firm is
  // created with a name already set) — without the `step === 1` guard this
  // effect would fire on that firmId change and bounce them to "/" via
  // router.replace before they ever see Step 3 (Import Firm HSN/SAC Library).
  useEffect(() => {
    if (!user || !firmId || step !== 1) return;
    async function checkAlreadyOnboarded() {
      const { data: firmData } = await supabase
        .from("firms")
        .select("name")
        .eq("id", firmId)
        .maybeSingle();
      if (firmData?.name) {
        // A member who only visited this page goes to their dashboard as before; one who STARTED a new-firm sign-up
        // with this address is told (the notice below) and never taken there silently (POST-A-480).
        if (landing === "existing-practice") setExistingFirmName(firmData.name);
        else if (landing === "go-home") router.replace("/");
      }
    }
    checkAlreadyOnboarded();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firmId, landing]);

  // ─── Navigation ───────────────────────────────────────────────────────
  function goNext() { setStep((s) => Math.min(s + 1, STEPS.length)); }
  function goBack() { setStep((s) => Math.max(s - 1, 1)); }
  async function finish() {
    // A firm must exist before entering the app, or AuthGuard will bounce the
    // (firm-less) user straight back to onboarding.
    let id: string | null;
    try {
      id = firmId ?? (await ensureFirmExists());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create your firm. Please try again.");
      setStep(2);
      return;
    }
    if (!id) {
      setError("Please enter your firm name (Step 2) before continuing.");
      setStep(2);
      return;
    }
    await refreshUserContext();
    // The wizard is done: its memory of this person's password step goes with it.
    onboardingProgress.clear();
    // A new owner the MFA policy covers is refused by every administration
    // screen until they enrol, and nothing at sign-in asks them to — so the
    // wizard's last step is the enrol screen for them, and Home for everyone
    // else. An unanswerable policy lands on Home, which is what it did before.
    const mustEnrol = await resolveEnrolmentRequired().catch(() => false);
    router.replace(onboardingCompletionTarget(mustEnrol));
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
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = reauthSending || saving;

  async function savePassword() {
    setError(null);
    setPwError(null);
    if (!ownerName.trim()) { setPwError("Please enter your full name."); return; }
    // Every rule the sign-in service enforces, before anything is sent (POST-A-477).
    const rulesProblem = passwordProblem(pw);
    if (rulesProblem) { setPwError(rulesProblem); return; }
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
        // The password typed IS the one already on the account (a second visit to this
        // step, or the page that came back after a save): it is set, so carry on.
        if (isSamePasswordError(upErr)) {
          otpTrace("step 1 response: same password — already set, carrying on");
          rememberPasswordSet();
          goNext();
          return;
        }
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
            if (isSessionMissingError(raErr)) throw new Error(SESSION_EXPIRED_MESSAGE);
            throw new Error(knownAuthErrorMessage(raErr) ?? "Could not send verification code. Please try again.");
          }
          otpTrace("step 2 response: reauthenticate OK — verification code emailed");
          // Remembered: reading the emailed code means leaving this tab, and coming back signs the person in again and
          // remounts this page; the code box has to come back with it (the password is typed again, never kept).
          advancedHere.current = true;
          if (user?.id) onboardingProgress.markReauthPending(user.id, true);
          setNeedsReauth(true);
          return;
        }
        // No session to act on at all — an expired/already-used magic link, or
        // a bookmark from before sign-out. Supabase's own message is the raw
        // SDK string "Auth session missing!"; show the CA something they can
        // act on instead (sweep-auth-and-public-04).
        if (isSessionMissingError(upErr)) throw new Error(SESSION_EXPIRED_MESSAGE);
        throw new Error(authErrorMessage(upErr));
      }
      otpTrace("step 1 response: password set without reauthentication");
      // Remembered BEFORE the page moves on: this component may already have been
      // unmounted by the guard, and the next mount reads it from the store.
      rememberPasswordSet();
      goNext();
    } catch (err) {
      setPwError(authErrorMessage(err, "Could not set your password. Please try again."));
    } finally {
      setSaving(false);
    }
  }

  // The password is already set (the person came back to this step): go on without
  // asking for one again. Their name is still needed for the firm.
  function continueWithSetPassword() {
    setError(null);
    setPwError(null);
    if (!ownerName.trim()) { setPwError("Please enter your full name."); return; }
    goNext();
  }

  async function verifyAndSetPassword() {
    if (!user?.email) return;
    setReauthError(null);
    setReauthSending(true);
    // The reauthentication code is sent verbatim — no truncation/parseInt/slice.
    const nonce = reauthOtp.trim();
    try {
      // Back from reading the emailed code the boxes are empty (the password is never kept): ask for it again.
      if (!pw) throw new Error("Type your password in the boxes above again, then enter the code.");
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
      if (upErr && isSamePasswordError(upErr)) {
        // The password typed IS the one already on the account: it is set, carry on.
        setReauthOtp("");
        rememberPasswordSet();
        goNext();
        return;
      }
      if (upErr) {
        otpTrace("verify response: updateUser returned error", {
          code: upErr.code, status: upErr.status, message: upErr.message,
        });
        // Surface the real reason so the user knows whether to request a new code.
        // Checked before isInvalidNonceError: "Auth session missing!" means
        // there is no session to reauthenticate at all, a different problem
        // from a wrong/expired code (sweep-auth-and-public-04).
        throw new Error(
          isSessionMissingError(upErr)
            ? SESSION_EXPIRED_MESSAGE
            : isInvalidNonceError(upErr)
              ? "That code is incorrect or has expired. Request a new code and try again."
              : authErrorMessage(upErr),
        );
      }
      otpTrace("verify response: password updated — reauthentication accepted");
      setNeedsReauth(false);
      setReauthOtp("");
      rememberPasswordSet();
      goNext();
    } catch (err) {
      setReauthError(authErrorMessage(err, "Verification failed. Please try again."));
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
        if (isSessionMissingError(raErr)) throw new Error(SESSION_EXPIRED_MESSAGE);
        throw new Error(knownAuthErrorMessage(raErr) ?? "Could not resend the code. Please try again in a moment.");
      }
      setReauthOtp("");
      setReauthError("A new code has been sent to your email.");
    } catch (err) {
      setReauthError(authErrorMessage(err, "Could not resend the code."));
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
    const gstinIssue = gstinProblem(firmForm.gstin);
    if (gstinIssue) errs.gstin = gstinIssue;
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
        if (!id) { setError("Please enter your firm name and try again."); return; }
        setStep(3);
        return;
      }
      // Firm exists — update its profile through the API. This used to write
      // `public.firms` straight over PostgREST, and it wrote `gst_number`: the
      // one column no backend reader reads, so a firm onboarded through this
      // screen ended up with `gstin` NULL and printed fee invoices with no
      // supplier GSTIN on them. POST /api/onboarding/firm has always written
      // the right column — it is only this UPDATE step that did not, so which
      // path a firm came through decided whether its own GSTIN was readable.
      const updateRes = await api.firm.saveProfile({
        name: firmForm.name.trim(),
        pan: firmForm.pan.trim(),
        gstin: firmForm.gstin.trim(),
        phone: firmForm.phone.trim(),
        address_line1: firmForm.address.trim(),
        city: firmForm.city.trim(),
        state: firmForm.state,
        pincode: firmForm.pincode.trim(),
      });
      if (!updateRes.success) throw new Error(updateRes.error ?? "Failed to save the firm profile.");
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
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save firm profile");
    } finally {
      setSaving(false);
    }
  }

  // ─── No session: nothing here to continue ──────────────────────────────
  // /onboarding is public (it has to run before a firm exists), so nothing
  // above redirected a session-less visitor away — the wizard rendered Step 1
  // regardless, submitting it surfaced the SDK's raw "Auth session missing!",
  // and the greeting interpolated a blank `user?.email` (sweep-auth-and-public-04).
  if (!mayRenderOnboardingWizard({ loading: authLoading, hasSession: !!session })) {
    return (
      <div className="min-h-screen bg-ps-bg flex items-center justify-center p-4">
        <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-ps-border p-8 text-center">
          <div className="flex items-center gap-2 justify-center mb-4">
            <LogoIcon size="sm" />
            <span className="text-sm font-semibold text-ps-body">PracticeSync AI</span>
          </div>
          <h1 className="text-xl font-bold text-ps-ink mb-2">You are not signed in</h1>
          <p className="text-sm text-ps-label mb-6">
            This setup page cannot continue until you are. If you have a sign-up email, open its link again: it can be opened more than once until it expires.
            {canEmailNewLink ? ` Or we can email a new link to ${stashedEmail}, the address you signed up with, and you can sign in if you already have a password.` : " Or request a new sign-up link, and sign in if you already have a password."}
          </p>
          {canEmailNewLink && (
            <div className="mb-3 space-y-2">
              <Button
                variant="plain" size="none" onClick={() => emailNewLink()} disabled={linkSending || linkWait > 0}
                className="w-full bg-brand text-white text-sm font-medium py-2 rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
              >
                {linkSending ? "Sending…" : linkWait > 0 ? `Email me a new link (wait ${linkWait}s)` : "Email me a new link"}
              </Button>
              {linkNote && (
                <p role={linkNote.tone === "problem" ? "alert" : "status"} className={`text-xs ${linkNote.tone === "problem" ? "text-state-problem" : "text-green-700"}`}>
                  {linkNote.text}
                </p>
              )}
            </div>
          )}
          <div className="flex flex-col gap-2">
            <Link
              href="/signup"
              className="flex items-center justify-center gap-2 px-5 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors"
            >
              Start a new sign-up
            </Link>
            <Link
              href="/login"
              className="flex items-center justify-center gap-2 px-5 py-2 border border-ps-border text-ps-body text-sm font-medium rounded-lg hover:bg-ps-bg transition-colors"
            >
              Sign in
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // ─── This address already has a practice (POST-A-480) ─────────────────
  if (landing === "existing-practice") {
    return (
      <div className="min-h-screen bg-ps-bg flex items-center justify-center p-4">
        <div data-existing-practice="" className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-ps-border p-8 text-center">
          <div className="flex items-center gap-2 justify-center mb-4">
            <LogoIcon size="sm" />
            <span className="text-sm font-semibold text-ps-body">PracticeSync AI</span>
          </div>
          {/* An h2, not a third h1: a screen's own h1 is on a frozen list (scripts/a-screen-names-itself-through-one-component). */}
          <h2 className="text-xl font-bold text-ps-ink mb-2">This address already has a practice</h2>
          <p className="text-sm text-ps-body mb-2">{signedInAsSentence(memberName, userRole, existingFirmName)}</p>
          <p className="text-sm text-ps-label mb-6">
            One sign-in belongs to one practice, so it cannot start a new firm. To set up a different firm, sign out
            and use another email address.
          </p>
          <div className="flex flex-col gap-2">
            <Button
              variant="plain" size="none"
              onClick={() => { clearSignupStash(browserStorage()); router.replace("/"); }}
              className="flex items-center justify-center gap-2 px-5 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors"
            >
              {existingFirmName ? `Continue to ${existingFirmName}` : "Continue to my practice"}
            </Button>
            <Button
              variant="plain" size="none"
              onClick={async () => { clearSignupStash(browserStorage()); await signOut(); router.replace("/signup"); }}
              className="flex items-center justify-center gap-2 px-5 py-2 border border-ps-border text-ps-body text-sm font-medium rounded-lg hover:bg-ps-bg transition-colors"
            >
              Sign out and use another address
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // ─── Render ────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-ps-bg flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-white rounded-2xl shadow-sm border border-ps-border p-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <LogoIcon size="sm" />
            <span className="text-sm font-semibold text-ps-body">PracticeSync AI</span>
          </div>
          <h1 className="text-2xl font-bold text-ps-ink mt-4">Welcome! Let&apos;s set up your firm</h1>
          <p className="text-sm text-ps-label mt-1">This takes about 2 minutes. You can always update these later in Settings.</p>
        </div>

        <ProgressBar step={step} />

        {error && <Callout tone="problem">{error}</Callout>}

        {provisionNote && (
          <div className="mb-4 px-4 py-3 bg-state-attention-surface border border-state-attention-border rounded-lg text-sm text-amber-800">
            {provisionNote}
          </div>
        )}

        {/* ── Step 1: Create Password ──────────────────────────────────────── */}
        {step === 1 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <KeyRound size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-ps-ink">Create your password</h2>
            </div>
            <p className="text-sm text-ps-label mb-5">
              Your email is verified. Set a password so you can sign in any time — you signed up with <span className="font-medium text-ps-body">{user?.email}</span>.
            </p>

            <div className="space-y-4 max-w-md">
              <div>
                <label className="text-xs font-medium text-ps-label block mb-1">Full Name<span className="text-state-problem ml-0.5">*</span></label>
                <input aria-label="Full name"
                  type="text"
                  value={ownerName}
                  onChange={(e) => setOwnerName(e.target.value)}
                  placeholder="e.g. CA Ravi Sharma"
                  autoComplete="name"
                  className="w-full text-sm text-ps-ink border border-ps-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg"
                />
              </div>
              {(!pwSet || pw !== "" || pw2 !== "") && <PasswordRules password={pw} id="onboarding-password-rules" />}
              <div>
                <label className="text-xs font-medium text-ps-label block mb-1">{pwSet ? "New password (only if you want to change it)" : "Password"}{!pwSet && <span className="text-state-problem ml-0.5">*</span>}</label>
                <div className="relative">
                  <input aria-label="Password"
                    aria-describedby={!pwSet || pw !== "" || pw2 !== "" ? "onboarding-password-rules" : undefined}
                    type={showPw ? "text" : "password"}
                    value={pw}
                    onChange={(e) => setPw(e.target.value)}
                    placeholder="Create a password"
                    autoComplete="new-password"
                    className={`w-full text-sm text-ps-ink border rounded-lg px-3 py-2 pr-10 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg ${pwError ? "border-red-400 bg-state-problem-surface" : "border-ps-border"}`}
                  />
                  <button type="button" onClick={() => setShowPw((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-ps-hint hover:text-ps-label">
                    {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-ps-label block mb-1">Confirm password{!pwSet && <span className="text-state-problem ml-0.5">*</span>}</label>
                <input aria-label="Confirm password"
                  type={showPw ? "text" : "password"}
                  value={pw2}
                  onChange={(e) => setPw2(e.target.value)}
                  placeholder="Re-enter your password"
                  autoComplete="new-password"
                  className={`w-full text-sm text-ps-ink border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg ${pwError ? "border-red-400 bg-state-problem-surface" : "border-ps-border"}`}
                />
              </div>
              {pwError && <p className="text-xs text-state-problem">{pwError}</p>}
              {pwSet && (
                <div className="flex items-center gap-2 text-sm text-green-700"><CheckCircle size={15} /> Password set</div>
              )}

              {needsReauth && (
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg space-y-3">
                  <p className="text-sm font-medium text-blue-900">Check your email for a verification code</p>
                  <p className="text-sm text-blue-700">
                    We sent an 8-digit code to <span className="font-medium">{user?.email}</span>. Enter it below to set your password.
                  </p>
                  <input aria-label="Email verification code"
                    type="text"
                    inputMode="numeric"
                    maxLength={8}
                    value={reauthOtp}
                    onChange={(e) => { setReauthError(null); setReauthOtp(e.target.value.replace(/\D/g, "")); }}
                    placeholder="8-digit code"
                    autoComplete="one-time-code"
                    className="w-full text-sm border border-blue-300 rounded-lg px-3 py-2 tracking-widest text-center focus:outline-none focus:ring-2 focus:ring-brand bg-white"
                  />
                  {reauthError && <p className="text-xs text-state-problem">{reauthError}</p>}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={verifyAndSetPassword}
                      disabled={reauthSending || reauthOtp.length < 8}
                      className="flex items-center gap-2 px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
                    >
                      {reauthSending ? "Verifying…" : "Verify & Set Password"}
                      {!reauthSending && <ChevronRight size={14} />}
                    </button>
                    <button
                      type="button"
                      onClick={resendReauthCode}
                      disabled={actionInFlight}
                      className="text-sm text-blue-700 hover:text-blue-900 hover:underline disabled:opacity-50"
                    >
                      Resend code
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end mt-8 pt-5 border-t border-ps-border">
              {(() => {
                // Once the password is set the step asks for nothing more; typing a new one makes it a change again
                // (lib/auth/passwordStep).
                const carryOn = passwordStepMode({ passwordSet: pwSet, pw, pw2 }) === "continue";
                return (
                  <button
                    onClick={carryOn ? continueWithSetPassword : savePassword}
                    disabled={!passwordStepButtonEnabled({ passwordSet: pwSet, pw, pw2, saving, needsReauth })}
                    className="flex items-center gap-2 px-5 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
                  >
                    {saving ? "Saving…" : carryOn ? "Continue" : "Set Password & Continue"}
                    {!saving && <ChevronRight size={16} />}
                  </button>
                );
              })()}
            </div>
          </div>
        )}

        {/* ── Step 2: Firm Profile ────────────────────────────────────────── */}
        {step === 2 && (
          <div>
            <div className="flex items-center gap-2 mb-5">
              <Building2 size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-ps-ink">Firm Profile</h2>
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
                placeholder="e.g. 27AABCU9603R1ZN"
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
                <label className="text-xs font-medium text-ps-label block mb-1">State</label>
                <select aria-label="State"
                  value={firmForm.state}
                  onChange={(e) => setFirmForm((p) => ({ ...p, state: e.target.value }))}
                  className="w-full text-sm text-ps-ink border border-ps-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg"
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

            <div className="flex items-center justify-between mt-8 pt-5 border-t border-ps-border">
              <button
                onClick={goBack}
                className="flex items-center gap-1 text-sm text-ps-label hover:text-ps-body transition-colors"
              >
                <ChevronLeft size={16} /> Back
              </button>
              <Button variant="plain" size="none"
                onClick={saveFirmProfile}
                disabled={actionInFlight}
                className="flex items-center gap-2 px-5 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
              >
                {saving ? "Setting up your workspace…" : "Continue"}
                {!saving && <ChevronRight size={16} />}
              </Button>
            </div>
          </div>
        )}

        {/* ── Step 3: Import Firm HSN/SAC Library ─────────────────────────── */}
        {step === 3 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Hash size={18} className="text-violet-600" />
              <h2 className="text-base font-semibold text-ps-ink">Import your HSN/SAC library</h2>
            </div>
            <p className="text-sm text-ps-label mb-5">
              PracticeSync does not ship or suggest HSN/SAC classifications — you own and curate the codes your
              firm bills against. Add a few now, import a list, or skip and add codes as you invoice.
            </p>

            {hsnAddedCount > 0 && (
              <div className="mb-4 flex items-center gap-2 rounded-lg bg-emerald-50 border border-emerald-100 px-3 py-2 text-sm text-emerald-700">
                <CheckCircle size={15} /> {hsnAddedCount} code{hsnAddedCount === 1 ? "" : "s"} in your library so far.
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setHsnQuickAddOpen(true)}
                className="flex items-start gap-3 rounded-xl border border-ps-border p-4 text-left hover:border-violet-300 hover:bg-violet-50/30 transition-colors"
              >
                <Plus size={18} className="text-violet-600 shrink-0 mt-0.5" />
                <span>
                  <span className="block text-sm font-medium text-ps-ink">Add codes one at a time</span>
                  <span className="block text-xs text-ps-hint mt-0.5">Quick for a handful of codes you already know.</span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => setHsnImportOpen(true)}
                className="flex items-start gap-3 rounded-xl border border-ps-border p-4 text-left hover:border-violet-300 hover:bg-violet-50/30 transition-colors"
              >
                <Upload size={18} className="text-violet-600 shrink-0 mt-0.5" />
                <span>
                  <span className="block text-sm font-medium text-ps-ink">Import a list</span>
                  <span className="block text-xs text-ps-hint mt-0.5">Download a blank template, fill it from your own records, upload it back.</span>
                </span>
              </button>
            </div>

            <a
              href={GST_PORTAL_HSN_SEARCH_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1.5 text-xs text-ps-label hover:text-violet-700 transition-colors"
            >
              <ExternalLink size={12} /> Get the official HSN/SAC list from the GST portal
            </a>

            <div className="flex items-center justify-between mt-8 pt-5 border-t border-ps-border">
              <button
                onClick={() => setStep(2)}
                className="flex items-center gap-1 text-sm text-ps-label hover:text-ps-body transition-colors"
              >
                <ChevronLeft size={16} /> Back
              </button>
              <div className="flex items-center gap-3">
                <Button variant="plain" size="none"
                  onClick={finish}
                  className="text-sm text-ps-label hover:text-ps-body transition-colors"
                >
                  Skip for now
                </Button>
                <Button variant="plain" size="none"
                  onClick={finish}
                  className="flex items-center gap-2 px-5 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors"
                >
                  {hsnAddedCount > 0 ? "Finish setup" : "Continue"}
                  <ChevronRight size={16} />
                </Button>
              </div>
            </div>
          </div>
        )}

      </div>

      {hsnQuickAddOpen && (
        <FirmHsnLibraryQuickAddModal
          onClose={() => setHsnQuickAddOpen(false)}
          onAdded={() => { setHsnQuickAddOpen(false); setHsnAddedCount((n) => n + 1); }}
        />
      )}

      {hsnImportOpen && (
        <CsvImportModal
          title="Import your HSN/SAC library"
          columns={HSN_LIBRARY_IMPORT_COLUMNS}
          templateFilename="hsn-sac-library-template.csv"
          validateRow={validateHsnLibraryImportRow}
          onImport={async (rows) => {
            const res = await importHsnLibraryRows(rows);
            setHsnAddedCount((n) => n + res.imported);
            return res;
          }}
          onClose={() => setHsnImportOpen(false)}
        />
      )}
    </div>
  );
}
