/**
 * THE GST AND MCA TRACKERS' PROMPTS FOR SEVERAL ROWS, OPENED FOR THEIR OWN SAKE (POST-A-555, third part).
 *
 * POST-A-130 moved every hand-built pop-up onto the shared dialog. Most were then opened in a browser; some were read, type-checked and
 * left standing on the shared piece's own drive. These two are opened by the nightly set for another reason (that they are held while the
 * filings are out), which is not this check. Here each is opened for the contract every dialog owes a person on a keyboard or a screen
 * reader:
 *
 *   its name is announced (a dialog named "Mark … as Filed"), it says it is modal, the page behind it cannot scroll, its buttons are
 *   inside it, Tab and Shift+Tab stay inside, Escape closes it, the page gets its scroll back, and the keyboard is handed back.
 *
 * WHAT THE DRIVE FOUND. Handed back to whom? The button that opens these prompts lives in the table's bulk bar, and the table takes the bar
 * away as soon as the action has run (the ticked rows are consumed while the prompt is still open). So when the prompt closed, by Cancel as
 * much as by Confirm, the opener was gone, `focus()` on it did nothing, and the keyboard fell to the top of the document: "Skip to content"
 * and the whole shell again, and nothing announced. That is true of every bulk action that opens a dialog. The shared dialog now hands the
 * keyboard to the page's main region when its opener has left the page (`giveFocusBack`, lib/ui/focusTrap.ts), and these two hold it.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { openGstTracker, openMcaTracker } from "../scenarios/dates.mjs";

export const group = "several-row-prompts";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

async function tabStaysInside(page, dialog, n, what) {
  await until(() => focusInside(dialog), `focus to be inside ${what}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await focusInside(dialog), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

const PROMPTS = [
  { tracker: "GST", open: openGstTracker("batch"), name: /^Mark 1 Filing as Filed$/, buttons: ["Cancel"], confirm: /^Confirm 1 Filing$/ },
  { tracker: "MCA", open: openMcaTracker("batch"), name: "Mark ROC Filings as Filed", buttons: ["Cancel"], confirm: /^Confirm 1 Filing$/ },
];

export const scenarios = PROMPTS.map((t) => ({
  id: `the-${t.tracker.toLowerCase()}-trackers-prompt-for-several-rows-is-a-named-dialog-that-keeps-the-keyboard-and-gives-focus-back`,
  title: `${t.tracker} tracker > Mark Filed (several rows): a named modal dialog with its buttons inside, Tab kept inside, the page locked, Escape closes it and the keyboard lands on the page\u2019s main region, not at the top of the document`,
  async run(env) {
    const { page } = env;
    await t.open(env);
    const dialog = page.getByRole("dialog", { name: t.name });
    await dialog.waitFor();
    assert.equal(await page.getByRole("dialog").count(), 1, `${t.tracker}: more than one dialog is open`);
    assert.equal(await dialog.getAttribute("aria-modal"), "true", `${t.tracker}: the prompt does not say it is modal`);
    assert.equal(await pageLocked(page), "hidden", `${t.tracker}: the page behind the prompt can still scroll`);
    for (const name of t.buttons) {
      assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${t.tracker}: ${name} is not inside the dialog`);
    }
    assert.equal(await dialog.getByRole("button", { name: t.confirm }).count(), 1, `${t.tracker}: the button that records the filings is not inside the dialog`);
    assert.match(await dialog.innerText(), /CA Confirmation Required/i, `${t.tracker}: the prompt lost its warning that nothing is submitted to the portal`);
    await tabStaysInside(page, dialog, 8, `the ${t.tracker} prompt for several rows`);
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "detached" });
    assert.equal(await pageLocked(page), "", `${t.tracker}: the page is still locked after the prompt closed`);
    // The table takes the bulk bar away as soon as the action has run (the ticked rows are consumed while the prompt is still open), so the
    // button that opened the prompt is gone when it closes. The keyboard must not fall to the top of the document: it lands on the page's
    // main region, from where Tab reaches the tracker, and never on the body.
    const landed = await page.evaluate(() => ({ tag: document.activeElement?.tagName ?? "", id: document.activeElement?.id ?? "" }));
    assert.notEqual(landed.tag, "BODY", `${t.tracker}: the keyboard fell to the top of the document when the prompt closed`);
    assert.equal(landed.id, "main-content", `${t.tracker}: focus did not land on the page's main region (it is on <${landed.tag.toLowerCase()} id="${landed.id}">)`);
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => !!document.activeElement?.closest("main")), true, `${t.tracker}: the next Tab did not stay in the page's own content`);
  },
}));
