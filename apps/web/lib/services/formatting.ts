/** Format paise (integer) to Indian currency display string */
export function formatPaise(paise: number): string {
  const rupees = paise / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(rupees);
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

export function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** Format an ISO timestamp as an Indian-locale date + time, or "—" when absent/invalid. */
export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const d = new Date(isoString);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString("en-IN");
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
};
