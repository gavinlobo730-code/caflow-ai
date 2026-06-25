"use client";

// Public, no-login engagement-letter signing page.
//
// The web app is a Next.js STATIC EXPORT, so this is one static route (/sign/)
// that reads the unguessable token from the ?t= query param at runtime and talks
// to the public backend endpoints. No Supabase/auth context is imported here —
// the recipient is a prospect, not a logged-in user.
//
// Electronic acceptance (typed name + explicit consent) is a valid contract
// under the Information Technology Act, 2000, Section 10A.

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, AlertCircle, FileText, XCircle } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Letter = {
  engagement_number: string;
  title: string;
  content: string;
  status: string;
  recipient_name: string | null;
  firm_name: string;
  signed_at: string | null;
  signed_by_name: string | null;
  rejected_at: string | null;
  expired: boolean;
};

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function LetterFrame({ html }: { html: string }) {
  // sandbox="" disables scripts/forms/popups entirely — the letter is display-only
  // formatting HTML, so this renders it safely without any XSS surface.
  const doc = `<!DOCTYPE html><html><head><meta charset="utf-8"/><style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;color:#1a1a1a;line-height:1.6;margin:0;padding:18px;}
    h2{font-size:18px;margin:0 0 12px;} h3{font-size:15px;margin:16px 0 4px;}
    ul{padding-left:20px;margin:6px 0;} li{margin:3px 0;} p{margin:8px 0;}
  </style></head><body>${html || ""}</body></html>`;
  return (
    <iframe
      title="Engagement letter"
      sandbox=""
      srcDoc={doc}
      className="w-full h-[440px] rounded-lg border border-slate-200 bg-white"
    />
  );
}

export default function SignPage() {
  const [token, setToken] = useState<string | null>(null);
  const [letter, setLetter] = useState<Letter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const [showDecline, setShowDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("t");
    if (!t) {
      setError("This signing link is missing its token. Please use the link from your email.");
      setLoading(false);
      return;
    }
    setToken(t);
    fetch(`${API}/api/public/engagement-letters/${encodeURIComponent(t)}`)
      .then(async (r) => {
        const j = await r.json().catch(() => null);
        if (!r.ok || !j?.success) {
          // Read both shapes: api_response uses `error`, FastAPI HTTPException
          // uses `detail`. Without `detail` a 503 (service issue) would be
          // mis-shown as the generic "invalid/expired" fallback.
          throw new Error(j?.error || j?.detail || "This engagement letter link is invalid or has expired.");
        }
        setLetter(j.data as Letter);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Unable to load this letter."))
      .finally(() => setLoading(false));
  }, []);

  async function post(path: string, body: Record<string, unknown>) {
    if (!token) return;
    setSubmitting(true);
    setActionErr(null);
    try {
      const r = await fetch(`${API}/api/public/engagement-letters/${encodeURIComponent(token)}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => null);
      if (!r.ok || !j?.success) throw new Error(j?.error || j?.detail || "Something went wrong. Please try again.");
      setLetter(j.data as Letter);
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 py-8 px-4">
      <div className="mx-auto w-full max-w-2xl">
        {/* Header */}
        <div className="mb-5 flex items-center gap-2 text-slate-500">
          <FileText size={18} />
          <span className="text-sm font-medium">Engagement Letter</span>
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white p-10 text-slate-500">
            <Loader2 size={18} className="animate-spin" /> Loading…
          </div>
        )}

        {!loading && error && (
          <div className="rounded-xl border border-red-200 bg-white p-8 text-center">
            <AlertCircle size={32} className="mx-auto mb-3 text-red-500" />
            <h1 className="text-lg font-semibold text-slate-900">Link unavailable</h1>
            <p className="mt-1 text-sm text-slate-600">{error}</p>
          </div>
        )}

        {!loading && letter && (
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            {/* Card header */}
            <div className="border-b border-slate-100 px-6 py-4">
              <p className="font-mono text-[11px] text-slate-400">{letter.engagement_number}</p>
              <h1 className="text-lg font-semibold text-slate-900">{letter.title}</h1>
              <p className="mt-0.5 text-sm text-slate-500">from {letter.firm_name}</p>
            </div>

            <div className="space-y-5 p-6">
              {/* Signed / rejected banners */}
              {letter.status === "Signed" && (
                <div className="flex items-start gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-3">
                  <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-green-600" />
                  <div>
                    <p className="text-sm font-semibold text-green-800">Accepted — thank you</p>
                    <p className="text-sm text-green-700">
                      Signed by {letter.signed_by_name || "you"}
                      {letter.signed_at ? ` on ${fmtDate(letter.signed_at)}` : ""}. A confirmation
                      has been recorded with {letter.firm_name}.
                    </p>
                  </div>
                </div>
              )}
              {letter.status === "Rejected" && (
                <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3">
                  <XCircle size={20} className="mt-0.5 shrink-0 text-red-500" />
                  <div>
                    <p className="text-sm font-semibold text-red-800">Engagement declined</p>
                    <p className="text-sm text-red-700">
                      You declined this engagement{letter.rejected_at ? ` on ${fmtDate(letter.rejected_at)}` : ""}.
                      If this was a mistake, please contact {letter.firm_name}.
                    </p>
                  </div>
                </div>
              )}

              {/* Expired — past validity date, can no longer be signed */}
              {letter.expired && letter.status !== "Signed" && letter.status !== "Rejected" && (
                <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
                  <AlertCircle size={20} className="mt-0.5 shrink-0 text-amber-600" />
                  <div>
                    <p className="text-sm font-semibold text-amber-800">This letter has expired</p>
                    <p className="text-sm text-amber-700">
                      This engagement letter is past its validity date and can no longer be signed
                      online. Please contact {letter.firm_name} to request an updated copy.
                    </p>
                  </div>
                </div>
              )}

              {/* Letter body */}
              <LetterFrame html={letter.content} />

              {/* Acceptance form — only when still actionable and not expired */}
              {(letter.status === "Sent" || letter.status === "Viewed") && !letter.expired && (
                <div className="space-y-4 border-t border-slate-100 pt-5">
                  {!showDecline ? (
                    <>
                      <div>
                        <label className="mb-1 block text-sm font-medium text-slate-700">
                          Full name (your electronic signature)
                        </label>
                        <input
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          placeholder="e.g. Rahul Patel"
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                        />
                      </div>
                      <label className="flex items-start gap-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          checked={consent}
                          onChange={(e) => setConsent(e.target.checked)}
                          className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        <span>
                          I, the person named above, have read and <strong>accept the terms</strong> of
                          this engagement letter. I understand that typing my name and confirming here
                          constitutes my electronic signature.
                        </span>
                      </label>

                      {actionErr && (
                        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                          <AlertCircle size={14} className="mt-0.5 shrink-0" />
                          {actionErr}
                        </div>
                      )}

                      <div className="flex flex-wrap gap-2">
                        <button
                          disabled={submitting || !name.trim() || !consent}
                          onClick={() => post("/sign", { signer_name: name.trim(), consent })}
                          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                        >
                          {submitting ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                          Accept &amp; Sign
                        </button>
                        <button
                          disabled={submitting}
                          onClick={() => { setShowDecline(true); setActionErr(null); }}
                          className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                        >
                          Decline
                        </button>
                      </div>
                      <p className="text-xs text-slate-400">
                        Your name, the date/time, and your IP address will be recorded as proof of acceptance.
                      </p>
                    </>
                  ) : (
                    <div className="space-y-3">
                      <label className="block text-sm font-medium text-slate-700">
                        Reason for declining (optional)
                      </label>
                      <textarea
                        value={declineReason}
                        onChange={(e) => setDeclineReason(e.target.value)}
                        rows={3}
                        placeholder="Let the firm know why, if you'd like…"
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-red-400 focus:ring-2 focus:ring-red-100"
                      />
                      {actionErr && (
                        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                          <AlertCircle size={14} className="mt-0.5 shrink-0" />
                          {actionErr}
                        </div>
                      )}
                      <div className="flex gap-2">
                        <button
                          disabled={submitting}
                          onClick={() => post("/reject", { reason: declineReason || undefined })}
                          className="flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                        >
                          {submitting ? <Loader2 size={14} className="animate-spin" /> : <XCircle size={14} />}
                          Confirm Decline
                        </button>
                        <button
                          disabled={submitting}
                          onClick={() => setShowDecline(false)}
                          className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                        >
                          Back
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        <p className="mt-5 text-center text-xs text-slate-400">Powered by PracticeSync</p>
      </div>
    </div>
  );
}
