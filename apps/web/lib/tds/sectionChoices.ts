/**
 * The sections the TDS screen offers, taken from what the server serves (`GET /api/tds/sections`) and nothing the browser knows.
 *
 * WHY THIS EXISTS (POST-A-278). `app/tds/page.tsx` kept a copy of fifteen sections and their plain-English names, used for the
 * deduction form, the Add Challan form, the filter and the table. A copy drifts: it held neither §194T, which the registry has
 * carried since the section began, nor §195, which the non-resident engine answers for, so a challan under either could not be
 * recorded on the screen and a deduction under one of them read "Not deposited" beside a sentence telling the CA to record it.
 * The names and the list of sections a challan may be recorded under are the server's now (`domain/tds/section_labels.py`).
 *
 * Nothing here holds a section, a name or a rate. A server one deploy behind sends no `challan_sections`; the list is then the
 * parents of the sections it does send, which is every one except §195, and the names are absent (a section is shown by its code).
 */
import type { TDSSection } from "@/lib/data/tds";

export interface ChallanSection { section: string; label: string | null }

export interface SectionChoices {
  /** section code (or clause key) -> its plain-English name, for the sections that have one. */
  labels: Record<string, string>;
  /** The sections a deduction may be recorded under here: those the server does not mark as unavailable (§192 is paid through
   *  payroll and §206C is collected, not deducted). */
  deductible: string[];
  /** The sections a challan may be recorded under, in the server's order. */
  challan: ChallanSection[];
  /** Every section a recorded deduction can carry, for the table's Section filter: the limbs the deduction form offers (a row holds
   *  "194J(a)", which the parents a challan names do not include) and the sections a challan names that the form does not (§195, and
   *  §192 on a row recorded before the save refused it). A filter built from one list drops the rows the other one's sections name. */
  filterable: string[];
}

export const NO_SECTIONS: SectionChoices = { labels: {}, deductible: [], challan: [], filterable: [] };

export function sectionChoices(answer: { sections: TDSSection[]; challan_sections?: ChallanSection[] }): SectionChoices {
  const labels: Record<string, string> = {};
  for (const s of answer.sections) if (s.label) labels[s.section] = s.label;
  for (const c of answer.challan_sections ?? []) if (c.label) labels[c.section] = c.label;
  const challan = answer.challan_sections ?? parentsOf(answer.sections).map((section) => ({ section, label: labels[section] ?? null }));
  const deductible = answer.sections.filter((s) => s.vendor_eligible !== false).map((s) => s.section);
  const filterable = [...deductible];
  // The challan list holds every parent the registry has, so it also holds §192, §206C and §194N, which the form no longer offers
  // and which a row recorded before the save refused them still carries: a filter that could not select them would hide those rows.
  for (const c of challan) if (!filterable.includes(c.section)) filterable.push(c.section);
  return { labels, deductible, challan, filterable };
}

function parentsOf(sections: TDSSection[]): string[] {
  const seen: string[] = [];
  for (const s of sections) {
    const parent = s.parent_section ?? s.section;
    if (!seen.includes(parent)) seen.push(parent);
  }
  return seen;
}

/** "194J — Professional / technical fees", or the bare code for a section with no name. */
export function sectionOptionText(section: string, labels: Record<string, string>): string {
  const label = labels[section];
  return label ? `${section} — ${label}` : section;
}
