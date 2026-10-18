"use client";

/**
 * Ask a Partner to reset a lost authenticator app (POST-A-006).
 *
 * One form for both doors: the sign-in screen (a locked-out person asking for their own) and the Team screen (a Partner
 * asking for a member's). It sends a request to the approval engine and says what happens next; the rules (who may ask,
 * that a DIFFERENT Partner decides, that the only Partner's own cannot be reset from here) are the server's and arrive as
 * the server's sentences, shown as they are.
 */
import { useState, type ReactNode } from "react";
import { CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/field";
import { AUTHENTICATOR_RESET, resetRequestPayload, type ResetTarget } from "@/lib/auth/authenticatorReset";

export default function AuthenticatorResetRequest({
  target, sentMessage, onSent,
}: {
  target: ResetTarget;
  /** What the person is told once the request is with the Partners. */
  sentMessage: ReactNode;
  onSent?: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  // Returned to the Button, which ignores a second click until it settles.
  async function send() {
    setError(null);
    try {
      const res = await api.approvals.create(AUTHENTICATOR_RESET, resetRequestPayload(target, reason));
      if (!res.success) throw new Error(res.error ?? "The request could not be sent.");
      setSent(true);
      onSent?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request could not be sent.");
    }
  }

  if (sent) {
    return (
      <p role="status" className="flex items-start gap-2 text-xs text-state-ready">
        <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
        <span>{sentMessage}</span>
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <Field label="Why does it need resetting?" hint="For example: new phone, or the old one was lost. The Partner who decides reads this.">
        <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
      </Field>
      {error && <p role="alert" className="text-xs text-state-problem">{error}</p>}
      <Button type="button" onClick={send} disabled={reason.trim().length === 0} className="w-full">
        Send request
      </Button>
    </div>
  );
}
