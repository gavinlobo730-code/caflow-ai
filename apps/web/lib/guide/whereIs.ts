/**
 * "WHERE IS…?": THE RULES OF THE GUIDE THAT REPLACED THE GUIDED TIPS (POST-A-538, the owner's decision of 21-11-2026).
 *
 * The owner tried the guided tips on the live Test Firm and asked for something else: a person asks where a thing is, in
 * their own words, and is told in a sentence, with a button that opens the screen. This module is the part of that which is a
 * rule and not a drawing: which screens a person may be pointed at, how an answer is turned into something to click, and the
 * plain search the guide falls back to.
 *
 * THREE THINGS IT GUARANTEES, AND HOW.
 *
 *  1. THE GUIDE NEVER POINTS AT A SCREEN THAT DOES NOT EXIST. Every answer is an ID out of `lib/navigation/screens.ts`, the one
 *     inventory of screens (the command palette reads the same list, and `scripts/every-screen-has-a-name.test.ts` holds it to
 *     the routes on disk). The model is asked to choose ids and is given nothing to write: an id that is not on the list is
 *     dropped here as well as on the server.
 *  2. IT NEVER SAYS ANYTHING THE PRODUCT DID NOT WRITE. The sentence a person reads is built here from the screen's own name
 *     and area. No word of the model's reaches the screen, so the model cannot describe a feature that does not exist.
 *  3. IT DOES NOT OFFER A SCREEN THE PERSON'S ROLE IS NOT OFFERED. `offeredTo` asks the same rules the menus ask (the area's
 *     role rule, the hidden addresses, a Settings link's own roles, My practice for a Partner, the People screens' permission
 *     pairs, payroll's). It is what is SHOWN, as every menu is: the server and each page still decide who may open what, and a
 *     screen inside an offered area that needs a finer permission still refuses for itself.
 *
 * Pure: no React and no request, so the rules are tested as plain code (`whereIs.test.ts`).
 */
import { ALL_SCREENS, screenHref, type Screen } from "../navigation/screens.ts";
import { getActiveWorkspaceForPathname } from "../workspace/routeOwnership.ts";
import type { UserRole } from "../auth/permissions.ts";
import { mayOpen } from "../access/screenAccess.ts";
import { SETTINGS_GROUPS, linkShownTo } from "../settings/groups.ts";
import { isPeoplePath, isPracticePath } from "../workspace/practiceWorkspace.ts";
import { outerMenu } from "../workspace/outerMenu.ts";

/** A question longer than this is cut before it is sent; the server refuses a longer one. */
export const MAX_QUESTION = 300;
/** How many screens an answer names at most. */
export const MAX_ANSWERS = 3;

/** A screen's id for the guide: its scope and its address as the inventory writes it. Unique across the list. */
export function screenId(s: Screen): string {
  return `${s.scope}:${s.href}`;
}

const BY_ID: ReadonlyMap<string, Screen> = new Map(ALL_SCREENS.map((s) => [screenId(s), s]));

export interface Who {
  role: UserRole | null;
  can: (resource: string, action: string) => boolean;
  /** False while the permission map is still being read: nothing is withheld on a pair until it is known. */
  resolved: boolean;
  /** Whether a client workspace's section (the first segment under the client) is offered to this person. */
  clientSectionOffered: (sectionId: string) => boolean;
}

/**
 * Whether this person is offered this screen, by the rules the menus ask.
 *
 * A firm screen is asked of the one table (`lib/access/screenAccess.ts`, POST-A-543): its area's rule and its own. The guide
 * therefore names exactly what the menu lists and what the page gate opens. Two families keep their own rule and are asked
 * first: a Settings page (the roles its own link names) and a screen inside a client (the sections that client offers).
 */
export function offeredTo(s: Screen, who: Who): boolean {
  if (s.scope === "client") return who.clientSectionOffered(s.href.split("/")[0]);
  const href = s.href;
  if (href === "/settings" || href.startsWith("/settings/")) {
    for (const group of SETTINGS_GROUPS) {
      const link = group.links.find((l) => l.href.split(/[?#]/)[0] === href);
      if (link) return linkShownTo(link, who.role);
    }
    return true;
  }
  const isPartner = who.role === "Partner";
  // Until the permissions are known nothing is withheld on a pair; the Partner-only rule is asked of the role and stands.
  const asker = who.resolved ? { can: who.can, isPartner } : { can: () => true, isPartner };
  return mayOpen(href, asker).allowed;
}

/** The ids of every screen this person is offered: what the guide may answer with. */
export function offeredIds(who: Who): string[] {
  return ALL_SCREENS.filter((s) => offeredTo(s, who)).map(screenId);
}

export interface GuideAnswer {
  id: string;
  name: string;
  /** Where it is, as a whole phrase in the menu's own names: "in the firm menu, under More, then Accounting". */
  where: string;
  /** The address to open, or null when the screen is inside a client's workspace and no client is open. */
  href: string | null;
}

/**
 * THE NAME EACH AREA HAS ON THE FIRM MENU. `workspaceConfig.ts` is where the menu reads them, and it imports icons a test
 * cannot load, so the names are repeated here and `scripts/the-guide-reads-the-one-list-of-screens.test.ts` holds this table
 * to that file word for word: a renamed area that the guide still called by its old name fails there.
 */
export const AREA_NAMES: Readonly<Record<string, string>> = {
  home: "Home", clients: "Clients", deadlines: "Deadlines", work: "Work", team: "Team", ai: "AI",
  accounting: "Accounting", payroll: "Payroll", relationships: "Relationships", health: "Health",
  practice: "My practice", knowledge: "Knowledge", engagements: "Engagements",
};

/**
 * WHO IS LOOKING AT THE MENU, for the sentence that says where a screen is. The inventory's own heading for a screen
 * ("Practice", "Insights", "General") is the command palette's grouping and is on no menu, so a sentence built from it sent a
 * Manager to look for Team "under Practice". The sentence is built from the menu the person actually has instead.
 */
export interface Places {
  /** The ids of the areas this person is offered on the firm menu, as the menu itself works them out. */
  areas: readonly string[];
}

/** Where a screen is, said in the names this person's menus use. */
export function whereOf(s: Screen, places: Places): string {
  if (s.scope === "client") return "inside a client’s workspace";
  const href = s.href;
  if (href === "/settings" || href.startsWith("/settings/")) return "in Settings, the gear at the top right";
  const menu = outerMenu(places.areas);
  const hasPractice = places.areas.includes("practice");
  // The People screens: a group inside My practice for somebody who has it, the Team entry for everybody else.
  if (isPeoplePath(href)) return hasPractice ? "in the firm menu, under My practice, in the People group" : "in the firm menu, under Team";
  const area = isPracticePath(href) ? "practice" : getActiveWorkspaceForPathname(href);
  const name = area ? AREA_NAMES[area] : undefined;
  if (!area || !name) return "";
  return menu.more.includes(area) ? `in the firm menu, under More, then ${name}` : `in the firm menu, under ${name}`;
}

/**
 * The answers to show for the ids the server chose, in its order: only ids on the inventory AND offered to this person, at
 * most `MAX_ANSWERS`, none twice. `clientId` is the open client, or null outside a workspace.
 */
export function answersFor(ids: readonly unknown[], offered: ReadonlySet<string>, clientId: string | null, places: Places): GuideAnswer[] {
  const out: GuideAnswer[] = [];
  const seen = new Set<string>();
  for (const id of ids) {
    if (typeof id !== "string" || seen.has(id) || !offered.has(id)) continue;
    const s = BY_ID.get(id);
    if (!s) continue;
    seen.add(id);
    out.push({ id, name: s.name, where: whereOf(s, places), href: screenHref(s, clientId) });
    if (out.length === MAX_ANSWERS) break;
  }
  return out;
}

/** The sentence under an answer: where the screen is and, for a client's screen with no client open, what to do first. */
export function sentenceFor(a: GuideAnswer): string {
  if (a.href === null) return `${a.name} is ${a.where}. Open a client first, then ask again or use the client’s menu.`;
  // A screen no menu lists (the search page) is named without a place it does not have.
  return a.where ? `${a.name} is ${a.where}.` : `${a.name} opens from the button here.`;
}

const SMALL_WORDS = new Set([
  "a", "an", "the", "is", "are", "do", "does", "i", "we", "my", "our", "me", "to", "of", "for", "in", "on", "at", "it", "and", "or",
  "how", "where", "what", "which", "can", "could", "should", "find", "see", "show", "open", "go", "get", "screen", "page", "place",
  "record", "enter", "add", "make", "create", "new", "this", "that", "from", "with", "by",
]);

/** The words of a question worth matching on: lower case, no punctuation, no small words, two letters or more. */
export function wordsOf(question: string): string[] {
  const words = (question || "").toLowerCase().replace(/[^a-z0-9()./\- ]+/g, " ").split(/\s+/).map((w) => w.replace(/^[.\-/]+|[.\-/?]+$/g, ""));
  return [...new Set(words.filter((w) => w.length >= 2 && !SMALL_WORDS.has(w)))];
}

/**
 * THE PLAIN SEARCH THE GUIDE FALLS BACK TO, when the AI is off, unreachable, over the firm's allowance or rate limited. It
 * matches the question's words against each offered screen's name, the other words a CA calls it by and its area, and returns
 * the ids of the best few. It understands no meaning: "where do I pay the government" finds nothing, and the screen says that
 * this was a plain search so a person knows to try the form number or the section.
 */
export function plainSearch(question: string, offered: ReadonlySet<string>, limit: number = MAX_ANSWERS): string[] {
  const words = wordsOf(question);
  if (!words.length) return [];
  const scored: Array<{ id: string; score: number; name: string }> = [];
  for (const s of ALL_SCREENS) {
    const id = screenId(s);
    if (!offered.has(id)) continue;
    const name = s.name.toLowerCase();
    const nameWords = name.split(/[^a-z0-9]+/);
    const section = s.section.toLowerCase();
    let score = 0;
    for (const w of words) {
      // A whole word of the name, or the start of one for a word long enough not to be a coincidence ("recon" finds
      // reconciliation; "pay" does not find payroll).
      if (nameWords.includes(w)) score += 5;
      else if (w.length >= 4 && nameWords.some((n) => n.startsWith(w))) score += 3;
      if (s.synonyms.some((x) => x === w)) score += 4;
      else if (s.synonyms.some((x) => x.split(/[^a-z0-9]+/).includes(w))) score += 3;
      else if (w.length >= 4 && s.synonyms.some((x) => x.split(/[^a-z0-9]+/).some((n) => n.startsWith(w)))) score += 1;
      if (section === w) score += 1;
    }
    if (score > 0) scored.push({ id, score, name: s.name });
  }
  scored.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
  return scored.slice(0, limit).map((x) => x.id);
}
