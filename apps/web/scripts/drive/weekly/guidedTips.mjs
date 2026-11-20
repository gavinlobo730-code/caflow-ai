/**
 * A GUIDED TIP IS DRAWN BESIDE THE THING IT EXPLAINS, TAKES NOTHING FROM THE PERSON, AND IS KEPT BY THE SERVER (POST-A-531),
 * driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. with tips on, the Clients screen draws the "Start with a client" tip beside the Add Client button (below it, its
 *      left edge inside the window), the button is described by the tip, nothing is dimmed or locked (the page still
 *      scrolls and the focus was not taken), "Got it" sends the tip's id once and the tip is gone; with every tip of the
 *      screen already closed on the server, none is drawn;
 *   2. tips that are off, and a state the server could not give, draw nothing; "Turn off tips" sends the switch once and
 *      the tip leaves only when the server has kept it (a refusal leaves the tip and says so);
 *   3. from the top of the page a keyboard reaches the tip straight after the skip link, Escape closes it from inside,
 *      a dialog opened over the page hides the tip while it is open, and the dashboard's last tip offers "Next" to the
 *      next screen of the tour;
 *   4. the switch in Settings shows the server's answer, a press sends it once and is shown as done only when kept, and
 *      "Show every tip again" empties the list.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { expectWrites, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "guided-tips";

const TIPS = /\/api\/guided-tips$/;
const SEEN = /\/api\/guided-tips\/seen$/;
const AGAIN = /\/api\/guided-tips\/show-again$/;

/** The server's side of one person's tips: it keeps what it is sent and answers with what it has, as the real routes do. */
function serverKeeps(env, start = { on: true, chosen: false, seen: [] }) {
  const kept = { ...start, seen: [...start.seen] };
  const state = () => ok({ on: kept.on, chosen: kept.chosen, seen: [...kept.seen] });
  env.stub.route({ method: "GET", re: TIPS, reply: state });
  env.stub.route({ method: "PUT", re: TIPS, reply: (req, body) => { kept.on = JSON.parse(body).on; kept.chosen = true; return state(); } });
  env.stub.route({ method: "POST", re: SEEN, reply: (req, body) => { const id = JSON.parse(body).tip_id; if (!kept.seen.includes(id)) kept.seen.push(id); return state(); } });
  env.stub.route({ method: "POST", re: AGAIN, reply: () => { kept.seen = []; return state(); } });
  return kept;
}

const tip = (page) => page.locator("[data-guided-tip]");
const addClient = (page) => page.locator('[data-tip="add-client"]').first();

async function atClients(env) {
  await env.page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
  await addClient(env.page).waitFor();
}

export const scenarios = [
  {
    id: "a-tip-sits-beside-its-button-and-got-it-is-kept",
    title: "the Clients tip is drawn below Add Client, describes it, locks nothing, and Got it sends its id once",
    async run(env) {
      const { page } = env;
      const kept = serverKeeps(env);
      await atClients(env);
      await tip(page).waitFor();
      assert.equal(await tip(page).getAttribute("data-guided-tip"), "add-client");
      assert.equal(await tip(page).count(), 1, "one tip at a time");
      await until(async () => (await tip(page).evaluate((el) => getComputedStyle(el).visibility)) === "visible", "the tip to be placed");
      const [button, box] = [await addClient(page).boundingBox(), await tip(page).boundingBox()];
      assert.ok(box.y >= button.y + button.height, `the tip (top ${box.y}) is not below the button (bottom ${button.y + button.height})`);
      assert.ok(box.y - (button.y + button.height) < 40, "the tip is not beside the button");
      const width = page.viewportSize().width;
      assert.ok(box.x >= 0 && box.x + box.width <= width, "the tip runs off the window");
      // The button is described by the tip's own words for as long as it is shown.
      const describedBy = await addClient(page).getAttribute("aria-describedby");
      assert.ok(describedBy, "the button is not described by its tip");
      assert.match(await page.locator(`[id="${describedBy.split(" ").pop()}"]`).innerText(), /“Add Client” creates one client/);
      // Not a modal: it says so, nothing took the focus, and nothing full-window was drawn over the page.
      assert.equal(await tip(page).getAttribute("aria-modal"), "false");
      assert.equal(await page.evaluate(() => document.activeElement === document.body || document.activeElement?.id === "main-content"), true, "the tip took the focus");
      assert.equal(await page.evaluate(() => document.body.style.overflow), "", "the page behind the tip was locked");
      await tip(page).getByRole("button", { name: "Got it" }).click();
      await tip(page).waitFor({ state: "detached" });
      await expectWrites(env.stub, SEEN, 1, "Got it");
      assert.deepEqual(kept.seen, ["add-client"]);
      assert.equal(await addClient(page).getAttribute("aria-describedby"), null, "the button is still described by a tip that is gone");
      // The server has it closed: opening the screen again draws none.
      await atClients(env);
      await page.waitForTimeout(1200);
      assert.equal(await tip(page).count(), 0, "a tip the server holds as closed was drawn again");
    },
  },
  {
    id: "tips-off-or-unread-draw-nothing-and-turning-them-off-waits-for-the-server",
    title: "off and unread draw nothing; Turn off tips is refused once (the tip stays and says so), then kept (the tip leaves)",
    async run(env) {
      const { page } = env;
      // Unread: the stub's own answer for a route nobody set is not a tips state.
      await atClients(env);
      await page.waitForTimeout(1200);
      assert.equal(await tip(page).count(), 0, "a tip was drawn from an answer that is not a tips state");
      // Off.
      const kept = serverKeeps(env, { on: false, chosen: true, seen: [] });
      await atClients(env);
      await page.waitForTimeout(1200);
      assert.equal(await tip(page).count(), 0, "a tip was drawn with tips off");
      // On, and the first Turn off is refused.
      kept.on = true;
      await atClients(env);
      await tip(page).waitFor();
      env.stub.route({ method: "PUT", re: TIPS, ...refuse("Not just now.", 503) });
      await tip(page).getByRole("button", { name: "Turn off tips" }).click();
      await tip(page).getByRole("alert").waitFor();
      assert.match(await tip(page).getByRole("alert").innerText(), /could not be saved just now, and nothing was changed/);
      assert.equal(kept.on, true);
      // Kept this time.
      env.stub.route({ method: "PUT", re: TIPS, reply: (req, body) => { kept.on = JSON.parse(body).on; kept.chosen = true; return ok({ on: kept.on, chosen: true, seen: [] }); } });
      await tip(page).getByRole("button", { name: "Turn off tips" }).click();
      await tip(page).waitFor({ state: "detached" });
      assert.equal(kept.on, false);
      await expectWrites(env.stub, TIPS, 2, "Turn off tips, twice", "PUT");
      await expectWrites(env.stub, SEEN, 0, "turning tips off closes no tip");
    },
  },
  {
    id: "a-keyboard-reaches-the-tip-and-a-dialog-hides-it",
    title: "Tab from the top reaches the tip after the skip link; a dialog hides it; Escape inside closes it; the dashboard offers Next",
    async run(env) {
      const { page } = env;
      const kept = serverKeeps(env);
      await atClients(env);
      await tip(page).waitFor();
      await page.keyboard.press("Tab");                                   // the skip link
      await page.keyboard.press("Tab");                                   // the tip's first control
      assert.equal(await page.evaluate(() => Boolean(document.activeElement?.closest("[data-guided-tip]"))), true,
        "the second Tab from the top of the page did not land in the tip");
      // A dialog over the page: the tip waits.
      await addClient(page).click();
      await page.getByRole("heading", { name: "Add New Client" }).waitFor();
      await until(async () => (await tip(page).count()) === 0, "the tip to hide while a dialog is open");
      await page.keyboard.press("Escape");
      await tip(page).waitFor();
      assert.deepEqual(kept.seen, [], "hiding a tip behind a dialog closed it");
      // Escape from inside the tip closes it.
      await tip(page).getByRole("button", { name: "Got it" }).focus();
      await page.keyboard.press("Escape");
      await tip(page).waitFor({ state: "detached" });
      await expectWrites(env.stub, SEEN, 1, "Escape inside the tip");
      // The dashboard: two tips, and the last one offers the way on.
      await page.goto(`${env.base}/`, { waitUntil: "networkidle" });
      await tip(page).waitFor();
      assert.equal(await tip(page).getAttribute("data-guided-tip"), "start-menu");
      assert.equal(await tip(page).getByRole("link").count(), 0, "Next is offered while this screen still has a tip");
      await tip(page).getByRole("button", { name: "Got it" }).click();
      await until(async () => (await tip(page).getAttribute("data-guided-tip").catch(() => null)) === "start-search", "the second tip of the dashboard");
      const next = tip(page).getByRole("link", { name: /^Next: / });
      // Clients' own tip is closed above, so the tour goes on to the next screen that still has one.
      assert.equal(await next.innerText(), "Next: deadlines");
      assert.match(await next.getAttribute("href"), /^\/deadlines\/?$/);
    },
  },
  {
    id: "the-settings-switch-is-the-servers-answer",
    title: "Settings shows the server's switch; a press is sent once and shown when kept; Show every tip again empties the list",
    async run(env) {
      const { page } = env;
      const kept = serverKeeps(env, { on: true, chosen: false, seen: ["start-menu", "start-search", "add-client"] });
      await page.goto(`${env.base}/settings/`, { waitUntil: "networkidle" });
      const card = page.locator("[data-guided-tips-card]");
      await card.waitFor();
      const toggle = card.getByRole("switch", { name: "Show guided tips" });
      assert.equal(await toggle.getAttribute("aria-checked"), "true");
      assert.match(await card.innerText(), /You have closed 3 tips/);
      await toggle.click();
      await until(async () => (await toggle.getAttribute("aria-checked")) === "false", "the switch to show off");
      assert.equal(kept.on, false);
      assert.match(await card.getByRole("status").innerText(), /Tips are off\./);
      await expectWrites(env.stub, TIPS, 1, "the switch", "PUT");
      await card.getByRole("button", { name: "Show every tip again" }).click();
      await until(async () => /have not closed any tip yet/.test(await card.innerText()), "the list to be emptied");
      assert.deepEqual(kept.seen, []);
      assert.equal(kept.on, false, "showing the tips again turned the switch");
      await expectWrites(env.stub, AGAIN, 1, "Show every tip again");
    },
  },
];
