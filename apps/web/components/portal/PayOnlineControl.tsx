"use client";

/**
 * The portal's Pay Now control and the one line that explains it when it is not available (PRE-B-002 part 2).
 *
 * PAY NOW STAYS VISIBLE. The owner decided on 9 October 2026 that the control is not hidden: until a real gateway
 * is set up it is a DISABLED button with the server's own label ("Pay Now · coming soon") and ONE sentence above
 * the table in the server's words, once, not per row. Nothing opens a payment page while it is disabled, and the
 * button has no `onClick` at all in that state.
 *
 * THE BROWSER DECIDES NOTHING: `block` (is a gateway set up, and the words) is the dashboard's `online_payment`,
 * `canPay` is the row's server-set `can_pay_online` (an issued or part-paid invoice with a balance). Both are
 * read with `readOnlinePayment`, which fails closed: a block that is missing or not clearly `available: true`
 * renders no enabled control, and a row that is not clearly `can_pay_online: true` renders no control at all.
 * This file holds no sentence about whether payment is available and no gateway name; the one literal label,
 * `Pay Now`, is only the control's name for a block that arrived without one.
 *
 * The enabled button is a `<Button>` whose `onClick` hands back the page's promise, so a second click while the
 * link is being made is ignored (frontend_ux-09: the portal dashboard is on the money-screen list).
 */
import { CreditCard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { readOnlinePayment } from "@/lib/payments/onlinePayment";

/** The id the disabled buttons point their `aria-describedby` at: the notice, rendered once above the table. */
export const ONLINE_PAYMENT_NOTICE_ID = "online-payment-notice";

export function OnlinePaymentNotice({ block, anyPayable }: { block: unknown; anyPayable: boolean }) {
  const b = readOnlinePayment(block);
  // Said only where it matters: a gateway that is not set up AND at least one invoice that could be paid.
  if (!b || b.available || !anyPayable) return null;
  const text = [b.headline, b.reason].filter((t): t is string => !!t).join(" ");
  if (!text) return null;
  return (
    <div id={ONLINE_PAYMENT_NOTICE_ID} className="mb-3">
      <Callout tone="note">{text}</Callout>
    </div>
  );
}

export function PayOnlineControl({
  block, canPay, busy, onPay,
}: {
  block: unknown;
  /** The row's server-set `can_pay_online`. */
  canPay: unknown;
  busy: boolean;
  onPay: () => Promise<unknown> | void;
}) {
  const b = readOnlinePayment(block);
  if (!b || canPay !== true) return null;
  const label = b.label || "Pay Now";
  if (!b.available) {
    return (
      <Button variant="plain" size="none" disabled aria-describedby={ONLINE_PAYMENT_NOTICE_ID}
        className="inline-flex items-center gap-1 text-xs text-ps-hint cursor-not-allowed mr-3">
        <CreditCard size={13} /> {label}
      </Button>
    );
  }
  return (
    <Button variant="plain" size="none" disabled={busy} onClick={onPay}
      className="inline-flex items-center gap-1 text-xs text-brand-dark hover:underline disabled:opacity-40 mr-3">
      <CreditCard size={13} /> {label}
    </Button>
  );
}
