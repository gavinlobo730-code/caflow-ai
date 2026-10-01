"use client";

import { useEffect, useState } from "react";
import { listTdsSections, type TDSSection } from "@/lib/data/tds";
import { arrayOrEmpty } from "@/lib/api/shape";

/**
 * Which s.194A(3)(i) limit a supplier's interest is tested against (TDS-30).
 *
 * Renders NOTHING unless the server says the chosen section carries limit
 * classes — so this file does not know that 194A is the section, any more than
 * it knows a rupee figure. The keys, the labels and the amounts all arrive from
 * `GET /api/tds/sections` (`threshold_classes`), and what to record is the
 * CA's answer to two questions this control puts in plain words: who pays, and
 * whether it is a deposit with a bank.
 *
 * "Not stated" is a real option and the default: it takes the section's own
 * limit, the lowest, which is what every supplier did before this existed. And
 * a payee being a senior citizen is NOT offered on its own — the server's
 * senior-citizen limit exists only for a deposit with a bank, so the options
 * are the server's three and nothing finer-grained.
 */
export function InterestThresholdClassSelect({
  section, value, onChange, disabled,
}: {
  section: string | null | undefined;
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  const [sections, setSections] = useState<TDSSection[]>([]);

  useEffect(() => {
    let cancelled = false;
    listTdsSections()
      .then((r) => { if (!cancelled) setSections(arrayOrEmpty<TDSSection>(r?.sections)); })
      .catch(() => { if (!cancelled) setSections([]); });
    return () => { cancelled = true; };
  }, []);

  const entry = sections.find((s) => s.section === (section ?? "").toUpperCase());
  const classes = arrayOrEmpty<{ key: string; label: string; threshold_paise: number }>(
    entry?.threshold_classes);
  if (classes.length === 0) return null;

  return (
    <div>
      <label className="block text-xs font-medium text-ps-label mb-1" htmlFor="interest-threshold-class">
        Interest limit (TDS threshold)
      </label>
      <select
        id="interest-threshold-class"
        className="w-full text-xs border border-ps-border rounded-lg px-3 py-2 bg-white disabled:opacity-40"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Not stated — the lowest limit applies</option>
        {classes.map((c) => (
          <option key={c.key} value={c.key}>{c.label}</option>
        ))}
      </select>
      <p className="text-xs text-ps-label mt-1">
        A payee&apos;s age alone does not raise the limit: the higher figures apply only where
        the one paying is a bank, a co-operative bank or a post office.
      </p>
    </div>
  );
}

export default InterestThresholdClassSelect;
