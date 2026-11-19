// What a client picker shows under a client's name, and what its search box reads (POST-A-487).
//
// Two clients of one firm often have names that differ by a word ("Sharma Enterprises", "Sharma Enterprises LLP"), and a
// tester who opened the dropdown inside a client could tell them apart by nothing: the switcher showed the name and the
// entity type only, although the list it reads already carried the GSTIN. The identifiers a CA tells clients apart by are
// the PAN and the GSTIN, so every picker shows them under the name and its box searches them.
//
// An identifier a client does not have is LEFT OUT and never drawn as a value: an unregistered client has no GSTIN, and
// the line then reads what there is. The GSTIN is the client's primary registration (the `gstin` column); a client may
// hold several (see the client's GST registrations), and this line does not claim to list them.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export interface ClientIdentity {
  client_name?: string | null;
  entity_type?: string | null;
  pan?: string | null;
  gstin?: string | null;
}

function present(v: string | null | undefined): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t === "" ? null : t;
}

/** "Private Limited · AABCU9603R · 27AABCU9603R1ZX": the entity type, then the PAN, then the GSTIN, whichever the client has. */
export function clientIdentityLine(c: ClientIdentity): string | undefined {
  const parts = [present(c.entity_type), present(c.pan), present(c.gstin)].filter((p): p is string => p !== null);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/** What a picker's search box reads: the name, the PAN and the GSTIN (and the entity type, which the line shows). */
export function clientSearchFields(c: ClientIdentity): string[] {
  return [present(c.client_name), present(c.pan), present(c.gstin), present(c.entity_type)].filter((p): p is string => p !== null);
}
