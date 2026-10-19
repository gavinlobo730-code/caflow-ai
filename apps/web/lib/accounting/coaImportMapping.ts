/**
 * The Schedule III mapping column of a chart-of-accounts CSV, checked before it is written (POST-A-164).
 *
 * `chart_of_accounts.schedule_iii_mapping` is refused by the database (migration 520) unless it is empty or something the
 * engine can read: a caption it presents, an older spelling it still honours, or the 'Fixed Assets' heading. The import screen
 * writes the table straight over PostgREST, so without this a CSV with a made-up caption would fail a whole batch with a raw
 * constraint message and no row number. The vocabulary is the SERVER's (`GET /api/accounting/schedule-iii/captions`: the menu
 * plus `also_accepted`), never a list kept here: a copy in the browser is how the mapping screen once offered five captions the
 * engine had never heard of.
 */

export interface CaptionsPayload {
  sections?: { heading: string; items: string[] }[];
  also_accepted?: string[];
}

/** Everything a stored mapping may hold, or null when the payload could not be read (so nothing can be vouched for). */
export function acceptedMappings(payload: CaptionsPayload | null | undefined): ReadonlySet<string> | null {
  if (!payload || !Array.isArray(payload.sections)) return null;
  const out = new Set<string>();
  for (const section of payload.sections) for (const item of section.items ?? []) out.add(item);
  for (const item of payload.also_accepted ?? []) out.add(item);
  return out.size > 0 ? out : null;
}

/**
 * Why a row's mapping cannot be imported, or null when it can. An empty value is "unmapped" and always fine. `value` is the
 * trimmed cell: a padded caption is something the database refuses, so the screen must not send one.
 */
export function mappingProblem(row: number, value: string, accepted: ReadonlySet<string> | null): string | null {
  if (value === "") return null;
  if (accepted === null) {
    return `Row ${row}: the Schedule III captions could not be loaded, so "${value}" could not be checked. Reload the page, or leave the mapping blank.`;
  }
  if (accepted.has(value)) return null;
  return `Row ${row}: "${value}" is not a Schedule III caption this product reads. Use a name from the mapping screen, or leave it blank.`;
}
