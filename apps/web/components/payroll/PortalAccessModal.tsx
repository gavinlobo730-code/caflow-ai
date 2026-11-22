"use client";

/** Employee portal access: invite, invite again, revoke.
 *
 *  THE LINK IS NEVER ON THIS SCREEN (POST-A-552, 22-11-2026). The invitation's link signs its holder in as the
 *  invitation's address: the activation page turns the bare token into a sign-in, and for an address that already has
 *  an account the server asks for that account's sign-in. This dialog used to be handed the link back and show it
 *  "to copy if the email does not arrive", so whoever could invite an employee could type the address of an existing
 *  account (a Partner, a member of another practice, a client's portal contact), copy the link and be signed in as
 *  that person. It also asked Supabase, from this browser, to mail a second sign-in link that came back to the same
 *  address with the token in it.
 *
 *  Now the server mails the one link itself and returns it to nobody, and this dialog is told only whether that mail
 *  went (`mail.sent`, and one sentence when it did not). A mail that did not arrive is answered by sending the
 *  invitation again, which makes a new link and stops the earlier one. */

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
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
  /** The address the server's mail went to, once it has gone: what the dialog then says, and nothing to copy. */
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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
      // The invitation exists either way, so the roster is told and the status says one is pending.
      setStatus((s) => s ? { ...s, invite_pending: true, email: trimmed } : s);
      // Only the server's own yes is "sent". An answer with no word about the mail (an older server) is not one.
      if (res.data?.mail?.sent !== true) {
        onChanged(`The invitation for ${employee.name} was created, but its email was not sent.`);
        setErr(res.data?.mail?.problem
          ?? "The invitation was created, but this screen was not told whether its email was sent. Send the invitation again.");
        return;
      }
      setSentTo(trimmed);
      onChanged(`Invitation sent to ${trimmed}.`);
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

        {err && <p role="alert" className="text-sm text-state-problem mb-3">{err}</p>}

        {status?.activated ? (
          <div>
            <p className="text-sm text-green-700 mb-4">Portal access is active.</p>
            <div className="flex gap-2">
              <Button disabled={busy} variant="outline" onClick={onClose}>Close</Button>
              <Button onClick={revoke} disabled={busy}
                      className="bg-red-600 hover:bg-red-700 text-white">
                {busy ? "Removing…" : "Remove access"}
              </Button>
            </div>
          </div>
        ) : sentTo ? (
          <div data-invitation-sent>
            <p className="text-sm text-ps-label mb-4">
              Invitation sent to <span className="font-medium text-ps-ink">{sentTo}</span>. The link in the email
              signs them in, works once and lasts 14 days. If it does not arrive, open this again and send a new
              invitation: the earlier link then stops working.
            </p>
            <Button onClick={onClose} disabled={busy}>Done</Button>
          </div>
        ) : (
          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">
              Their email address *
            </label>
            <input aria-label="Their email address" value={email} onChange={(e) => setEmail(e.target.value)}
                   placeholder="name@example.com" type="email"
                   className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm mb-1" />
            {status?.invite_pending && (
              <p className="text-xs text-state-attention mb-2">
                An invitation is already pending. Sending again replaces it —
                the earlier link stops working.
              </p>
            )}
            <div className="flex gap-2 mt-3">
              <Button disabled={busy} variant="outline" onClick={onClose}>Cancel</Button>
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

