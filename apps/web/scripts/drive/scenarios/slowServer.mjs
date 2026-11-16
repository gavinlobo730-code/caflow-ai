/**
 * Group: slow-server. A placeholder a screen draws itself says when the server may be waking up (POST-A-147).
 *
 * The shared skeletons have said it since frontend_ux-05 (the smoke walk's `slowServerScenario` holds them); a screen that drew its
 * own placeholder said nothing however long it waited, and those were the screens a demo opens first. Each scenario holds one read
 * past the three seconds the notice waits, and finds the sentence INSIDE the screen's own region (named for what it loads), never
 * more than once on the page, and gone with the answer:
 *
 *   1. the hub on the firm's home dashboard (its fifteen tiles were a grid of hand-made pulsing blocks);
 *   2. a client's Schedule III ratios (a spinner and "Computing both years…").
 */
import assert from "node:assert/strict";
import { CLIENT_ROW } from "../fixtures.mjs";
import { ok } from "../stub.mjs";
import { WAKING_SENTENCE } from "../../walkAudits.mjs";

export const group = "slow-server";

/** Held past the notice's three seconds and well short of its twenty-second Retry, which a LoadingRegion never offers anyway. */
const HELD_MS = 5_000;

async function saidInsideThenGone(page, region, released) {
  // What a person sees first: the sentence, somewhere on the page, while the read is held. Then that it is the screen's own region
  // that says it, not some other placeholder that happens to be pending beside it.
  await page.getByText(WAKING_SENTENCE).first().waitFor({ timeout: HELD_MS - 500 })
    .catch(() => { throw new Error(`nothing on the page said "${WAKING_SENTENCE}" while the read was held`); });
  assert.equal(await region.count(), 1, "the screen's own placeholder is not a named loading region");
  assert.equal(await region.getByText(WAKING_SENTENCE).count(), 1, "the sentence was said, but not by the screen's own region");
  assert.equal(await page.getByText(WAKING_SENTENCE).count(), 1, "the sentence was said more than once on the page");
  assert.equal(await region.getByRole("button", { name: "Retry" }).count(), 0, "a screen's own placeholder offers no Retry");
  await released();
  await region.waitFor({ state: "detached", timeout: HELD_MS + 4000 });
  assert.equal(await page.getByText(WAKING_SENTENCE).count(), 0, "the sentence outlived the wait");
}

export const scenarios = [
  {
    id: "the-home-dashboards-hub-says-the-server-is-waking-up-while-it-reads",
    title: "the hub's placeholder on the home dashboard says the server may be waking up after three seconds, and goes with the answer",
    async run({ page, stub, base }) {
      let answered = false;
      stub.route({ method: "GET", re: /\/api\/hub(\?|$)/, delay: HELD_MS, reply: () => { answered = true; return ok({ tiles: [] }); } });
      await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
      await saidInsideThenGone(page, page.getByRole("status", { name: "Loading the hub" }), async () => {
        for (let i = 0; i < 100 && !answered; i += 1) await new Promise((r) => setTimeout(r, 100));
      });
    },
  },
  {
    id: "a-clients-ratios-say-the-server-is-waking-up-while-both-years-are-computed",
    title: "the ratios screen's 'Computing both years…' says the server may be waking up after three seconds, and goes with the answer",
    async run({ page, stub, at }) {
      let answered = false;
      stub.route({ method: "GET", re: /\/api\/clients\/[^/?]+(\?|$)/, reply: () => ok(CLIENT_ROW) });
      stub.route({
        method: "GET", re: /\/api\/accounting\/schedule-iii\/ratios\?/, delay: HELD_MS,
        reply: () => { answered = true; return ok({ ratios: [], current_fy: "2025-26", previous_fy: "2024-25", gaps: [] }); },
      });
      await page.goto(at("/reports/ratios/"), { waitUntil: "domcontentloaded" });
      await saidInsideThenGone(page, page.getByRole("status", { name: "Computing both years" }), async () => {
        for (let i = 0; i < 100 && !answered; i += 1) await new Promise((r) => setTimeout(r, 100));
      });
    },
  },
];
