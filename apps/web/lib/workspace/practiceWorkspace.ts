/**
 * MY PRACTICE: THE FIRM'S OWN WORKSPACE, ON ADDRESSES THAT ALREADY EXIST (POST-A-532).
 *
 * The owner, on the live Test Firm on 20-11-2026, could not find where a firm keeps its own books: the practice is a client of
 * itself (`docs/architecture/11-revenue-ops-and-knowledge.md`), Partner-only and left out of every client list, and the one
 * door to its books was a small button on the Accounting overview. Its other screens (billing schedules, collections, the
 * receivables ageing, revenue, profitability) sat on a separate menu, in the firm's navy frame, as though they were about
 * something else. The owner asked for one place, with everything a client's workspace has and more.
 *
 * NOTHING NEW IS ADDRESSED. The live site has 99 of its 100 dynamic address rules in use (CLAUDE.md, Deployment), so My
 * practice is a FRAME over two sets of addresses that exist: the practice's own client workspace
 * (`/clients/<the practice's id>/…`, which a Partner could always open) and the fixed `/practice/…` screens. The frame is the
 * client workspace's own shell with a bar that says whose workspace this is; this module is what both halves ask.
 *
 * Pure, with no imports, so the rules are tested as plain code (`practiceWorkspace.test.ts`).
 */

/** The fixed addresses drawn in the My practice frame: the address itself and everything under it. */
export const PRACTICE_PREFIXES: readonly string[] = ["/practice", "/billing", "/accounting/receivables"];

function withoutTrailingSlash(path: string): string {
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

/** Whether a fixed address is one of My practice's own screens. A client's workspace is not asked here: that is the client's
 *  own row (`is_internal`), which only the server knows. */
export function isPracticePath(pathname: string): boolean {
  const path = withoutTrailingSlash((pathname || "").split(/[?#]/)[0]);
  return PRACTICE_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix + "/"));
}

export interface PracticeSection {
  id: string;
  /** The words on the tile. Where the firm menu lists the same screen, the same words (`practiceWorkspace.test.ts` holds it). */
  label: string;
  href: string;
}

/**
 * The screens about RUNNING the practice: what it bills, what it is owed and what it earns. Fixed addresses, every one a
 * Partner-only screen that existed before this. The firm's own books are not in this list: they are the client workspace's
 * sections, opened on the practice's own client (`booksSectionsFor`).
 */
export const PRACTICE_SECTIONS: readonly PracticeSection[] = [
  { id: "home",          label: "Practice home",         href: "/practice/" },
  { id: "billing",       label: "Billing Schedules",     href: "/practice/billing/" },
  { id: "collections",   label: "Collections",           href: "/practice/collections/" },
  { id: "ar",            label: "AR Aging",              href: "/practice/ar/" },
  { id: "revenue",       label: "Revenue",               href: "/practice/revenue/" },
  { id: "profitability", label: "Profitability",         href: "/practice/profitability/" },
  { id: "benchmark",     label: "Client benchmark",      href: "/practice/benchmark/" },
  { id: "compliance",    label: "Compliance Workload",   href: "/practice/compliance/" },
  { id: "instructions",  label: "Practice instructions", href: "/practice/instructions/" },
  // The old Fee Billing screen, a read-only record since the firm's own billing moved here (POST-B-193).
  { id: "earlier-bills", label: "Earlier fee bills",     href: "/billing/" },
  // What is still owed on those earlier bills, by age. The practice's receivables on the new engine are AR Aging above.
  { id: "earlier-receivables", label: "Earlier fee receivables", href: "/accounting/receivables/" },
];

/**
 * The team and its hours: screens My practice POINTS AT and does not hold. They are the firm's own (who works here, what each
 * is working on, the hours recorded), a Manager reaches them too, and they stay in the firm's menus and the firm's frame; a
 * Partner looking for "my practice" looks for them here as well, so they are listed, last, under a heading that says they
 * open in the firm's menus. The words are the menus' own (`practiceWorkspace.test.ts` holds it).
 */
export const PRACTICE_TEAM_SECTIONS: readonly PracticeSection[] = [
  { id: "team",     label: "Team",          href: "/team/" },
  { id: "workload", label: "Workload",      href: "/team/workload/" },
  { id: "time",     label: "Time Tracking", href: "/time/" },
];

/**
 * The client-workspace sections NOT offered for the practice, each with why. Everything else a client has, the practice has.
 * A section is left out only where the screen would be about something the practice is not (a client the firm serves); the
 * reason is the rule, so a section is not dropped because it looked unimportant. Payroll was on this list while the server
 * refused it for the practice (guardrail G4); the firm now runs its own staff's payroll here, and only a Partner may.
 */
export const NOT_FOR_THE_PRACTICE: Readonly<Record<string, string>> = {
  portal: "the client portal is where a client reads what the firm shares with it; the firm has no portal into itself",
  lifecycle: "onboarding, renewal and offboarding are the stages of a client the firm serves",
  health: "the practice is left out of client health scoring (guardrail G2), so its screen would say 'not yet scored' for good",
  knowledge: "a client's articles are the firm's notes ABOUT a client; the firm's own are the Knowledge base",
  instructions: "the standing notes for the practice itself are Practice instructions, on this menu",
};

/** The client sections offered for the practice's own books: every section but the ones `NOT_FOR_THE_PRACTICE` names. */
export function booksSectionsFor<T extends { id: string }>(sections: readonly T[]): T[] {
  return sections.filter((s) => !(s.id in NOT_FOR_THE_PRACTICE));
}

/** The practice screen an address is, or null (the practice's books, or not My practice at all). The home screen is matched
 *  exactly, so it is not "active" on every screen under it. */
export function practiceSectionAt(pathname: string): PracticeSection | null {
  const path = withoutTrailingSlash((pathname || "").split(/[?#]/)[0]);
  let best: PracticeSection | null = null;
  for (const s of PRACTICE_SECTIONS) {
    const href = withoutTrailingSlash(s.href);
    const hit = s.id === "home" ? path === href : path === href || path.startsWith(href + "/");
    if (hit && (!best || href.length > withoutTrailingSlash(best.href).length)) best = s;
  }
  return best;
}

export type PracticeLookup =
  | { state: "idle" | "resolving" | "not-set-up" | "unavailable"; practiceId: null }
  | { state: "ready"; practiceId: string };

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/**
 * What `GET /api/practice` said about the practice's own client. `ready` has its id. `not-set-up` is ONLY the server's own
 * "not provisioned"; an answer that is refused, failed or shaped like something else is `unavailable`, because "set it up"
 * said to a Partner whose read failed sends them to create something that exists.
 */
export function readPracticeLookup(res: unknown): PracticeLookup {
  const body = asObject(res);
  const data = body?.success === true ? asObject(body.data) : null;
  if (!data) return { state: "unavailable", practiceId: null };
  if (typeof data.internal_client_id === "string" && data.internal_client_id) return { state: "ready", practiceId: data.internal_client_id };
  return data.provisioned === false ? { state: "not-set-up", practiceId: null } : { state: "unavailable", practiceId: null };
}
