/**
 * THE FIRM MENU'S OUTER LIST: WHAT A PERSON SEES FIRST, AND WHAT SITS UNDER "MORE" (the owner's decision of 21-11-2026).
 *
 * The menu listed thirteen areas in one column for a Partner. The owner, on the live Test Firm, asked that it show less: the
 * areas a practice opens every day stay in the list, and the rest go under one "More" entry. Nothing is removed and nothing
 * changes about who may open what; this is only the order and the grouping of the areas a person was already offered.
 *
 * TWO RULES, AND THE CALLER SUPPLIES WHO IS LOOKING:
 *
 *  1. Somebody who is offered My practice is not offered a separate Team entry. The People screens are a group inside My
 *     practice for them (`practiceWorkspace.PRACTICE_PEOPLE_SECTIONS`), so a second entry would be two doors into one room on
 *     one list. Everybody else keeps Team where it was: a Manager runs the team and has no My practice.
 *  2. "More" exists only when it would hold at least two areas. One area under a heading of its own is a click for nothing,
 *     so a single one is listed with the rest.
 *
 * Pure, with no imports, so the rule is tested as plain code (`outerMenu.test.ts`); ids are plain strings because
 * `workspaceConfig.ts` imports icons a test cannot load.
 */

/** The areas listed first, in this order, when the person is offered them. */
export const MAIN_AREAS: readonly string[] = ["home", "clients", "deadlines", "work", "team", "practice", "ai"];

/** The areas that sit under "More", in this order, when the person is offered them. */
export const MORE_AREAS: readonly string[] = ["accounting", "payroll", "relationships", "health", "knowledge", "engagements"];

export interface OuterMenu {
  /** The areas listed directly, in order. */
  main: string[];
  /** The areas under "More", in order. Empty when there is no "More" entry. */
  more: string[];
}

/** The id the menu uses for the "More" entry itself, which is not an area. */
export const MORE_ID = "more";

/**
 * The outer menu for somebody offered `offered` (the ids of the areas the role and permission rules admit, in any order).
 * An area that is on neither list is kept, after the main ones, so a new area cannot vanish from the menu by being left
 * off both.
 */
export function outerMenu(offered: readonly string[]): OuterMenu {
  const has = new Set(offered);
  const listed = (id: string) => has.has(id) && !(id === "team" && has.has("practice"));
  const unplaced = offered.filter((id) => !MAIN_AREAS.includes(id) && !MORE_AREAS.includes(id));
  const main = [...MAIN_AREAS.filter(listed), ...unplaced];
  const more = MORE_AREAS.filter(listed);
  return more.length < 2 ? { main: [...main, ...more], more: [] } : { main, more };
}

/**
 * The area whose list the open menu shows: the one under the pointer, else the one the address is in, else Home. An area the
 * person is not offered is never shown; the People screens stand in My practice for somebody who has it.
 */
export function areaShown(hovered: string | null, active: string | null, menu: OuterMenu): string {
  const all = [...menu.main, ...menu.more];
  for (const id of [hovered, active]) {
    if (!id) continue;
    if ((id === MORE_ID && menu.more.length > 0) || all.includes(id)) return id;
    if (id === "team" && all.includes("practice")) return "practice";
  }
  return all.includes("home") ? "home" : (all[0] ?? "home");
}

