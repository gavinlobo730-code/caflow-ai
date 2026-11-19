"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { requestSignupLink } from "@/lib/auth/requestSignupLink";
import { Button } from "@/components/ui/button";
import { ArrowRight, Mail } from "lucide-react";
import { FrontDoor } from "@/components/FrontDoor";

export default function SignupPage() {
  const [firmName, setFirmName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [validUntil, setValidUntil] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // "Send it again" waits as long as the SERVER says after each send (its own cooldown for an address), so a second press
  // cannot meet the server's refusal; the refusal itself, if it comes, says how long is left.
  const [waitLeft, setWaitLeft] = useState(0);
  useEffect(() => {
    if (waitLeft <= 0) return;
    const t = setTimeout(() => setWaitLeft((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [waitLeft]);

  async function sendLink(): Promise<boolean> {
    if (!firmName.trim() || !fullName.trim() || !email.trim()) return false;
    setLoading(true);
    setError(null);
    try {
      // The SERVER keeps the link and mails it (POST-A-485): what it was asked for (the firm's name and the person's) travels with it,
      // so it means the same in whichever browser it is opened (POST-A-497). The address and names are also kept in this browser
      // (inside requestSignupLink) so a link that can no longer be used can offer "Email me a new link" without asking again.
      const asked = await requestSignupLink({ email, firmName, fullName });
      setSent(true);
      setValidUntil(asked.validUntil);
      setWaitLeft(asked.waitSeconds);
      return true;
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "The link could not be sent just now. Please try again.");
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await sendLink();
  }

  return (
    <FrontDoor>
      {sent ? (
        <div className="text-center space-y-4 py-4">
          <div className="w-14 h-14 rounded-2xl bg-emerald-50 border border-emerald-100 flex items-center justify-center mx-auto">
            <Mail size={22} className="text-emerald-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-ps-ink">Check your inbox</h2>
            <p className="text-sm text-ps-label mt-2 leading-relaxed">
              We sent a link to <span className="text-ps-ink font-medium">{email}</span>. Open it to finish setting up your firm.
            </p>
            <p className="text-xs text-ps-hint mt-3">
              The link works{validUntil ? ` until ${validUntil}` : " for 24 hours"} and until your practice has been created, and you can open it again
              if you are interrupted. Didn&apos;t receive it? Check your spam folder, or send it again.
            </p>
          </div>
          {error && <p role="alert" className="text-sm text-state-problem">{error}</p>}
          <Button
            variant="plain" size="none"
            onClick={() => sendLink()}
            disabled={loading || waitLeft > 0}
            className="text-sm font-medium text-brand hover:text-brand-dark disabled:opacity-50 disabled:cursor-not-allowed underline underline-offset-4"
          >
            {loading ? "Sending…" : waitLeft > 0 ? `Send it again (wait ${waitLeft}s)` : "Send it again"}
          </Button>
        </div>
      ) : (
        <>
          <div className="mb-6">
            <h2 className="text-xl font-bold text-ps-ink tracking-tight">Create your firm</h2>
            <p className="text-sm text-ps-label mt-1">Get started in minutes — no credit card required</p>
          </div>

          {error && (
            <div role="alert" className="flex items-start gap-2.5 p-3.5 rounded-lg bg-state-problem-surface border border-state-problem-border mb-5">
              <div className="w-4 h-4 rounded-full bg-state-problem-surface flex items-center justify-center shrink-0 mt-0.5">
                <span className="text-state-problem text-3xs font-bold leading-none">!</span>
              </div>
              <p className="text-sm text-red-600 leading-snug">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Each box is tied to its label by `htmlFor`/`id` and says what it
                holds to the browser (`autoComplete`). There is no password on
                this screen — the account is opened from the emailed link — so
                nothing here is `new-password`; the email is `email`, not
                `username`, because this is not a sign-in form. */}
            {[
              { id: "signup-firm-name", name: "firm_name", autoComplete: "organization", label: "Firm Name", value: firmName, setter: setFirmName, placeholder: "e.g. Sharma & Associates", type: "text" },
              { id: "signup-full-name", name: "name", autoComplete: "name", label: "Your Full Name", value: fullName, setter: setFullName, placeholder: "e.g. CA Ravi Sharma", type: "text" },
              { id: "signup-email", name: "email", autoComplete: "email", label: "Email Address", value: email, setter: setEmail, placeholder: "you@example.com", type: "email" },
            ].map(({ id, name, autoComplete, label, value, setter, placeholder, type }) => (
              <div key={id} className="space-y-1.5">
                <label htmlFor={id} className="block text-sm font-semibold text-ps-ink">{label}</label>
                <input
                  id={id} name={name} autoComplete={autoComplete}
                  type={type} value={value} onChange={(e) => setter(e.target.value)}
                  placeholder={placeholder} required
                  className="w-full bg-white border border-ps-border rounded-lg px-4 py-3 text-sm text-ps-ink placeholder:text-ps-hint outline-none focus:border-brand focus:ring-4 focus:ring-brand/[0.08] transition-all"
                />
              </div>
            ))}
            <button
              type="submit" disabled={loading}
              className="w-full flex items-center justify-center gap-2 bg-brand hover:bg-brand-dark disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold px-4 py-3 rounded-lg transition-colors shadow-sm mt-2"
            >
              {loading ? (
                <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Sending…</>
              ) : (
                <>Get started <ArrowRight size={15} /></>
              )}
            </button>
          </form>

          <p className="text-center text-xs text-ps-hint mt-4">
            If this address already has an account, the link signs you in to it. It does not create a second one.
          </p>
          <p className="text-center text-sm text-ps-hint mt-3">
            Already have an account?{" "}
            <Link href="/login" className="text-blue-600 hover:text-blue-700 font-medium transition-colors">
              Sign in →
            </Link>
          </p>
        </>
      )}
    </FrontDoor>
  );
}
