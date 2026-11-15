/**
 * What a new MCA filing may name, as the server answers it (`GET /api/mca-workspace/filing-choices`, POST-A-291): the client's ACTIVE
 * companies and the financial years the compliance calendar holds the form's obligation open in.
 *
 * WHY THE SCREENS ASK. The calendar's AOC-4 and MGT-7 obligations are one per client per year while the filings are each company's, so a
 * filing that names no company cannot close the obligation of a client with several; and the firm-level form used to offer the CURRENT
 * financial year from the browser's clock, while a form filed in season is for the year that has just ended.
 *
 * A PAYLOAD IS NOT A LIST UNTIL IT IS CHECKED: `readFilingChoices` answers null for anything that is not the shape the server sends, and
 * a screen then falls back to the boxes it always had (a typed CIN, a typed year) and says the choices could not be read.
 */

export interface FilingCompany { id: string; company_name: string; cin: string | null }
export interface FilingPeriod { financial_year: string; due_date: string | null; status: string | null }
export interface FilingChoices {
  companies: FilingCompany[];
  /** More than one active company: the filing must name one, and the server refuses one that does not. */
  company_required: boolean;
  /** The form stands for an obligation on the calendar (AOC-4, MGT-7, ADT-1), so a filing of it needs a year or it can never close it. */
  has_obligation: boolean;
  /** Newest first; null when no year is offered (`periods_note` says why). */
  periods: FilingPeriod[] | null;
  periods_note: string | null;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);

/** The server's answer as `FilingChoices`, or null when it is not that shape. A row that is not a company or a year is not guessed at. */
export function readFilingChoices(data: unknown): FilingChoices | null {
  if (!isObject(data) || !Array.isArray(data.companies)) return null;
  if (data.periods !== null && !Array.isArray(data.periods)) return null;
  const companies: FilingCompany[] = [];
  for (const c of data.companies) {
    if (!isObject(c) || !text(c.id)) return null;
    companies.push({ id: String(c.id), company_name: text(c.company_name) ?? String(c.id), cin: text(c.cin) });
  }
  let periods: FilingPeriod[] | null = null;
  if (Array.isArray(data.periods)) {
    periods = [];
    for (const p of data.periods) {
      if (!isObject(p) || !text(p.financial_year)) return null;
      periods.push({ financial_year: String(p.financial_year), due_date: text(p.due_date), status: text(p.status) });
    }
  }
  return {
    companies,
    company_required: companies.length > 1,
    has_obligation: data.has_obligation === true,
    periods,
    periods_note: text(data.periods_note),
  };
}

/** The company a filing names: the one chosen, or the client's only active company when there is just one, or none. */
export function chosenCompany(choices: FilingChoices | null, chosenId: string): FilingCompany | null {
  if (!choices) return null;
  if (choices.companies.length === 1) return choices.companies[0];
  return choices.companies.find((c) => c.id === chosenId) ?? null;
}

/** The year preselected for a new filing: the only year the calendar holds open, or none when it holds several (the CA chooses). */
export function preselectedYear(choices: FilingChoices | null): string {
  return choices?.periods && choices.periods.length === 1 ? choices.periods[0].financial_year : "";
}
