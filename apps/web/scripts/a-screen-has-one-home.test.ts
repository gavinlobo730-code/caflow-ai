/**
 * A screen belongs to ONE module, and one sidebar lists it.
 *
 * `a-module-shows-all-of-itself.test.ts` holds the other direction — every
 * named firm screen is in the panel of the workspace that OWNS it — and it is
 * deliberately silent about a screen listed in several panels, because listing
 * one is what it measures. That silence is where PAY-28 lived.
 *
 * WHAT WAS WRONG. Payroll's six screens sat across THREE top-level areas:
 * `/payroll` and `/payroll/statutory` under Accounting, `/payroll/attendance`
 * under TEAM, and `/payroll/people`, `/payroll/declarations` and
 * `/payroll/reports` in no panel at all. 2.5 closed the third of those by
 * putting all six under an Accounting sub-heading — and left `/payroll/
 * attendance` in BOTH panels, so the same screen was two clicks apart under
 * two different module headings, lighting a different rail icon depending on
 * which one a CA had used. A bureau running payroll for a dozen clients — a
 * service a practice SELLS, priced per employee per month — had no home for it.
 *
 * Payroll is the thirteenth top-level workspace now (`docs/architecture/
 * 10-payroll.md` specifies exactly that), so the six live in `PayrollPanel`
 * and nowhere else.
 *
 * THE RULE RATHER THAN A SPELLING OF IT. This does not assert "attendance is
 * not in TeamPanel" — that is one instance, and the next module to grow a
 * convenience link somewhere else would pass it. It asserts that **no named
 * firm screen appears in more than one panel**, which is the property that was
 * actually violated and the one that stays true however the panels are
 * reorganised. It is also the check that would have caught the duplication on
 * the day 2.5 introduced it.
 *
 * A DELIBERATE CROSS-MODULE POINTER IS AN ENTRY HERE, NOT AN EXCEPTION TO THE
 * RULE. `LISTED_TWICE` is frozen, carries an argument per entry, and has a
 * staleness test in the other direction, so an entry that stops being needed
 * has to come out — the discipline `NO_BROWSE_SURFACE` takes next door.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { SCREENS } from "../lib/navigation/screens.ts";
import { stripComments } from "./stripComments.ts";

const WEB = join(import.meta.dirname, "..");
const PANELS = join(WEB, "components/panels");

/**
 * Screens a second panel is allowed to point at, and why. Only ever a screen
 * whose OWNING panel also lists it — this is a pointer, never a home.
 */
const LISTED_TWICE: Record<string, string> = {
  "/deadlines":
    "owned by DeadlinesPanel; HomePanel lists it because Home is the " +
    "launchpad and the deadline list is one of the two things due today. " +
    "⚠️ It is also in STAFF_HIDDEN_HREFS, and HomePanel had no role filter " +
    "at all until this guard found it — so an Executive, a Reviewer and a " +
    "Client were offered from Home a workspace the rail deliberately hides " +
    "from them. HomePanel now filters on canAccessHref",
  "/work":
    "owned by WorkPanel; HomePanel lists it for the same reason as " +
    "/deadlines — the work queue is the other of the two. ⚠️ Worth knowing: " +
    "the `work` WORKSPACE is in STAFF_HIDDEN_WORKSPACES and the `/work` HREF " +
    "is not in STAFF_HIDDEN_HREFS, so `canAccessWorkspace` and " +
    "`canAccessHref` give opposite answers about one destination. Left as it " +
    "is rather than picked by me: which is right is a product decision, and " +
    "the href rule is the one the panels apply",
  "/clients":
    "owned by ClientsPanel; the second occurrence is not a sidebar entry at " +
    "all — DeadlinesPanel's triage note says 'To file, open a client' with " +
    "the word linked. Prose in a panel, which this guard cannot tell from a " +
    "nav item and should not try to: the rule is about where a screen LIVES",
  "/settings/dsc-tracker":
    "owned by SettingsPanel; DeadlinesPanel lists it under Critical Tools " +
    "because a DSC that expires IS a filing deadline — a return cannot be " +
    "signed without one — and a CA works that from the calendar rather than " +
    "from Settings",
  "/settings/statutory-values":
    "owned by SettingsPanel; PayrollPanel points at it because it IS the " +
    "architecture doc's payroll Setup section — which states' professional " +
    "tax and LWF this firm has recorded slabs for. Building /payroll/setup " +
    "as well would be a second screen for one fact, which is the mistake " +
    "this codebase records at /accounting/retainer and /gst/reconciliation. " +
    "PayrollPanel draws it with an outbound mark so the rail icon changing " +
    "is not a surprise",
};

/**
 * ⚠️ COMMENTS ARE STRIPPED FIRST, and the first run of this guard is why.
 * Every panel that gave up a screen now carries a comment SAYING which screen
 * left and not to add it back — `PayrollPanel` names `/accounting/retainer`
 * as the precedent it is following, `TeamPanel` names `/payroll/attendance` as
 * the thing that moved — so a plain substring search read the explanation as
 * the deed and reported four panels as listing screens they had just been
 * cleaned of. A guard that a warning against the defect makes fail is a guard
 * nobody can write the warning for.
 */
function panelSources(): Array<{ name: string; src: string }> {
  return readdirSync(PANELS)
    .filter((f) => f.endsWith("Panel.tsx"))
    .map((f) => ({
      name: f.replace(/\.tsx$/, ""),
      src: stripComments(readFileSync(join(PANELS, f), "utf8")),
    }));
}

/** Which panels declare this href. Quoted, so `/gst` is not satisfied by
 *  `/gst/gstr1` — the same match `a-module-shows-all-of-itself` uses. */
function panelsListing(href: string, panels: Array<{ name: string; src: string }>): string[] {
  const re = new RegExp(`["'\`]${href.replace(/\//g, "\\/")}["'\`]`);
  return panels.filter((p) => re.test(p.src)).map((p) => p.name);
}

test("the sweep sees a real population of panels and screens", () => {
  // Vacuity floors on the POPULATION, never on the offenders: a floor counting
  // what is still wrong goes green by breaking the thing that finds it.
  const panels = panelSources();
  assert.ok(panels.length >= 10, `only ${panels.length} panels found under components/panels`);
  const firm = SCREENS.filter((s) => s.scope === "firm");
  assert.ok(firm.length >= 90, `only ${firm.length} firm screens — screens.ts has probably moved`);
});

test("no firm screen is listed in more than one panel", () => {
  const panels = panelSources();
  const doubled: string[] = [];
  for (const s of SCREENS) {
    if (s.scope !== "firm") continue;
    // `/` is not askable and is not a module screen. Every panel computes its
    // own active state with `pathname.startsWith(href + "/")`, so the string
    // `"/"` appears in all thirteen as CODE — stripping comments cannot help,
    // and there is nothing to tell that apart from a declared link to Home.
    // Home is the rail's own first tile in any case.
    if (s.href === "/") continue;
    if (s.href in LISTED_TWICE) continue;
    const where = panelsListing(s.href, panels);
    if (where.length > 1) doubled.push(`${s.href} (${s.name})  —  ${where.sort().join(", ")}`);
  }
  assert.deepEqual(
    doubled.sort(),
    [],
    "These screens are listed in several module sidebars, so the same page " +
      "sits under two module headings and lights a different rail icon " +
      "depending on which one the CA used. Decide which module OWNS each and " +
      "remove it from the others; if a second panel must point at one, add it " +
      "to LISTED_TWICE here with the argument.\n  " + doubled.sort().join("\n  "),
  );
});

test("every LISTED_TWICE entry is still listed twice, and names a real screen", () => {
  // The other direction. An allowlist nobody re-reads is how an exemption
  // outlives its reason.
  const panels = panelSources();
  const named = new Set(SCREENS.map((s) => s.href));
  const stale: string[] = [];
  for (const href of Object.keys(LISTED_TWICE)) {
    if (!named.has(href)) { stale.push(`${href} — not a named screen`); continue; }
    const where = panelsListing(href, panels);
    if (where.length < 2) stale.push(`${href} — now in ${where.length} panel(s): ${where.join(", ")}`);
  }
  assert.deepEqual(stale, [], "LISTED_TWICE entries that no longer describe anything:\n  " + stale.join("\n  "));
});

test("payroll's six screens are all in PayrollPanel and in no other", () => {
  // The named negative control. These are the exact screens PAY-28 found
  // spread over three top-level areas, so a rewrite that made the sweep above
  // vacuous would still have to keep them right.
  const panels = panelSources();
  for (const href of [
    "/payroll", "/payroll/attendance", "/payroll/declarations",
    "/payroll/people", "/payroll/reports", "/payroll/statutory",
  ]) {
    assert.deepEqual(
      panelsListing(href, panels),
      ["PayrollPanel"],
      `${href} should be listed by PayrollPanel and nothing else`,
    );
  }
});
