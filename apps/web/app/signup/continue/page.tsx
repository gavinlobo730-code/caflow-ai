"use client";

/**
 * Where a sign-up link lands (POST-A-485, 497).
 *
 * The link used to be the sign-in library's own emailed one-time link: the first opener won, so a mail scanner that opens links before the
 * person does, a second click, or the link opened on a phone after the laptop left the person on a page that said it had expired. And what
 * the link MEANT (a NEW practice, not the existing one this address belongs to) lived in a note in the browser that had sent the form, so the
 * link opened in another browser entered an existing practice silently. The SERVER keeps the link now, and this page is what it opens:
 *
 *   1. It asks the server what the link is for (`api.signup.look`), which signs nobody in and uses nothing up, so a mail scanner that opens
 *      the page spends nothing. A link that cannot be used (expired, replaced by a newer one, or used up by creating the practice) gets
 *      one sentence, and the person can have a new one sent from the address and names this browser kept.
 *   2. It WAITS FOR A PRESS before signing anybody in. The press asks the server for a sign-in for the link's OWN address
 *      (`api.signup.session`), writes what the link was asked for (the firm's name and the person's) where the wizard reads it, redeems the
 *      sign-in with `verifyOtp`, and goes on to the wizard. The names come from the SERVER's answer, so the intent travels with the link and
 *      not with the browser that sent the form (POST-A-497): an address that already has a practice is told so by the wizard
 *      (POST-A-480), in any browser.
 *   3. Nothing is used up by the press, so a second click, a reload, or the link opened on another device all work, until the link expires or
 *      the practice has been created.
 *   4. A browser signed in as somebody else says so and asks before it signs them out, as the staff invitation's page does; a browser
 *      already signed in as the link's address has nothing to sign in to and carries on.
 *
 * The decisions are `lib/auth/signupContinue`, tested apart from the page.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { EmailOtpType } from "@supabase/supabase-js";
import { api } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { FrontDoor } from "@/components/FrontDoor";
import { Button } from "@/components/ui/button";
import { LoadingRegion } from "@/components/ui/skeleton";
import { requestSignupLink } from "@/lib/auth/requestSignupLink";
import { readSignupStash, writeSignupStash } from "@/lib/auth/signupStash";
import { LINK_NOT_ACTIVE, canAskAgain, pressFor, stashFrom, viewFor, type LinkState } from "@/lib/auth/signupContinue";

type Seen = { email: string; firm_name: string; full_name: string; valid_until: string };
type Looked = { state: LinkState; seen?: Seen; message?: string };

const COULD_NOT_SIGN_IN =
  "We could not sign you in from this link just now. Press the button again in a moment; if it still fails, ask for a new link.";
const COULD_NOT_ASK = "Could not check this link just now. Please try again.";

function browserStorage(): Storage | null {
  try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; }
}

/**
 * The link's secret, from the FRAGMENT of the address (`/signup/continue/#token=…`). A fragment is never sent to a server, so neither the
 * static host's request log, a mail scanner's log nor a `Referer` header can hold a secret that, unlike the library's one-time link, keeps
 * working until it expires or the practice is created. Read on the client only: the prerendered page has no address to read.
 */
function tokenFromAddress(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") ?? "";
}

function sentenceOf(e: unknown, fallback: string): string {
  const message = e instanceof Error ? e.message.trim() : "";
  return message || fallback;
}

/** Ask the server what the link is for. Nothing is signed in or used up. */
async function lookAtLink(token: string): Promise<Looked> {
  if (!token) return { state: "gone" };
  try {
    const res = await api.signup.look(token);
    if (!res.success || !res.data) return { state: "gone" };
    return { state: "live", seen: res.data };
  } catch (e) {
    const message = e instanceof Error ? e.message : "";
    if (LINK_NOT_ACTIVE.test(message)) return { state: "gone" };
    return { state: "problem", message: sentenceOf(e, COULD_NOT_ASK) };
  }
}

export default function ContinueSignupPage() {
  const router = useRouter();
  const { session, signOut } = useAuth();
  const [token] = useState(tokenFromAddress);
  const signedInAs = session?.user?.email ?? null;

  const [looked, setLooked] = useState<Looked>({ state: "checking" });
  const [busy, setBusy] = useState(false);
  const [pressError, setPressError] = useState<string | null>(null);

  const ask = useCallback(async () => {
    setLooked({ state: "checking" });
    setLooked(await lookAtLink(token));
  }, [token]);
  useEffect(() => { void ask(); }, [ask]);

  const view = viewFor({ link: looked.state, signedInAs, linkAddress: looked.seen?.email });

  /** The press: sign in as the link's own address (unless this browser already is), keep what the link was asked for, carry on. */
  async function signInAndCarryOn(seen: Seen, alreadyThisAddress: boolean) {
    if (alreadyThisAddress) {
      writeSignupStash(browserStorage(), stashFrom(seen));
      router.replace("/onboarding");
      return;
    }
    const res = await api.signup.session(token);
    if (!res.success || !res.data) throw new Error(res.error ?? COULD_NOT_SIGN_IN);
    // The intent first, and from the SERVER's answer: the wizard reads it as soon as the sign-in lands (POST-A-497).
    writeSignupStash(browserStorage(), stashFrom(res.data));
    const { error } = await getSupabaseClient().auth.verifyOtp({
      token_hash: res.data.token_hash,
      type: res.data.verification_type as EmailOtpType,
    });
    if (error) throw new Error(COULD_NOT_SIGN_IN);
    router.replace("/onboarding");
  }

  async function press() {
    if (busy || looked.state !== "live" || !looked.seen) return;
    setBusy(true);
    setPressError(null);
    try {
      await signInAndCarryOn(looked.seen, pressFor(signedInAs, looked.seen.email) === "carry_on");
    } catch (e) {
      setPressError(sentenceOf(e, COULD_NOT_SIGN_IN));
    } finally {
      setBusy(false);
    }
  }

  // Asked, never done silently: the person signed in here leaves this browser so the link's address can continue.
  async function switchAndPress() {
    if (busy || looked.state !== "live" || !looked.seen) return;
    setBusy(true);
    setPressError(null);
    try {
      await signOut();
      await signInAndCarryOn(looked.seen, false);
    } catch (e) {
      setPressError(sentenceOf(e, COULD_NOT_SIGN_IN));
    } finally {
      setBusy(false);
    }
  }

  // "Email me a new link", from the address and names this browser kept when the form was filled in.
  const [stash] = useState(() => readSignupStash(browserStorage()));
  const [sending, setSending] = useState(false);
  const [waitLeft, setWaitLeft] = useState(0);
  const [note, setNote] = useState<{ tone: "ok" | "problem"; text: string } | null>(null);
  useEffect(() => {
    if (waitLeft <= 0) return;
    const timer = setTimeout(() => setWaitLeft((n) => n - 1), 1000);
    return () => clearTimeout(timer);
  }, [waitLeft]);
  async function emailNewLink() {
    if (sending || waitLeft > 0 || !canAskAgain(stash)) return;
    setSending(true);
    setNote(null);
    try {
      const sent = await requestSignupLink({ email: stash.email ?? "", firmName: stash.firmName ?? "", fullName: stash.fullName ?? "" });
      setNote({ tone: "ok", text: `A new link is on its way to ${stash.email}. It works until ${sent.validUntil}, and you can open it more than once.` });
      setWaitLeft(sent.waitSeconds);
    } catch (e) {
      setNote({ tone: "problem", text: sentenceOf(e, "Could not send a new link. Please try again.") });
    } finally {
      setSending(false);
    }
  }

  return (
    <FrontDoor width="wide">
      <div className="text-center space-y-4">
        {view === "checking" && (
          // Drawn by a read (what the link is for), so it says when the server is slow, as every placeholder does (POST-A-147).
          <LoadingRegion label="Checking your sign-up link" className="space-y-4">
            <div className="flex items-center justify-center gap-1.5 py-4">
              <div className="w-2 h-2 rounded-full bg-brand-light animate-bounce [animation-delay:0ms]" />
              <div className="w-2 h-2 rounded-full bg-brand-light animate-bounce [animation-delay:150ms]" />
              <div className="w-2 h-2 rounded-full bg-brand-light animate-bounce [animation-delay:300ms]" />
            </div>
            <p className="text-sm text-ps-label">Checking your sign-up link…</p>
          </LoadingRegion>
        )}

        {view === "ready" && looked.seen && (
          <div data-signup-continue-ready="" className="space-y-4">
            <h2 className="text-lg font-semibold text-ps-ink">Continue setting up {looked.seen.firm_name}</h2>
            <p className="text-sm text-ps-label">
              This link starts a new practice for <strong>{looked.seen.email}</strong>. Press the button to sign in and carry on.
              The link works until {looked.seen.valid_until} and until your practice has been created, so you can open it again if you are interrupted.
            </p>
            {pressError && <p role="alert" className="text-sm text-state-problem">{pressError}</p>}
            <Button
              variant="plain" size="none" onClick={() => press()} disabled={busy}
              className="w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
            >
              {busy ? "Signing you in…" : "Continue"}
            </Button>
            <p className="text-xs text-ps-hint">
              If this address already has an account, the link signs you in to it and does not create a second one.
            </p>
          </div>
        )}

        {view === "other_account" && looked.seen && (
          <div data-signup-continue-other-account="" className="space-y-4">
            <h2 className="text-lg font-semibold text-ps-ink">This link is for another address</h2>
            <p className="text-sm text-ps-label">
              This browser is signed in as <strong>{signedInAs}</strong>. The link is for <strong>{looked.seen.email}</strong>.
              To continue as {looked.seen.email}, sign out here first.
            </p>
            {pressError && <p role="alert" className="text-sm text-state-problem">{pressError}</p>}
            <Button
              variant="plain" size="none" onClick={() => switchAndPress()} disabled={busy}
              className="w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
            >
              {busy ? "Signing you in…" : `Sign out and continue as ${looked.seen.email}`}
            </Button>
            <button
              type="button" onClick={() => router.replace("/")} disabled={busy}
              className="w-full border border-ps-border text-ps-label text-sm py-2.5 rounded-lg hover:bg-ps-bg disabled:opacity-50"
            >
              Stay signed in as {signedInAs}
            </button>
          </div>
        )}

        {view === "gone" && (
          <div data-signup-continue-gone="" className="space-y-4">
            <h2 className="text-lg font-semibold text-ps-ink">This sign-up link is no longer active</h2>
            <p className="text-sm text-ps-label">
              It may have expired (a link works for 24 hours), been replaced by a newer one, or already been used to create the practice.
              {canAskAgain(stash)
                ? " We can email a new one to the address you signed up with, or you can sign in if you already have a password."
                : " Start the sign-up again for a new link, or sign in if you already have a password."}
            </p>
            {canAskAgain(stash) && (
              <div className="space-y-2">
                <Button
                  variant="plain" size="none" onClick={() => emailNewLink()} disabled={sending || waitLeft > 0}
                  className="w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-50"
                >
                  {sending ? "Sending…" : waitLeft > 0 ? `Email me a new link (wait ${waitLeft}s)` : "Email me a new link"}
                </Button>
                {note && (
                  <p role={note.tone === "problem" ? "alert" : "status"} className={`text-xs ${note.tone === "problem" ? "text-state-problem" : "text-green-700"}`}>
                    {note.text}
                  </p>
                )}
              </div>
            )}
            <div className="flex flex-col gap-2">
              {!canAskAgain(stash) && (
                <Link href="/signup" className="flex items-center justify-center px-5 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors">
                  Start the sign-up again
                </Link>
              )}
              <Link href="/login" className="flex items-center justify-center px-5 py-2 border border-ps-border text-ps-body text-sm font-medium rounded-lg hover:bg-ps-bg transition-colors">
                Sign in
              </Link>
            </div>
          </div>
        )}

        {view === "problem" && (
          <div data-signup-continue-problem="" className="space-y-4">
            <h2 className="text-lg font-semibold text-ps-ink">This link could not be checked</h2>
            <p role="alert" className="text-sm text-ps-label">{looked.message ?? COULD_NOT_ASK}</p>
            <Button
              variant="plain" size="none" onClick={() => ask()}
              className="w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors"
            >
              Try again
            </Button>
          </div>
        )}
      </div>
    </FrontDoor>
  );
}
