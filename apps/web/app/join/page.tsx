"use client";

/**
 * Where a staff invitation's link lands (POST-A-445).
 *
 * The invitation used to be Supabase's own sign-in link, sent from the Partner's browser, which came back here with
 * the session in the URL. It lasted only as long as Supabase keeps a one-time code, far less than the seven days the
 * invitation was good for, so a link opened the next day signed nobody in. The SERVER sends the invitation now, and
 * its link is `/join?token=...` and nothing else. This page turns the token into a sign-in itself:
 *
 *   1. A session already in this browser (an older invitation's link, whose session arrives in the URL's fragment a
 *      moment after the page loads, or the invited address signed in the usual way) is tried first: accept-invite
 *      with it.
 *   2. Signed out, the page WAITS FOR A PRESS before it signs anybody in. A mail scanner that opens links and runs
 *      their scripts would otherwise sign in, accept and use the invitation up before its owner saw it. The press asks
 *      the server for a sign-in for the invitation's OWN address (`POST /api/identity/accept-invite/session`, opened
 *      only for a live invitation the server mailed, and never for an address that already has a sign-in: that person
 *      is told to sign in as usual and open the link again), redeems it with `verifyOtp`, and accepts.
 *   3. If the browser is signed in as somebody else, it says so (learning the invited address without opening a
 *      sign-in, so merely looking creates nothing at Supabase) and asks before signing them out; it never swaps one
 *      person's session for another's silently, and it opens the sign-in only after the sign-out. (The owner, inviting himself on the live site, opened the link in
 *      the browser he was signed in to as the Partner.)
 *   4. Once accepted, the person's membership is read again before "Go to Dashboard", or the app would still think
 *      the new member has no practice and send them to create one.
 *
 * Identity is never taken from the URL: accept-invite reads the firm and the role off the server's invite row and
 * the address off the verified session (F21).
 *
 * THE JOURNEY OUTLIVES THE PAGE. Signing in here changes the session under the page, and the app's sign-in guard
 * withholds every page while it works out whether a second factor is owed, so this component is unmounted and
 * mounted again in the middle of its own work. A journey kept in the component would start again on the new mount
 * and accept a second time; the server would refuse the spent token and the person who had just joined would be told
 * the invitation could not be used (found by driving it, 16-11-2026). So the journey is kept per token outside the
 * component: a new mount waits for the journey already under way, and the button's journey replaces it.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import type { EmailOtpType } from "@supabase/supabase-js";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { LogoIcon } from "@/components/LogoIcon";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type Status = "checking" | "ready" | "other_account" | "done" | "error";

/** A sign-in the server opened for the invitation's own address. */
interface OpenedSignIn {
  token_hash: string;
  verification_type: string;
  email: string;
}

/** Where a journey ended. */
type Outcome =
  | { kind: "done"; role?: string; full_name?: string }
  | { kind: "ready" }
  | { kind: "other_account"; signedInAs: string; invitedAs: string }
  | { kind: "error"; message: string };

/** An older invitation's link brings its session in the URL's fragment, a moment after load: wait this long for it. */
const OLDER_LINK_WAITS = 8;
const OLDER_LINK_WAIT_MS = 750;

/** The server's one refusal for an invitation that cannot be accepted (routers/identity._live_invitation). */
const REFUSED = /Invalid or expired invite/;

const CANNOT_BE_USED =
  "This invitation can no longer be used. It may have expired, been replaced by a newer one, been withdrawn, or " +
  "already been accepted. Ask the practice to send it again from their Team screen.";

const COULD_NOT_SIGN_IN =
  "We could not sign you in from this invitation. Open the link again; if it still fails, ask the practice to send " +
  "the invitation again.";

function sentenceFor(e: unknown): string {
  const message = e instanceof Error ? e.message : "";
  if (!message || REFUSED.test(message)) return CANNOT_BE_USED;
  return message;
}

/** The journey under way for each token, kept outside the component so a remount waits for it (see the header). */
const journeys = new Map<string, Promise<Outcome>>();

async function accept(token: string): Promise<Outcome> {
  const res = await api.identity.acceptInvite(token);
  if (!res.success) throw new Error(res.error ?? "Invalid or expired invite.");
  return { kind: "done", role: res.data.role, full_name: res.data.full_name };
}

async function signInWith(signIn: OpenedSignIn): Promise<void> {
  const { error } = await getSupabaseClient().auth.verifyOtp({
    token_hash: signIn.token_hash,
    type: signIn.verification_type as EmailOtpType,
  });
  if (error) throw new Error(COULD_NOT_SIGN_IN);
}

async function openSignIn(token: string): Promise<OpenedSignIn> {
  const res = await api.identity.inviteSession(token);
  if (!res.success || !res.data) throw new Error(res.error ?? "Invalid or expired invite.");
  return res.data;
}

/** What the page does on its own: use a session already here, or wait for a press. It signs nobody in by itself. */
async function join(token: string): Promise<Outcome> {
  const supabase = getSupabaseClient();
  const read = async () => (await supabase.auth.getSession()).data?.session ?? null;
  let session = await read();
  const fromOlderLink = typeof window !== "undefined" && /access_token=/.test(window.location.hash);
  for (let i = 0; !session && fromOlderLink && i < OLDER_LINK_WAITS; i++) {
    await new Promise((r) => setTimeout(r, OLDER_LINK_WAIT_MS));
    session = await read();
  }
  if (!session) return { kind: "ready" };

  try {
    return await accept(token);
  } catch (e) {
    // A sentence of its own (this sign-in already belongs to a practice) is the answer; only the one refusal every
    // spent, withdrawn or mismatched invitation shares leaves open whose invitation this is.
    if (!REFUSED.test(e instanceof Error ? e.message : "")) return { kind: "error", message: sentenceFor(e) };
  }
  // Whose invitation this is, asked WITHOUT opening a sign-in: merely looking must create nothing at Supabase.
  let invitedAs: string;
  try {
    const res = await api.identity.inviteAddress(token);
    if (!res.success || !res.data) throw new Error(res.error ?? "Invalid or expired invite.");
    invitedAs = res.data.email;
  } catch (e) {
    return { kind: "error", message: sentenceFor(e) };
  }
  const current = (session.user?.email ?? "").trim().toLowerCase();
  if (current !== invitedAs.trim().toLowerCase()) {
    return { kind: "other_account", signedInAs: session.user?.email ?? "another account", invitedAs };
  }
  return { kind: "error", message: CANNOT_BE_USED };
}

/** The press: open a sign-in for the invitation's own address, redeem it, accept. */
async function joinSignedOut(token: string): Promise<Outcome> {
  try {
    await signInWith(await openSignIn(token));
    return await accept(token);
  } catch (e) {
    return { kind: "error", message: sentenceFor(e) };
  }
}

export default function JoinPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { signOut, refreshUserContext } = useAuth();

  const token = searchParams.get("token") ?? "";

  const [status, setStatus] = useState<Status>("checking");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [result, setResult] = useState<{ role?: string; full_name?: string } | null>(null);
  const [signedInAs, setSignedInAs] = useState<string | null>(null);
  const [invitedAs, setInvitedAs] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function show(outcome: Outcome) {
    if (outcome.kind === "done") {
      setResult({ role: outcome.role, full_name: outcome.full_name });
      setStatus("done");
      // The app read this person's membership when they signed in, before the accept linked it; read it again.
      void refreshUserContext();
    } else if (outcome.kind === "ready") {
      setStatus("ready");
    } else if (outcome.kind === "other_account") {
      setSignedInAs(outcome.signedInAs);
      setInvitedAs(outcome.invitedAs);
      setStatus("other_account");
    } else {
      setErrorMsg(outcome.message);
      setStatus("error");
    }
  }

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setErrorMsg("This invite link is missing its token.");
      setStatus("error");
      return;
    }
    let journey = journeys.get(token);
    if (!journey) {
      journey = join(token);
      journeys.set(token, journey);
    }
    journey.then((outcome) => { if (!cancelled) show(outcome); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A press, never the page by itself: the journey replaces the one that asked, so a remount while it runs (signing
  // in makes the sign-in guard withhold the page for a moment) waits for this one.
  async function run(start: () => Promise<Outcome>) {
    if (busy) return;
    setBusy(true);
    const journey = start();
    journeys.set(token, journey);
    try {
      show(await journey);
    } finally {
      setBusy(false);
    }
  }

  function joinNow() {
    return run(() => joinSignedOut(token));
  }

  // Asked, never done silently: the person signed in here leaves this browser so the invited address can join. The
  // sign-in is opened AFTER the sign-out, so it is a fresh one.
  function switchAndJoin() {
    return run(async (): Promise<Outcome> => {
      try {
        await signOut();
      } catch (e) {
        return { kind: "error", message: sentenceFor(e) };
      }
      return joinSignedOut(token);
    });
  }

  async function goToDashboard() {
    await refreshUserContext();
    router.replace("/");
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-600 via-indigo-900 to-blue-400 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <LogoIcon size="xl" />
          <h1 className="text-white text-2xl font-bold">PracticeSync AI</h1>
        </div>

        <div className="bg-white rounded-2xl shadow-2xl p-8 text-center space-y-4">
          {status === "checking" && (
            <>
              <div className="flex items-center justify-center gap-1.5 py-4">
                <div className="w-2 h-2 rounded-full bg-brand-light animate-bounce [animation-delay:0ms]" />
                <div className="w-2 h-2 rounded-full bg-brand-light animate-bounce [animation-delay:150ms]" />
                <div className="w-2 h-2 rounded-full bg-brand-light animate-bounce [animation-delay:300ms]" />
              </div>
              <p className="text-sm text-ps-label">Verifying your invite and setting up your account…</p>
            </>
          )}

          {status === "ready" && (
            <div data-join-ready="" className="space-y-4">
              <h2 className="text-lg font-semibold text-ps-ink">You have been invited to join a practice</h2>
              <p className="text-sm text-ps-label">
                Press the button to sign in as the invited email address and join. If that address already has a
                PracticeSync sign-in, sign in with it first and then open this link again.
              </p>
              <Button
                variant="plain"
                size="none"
                onClick={() => joinNow()}
                disabled={busy}
                className="w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
              >
                {busy ? "Signing you in…" : "Accept the invitation"}
              </Button>
            </div>
          )}

          {status === "other_account" && invitedAs && (
            <div data-join-other-account="" className="space-y-4">
              <h2 className="text-lg font-semibold text-ps-ink">This invitation is for another address</h2>
              <p className="text-sm text-ps-label">
                This browser is signed in as <strong>{signedInAs}</strong>. The invitation is for{" "}
                <strong>{invitedAs}</strong>. To join as {invitedAs}, sign out here first.
              </p>
              <Button
                variant="plain"
                size="none"
                onClick={() => switchAndJoin()}
                disabled={busy}
                className="w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
              >
                {busy ? "Signing you in…" : `Sign out and join as ${invitedAs}`}
              </Button>
              <button
                type="button"
                onClick={() => router.replace("/")}
                disabled={busy}
                className="w-full border border-ps-border text-ps-label text-sm py-2.5 rounded-lg hover:bg-ps-bg disabled:opacity-50"
              >
                Stay signed in as {signedInAs}
              </button>
            </div>
          )}

          {status === "done" && (
            <>
              <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mx-auto">
                <svg className="w-6 h-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-ps-ink">
                Welcome to the team{result?.full_name ? `, ${result.full_name}` : ""}!
              </h2>
              {result?.role && (
                <p className="text-sm text-ps-label">
                  You&apos;ve been added as <strong>{result.role}</strong>.
                </p>
              )}
              <Button
                variant="plain"
                size="none"
                onClick={() => goToDashboard()}
                className="w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors"
              >
                Go to Dashboard →
              </Button>
            </>
          )}

          {status === "error" && (
            <>
              <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto">
                <svg className="w-6 h-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-ps-ink">This invitation could not be used</h2>
              <p role="alert" className="text-sm text-ps-label">{errorMsg}</p>
              <p className="text-xs text-ps-hint">
                Already joined? <Link href="/login" className="text-brand underline">Sign in</Link>.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
