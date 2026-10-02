"use client";

/** Employee portal access — invite, re-invite, revoke.
 *
 *  The activation link comes back ONCE, from this call. Only its sha256 is
 *  stored server-side, so it can never be fetched again — which is why the link
 *  is shown here for copying, not just emailed and forgotten. Re-inviting mints
 *  a fresh link and invalidates this one.
 *
 *  THE BROWSER ALSO SENDS THE REAL SIGN-IN EMAIL, THE SAME WAY THE CLIENT
 *  PORTAL DOES (apps/web/app/clients/[id]/portal/page.tsx:handleSendInvite).
 *  `POST .../portal-invite` only records the invite server-side and mints the
 *  single-use token — it does not, and cannot, make Supabase Auth send
 *  anything, and `_send_invite_email` on the backend sends a plain HTML link
 *  with no Supabase session behind it at all. Opening that bare link (or the
 *  identical one shown below for copying) used to poll for a magic-link
 *  session that was never coming and always end in "This invitation cannot
 *  be used" — the activation page waits for `detectSessionInUrl` to parse an
 *  auth hash fragment, and only a URL Supabase's own Auth API produced ever
 *  carries one. `signInWithOtp({ email, options: { emailRedirectTo } })` is
 *  what asks Supabase to actually send that email, redirecting back to this
 *  same activation URL with the session attached — it does not touch or
 *  require the CA's own signed-in session on this browser, exactly as it
 *  does not on the client-portal invite. The backend's own email keeps
 *  working as the courtesy fallback if this send fails (rate limits, mainly)
 *  — the invite record itself is already committed either way. */

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { portalInviteEmailFailureMessage } from "@/lib/portal/inviteError";
import { type Employee } from "@/components/payroll/shared";
import { confirmDialog } from "@/components/ui/confirm-dialog";

export function PortalAccessModal({ employee, onClose, onChanged }: {
  employee: Employee;
  onClose: () => void;
  onChanged: (msg: string) => void;
}) {
  const [status, setStatus] = useState<{ activated: boolean; invite_pending: boolean;
                                         email: string | null } | null>(null);
  const [email, setEmail] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.payroll.portalStatus(employee.id);
        const d = res.data;
        if (d) { setStatus(d); setEmail(d.email ?? ""); }
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Couldn't read portal status.");
      }
    })();
  }, [employee.id]);

  async function invite() {
    setBusy(true); setErr(null);
    try {
      const trimmed = email.trim();
      const res = await api.payroll.invitePortal(employee.id, trimmed);
      if (!res.success) throw new Error(res.error ?? "Couldn't send the invitation.");
      const activationUrl = res.data?.activation_url ?? null;
      setLink(activationUrl);

      // The record is already committed server-side at this point — only the
      // sign-in email itself can still fail below (most often Supabase
      // Auth's own send-rate limit), which is why a failure here still
      // leaves the invite usable via the copyable link and a later re-send.
      if (activationUrl) {
        const { error: otpErr } = await getSupabaseClient().auth.signInWithOtp({
          email: trimmed, options: { emailRedirectTo: activationUrl },
        });
        if (otpErr) throw new Error(portalInviteEmailFailureMessage(otpErr.message));
      }

      onChanged(`Invitation sent to ${trimmed}.`);
      setStatus((s) => s ? { ...s, invite_pending: true, email: trimmed } : s);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't send the invitation.");
    } finally { setBusy(false); }
  }

  async function revoke() {
    if (!(await confirmDialog({ message: `Remove portal access for ${employee.name}? They will no longer be able to sign in and view their payslips. You can invite them again later.`, danger: true, confirmLabel: "Remove" }))) return;
    setBusy(true); setErr(null);
    try {
      await api.payroll.revokePortal(employee.id);
      onChanged(`Portal access removed for ${employee.name}.`);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't remove access.");
    } finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg p-5">
        <h2 className="font-semibold text-ps-ink">Payslip portal — {employee.name}</h2>
        <p className="text-sm text-ps-label mt-1 mb-4">
          Lets this employee sign in and see their own payslips and leave
          balance. They see nothing else.
        </p>

        {err && <p className="text-sm text-red-600 mb-3">{err}</p>}

        {status?.activated ? (
          <div>
            <p className="text-sm text-green-700 mb-4">Portal access is active.</p>
            <div className="flex gap-2">
              <Button variant="outline" onClick={onClose}>Close</Button>
              <Button onClick={revoke} disabled={busy}
                      className="bg-red-600 hover:bg-red-700 text-white">
                {busy ? "Removing…" : "Remove access"}
              </Button>
            </div>
          </div>
        ) : link ? (
          <div>
            <p className="text-sm text-ps-label mb-2">
              Invitation sent. If the email does not arrive, share this link —
              it works once and expires in 14 days.
            </p>
            <div className="flex gap-2 mb-4">
              <input readOnly value={link}
                     className="flex-1 border border-ps-border rounded-lg px-3 py-2 text-xs font-mono" />
              <Button variant="outline" onClick={() => {
                navigator.clipboard?.writeText(link);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}>{copied ? "Copied" : "Copy"}</Button>
            </div>
            <Button onClick={onClose}>Done</Button>
          </div>
        ) : (
          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">
              Their email address *
            </label>
            <input value={email} onChange={(e) => setEmail(e.target.value)}
                   placeholder="name@example.com" type="email"
                   className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm mb-1" />
            {status?.invite_pending && (
              <p className="text-xs text-state-attention mb-2">
                An invitation is already pending. Sending again replaces it —
                the earlier link stops working.
              </p>
            )}
            <div className="flex gap-2 mt-3">
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button onClick={invite} disabled={busy || !email.trim().includes("@")}>
                {busy ? "Sending…" : status?.invite_pending ? "Send a new invitation" : "Send invitation"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Add Employee Modal ────────────────────────────────────────────────────

