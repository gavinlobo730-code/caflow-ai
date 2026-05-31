/** Format paise (integer) to Indian currency display string */
export function formatPaise(paise: number): string {
  const rupees = paise / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(rupees);
}

export function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
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
