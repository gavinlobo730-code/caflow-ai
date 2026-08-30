/**
 * WHICH STATUTORY REGIME AN ENTITY IS ACTUALLY IN.
 *
 * The single place the product decides whether to OFFER an MCA / ROC
 * capability, and whether it may describe a set of financial statements as
 * "Schedule III". Every call site imports from here; a second copy of these
 * rules is the thing not to do, because the two would drift and only one of
 * them would be law.
 *
 * WHY IT EXISTS
 *     A proprietorship client was shown an "MCA Compliance Workspace" —
 *     Company Master, Directors, Annual Filings, Event Filings — and the
 *     screen read "No companies registered". That reads like missing data.
 *     The truth is that the obligation does not exist and never will: a
 *     proprietorship has no registration with the Registrar of Companies to
 *     be missing. Year End had the same shape, advertising "Schedule III
 *     financial statements" to entities Schedule III does not bind.
 *
 * WHAT THIS IS NOT
 *     Not a computation, and not an access control. It decides what the UI
 *     OFFERS. Every due date, every filing and every statement is still
 *     computed in apps/api — services/compliance_engine.py remains the sole
 *     authority for the dates, and no date is restated here. The gate is an
 *     affordance: hiding a control the entity can never legitimately use, in
 *     preference to showing one that is dead on arrival.
 *
 * THE LAW
 *     MCA / ROC filings under the COMPANIES ACT 2013 — AOC-4 (§137,
 *     financial statements), MGT-7 (§92, annual return) and ADT-1 (§139,
 *     intimation of auditor appointment) — bind COMPANIES: Private Limited,
 *     Public Limited, One Person Company and Section 8. They do not bind a
 *     proprietorship (which has no registration at all) or a partnership
 *     firm (registered with the Registrar of FIRMS under the Indian
 *     Partnership Act 1932 — a different registrar, not the MCA).
 *
 *     AN LLP IS THE TRAP. An LLP *is* on the MCA portal and does have a
 *     DIN-equivalent (DPIN) and a CIN-equivalent (LLPIN) — so treating it as
 *     "no MCA obligation" is wrong. But it files under the LIMITED LIABILITY
 *     PARTNERSHIP ACT 2008: Form 11 (annual return, §35) and Form 8
 *     (Statement of Account & Solvency, §34), NOT AOC-4 and NOT MGT-7.
 *     Offering an LLP the company forms would be a new wrong answer
 *     replacing the old one, so an LLP gets its own regime here.
 *
 *     SCHEDULE III to the Companies Act 2013 (§129) prescribes the FORM of a
 *     company's balance sheet and statement of profit and loss. A
 *     proprietorship or a firm still closes its books and still needs a
 *     balance sheet and a P&L — for the ITR, and for the §44AB tax audit
 *     where turnover crosses the threshold — but not in Schedule III format.
 *     So Year End stays available to everyone; only the Schedule III LABEL
 *     is gated.
 */

import type { EntityType } from "@/lib/types";

/** What the caller has on hand: `clients.entity_type` is a text column, and
 *  can be absent while the client row is still loading. */
export type EntityTypeInput = EntityType | string | null | undefined;

/**
 * Which filing regime an entity is in.
 *   "companies-act" — Companies Act 2013 forms: AOC-4, MGT-7, ADT-1.
 *   "llp-act"       — on the MCA, but LLP Act 2008: Form 11, Form 8.
 *   "none"          — nothing is filed with the MCA at all.
 */
export type McaRegime = "companies-act" | "llp-act" | "none";

/** Case- and spacing-insensitive key. `clients.entity_type` is constrained by
 *  a CHECK to the canonical spellings (migration 001), but this module is also
 *  handed values from elsewhere (mca_companies.company_type uses short codes),
 *  so it normalises rather than trusting the exact string. */
function key(entityType: EntityTypeInput): string {
  return String(entityType ?? "").trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * Entities incorporated under the Companies Act 2013 — the ones AOC-4 (§137),
 * MGT-7 (§92), ADT-1 (§139) and Schedule III (§129) bind.
 *
 * `clients.entity_type` today offers only "Private Limited" and "Public
 * Limited" of these (migration 001's CHECK). One Person Company and Section 8
 * are companies in law and are recognised here so that adding either to the
 * CHECK does not silently strip a real company of its MCA workspace; "opc" is
 * the short code mca_companies.company_type uses.
 */
const COMPANIES_ACT_COMPANY = new Set([
  "private limited",
  "public limited",
  "one person company",
  "opc",
  "section 8",
  "section 8 company",
]);

/** Limited Liability Partnership Act 2008 entities. */
const LLP_ACT_ENTITY = new Set([
  "llp",
  "limited liability partnership",
]);

/**
 * The regime this entity files in. Anything unrecognised is "none": every
 * value `clients.entity_type` can legally hold is classified above, so an
 * unknown string is data drift, and the honest answer to drift is not to
 * assert a Companies Act obligation the app cannot substantiate.
 * scripts/entity-obligations.test.ts pins that the database CHECK constraint
 * and this module stay in step, so a new entity type cannot be added to the
 * schema without being classified here.
 */
export function mcaRegime(entityType: EntityTypeInput): McaRegime {
  const k = key(entityType);
  if (COMPANIES_ACT_COMPANY.has(k)) return "companies-act";
  if (LLP_ACT_ENTITY.has(k)) return "llp-act";
  return "none";
}

/**
 * True where the entity is incorporated under the Companies Act 2013 — i.e.
 * where AOC-4 (§137), MGT-7 (§92) and ADT-1 (§139), the only forms the MCA
 * workspace implements, actually apply. False for an LLP: it files on the MCA
 * portal, but Form 11 and Form 8 under the LLP Act 2008 instead.
 */
export function isCompaniesActCompany(entityType: EntityTypeInput): boolean {
  return mcaRegime(entityType) === "companies-act";
}

/**
 * True where the entity files anything at all with the Ministry of Corporate
 * Affairs — Companies Act 2013 companies AND LLPs (LLP Act 2008, Form 11 /
 * Form 8). This is the gate for OFFERING an MCA entry point: a proprietorship
 * or a partnership firm has no MCA registration, so no MCA control is shown
 * to it at all.
 */
export function hasMcaObligations(entityType: EntityTypeInput): boolean {
  return mcaRegime(entityType) !== "none";
}

/**
 * True where financial statements must take the Schedule III form —
 * Companies Act 2013 §129 read with Schedule III, which binds companies. A
 * proprietorship, a firm, an LLP, a trust or a society still prepares a
 * balance sheet and a P&L (for the ITR, and for a §44AB tax audit), but not
 * in Schedule III format, so the label must not be claimed for them.
 *
 * An LLP's Statement of Account & Solvency is prescribed by the LLP Rules
 * 2009 under §34 of the LLP Act 2008, not by Schedule III — which is why this
 * follows the company test and not `hasMcaObligations`.
 */
export function usesScheduleIII(entityType: EntityTypeInput): boolean {
  return isCompaniesActCompany(entityType);
}

/** The canonical entity type as stored, for display; "" when unrecorded. */
function shown(entityType: EntityTypeInput): string {
  return String(entityType ?? "").trim();
}

/** Why an entity outside the Companies Act is outside it. Keyed on the
 *  normalised entity type; the registrar named is the load-bearing part. */
const OUTSIDE_THE_COMPANIES_ACT: Record<string, string> = {
  "proprietorship":
    "A proprietorship has no separate legal registration — the proprietor is the business — so there is nothing registered with the Registrar of Companies and nothing to file there.",
  "individual":
    "An individual is not a registered entity and files nothing with the Registrar of Companies.",
  "partnership":
    "A partnership firm is registered with the Registrar of FIRMS under the Indian Partnership Act 1932 — a different registrar from the Registrar of Companies, and outside the MCA's filing regime altogether.",
  "trust":
    "A trust is created under trust law — the Indian Trusts Act 1882 for a private trust, the relevant State public-trust Act for a public one — and is not registered with the Registrar of Companies.",
  "society":
    "A society is registered under the Societies Registration Act 1860 (or the equivalent State Act), not with the Registrar of Companies.",
};

const COMPANY_FORMS_SENTENCE =
  "AOC-4 (§137), MGT-7 (§92) and ADT-1 (§139) of the Companies Act 2013 bind companies — Private Limited, Public Limited, One Person Company and Section 8.";

/**
 * A plain explanation of why this entity does not get the MCA workspace, or
 * null where it does (a Companies Act company, for which there is nothing to
 * explain). The first sentence names the entity type, so a CA who arrives at
 * the page by URL is told what is true rather than shown an empty list.
 */
export function mcaScopeNote(entityType: EntityTypeInput): string | null {
  const regime = mcaRegime(entityType);
  if (regime === "companies-act") return null;

  const name = shown(entityType);
  if (regime === "llp-act") {
    return (
      `This client is an ${name || "LLP"}. An LLP is on the MCA portal and has a DPIN and an LLPIN, ` +
      "but it files under the Limited Liability Partnership Act 2008 — Form 11 (annual return, §35) " +
      "and Form 8 (Statement of Account & Solvency, §34) — not AOC-4, MGT-7 or ADT-1, which are " +
      "Companies Act 2013 forms for companies."
    );
  }

  if (!name) {
    return (
      "This client's entity type is not recorded, so no Companies Act 2013 filing obligation can be " +
      `established for it. ${COMPANY_FORMS_SENTENCE}`
    );
  }
  const reason =
    OUTSIDE_THE_COMPANIES_ACT[key(entityType)] ??
    `A ${name} is not incorporated under the Companies Act 2013 and is not registered with the Registrar of Companies.`;
  // "an Individual"/"an LLP", not "a Individual" — this sentence is shown to
  // the CA verbatim, so the article has to agree with the entity name.
  const article = /^[AEIOU]/i.test(name) ? "an" : "a";
  return `This client is ${article} ${name}. ${reason} ${COMPANY_FORMS_SENTENCE}`;
}
