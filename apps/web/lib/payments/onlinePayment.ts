/**
 * What the SERVER says about online payment — the shape only (PRE-B-002 part 2).
 *
 * THE BROWSER DECIDES NOTHING HERE AND HOLDS NO WORDS. Whether a pay control is enabled, what it is labelled and
 * the one sentence under it all come from the API (`apps/api/domain/payments/availability.py`, served on the
 * portal dashboard as `online_payment` and on a payment history for the practice side). This file is the type of
 * that block and one reading of it, nothing more: no label, no sentence, no gateway name, no setting name. A
 * sentence kept here would be a second copy of the wording the register (`docs/open-items/coming-soon.md`) holds
 * the server to, and the first redeploy that reworded one would leave the screen saying the other.
 *
 * FAILING CLOSED. A block that is missing (the frontend redeployed ahead of the backend), not an object, or whose
 * `available` is anything but the boolean `true` is read as NOT available. A screen that cannot tell shows no
 * enabled control; it never guesses that payment works.
 */
import { objectOrNull } from "@/lib/api/shape";

export interface OnlinePaymentBlock {
  /** True only when the server says a real gateway is set up. */
  available: boolean;
  /** The control's label as the server words it ("Pay Now", or the coming-soon form). */
  label: string;
  /** "Online payment is coming soon." — null when available. */
  headline: string | null;
  /** The one reason line — null when available. */
  reason: string | null;
  /** Practice side only: why, and the NAMES of the settings to check (never a value). */
  state?: string;
  settings_to_check?: string[];
}

/** The block as the server sent it, or `null` when it is not an object. */
export function readOnlinePayment(data: unknown): OnlinePaymentBlock | null {
  const block = objectOrNull<Partial<OnlinePaymentBlock>>(data);
  if (!block) return null;
  return {
    available: block.available === true,
    label: typeof block.label === "string" ? block.label : "",
    headline: typeof block.headline === "string" ? block.headline : null,
    reason: typeof block.reason === "string" ? block.reason : null,
    state: typeof block.state === "string" ? block.state : undefined,
    settings_to_check: Array.isArray(block.settings_to_check)
      ? block.settings_to_check.filter((s): s is string => typeof s === "string")
      : undefined,
  };
}
