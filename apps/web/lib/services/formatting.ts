import {
  formatPaise as formatPaiseAuthority,
  type PaiseInput,
} from "@/lib/money/format";
import {
  formatDate as formatDateAuthority,
  formatDateTime as formatDateTimeAuthority,
} from "@/lib/dates/format";

/**
 * Format paise (integer) to an Indian currency display string.
 *
 * DELEGATES to `lib/money/format`, which is the authority, rather than
 * building a second `Intl.NumberFormat`. This signature is kept because 73
 * files import it, and re-exporting is what lets them move one at a time.
 *
 * The delegation is not cosmetic — it fixes what this body did:
 * `formatPaise(undefined)` rendered the literal **"₹NaN"** on a screen, and
 * `formatPaise(null)` rendered **"₹0.00"**, which is worse, because a figure
 * nobody holds was shown as one somebody computed. Both now render an em
 * dash. The widened parameter type is why: a `number`-only signature could
 * not say so, while every caller was already free to pass an absent value
 * through it.
 */
export function formatPaise(paise: PaiseInput): string {
  return formatPaiseAuthority(paise);
}

/**
 * Format an integer minor-unit amount in ANY currency (Multi-Currency Phase 5).
 * `minor` is integer minor units (e.g. cents/paise); `minorUnits` is the ISO 4217
 * exponent (INR/USD → 2, JPY → 0). Display-only; the base (INR) amount stays
 * authoritative everywhere. Falls back to a plain code prefix for exotic codes.
 */
export function formatMoney(minor: number, currency = "INR", minorUnits = 2): string {
  const major = minor / Math.pow(10, minorUnits);
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      minimumFractionDigits: minorUnits,
      maximumFractionDigits: minorUnits,
    }).format(major);
  } catch {
    // Unknown ISO code → Intl throws; degrade gracefully to "USD 1,234.56".
    return `${currency} ${major.toLocaleString("en-IN", {
      minimumFractionDigits: minorUnits,
      maximumFractionDigits: minorUnits,
    })}`;
  }
}

/**
 * A calendar date, `05 Sep 2026`. DELEGATES to `lib/dates/format`, which is the
 * one date format (frontend_ux-20) — the signature stays because 35 files
 * import it, and re-exporting is what lets them move one at a time.
 *
 * The delegation fixes what the body did: `new Date("2026-03-31")
 * .toLocaleDateString(...)` read a bare date as UTC midnight in the BROWSER's
 * zone, so 31 March printed as 30 March west of Greenwich; the month was
 * whatever ICU says ("Sept" today); and an empty or invalid value printed the
 * literal "Invalid Date". An unreadable value is now "—".
 */
export function formatDate(isoString: string | null | undefined): string {
  return formatDateAuthority(isoString);
}

/** A moment in IST, `05 Sep 2026, 3:30 pm`, or "—" when absent/invalid. It
 * printed `toLocaleString("en-IN")` — "5/9/2026, 10:00:00 am" in the BROWSER's
 * zone, seconds and all — before it delegated to `lib/dates/format`. */
export function formatDateTime(isoString: string | null | undefined): string {
  return formatDateTimeAuthority(isoString);
}

export function formatRelativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return formatDate(isoString);
}

export const ENTITY_TYPE_LABELS: Record<string, string> = {
  Proprietorship: "Prop.",
  Partnership: "Partnership",
  LLP: "LLP",
  "Private Limited": "Pvt. Ltd.",
  "Public Limited": "Ltd.",
  Trust: "Trust",
  Society: "Society",
  Individual: "Individual",
  HUF: "HUF",
  AOP: "AOP",
  BOI: "BOI",
};
