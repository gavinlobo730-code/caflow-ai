"use client";

/**
 * Employee portal activation — the landing page for the invite link emailed by
 * services/employee_portal_service.py::_send_invite_email.
 *
 * Deliberately a SEPARATE page from /portal/activate rather than a branch
 * inside it. That one binds a client_portal_users membership; this binds a
 * payroll_employees row. They authorise through different endpoints, land on
 * different dashboards, and an employee is neither firm staff nor a client
 * contact — folding them together would mean one page guessing which kind of
 * invite it holds, and guessing wrong would bind the wrong thing.
 *
 * Flow: wait for the magic-link session → present the token to
 * POST /api/portal/employee/accept-invite (this is the step that sets
 * auth_user_id and portal_enabled) → collect a password so they can sign in
 * again at /portal/login without needing a fresh link every time.
 *
 * The query parameter is `token`, matching employee_portal_service's
 * activation_url(). The client page uses `invite` — they are separate links and
 * neither should be assumed to match the other.
 *
 * Same reauthentication-nonce fallback as /portal/activate and onboarding: a
 * magic-link session that is not "recently signed in" needs
 * reauthenticate() → updateUser({ password, nonce }). See lib/auth/reauth.ts.
 *
 * Re-visiting a spent link: the token is single use, so the second accept
 * fails. That is only an error if this identity has no access yet — someone who
 * already finished is sent on to their payslips instead of shown "invalid".
 */
import { useState, useEffect, useRef, FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import { setPasswordWithReauthNonce, isInvalidNonceError } from "@/lib/auth/reauth";
import { Eye, EyeOff, ShieldCheck, AlertCircle, Loader2 } from "lucide-react";

const MIN_LENGTH = 10;
const SESSION_WAIT_ATTEMPTS = 10;
const SESSION_WAIT_INTERVAL_MS = 500;

type Stage = "verifying" | "invalid" | "form" | "reauth" | "done";

/** Does this identity already have employee-portal access?
 *
 * Asked of the database, not the API: migration 262's employee_sees_own_record
 * returns their own row only once auth_user_id is bound AND portal_enabled is
 * true — exactly the state acceptance produces. So one row back means they are
 * already activated, and a spent token is nothing to worry about. */
async function alreadyActivated(): Promise<boolean> {
  try {
    const sb = getSupabaseClient();
    const { data: { session } } = await sb.auth.getSession();
    if (!session) return false;
    const { data } = await sb
      .from("payroll_employees")
      .select("id")
      .eq("auth_user_id", session.user.id)
      .eq("portal_enabled", true)
      .maybeSingle();
    return Boolean(data);
  } catch {
    return false;
  }
}

export default function EmployeeActivatePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const supabase = getSupabaseClient();
  const token = searchParams.get("token");

  const [stage, setStage] = useState<Stage>("verifying");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reauthOtp, setReauthOtp] = useState("");
  const [reauthError, setReauthError] = useState<string | null>(null);
  // Mirrors `pw` so verifyReauth() reads what was typed before the nonce
  // round-trip, which re-renders this component.
  const pwRef = useRef("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!token) {
        if (!cancelled) setStage("invalid");
        return;
      }
      // The magic link signs the browser in as it opens (detectSessionInUrl),
      // but not synchronously — poll rather than read once.
      let session = null;
      for (let attempt = 0; attempt < SESSION_WAIT_ATTEMPTS; attempt++) {
        const { data } = await supabase.auth.getSession();
        if (data?.session) { session = data.session; break; }
        await new Promise((r) => setTimeout(r, SESSION_WAIT_INTERVAL_MS));
      }
      if (cancelled) return;
      if (!session) { setStage("invalid"); return; }

      try {
        await api.portalSelf.acceptEmployeeInvite(token);
        if (!cancelled) setStage("form");
      } catch {
        const active = await alreadyActivated();
        if (cancelled) return;
        if (active) router.replace("/portal/employee");
        else setStage("invalid");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSetPassword(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (pw.length < MIN_LENGTH) {
      setError(`Use at least ${MIN_LENGTH} characters.`);
      return;
    }
    if (pw !== pw2) {
      setError("The two passwords do not match.");
      return;
    }
    setSaving(true);
    pwRef.current = pw;
    try {
      const { error: err } = await supabase.auth.updateUser({ password: pw });
      if (err) {
        if (isInvalidNonceError(err)) {
          // Not "recently signed in" — Supabase emails a nonce to confirm.
          await supabase.auth.reauthenticate();
          setStage("reauth");
          return;
        }
        throw new Error(err.message);
      }
      setStage("done");
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : "Could not set your password.");
    } finally {
      setSaving(false);
    }
  }

  async function verifyReauth(e: FormEvent) {
    e.preventDefault();
    setReauthError(null);
    setSaving(true);
    try {
      const { error: err } = await setPasswordWithReauthNonce(
        supabase.auth, pwRef.current, reauthOtp);
      if (err) throw new Error(err.message);
      setStage("done");
    } catch (ex) {
      setReauthError(ex instanceof Error ? ex.message : "That code did not work.");
    } finally {
      setSaving(false);
    }
  }

  const shell = (children: React.ReactNode) => (
    <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-white rounded-xl border border-[#F1F5F9] p-6 shadow-sm">
        {children}
      </div>
    </div>
  );

  if (stage === "verifying") {
    return shell(
      <div className="flex items-center gap-3 text-[#64748B]">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Checking your invitation…</span>
      </div>
    );
  }

  if (stage === "invalid") {
    return shell(
      <div>
        <div className="flex items-start gap-2 mb-3">
          <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <h1 className="text-base font-semibold text-[#0F172A]">
              This invitation cannot be used
            </h1>
            {/* Deliberately one message for every cause. The backend returns an
                identical 404 whether the token is unknown, expired, already
                used, or issued to a different address — saying which would let
                someone probe for valid links. */}
            <p className="text-sm text-[#64748B] mt-1">
              It may have expired, already been used, or been sent to a
              different email address. Ask your employer to send a new one.
            </p>
          </div>
        </div>
        <Link href="/portal/login" className="text-sm text-blue-600 hover:underline">
          Go to sign in
        </Link>
      </div>
    );
  }

  if (stage === "done") {
    return shell(
      <div>
        <div className="flex items-start gap-2 mb-4">
          <ShieldCheck className="w-5 h-5 text-green-600 shrink-0 mt-0.5" />
          <div>
            <h1 className="text-base font-semibold text-[#0F172A]">You&apos;re all set</h1>
            <p className="text-sm text-[#64748B] mt-1">
              You can now view your payslips and leave balance any time.
            </p>
          </div>
        </div>
        <button
          onClick={() => router.replace("/portal/employee")}
          className="w-full bg-[#0F172A] text-white rounded-lg py-2.5 text-sm font-medium hover:bg-[#1E293B]"
        >
          View my payslips
        </button>
      </div>
    );
  }

  if (stage === "reauth") {
    return shell(
      <form onSubmit={verifyReauth}>
        <h1 className="text-base font-semibold text-[#0F172A]">Confirm it&apos;s you</h1>
        <p className="text-sm text-[#64748B] mt-1 mb-4">
          We emailed you a short code. Enter it to finish setting your password.
        </p>
        <input
          value={reauthOtp}
          onChange={(e) => setReauthOtp(e.target.value)}
          placeholder="6-digit code"
          className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm mb-3"
          autoComplete="one-time-code"
        />
        {reauthError && <p className="text-sm text-red-600 mb-3">{reauthError}</p>}
        <button
          type="submit"
          disabled={saving || !reauthOtp.trim()}
          className="w-full bg-[#0F172A] text-white rounded-lg py-2.5 text-sm font-medium disabled:opacity-50"
        >
          {saving ? "Confirming…" : "Confirm"}
        </button>
      </form>
    );
  }

  return shell(
    <form onSubmit={handleSetPassword}>
      <h1 className="text-base font-semibold text-[#0F172A]">Choose a password</h1>
      <p className="text-sm text-[#64748B] mt-1 mb-4">
        Your access is active. Set a password so you can sign in whenever you
        like, without waiting for another email.
      </p>

      <div className="relative mb-3">
        <input
          type={showPw ? "text" : "password"}
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          placeholder={`At least ${MIN_LENGTH} characters`}
          className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 pr-10 text-sm"
          autoComplete="new-password"
        />
        <button
          type="button"
          onClick={() => setShowPw((v) => !v)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8]"
          aria-label={showPw ? "Hide password" : "Show password"}
        >
          {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>

      <input
        type={showPw ? "text" : "password"}
        value={pw2}
        onChange={(e) => setPw2(e.target.value)}
        placeholder="Repeat password"
        className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm mb-3"
        autoComplete="new-password"
      />

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      <button
        type="submit"
        disabled={saving}
        className="w-full bg-[#0F172A] text-white rounded-lg py-2.5 text-sm font-medium disabled:opacity-50"
      >
        {saving ? "Saving…" : "Set password"}
      </button>
    </form>
  );
}
