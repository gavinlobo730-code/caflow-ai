/**
 * The assessment year, and why it is not the financial year.
 *
 * IT Act §2(9): the assessment year is the twelve months beginning 1 April
 * NEXT after the previous year (§3). So income earned in FY 2025-26 is
 * assessed in AY 2026-27, and every income-tax artefact a CA handles — the
 * ITR, Form 26AS, the Annual Information Statement under §285BB — is labelled
 * by the ASSESSMENT year.
 *
 * The two labels look identical ('2025-26', '2026-27'), which is exactly why
 * they get muddled: a screen that offers "financial year" and sends it to an
 * AIS endpoint reconciles the wrong statement against the wrong return, and
 * nothing about the request looks wrong. Keeping the conversion in one named
 * function, with a test, is the whole defence.
 */

/** 'YYYY-YY', both halves consistent. '2026-28' is not a year label. */
export function isYearLabel(value: string): boolean {
  const m = /^(\d{4})-(\d{2})$/.exec(String(value ?? "").trim());
  if (!m) return false;
  const start = Number(m[1]);
  return String((start + 1) % 100).padStart(2, "0") === m[2];
}

/** FY 2025-26 → AY 2026-27. Returns '' for anything that is not a label. */
export function assessmentYearForFy(fy: string): string {
  if (!isYearLabel(fy)) return "";
  const start = Number(fy.slice(0, 4)) + 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

/** AY 2026-27 → FY 2025-26. Returns '' for anything that is not a label. */
export function financialYearForAy(ay: string): string {
  if (!isYearLabel(ay)) return "";
  const start = Number(ay.slice(0, 4)) - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

/**
 * The assessment years a CA is plausibly working on, newest first.
 *
 * Starts at the AY for the financial year that has ENDED, not at the AY for
 * the year in progress: on 10 September 2026 the return being prepared is
 * AY 2026-27 (FY 2025-26), and offering AY 2027-28 first points at a year
 * whose income is still being earned. The year in progress is still offered,
 * because an advance-tax review legitimately looks at it.
 */
export function assessmentYearChoices(count = 5, today: Date = new Date()): string[] {
  const year = today.getFullYear();
  // The FY that ended most recently: before 1 April, last FY started two
  // calendar years ago.
  const endedFyStart = today.getMonth() >= 3 ? year - 1 : year - 2;
  const first = endedFyStart + 1;
  return Array.from({ length: count }, (_, i) => {
    const s = first + 1 - i;   // one ahead of the settled AY, then backwards
    return `${s}-${String((s + 1) % 100).padStart(2, "0")}`;
  });
}
