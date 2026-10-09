/**
 * The small things every scenario needs: finding Playwright, finding a Chromium, pressing a button twice before
 * the page can draw, choosing from one of the product's own pickers, and saying "this URL was written exactly
 * N times".
 *
 * PLAYWRIGHT IS NOT A DEPENDENCY OF THIS PACKAGE, for the reason the walk's header gives: it is a ~40 MB install
 * the frontend job every pull request runs does not need. The workflow that runs the drive installs it in its
 * own job (it is the walk's job; the drive runs after the walk, on the same install and the same build), and
 * `loadPlaywright` below looks for it in the three places it can be: the package the workflow added, a plain
 * `playwright`, and a path in `PLAYWRIGHT_MODULE` for a machine that keeps it outside the project.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";

export async function loadPlaywright() {
  const tries = [
    () => import("@playwright/test"),
    () => import("playwright"),
    () => (process.env.PLAYWRIGHT_MODULE ? import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href) : Promise.reject(new Error("unset"))),
  ];
  for (const attempt of tries) {
    try {
      const pw = await attempt();
      const chromium = pw.chromium ?? pw.default?.chromium;
      if (chromium) return chromium;
    } catch { /* try the next place */ }
  }
  console.error(
    "Playwright is not installed.\n" +
    "  cd apps/web && pnpm add -D @playwright/test      (and remove it again before committing: it is not a\n" +
    "  project dependency, see scripts/smoke-walk.mjs above loadChromium() for why)\n" +
    "or point PLAYWRIGHT_MODULE at an install, e.g. /opt/node-tools/node_modules/playwright/index.mjs.");
  process.exit(2);
}

/** The Chromium already on disk, when there is one (the walk's rule: Playwright's own download is disabled in
 *  some environments and the installed build may not be the one this version expects). Undefined lets Playwright
 *  use its own, which is what a CI runner has after `playwright install`. */
export function installedChromium() {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!fs.existsSync(root)) return undefined;
  for (const dir of fs.readdirSync(root).filter((d) => d.startsWith("chromium-")).sort().reverse()) {
    for (const rel of ["chrome-linux/chrome", "chrome-linux64/chrome"]) {
      const p = path.join(root, dir, rel);
      if (fs.existsSync(p)) return p;
    }
  }
  return undefined;
}

/**
 * Click every one of `locators` before the page gets a turn to render.
 *
 * THIS IS THE DEFECT, REPRODUCED. A person's double-click is two click events a few milliseconds apart, and
 * React commits the first click's `setSaving(true)` only after both have run; a guard held in React state
 * (`disabled={saving}`) therefore reads `false` twice. `element.click()` called twice inside ONE evaluate is the
 * same thing with the timing removed: no render can sit between the two. Playwright's own `dblclick()` is not
 * this, since it waits for the page to settle between the events and so tests a slower person than the one who
 * posted eleven journals.
 */
export async function sameTick(...locators) {
  const handles = [];
  for (const locator of locators) {
    // `elementHandle` waits for the element to exist and be attached, with the locator's own timeout.
    handles.push(await locator.elementHandle());
  }
  const page = locators[0].page();
  await page.evaluate((els) => { for (const el of els) el.click(); }, handles);
}

/** The same button pressed twice in one tick: the double-click. */
export async function sameTickDouble(locator) {
  const handle = await locator.elementHandle();
  await locator.page().evaluate((el) => { el.click(); el.click(); }, handle);
}

/** Pick an option in one of the product's own comboboxes. Scoped to the open listbox: an unscoped
 *  `getByRole("option")` also matches an ordinary `<select>`'s options elsewhere on the same screen. */
export async function pick(page, trigger, optionText) {
  await trigger.click();
  await page.locator("[role=listbox] [role=option]", { hasText: optionText }).first().click();
}

/** Assert `re` was written exactly `n` times. The message names what WAS written, because "expected 1, got 2"
 *  does not say which two. */
export async function expectWrites(stub, re, n, what, method) {
  await stub.quiet();
  const seen = stub.writesTo(re, method);
  assert.equal(seen.length, n,
    `${what}: expected ${n} write(s) to ${re}, saw ${seen.length}` +
    (seen.length ? ` (${seen.map((w) => `${w.method} ${w.path}`).join(", ")})` : "") +
    `. All writes: ${stub.allWrites().map((w) => `${w.method} ${w.path}`).join(", ") || "none"}`);
}

/** The three browser contexts the date scenarios run under. A date is a calendar day and the two usual ways of
 *  getting it wrong are mirror images: `new Date("2026-03-31")` is UTC midnight, which is the PREVIOUS day in a
 *  zone behind UTC (Los Angeles), and `new Date(2026, 2, 31).toISOString()` is local midnight, which is the
 *  previous day in any zone AHEAD of it (Kolkata at +5:30, Kiritimati at +14). Kolkata is the product's own zone,
 *  so it is the one a developer sees; Los Angeles and Kiritimati are the two ends. A field that goes through
 *  either of those routes is wrong in at least one of the three. */
export const TZ_MATRIX = [
  { locale: "en-US", timezoneId: "America/Los_Angeles" },
  { locale: "en-IN", timezoneId: "Asia/Kolkata" },
  { locale: "en-GB", timezoneId: "Pacific/Kiritimati" },
];
