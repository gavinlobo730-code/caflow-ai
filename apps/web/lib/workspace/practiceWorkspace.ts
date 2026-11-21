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

export interface PeopleSection extends PracticeSection {
  /** The rbac pair the screen's own reads need, read off its endpoint; the entry is not offered to somebody without it. */
  requires: readonly [resource: string, action: string];
}

/**
 * THE PEOPLE OF THE FIRM: ONE LIST OF SCREENS, TWO DOORS (the owner's decision of 21-11-2026).
 *
 * Who works here, who handles which client, what is waiting for approval, who signed in and how loaded each person is. To a
 * Partner these are part of "my practice", and the first build of My practice sent them back out to the firm's own menu with a
 * line of small print, which the owner met on the live Test Firm as being thrown out of the room he was in. A Manager has no
 * key to My practice (guardrail G1: the firm's money is the Partner's) and runs the team day to day, because work is delegated
 * from the Partner to the Manager and from the Manager to the team.
 *
 * So the screens keep their addresses and are reached through two doors. Somebody who may open My practice is drawn them in
 * the My practice frame (`wearsThePracticeFrame`) and finds them in its People group, and has no separate Team entry on the
 * outer menu (`lib/workspace/outerMenu.ts`). Everybody else who may see them reaches them from the firm menu's Team entry, in
 * the firm's frame, as before. The frame follows the PERSON and not a marker on the address, so a bookmark, a link in a
 * notification and the command palette all land in the right frame. `TeamPanel` (the Manager's door) lists the same screens
 * in the same words, and `practiceWorkspace.test.ts` holds the two lists to each other.
 *
 * Time Tracking is not here: every member of staff records hours, so it lives in Work, where everybody finds it.
 */
export const PRACTICE_PEOPLE_SECTIONS: readonly PeopleSection[] = [
  { id: "team",          label: "Team",          href: "/team/",               requires: ["team", "read"] },
  { id: "assignments",   label: "Assignments",   href: "/team/assignments/",   requires: ["assignment", "read"] },
  { id: "approvals",     label: "Approvals",     href: "/approvals/",          requires: ["approval", "read"] },
  { id: "workload",      label: "Workload",      href: "/team/workload/",      requires: ["workload", "read"] },
  { id: "login-history", label: "Login History", href: "/team/login-history/", requires: ["team", "read"] },
];

/** The address prefixes of the People screens: each address and everything under it. */
export const PEOPLE_PREFIXES: readonly string[] = ["/team", "/approvals"];

/** Whether an address is one of the People screens. Which frame it is drawn in depends on who is looking. */
export function isPeoplePath(pathname: string): boolean {
  const path = withoutTrailingSlash((pathname || "").split(/[?#]/)[0]);
  return PEOPLE_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix + "/"));
}

/**
 * Whether a fixed address is drawn in the My practice frame for this person. The practice's own screens always are (the
 * server refuses their reads to anybody else, and the page's own guard sends them away). A People screen is only for
 * somebody who may open My practice; for everybody else it is a firm screen.
 */
export function wearsThePracticeFrame(pathname: string, mayOpenPractice: boolean): boolean {
  return isPracticePath(pathname) || (mayOpenPractice && isPeoplePath(pathname));
}

/** The People screens offered to this person: every one whose reads they are allowed. Nothing is withheld while the
 *  permission map is still being read, so an entry does not appear a moment after the others. */
export function peopleSectionsOffered(can: (resource: string, action: string) => boolean, resolved: boolean): PeopleSection[] {
  return PRACTICE_PEOPLE_SECTIONS.filter((s) => !resolved || can(s.requires[0], s.requires[1]));
}

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

/** The practice or People screen an address is, or null (the practice's books, or not My practice at all). The home screen
 *  is matched exactly, so it is not "active" on every screen under it; of two screens that both match, the longer address
 *  wins, so `/team/assignments/` is Assignments and not Team. */
export function practiceSectionAt(pathname: string): PracticeSection | null {
  const path = withoutTrailingSlash((pathname || "").split(/[?#]/)[0]);
  let best: PracticeSection | null = null;
  for (const s of [...PRACTICE_SECTIONS, ...PRACTICE_PEOPLE_SECTIONS]) {
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
