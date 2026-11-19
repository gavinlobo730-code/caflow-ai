"use client";

/**
 * Security settings — password change + Multi-Factor Authentication (TOTP).
 *
 * Change Password requires the CURRENT password before accepting a new one.
 * The check is made on a THROWAWAY client that keeps nothing (lib/auth/
 * verifyCurrentPassword, lib/supabase/client.makeEphemeralAuthClient), so it
 * never replaces this browser's session, and the password is sent again in the
 * update itself (`current_password`) for the project's "Require current
 * password when updating" switch, which refuses a change without it (POST-A-512).
 * A live session alone isn't proof of identity here; without this, anyone who
 * gets to an unlocked, already-signed-in browser could silently lock the real
 * owner out by just setting a new password. This is on top of, not instead of,
 * Supabase's own session auth — a stolen/left-open SESSION and knowledge of the
 * CURRENT PASSWORD are different things, and this form demands both.
 *
 * MFA section: lets any signed-in user enrol an authenticator app (Google
 * Authenticator, Authy, 1Password, …) as a TOTP second factor, scan a QR
 * code, and verify a 6-digit code. Required before REQUIRE_MFA is enabled
 * for MFA-required roles (default: Partner) — otherwise those users would be
 * locked out. Uses Supabase Auth MFA: enroll → challenge → verify. The
 * verified factor lets the user elevate to aal2 at login (see app/login).
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { ShieldCheck, Smartphone, Trash2, CheckCircle2, Loader2, AlertCircle, KeyRound } from "lucide-react";
import { getSupabaseClient, makeEphemeralAuthClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { setPasswordWithReauthNonce, isInvalidNonceError } from "@/lib/auth/reauth";
import { Callout } from "@/components/ui/callout";
import { api, type SecurityPosture } from "@/lib/api/index";
import { objectWithLists } from "@/lib/api/shape";
import Link from "next/link";
import { setupPageLead, SETUP_CONTINUE_HREF } from "@/lib/auth/mfaEnrolment";
import { authErrorMessage } from "@/lib/auth/authErrorMessage";

import { todayIstISO } from "@/lib/dates/format";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingRegion } from "@/components/ui/skeleton";
import { passwordProblem } from "@/lib/auth/passwordRules";
import { rememberPasswordNotice, takePasswordNotice, rememberPasswordRefusal, takePasswordRefusal } from "@/lib/auth/passwordNotice";
import { verifyCurrentPassword } from "@/lib/auth/verifyCurrentPassword";
import { PasswordField } from "@/components/auth/PasswordField";
import { PasswordRules } from "@/components/auth/PasswordRules";
import { MyDevicesCard } from "@/components/security/MyDevicesCard";

interface Factor {
  id: string;
  friendly_name?: string | null;
  status: string; // 'verified' | 'unverified'
  factor_type: string;
}

interface Enrolling {
  factorId: string;
  qr: string;      // SVG data-URI
  secret: string;  // manual-entry secret
}

export default function SecuritySettingsPage() {
  // `?setup=1` is where onboarding and the "Secure your account" banner send
  // somebody who has no authenticator yet. Read in an effect: static export.
  const [setup, setSetup] = useState(false);
  useEffect(() => {
    setSetup(new URLSearchParams(window.location.search).get("setup") === "1");
  }, []);
  const { mustEnrolMfa, mfaLockedSentence } = useAuth();
  const lead = setupPageLead(setup, mustEnrolMfa);
  return (
    <div className="p-6 max-w-2xl mx-auto space-y-5">
      <PageHeader
        title="Security"
        subtitle="Manage your password and two-factor authentication"
      />
      {lead === "continue" && (
        <Callout tone="note" title="You're all set">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm">Your account has what it needs. Carry on to your workspace.</p>
            <Link
              href={SETUP_CONTINUE_HREF}
              className="inline-flex items-center rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark"
            >
              Continue to your workspace
            </Link>
          </div>
        </Callout>
      )}
      {setup ? (
        <>
          {lead === "welcome" && (
          <Callout tone="note" title="Welcome — one last step">
            <p className="text-sm">
              Your practice holds clients&apos; financial records, so some screens open only after you
              add an authenticator app (Google Authenticator, Authy, 1Password or similar).
              {/* What they are for THIS person is the server's sentence (PRE-A-021), never a fixed list. */}
              {mfaLockedSentence ? <> {mfaLockedSentence}</> : null} It takes about a minute: scan the code
              below, then enter the 6-digit number the app shows.
            </p>
          </Callout>
          )}
          <MfaCard />
          <ChangePasswordCard />
        </>
      ) : (
        <>
          <ChangePasswordCard />
          <MfaCard />
          <MyDevicesCard />
          <PostureCard />
        </>
      )}
    </div>
  );
}

/** ── Deployment posture (Partner only) ──────────────────────────────────────
 *
 * SECURITY-PRIVACY-16. Whether row-level security and two-step sign-in are
 * really on for the whole practice is decided by two switches that live in the
 * hosting dashboard, where nobody reading the code can see them. The server
 * reports what it actually resolved (`GET /api/security/posture`, Partner-only
 * and behind the MFA guard) and this card shows it — sentences, tones and
 * booleans as served, nothing derived here.
 *
 * Hidden for anyone `firm:admin` is not granted to, because the endpoint would
 * refuse them: a card that can only ever say "forbidden" is noise.
 */
function PostureCard() {
  const { can } = useAuth();
  const allowed = can("firm", "admin");
  const [posture, setPosture] = useState<SecurityPosture | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!allowed) return;
    let live = true;
    api.security.posture()
      .then((res) => {
        if (!live) return;
        if (!res.success) { setError(res.error || "Could not read the security posture."); return; }
        const next = objectWithLists<SecurityPosture>(res.data, "problems", "mfa_required_roles");
        if (!next) { setError("The server answered with something unreadable."); return; }
        setError(null);
        setPosture(next);
      })
      .catch(() => { if (live) setError("Could not read the security posture."); });
    return () => { live = false; };
  }, [allowed]);

  if (!allowed) return null;

  const rows: Array<{ label: string; on: boolean; note?: string }> = posture ? [
    { label: "Database access runs as the signed-in user (row-level security)", on: posture.use_user_jwt },
    {
      label: "Two-step sign-in required",
      on: posture.require_mfa,
      note: posture.require_mfa && posture.mfa_required_roles.length > 0
        ? `for ${posture.mfa_required_roles.join(", ")}` : undefined,
    },
    { label: "Scheduled jobs (reminders, recurring documents)", on: posture.scheduler_enabled },
  ] : [];

  return (
    // `id` is the Settings link's anchor (PRE-A-023: Security and access → How this deployment is set up), and
    // the scroll margin keeps the heading clear of the sticky Settings tab row.
    <div id="deployment" className="scroll-mt-16 bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
        <ShieldCheck size={15} className="text-blue-600" />
        <h2 className="text-sm font-semibold text-ps-ink">How this deployment is set up</h2>
      </div>
      <div className="px-5 py-4 space-y-3">
        {error && (
          <p className="text-xs text-red-600 flex items-start gap-1.5"><AlertCircle size={13} className="mt-0.5 shrink-0" /> {error}</p>
        )}
        {!posture && !error && <LoadingRegion label="Reading the live settings" className="text-sm text-ps-label">Reading the live settings…</LoadingRegion>}
        {posture && (
          <>
            <ul className="divide-y divide-ps-border">
              {rows.map((r) => (
                <li key={r.label} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="text-ps-body">
                    {r.label}{r.note ? <span className="text-ps-label"> — {r.note}</span> : null}
                  </span>
                  <span
                    className={
                      "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium " +
                      (r.on ? "bg-state-ready-surface text-state-ready" : "bg-state-problem-surface text-state-problem")
                    }
                  >
                    {r.on ? "On" : "Off"}
                  </span>
                </li>
              ))}
            </ul>
            {posture.problems.map((p) => (
              <Callout key={p.code} tone={p.tone}>{p.message}</Callout>
            ))}
            <p className="text-xs text-ps-label">
              This is what the running service reports about itself, not what a note says it should be.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

/** ── Change Password ─────────────────────────────────────────────────────── */
function ChangePasswordCard() {
  const supabase = getSupabaseClient();
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  // A sentence left by an earlier mount of this card, for the success AND for a refusal: if the page is rebuilt while a change is in
  // flight, the answer arrives at a page that has gone, and it is shown by the page that replaced it (POST-A-493, POST-A-512).
  const [error, setError] = useState<string | null>(() => takePasswordRefusal());
  const [notice, setNotice] = useState<string | null>(() => takePasswordNotice());
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  // Reauthentication-nonce fallback — same "Secure password change" gap
  // onboarding's password step and /auth/reset-password already handle.
  const [needsReauth, setNeedsReauth] = useState(false);
  const [reauthOtp, setReauthOtp] = useState("");

  function reset() {
    setCurrent(""); setNext(""); setConfirm("");
    setNeedsReauth(false); setReauthOtp("");
  }

  /** The password was saved: say so here, or, if this page was unmounted while it was being saved, on the one that replaced it. */
  function passwordSaved() {
    const sentence = "Your password has been updated.";
    if (!mounted.current) { rememberPasswordNotice(sentence); return; }
    setNotice(sentence);
    reset();
  }

  /** The change was refused: say why, here or on the page that replaced this one. A refusal is never silent (POST-A-512). */
  function refused(sentence: string) {
    if (!mounted.current) { rememberPasswordRefusal(sentence); return; }
    setError(sentence);
  }

  async function submit() {
    setError(null); setNotice(null);
    if (!current) { setError("Enter your current password."); return; }
    // Every rule the sign-in service enforces, before anything is sent (POST-A-477).
    const rulesProblem = passwordProblem(next);
    if (rulesProblem) { setError(rulesProblem); return; }
    if (next !== confirm) { setError("New passwords do not match."); return; }
    if (!user?.email) { setError("Could not determine your account email. Please refresh and try again."); return; }
    setBusy(true);
    try {
      // Prove identity with the CURRENT password before changing it — a live session is not sufficient on its own (see the card's doc
      // comment). The proof is made on a throwaway client that keeps nothing, so it neither replaces this browser's session (which
      // rebuilt this page and dropped a person with an authenticator back to the first level) nor depends on the project's switch.
      const proof = await verifyCurrentPassword(user.email, current, makeEphemeralAuthClient);
      if (!proof.ok) { refused(proof.message); return; }

      // The current password goes in the update itself: with the project's "Require current password when updating" switch on, a
      // change without it is refused with `current_password_required` (seen live on 19-11-2026, POST-A-512).
      const { error: upErr } = await supabase.auth.updateUser({ password: next, current_password: current });
      if (upErr) {
        if (upErr.message.toLowerCase().includes("reauthentication")) {
          const { error: raErr } = await supabase.auth.reauthenticate();
          if (raErr) { refused("Could not send a verification code. Please try again."); return; }
          setNeedsReauth(true);
          return;
        }
        refused(authErrorMessage(upErr));
        return;
      }
      passwordSaved();
    } catch (e) {
      refused(authErrorMessage(e, "Could not update your password. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  async function verifyReauth() {
    setError(null);
    setBusy(true);
    try {
      const { error: upErr } = await setPasswordWithReauthNonce(supabase.auth, next, reauthOtp, current);
      if (upErr) {
        refused(isInvalidNonceError(upErr) ? "That code is incorrect or has expired. Try changing your password again." : authErrorMessage(upErr));
        return;
      }
      passwordSaved();
    } catch (e) {
      refused(authErrorMessage(e, "Verification failed. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const inputCls = "w-full px-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand";

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
        <KeyRound size={15} className="text-blue-600" />
        <h2 className="text-sm font-semibold text-ps-ink">Change Password</h2>
      </div>

      <div className="px-5 py-4 space-y-4">
        {error && (
          <p role="alert" className="text-xs text-state-problem flex items-start gap-1.5"><AlertCircle size={13} className="mt-0.5 shrink-0" /> {error}</p>
        )}
        {notice && (
          <p role="status" className="text-xs text-state-ready flex items-start gap-1.5"><CheckCircle2 size={13} className="mt-0.5 shrink-0" /> {notice}</p>
        )}

        {needsReauth ? (
          <div className="space-y-3">
            <p className="text-sm text-ps-body">
              For your security, we sent a verification code to your email. Enter it below to finish changing your password.
            </p>
            <div className="flex gap-2">
              <input aria-label="Verification code from your email"
                value={reauthOtp}
                onChange={(e) => setReauthOtp(e.target.value.replace(/\D/g, "").slice(0, 8))}
                inputMode="numeric" maxLength={8} placeholder="123456"
                className="w-36 text-center tracking-widest font-mono text-base border border-ps-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand"
              />
              <button
                onClick={verifyReauth}
                disabled={busy || reauthOtp.length < 6}
                className="px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark disabled:opacity-50"
              >
                {busy ? "Verifying…" : "Verify & update"}
              </button>
              <button
                onClick={() => { setNeedsReauth(false); setReauthOtp(""); }}
                className="px-4 py-2 text-sm text-ps-label border border-ps-border rounded-lg hover:bg-ps-bg"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {/* Each box has its OWN eye and hides only itself (POST-A-513): one setting used to drive all three while only the
                new-password box carried the eye, so the current password showed in clear with nothing beside it to hide it. */}
            <div className="space-y-1.5">
              <label htmlFor="security-current-password" className="block text-xs font-medium text-ps-label">Current password</label>
              <div className="max-w-sm">
                <PasswordField id="security-current-password" label="current password" autoComplete="current-password"
                  value={current} onChange={setCurrent} inputClassName={inputCls} />
              </div>
            </div>
            <PasswordRules password={next} id="security-password-rules" />
            <div className="space-y-1.5">
              <label htmlFor="security-new-password" className="block text-xs font-medium text-ps-label">New password</label>
              <div className="max-w-sm">
                <PasswordField id="security-new-password" label="new password" autoComplete="new-password"
                  value={next} onChange={setNext} inputClassName={inputCls} placeholder="Create a password"
                  ariaDescribedBy="security-password-rules" />
              </div>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="security-confirm-password" className="block text-xs font-medium text-ps-label">Confirm new password</label>
              <div className="max-w-sm">
                <PasswordField id="security-confirm-password" label="confirmation of the new password" autoComplete="new-password"
                  value={confirm} onChange={setConfirm} inputClassName={inputCls} />
              </div>
            </div>
            <button
              onClick={submit}
              disabled={busy || !current || !next || !confirm}
              className="px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark disabled:opacity-50"
            >
              {busy ? "Updating…" : "Update password"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function MfaCard() {
  const supabase = getSupabaseClient();
  const { refreshUserContext, resolveEnrolmentRequired } = useAuth();
  // The session is aal2 once a factor verifies, so the permissions map the
  // aal1 token was refused, and the enrolment banner, are re-asked here rather
  // than left to whichever auth event happens to fire next.
  const reResolveAccess = useCallback(() => {
    refreshUserContext().catch(() => {});
    resolveEnrolmentRequired().catch(() => {});
  }, [refreshUserContext, resolveEnrolmentRequired]);
  const [factors, setFactors] = useState<Factor[]>([]);
  const [loading, setLoading] = useState(true);
  const [enrolling, setEnrolling] = useState<Enrolling | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const verified = factors.filter((f) => f.status === "verified");
  const mfaEnabled = verified.length > 0;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data, error } = await supabase.auth.mfa.listFactors();
      if (error) throw error;
      // `all` includes unverified factors; show verified TOTP factors as active.
      const all = ((data as { all?: Factor[] } | null)?.all ?? []) as Factor[];
      setFactors(all.filter((f) => f.factor_type === "totp"));
    } catch (e) {
      setError(authErrorMessage(e, "Could not load MFA status."));
    } finally {
      setLoading(false);
    }
  }, [supabase]);

  useEffect(() => { load(); }, [load]);

  /** Begin TOTP enrolment: clears any stale unverified factor, then enrols. */
  async function startEnroll() {
    setBusy(true); setError(null); setNotice(null);
    try {
      // Remove any leftover unverified factors so enroll() doesn't conflict.
      for (const f of factors.filter((f) => f.status === "unverified")) {
        await supabase.auth.mfa.unenroll({ factorId: f.id }).catch(() => {});
      }
      const { data, error } = await supabase.auth.mfa.enroll({
        factorType: "totp",
        friendlyName: `Authenticator ${todayIstISO()}`,
      });
      if (error) throw error;
      const d = data as { id: string; totp: { qr_code: string; secret: string } };
      setEnrolling({ factorId: d.id, qr: d.totp.qr_code, secret: d.totp.secret });
      setCode("");
    } catch (e) {
      setError(authErrorMessage(e, "Could not start enrolment."));
    } finally {
      setBusy(false);
    }
  }

  /** Verify the 6-digit code to activate the factor (challenge + verify). */
  async function verifyEnroll() {
    if (!enrolling || code.trim().length < 6) return;
    setBusy(true); setError(null);
    try {
      const { error } = await supabase.auth.mfa.challengeAndVerify({
        factorId: enrolling.factorId,
        code: code.trim(),
      });
      if (error) throw error;
      setEnrolling(null);
      setCode("");
      setNotice("Multi-factor authentication is now enabled for your account.");
      reResolveAccess();
      await load();
    } catch (e) {
      setError(authErrorMessage(e, "Invalid code — check your authenticator app and try again."));
    } finally {
      setBusy(false);
    }
  }

  async function removeFactor(factorId: string) {
    setBusy(true); setError(null); setNotice(null);
    try {
      const { error } = await supabase.auth.mfa.unenroll({ factorId });
      if (error) throw error;
      setNotice("Authenticator removed.");
      reResolveAccess();
      await load();
    } catch (e) {
      setError(authErrorMessage(e, "Could not remove the authenticator."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
        <ShieldCheck size={15} className="text-blue-600" />
        <h2 className="text-sm font-semibold text-ps-ink">Two-Factor Authentication (TOTP)</h2>
        {mfaEnabled && (
          <span className="ml-auto inline-flex items-center gap-1 text-2xs font-medium text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
            <CheckCircle2 size={11} /> Enabled
          </span>
        )}
      </div>

        <div className="px-5 py-4 space-y-4">
          {error && (
            <p className="text-xs text-red-600 flex items-start gap-1.5"><AlertCircle size={13} className="mt-0.5 shrink-0" /> {error}</p>
          )}
          {notice && (
            <p className="text-xs text-green-700 flex items-start gap-1.5"><CheckCircle2 size={13} className="mt-0.5 shrink-0" /> {notice}</p>
          )}

          {loading ? (
            <p className="text-sm text-ps-hint flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
          ) : enrolling ? (
            /* ── Enrolment in progress: QR + verify ── */
            <div className="space-y-4">
              <p className="text-sm text-ps-body">
                1. Scan this QR code with your authenticator app (Google Authenticator, Authy, 1Password…).
              </p>
              <div className="flex flex-col sm:flex-row gap-4 items-start">
                {/* qr_code is an SVG data-URI returned by Supabase */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={enrolling.qr} alt="MFA QR code" className="w-44 h-44 border border-ps-border rounded-lg bg-white" />
                <div className="space-y-2">
                  <p className="text-xs text-ps-label">Can&apos;t scan? Enter this key manually:</p>
                  <code className="block text-xs font-mono bg-ps-bg border border-ps-border rounded-lg px-3 py-2 break-all">{enrolling.secret}</code>
                </div>
              </div>
              <div className="space-y-1.5">
                <p className="text-sm text-ps-body">2. Enter the 6-digit code from the app:</p>
                <div className="flex gap-2">
                  <input aria-label="6-digit code from the authenticator app"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="123456"
                    className="w-36 text-center tracking-widest font-mono text-base border border-ps-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand"
                  />
                  <button
                    onClick={verifyEnroll}
                    disabled={busy || code.length < 6}
                    className="px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark disabled:opacity-50"
                  >
                    {busy ? "Verifying…" : "Verify & enable"}
                  </button>
                  <button
                    onClick={() => { setEnrolling(null); setCode(""); load(); }}
                    className="px-4 py-2 text-sm text-ps-label border border-ps-border rounded-lg hover:bg-ps-bg"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          ) : mfaEnabled ? (
            /* ── Already enrolled: list + remove ── */
            <div className="space-y-3">
              <p className="text-sm text-ps-body">Your account is protected by an authenticator app.</p>
              {verified.map((f) => (
                <div key={f.id} className="flex items-center justify-between bg-ps-bg border border-ps-border rounded-lg px-3 py-2.5">
                  <div className="flex items-center gap-2.5">
                    <Smartphone size={15} className="text-ps-label" />
                    <span className="text-sm text-ps-ink">{f.friendly_name || "Authenticator app"}</span>
                  </div>
                  <button
                    onClick={() => removeFactor(f.id)}
                    disabled={busy}
                    className="flex items-center gap-1 text-xs text-red-600 hover:text-state-problem disabled:opacity-50"
                  >
                    <Trash2 size={12} /> Remove
                  </button>
                </div>
              ))}
              <button
                onClick={startEnroll}
                disabled={busy}
                className="text-xs text-blue-600 hover:underline disabled:opacity-50"
              >
                + Add another authenticator
              </button>
            </div>
          ) : (
            /* ── Not enrolled ── */
            <div className="space-y-3">
              <p className="text-sm text-ps-body">
                Add an authenticator app to require a 6-digit code at sign-in. This is required for Partner accounts.
              </p>
              <button
                onClick={startEnroll}
                disabled={busy}
                className="flex items-center gap-2 px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark disabled:opacity-50"
              >
                <Smartphone size={15} /> {busy ? "Starting…" : "Set up authenticator app"}
              </button>
            </div>
          )}
        </div>
      </div>
  );
}
