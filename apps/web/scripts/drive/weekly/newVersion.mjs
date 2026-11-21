/**
 * A TAB LEARNS THAT A NEWER BUILD IS LIVE, SAYS SO ONCE, AND LOADS IT ONLY AT THE PERSON'S OWN MOVE (POST-A-529),
 * driven in a browser.
 *
 * Against the built site, with the pinned clock moved by the scenario and the live site's answer to /version.json stubbed:
 *
 *   1. nothing is asked in the tab's first seconds; a first look that finds the tab's own build draws nothing; an answer
 *      that is not the file (other JSON, a page of HTML) draws nothing; a newer build draws the card once, in the same
 *      document (nothing was reloaded), and the tab stops asking;
 *   2. moving to another screen loads the new build by itself, once: the document is new and the tab remembers which
 *      build it loaded for. While a cache still serves the old build the card comes back, and the NEXT move does not
 *      reload again; "Load it now" does.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { until } from "../kit.mjs";

export const group = "new-version";

const VERSION = /\/version\.json(\?.*)?$/;
const NEWER = "0123abc0123abc0123abc0123abc0123abc01234";
const here = path.dirname(fileURLToPath(import.meta.url));

/** The id of the build being driven, read from the file the build wrote. */
function builtVersion() {
  const file = path.join(here, "..", "..", "..", "out", "version.json");
  assert.ok(fs.existsSync(file), "the build wrote no out/version.json: was it built with `npm run build`?");
  return JSON.parse(fs.readFileSync(file, "utf8")).version;
}

const region = (page) => page.locator("[data-new-version]");
const json = (version) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ version }) });
const sameDocument = (page) => page.evaluate(() => window.__newVersionScenario === true);

/** The live site's side of the file: it answers what it is told to and counts the asks. */
async function liveSiteAnswers(page, first) {
  const live = { answer: first, asked: 0 };
  await page.route(VERSION, (route) => { live.asked += 1; return route.fulfill(live.answer()); });
  return live;
}

// THE CLOCK. The drive pins `Date` for every scenario and leaves the timers real, so the tab's slow beat would take real
// minutes. The scenarios move the pinned time themselves and bring the tab "back to the front" (the event a browser sends
// when a person returns to a tab), which is the rule's other way of looking; the beat itself is the rule's own unit test.
const AFTER_OPENING = 31_000;
const AWAY = 61_000;

async function comeBackAfter(env, ms) {
  const now = await env.page.evaluate(() => Date.now());
  await env.page.context().clock.setFixedTime(new Date(now + ms));
  await env.page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
}

// The service worker answers a page's requests itself once it is in control, and a request it makes is not one this
// scenario can answer for the live site. So these two scenarios do not let it register (the page's own registration call
// is answered and does nothing); what the worker does with the file is held by
// `scripts/a-tab-learns-that-a-newer-build-is-live.test.ts`.
async function withoutTheServiceWorker(page) {
  await page.addInitScript(() => {
    if (navigator.serviceWorker) navigator.serviceWorker.register = () => new Promise(() => {});
  });
}

export const scenarios = [
  {
    id: "a-tab-is-told-once-and-only-by-a-real-answer",
    title: "the first look is not at once; the tab's own build, a file that is not the one expected and a page of HTML say nothing; a newer build draws the card once and the tab stops asking",
    async run(env) {
      const { page } = env;
      const mine = builtVersion();
      const live = await liveSiteAnswers(page, () => json(mine));
      await withoutTheServiceWorker(page);
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await region(page).waitFor({ state: "attached" });
      await page.evaluate(() => { window.__newVersionScenario = true; });
      await comeBackAfter(env, 5_000);
      await page.waitForTimeout(300);
      assert.equal(live.asked, 0, "the file was asked for in the tab's first seconds");
      await comeBackAfter(env, AFTER_OPENING);
      await until(() => live.asked === 1, "the first look");
      assert.equal(await region(page).getAttribute("data-new-version"), "none", "the tab's own build was drawn as news");
      // Back again a moment later: not asked twice in a row.
      await comeBackAfter(env, 5_000);
      await page.waitForTimeout(300);
      assert.equal(live.asked, 1, "the file was asked for again seconds after a look");

      // (An answer the browser itself calls a failure, a 503 or no answer at all, cannot be driven here: the drive fails any
      // scenario whose page logs a failed request. That branch is two lines the wiring test reads.)
      live.answer = () => ({ status: 200, contentType: "application/json", body: JSON.stringify({ build: "something else" }) });
      await comeBackAfter(env, AWAY);
      await until(() => live.asked === 2, "the second look");
      live.answer = () => ({ status: 200, contentType: "text/html", body: "<!doctype html><title>Not the file</title>" });
      await comeBackAfter(env, AWAY);
      await until(() => live.asked === 3, "the third look");
      await page.waitForTimeout(300);
      assert.equal(await region(page).getAttribute("data-new-version"), "none", "an answer that is not the file was drawn as news");

      live.answer = () => json(NEWER);
      await comeBackAfter(env, AWAY);
      await until(async () => (await region(page).getAttribute("data-new-version")) === "ready", "the card");
      const words = await region(page).innerText();
      assert.match(words, /A newer version of PracticeSync is ready/);
      assert.match(words, /next time you move to another screen/);
      assert.doesNotMatch(words, new RegExp(`${NEWER}|${mine}`), "a build id is drawn to a person");
      assert.equal(await region(page).getByRole("button", { name: "Load it now" }).count(), 1);
      assert.equal(await sameDocument(page), true, "the tab was reloaded without the person moving");
      // Told once: the tab stops asking, and nothing reloads it while the person stays on the screen.
      const asked = live.asked;
      await comeBackAfter(env, 10 * AWAY);
      await page.waitForTimeout(400);
      assert.equal(live.asked, asked, "a tab that knows went on asking");
      assert.equal(await sameDocument(page), true, "the tab was reloaded while the person stayed on the screen");
    },
  },
  {
    id: "the-new-build-loads-at-the-next-move-once",
    title: "moving to another screen loads the new build once; while the old build is still served the card returns and the next move does not reload; the button does",
    async run(env) {
      const { page } = env;
      await liveSiteAnswers(page, () => json(NEWER));
      await withoutTheServiceWorker(page);
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await region(page).waitFor({ state: "attached" });
      await comeBackAfter(env, AFTER_OPENING);
      await until(async () => (await region(page).getAttribute("data-new-version")) === "ready", "the card");
      await page.evaluate(() => { window.__newVersionScenario = true; });

      // The person moves: the bar's own link to Settings.
      await page.locator('a[href="/settings/"], a[href="/settings"]').first().click();
      await page.waitForURL(/\/settings\/?$/);
      await until(async () => (await sameDocument(page).catch(() => true)) === false, "the new build to load after the move");
      await page.waitForLoadState("networkidle");
      assert.equal(await page.evaluate((key) => window.sessionStorage.getItem(key), "practicesync_new_version_loaded_for"), NEWER);

      // This build is still the old one (the scenario serves it), so the tab is told again, and a move does not reload twice.
      await region(page).waitFor({ state: "attached" });
      await page.evaluate(() => { window.__newVersionScenario = true; });
      await comeBackAfter(env, AFTER_OPENING);
      await until(async () => (await region(page).getAttribute("data-new-version")) === "ready", "the card after the load");
      await page.evaluate(() => window.next.router.push("/clients/"));
      await page.waitForURL(/\/clients\/?$/);
      await page.waitForTimeout(800);
      assert.equal(await sameDocument(page), true, "the tab reloaded a second time for the same build");
      assert.equal(await region(page).getAttribute("data-new-version"), "ready", "the card went away with the old build still running");

      // The button is the person's own way.
      await region(page).getByRole("button", { name: "Load it now" }).click();
      await until(async () => (await sameDocument(page).catch(() => true)) === false, "the load after the button");
    },
  },
];
