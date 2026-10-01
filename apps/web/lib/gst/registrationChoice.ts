/**
 * Which of a client's GST registrations a return is being prepared for (GST-17).
 *
 * WHAT WAS WRONG
 *   A client is one legal person and may hold several GSTINs (GST-20, migration
 *   390), and the API has accepted `gstin` on every compute call since. The
 *   screens never sent one: both compute calls posted `client_id` and `period`
 *   and nothing else, so only the PRIMARY registration could be built from the
 *   UI, and "New GSTR-1" / "New GSTR-3B" asked the CA to TYPE a fifteen
 *   character number — which is how a return gets saved under a GSTIN the
 *   client does not hold.
 *
 * THIS MODULE DECIDES NOTHING STATUTORY. Whether a registration files GSTR-1
 * and GSTR-3B at all (a composition dealer or an ISD does not), which one is
 * primary and what the caveat says are all `domain/gst/registrations.py`'s
 * answers, served by `GET /api/client-gst-registrations`. What lives here is
 * only the three rules of CHOOSING one, kept in one place so the four screens
 * that choose cannot choose differently:
 *
 *   1. THE LIST IS THE SERVER'S AND ITS ORDER IS KEPT. The primary comes first,
 *      because a screen opens on `[0]` and that has to be the registration every
 *      existing document already carries.
 *   2. A GSTIN THE CLIENT DOES NOT HOLD IS REFUSED, NEVER DEFAULTED. If the
 *      current choice is not in the list it is `refused`, not silently replaced
 *      by the primary — filing one registration's return under another's number
 *      is the exact failure the picker exists to prevent.
 *   3. A REGISTRATION THAT FILES A DIFFERENT RETURN IS NOT OFFERED for GSTR-1
 *      or GSTR-3B. It is shown with the server's sentence naming what it files
 *      instead.
 *
 * AND THE PICKER DOES NOT FILTER. No invoice, bill or note names a registration
 * (GST-16 is open), so choosing one changes which GSTIN the return is filed
 * under and not which documents it contains. The server's caveat for the chosen
 * registration travels with it (`caveatFor`), shown beside the choice.
 */

/** The subset of `ClientGstRegistration` this module reads. Structural, so a
 *  test can hand it a literal and the screens can hand it the wire type. */
export interface RegistrationOption {
  gstin: string;
  label: string;
  is_primary: boolean;
  effective_to?: string | null;
  files_gstr1_and_3b: boolean;
  other_return_form?: string | null;
  documents_not_split_caveat?: string | null;
}

/** What a choice resolves to. `gstin` is what to SEND; `refused` is why not. */
export interface Choice {
  /** Undefined means "send none and let the server answer with the primary" —
   *  which is the contract for an omitted `gstin` and is only reachable when the
   *  client holds one registration or the list could not be read. */
  gstin?: string;
  refused?: string;
}

/** The registrations a GSTR-1 or GSTR-3B can be prepared for. */
export function fileable(list: readonly RegistrationOption[]): RegistrationOption[] {
  return list.filter((r) => r.files_gstr1_and_3b);
}

/** Does the CA have a choice to make? Two or more that file the ordinary pair. */
export function needsPicker(list: readonly RegistrationOption[]): boolean {
  return fileable(list).length > 1;
}

/** The registration a screen opens on: the first that files the ordinary pair,
 *  which the server orders PRIMARY FIRST. Null where none does. */
export function defaultGstin(list: readonly RegistrationOption[]): string | null {
  return fileable(list)[0]?.gstin ?? null;
}

/**
 * Turn the current choice into what the request carries.
 *
 * `list` is what the server said the client holds; `selected` is what the CA (or
 * the default) has chosen. An EMPTY list means the registrations could not be
 * read or the client has none, and sending nothing is then right — the server
 * resolves the primary, or refuses with a sentence if there is none.
 */
export function resolveChoice(list: readonly RegistrationOption[],
                              selected: string | null | undefined): Choice {
  if (list.length === 0) return {};
  const wanted = (selected ?? "").trim().toUpperCase();
  const options = fileable(list);
  if (!wanted) {
    const first = options[0]?.gstin;
    return first ? { gstin: first } : {
      refused: "None of this client's registrations files GSTR-1 and GSTR-3B.",
    };
  }
  const held = list.find((r) => r.gstin.toUpperCase() === wanted);
  if (!held) {
    return { refused: `${wanted} is not a registration this client holds. ` +
                      "Choose one from the list." };
  }
  if (!held.files_gstr1_and_3b) {
    return { refused: held.other_return_form
      ? `${wanted} does not file GSTR-1 or GSTR-3B: ${held.other_return_form}`
      : `${wanted} does not file GSTR-1 or GSTR-3B.` };
  }
  return { gstin: held.gstin };
}

/** The request body for a compute call: the caller's fields plus `gstin` where
 *  one was chosen. `gstin` is OMITTED, never sent as an empty string, when there
 *  is none — an empty value is a different request from an absent one. */
export function withRegistration<T extends Record<string, unknown>>(
  body: T, choice: Choice,
): T & { gstin?: string } {
  return choice.gstin ? { ...body, gstin: choice.gstin } : { ...body };
}

/** The server's caveat for the chosen registration, or null. Null is the truth
 *  for a client with one registration; it is not "unknown". */
export function caveatFor(list: readonly RegistrationOption[],
                          gstin: string | null | undefined): string | null {
  const wanted = (gstin ?? "").trim().toUpperCase();
  return list.find((r) => r.gstin.toUpperCase() === wanted)
    ?.documents_not_split_caveat ?? null;
}

/** One line for a dropdown option. */
export function optionLabel(r: RegistrationOption): string {
  const bits = [r.label || r.gstin];
  if (r.is_primary) bits.push("primary");
  if (r.effective_to) bits.push(`closed ${r.effective_to}`);
  if (!r.files_gstr1_and_3b) bits.push("files a different return");
  return bits.join(" — ");
}
