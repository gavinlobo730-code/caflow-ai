/**
 * Group L: every control a person fills in on the two income-tax screens whose date boxes were converted has a name a screen
 * reader can say (POST-A-126, driven in a browser).
 *
 * The nightly axe walk holds a per-route baseline (`scripts/axe-baseline.json`), and a violation that has been fixed must delete
 * its own line in the commit that fixes it, or the walk fails the next night as "no longer fires". Axe is not installed on the
 * machines this is built on, so the claim "these screens no longer have an unlabelled date box" is checked here with the rule axe's
 * `label` check applies: a form control (not hidden, not a button) is named by an `aria-label`, an `aria-labelledby`, a `<label for>`
 * naming its id, a `<label>` around it, a `title`, or (axe 4.8 and later) a non-empty placeholder.
 */
import assert from "node:assert/strict";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "labels";

/** The controls of the page that axe's `label` rule would flag, each as a short description. */
async function unnamedControls(page, { placeholderNames = true } = {}) {
  return page.evaluate((placeholderNames) => {
    const out = [];
    for (const el of document.querySelectorAll("input, select, textarea")) {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (["hidden", "button", "submit", "reset", "image"].includes(type)) continue;
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || el.closest("[hidden]")) continue;
      const named =
        (el.getAttribute("aria-label") || "").trim() ||
        (el.getAttribute("aria-labelledby") || "").trim() ||
        (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) ||
        el.closest("label") ||
        (el.getAttribute("title") || "").trim() ||
        (placeholderNames && (el.getAttribute("placeholder") || "").trim());
      if (!named) out.push(`${el.tagName.toLowerCase()}${type ? `[type=${type}]` : ""}${el.id ? `#${el.id}` : ""} ${(el.className || "").toString().slice(0, 40)}`);
    }
    return out;
  }, placeholderNames);
}

export const scenarios = [
  {
    id: "the-advance-tax-screen-has-no-unnamed-control",
    title: "the advance-tax screen, with a client chosen and an estimate typed, has no form control a screen reader would call 'edit text'",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
      await page.getByPlaceholder("Enter tax amount").fill("100000");
      await page.getByLabel("Instalment 1 paid on").waitFor();
      assert.deepEqual(await unnamedControls(page), [], "an unnamed control is on the advance-tax screen");
      // …and as the nightly walk sees it, with no client chosen: the return-furnished box was the one unlabelled control there (axe's
      // `label` baseline line for this route), and it is named now.
      await page.goto(`${env.base}/income-tax/advance-tax/`, { waitUntil: "networkidle" });
      assert.deepEqual(await unnamedControls(page), [], "an unnamed control is on the advance-tax screen as the walk sees it");
    },
  },
  {
    id: "the-capital-gains-screen-has-no-unnamed-control",
    title: "the capital-gains calculator has no form control a screen reader would call 'edit text'",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/income-tax/capital-gains/`, { waitUntil: "networkidle" });
      // The one `select` without a name is the walk's `select-name` baseline line for this route, a separate rule with a separate fix;
      // the calculator's two date boxes were its `label` line and are named now.
      const unnamed = (await unnamedControls(page)).filter((c) => !c.startsWith("select"));
      assert.deepEqual(unnamed, [], "an unnamed input is on the capital-gains screen");
    },
  },
];
