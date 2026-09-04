"use client";

/** Employee portal access — invite, re-invite, revoke.
 *
 *  The activation link comes back ONCE, from this call. Only its sha256 is
 *  stored server-side, so it can never be fetched again — which is why the link
 *  is shown here for copying, not just emailed and forgotten. Re-inviting mints
 *  a fresh link and invalidates this one. */

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { type Employee } from "@/components/payroll/shared";

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
      const res = await api.payroll.invitePortal(employee.id, email.trim());
      setLink(res.data?.activation_url ?? null);
      onChanged(`Invitation sent to ${email.trim()}.`);
      setStatus((s) => s ? { ...s, invite_pending: true, email: email.trim() } : s);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't send the invitation.");
    } finally { setBusy(false); }
  }

  async function revoke() {
    if (!confirm(`Remove portal access for ${employee.name}? They will no longer be able to sign in and view their payslips. You can invite them again later.`)) return;
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
        <h2 className="font-semibold text-[#0F172A]">Payslip portal — {employee.name}</h2>
        <p className="text-sm text-[#64748B] mt-1 mb-4">
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
            <p className="text-sm text-[#475569] mb-2">
              Invitation sent. If the email does not arrive, share this link —
              it works once and expires in 14 days.
            </p>
            <div className="flex gap-2 mb-4">
              <input readOnly value={link}
                     className="flex-1 border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs font-mono" />
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
            <label className="block text-xs font-medium text-[#475569] mb-1">
              Their email address *
            </label>
            <input value={email} onChange={(e) => setEmail(e.target.value)}
                   placeholder="name@example.com" type="email"
                   className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm mb-1" />
            {status?.invite_pending && (
              <p className="text-xs text-amber-700 mb-2">
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

