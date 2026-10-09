/**
 * Group C: typing is not lost to a reload, and what is offered back is offered, never applied (frontend_ux-23).
 *
 * The journal editor and the purchase bill editor keep an UNSENT DRAFT in `sessionStorage` while a form is dirty
 * (`lib/drafts/unsentDraft`), warn with the browser's own leave-site prompt when the page is closed or reloaded
 * over unsaved work, and on the next visit OFFER the draft in a banner. The rules a source guard can state but not
 * see work: the banner appears, Restore fills the fields, Discard really discards, a successful save clears the
 * draft, a REFUSED save keeps it (the work is not saved, so it must not be lost), and a form nobody touched
 * raises no prompt at all.
 *
 * A reload while dirty raises a native `beforeunload` dialog. The runner accepts it (a dialog nobody answers
 * hangs the reload) and records that it happened in `env.natives`; any other native dialog fails the scenario.
 */
import assert from "node:assert/strict";
import { pick } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "drafts";

const DRAFT_KEYS = (page) =>
  page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith("ps:draft:v1")));

/** Wait for the editor's debounced draft write: the key appears once the form has been dirty a moment. */
async function waitForDraft(page) {
  await page.waitForFunction(
    () => Object.keys(sessionStorage).some((k) => k.startsWith("ps:draft:v1")), null, { timeout: 8000 });
}

// ── the journal editor ──────────────────────────────────────────────────────────────────────────────────

async function openJournal({ page, at }) {
  await page.goto(at("/accounting/journal/new/edit/"), { waitUntil: "networkidle" });
  await page.waitForSelector("#je-narration");
}
async function dirtyJournal(page) {
  await page.fill("#je-narration", "Rent for October");
  await page.locator('input[aria-label="Debit"]').first().fill("45000");
  await waitForDraft(page);
}
const JOURNAL_BANNER = "Restore your unsaved journal entry?";

// ── the purchase bill editor ────────────────────────────────────────────────────────────────────────────

async function openBill({ page, at }) {
  await page.goto(at("/purchases/bills/new/edit/"), { waitUntil: "networkidle" });
  await page.waitForSelector('button[aria-label="Vendor"]');
}
async function dirtyBill(page) {
  await pick(page, page.locator('button[aria-label="Vendor"]'), "Gamma Supplies");
  await page.fill('input[placeholder="INV-001"]', "GS/2026/114");
  await waitForDraft(page);
}
const BILL_BANNER = "Restore your unsaved purchase bill?";

export const scenarios = [
  {
    id: "journal-reload-offers-restore",
    title: "a reload over a dirty journal warns, then offers the draft; Restore fills the fields",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await dirtyJournal(page);
      await page.reload({ waitUntil: "networkidle" });
      assert.ok(env.natives.includes("beforeunload"), "reloading a dirty form raised no leave-site prompt");
      await page.waitForSelector("#je-narration");
      await page.getByText(JOURNAL_BANNER).waitFor();
      assert.equal(await page.inputValue("#je-narration"), "", "the draft was APPLIED on load: it must only be offered");
      await page.getByRole("button", { name: "Restore draft" }).click();
      assert.equal(await page.inputValue("#je-narration"), "Rent for October");
      assert.equal(await page.locator('input[aria-label="Debit"]').first().inputValue(), "45000");
    },
  },
  {
    id: "journal-discard-really-discards",
    title: "Discard it removes the draft: the next reload offers nothing",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await dirtyJournal(page);
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText(JOURNAL_BANNER).waitFor();
      await page.getByRole("button", { name: "Discard it" }).click();
      assert.deepEqual(await DRAFT_KEYS(page), [], "Discard left the draft in sessionStorage");
      await page.reload({ waitUntil: "networkidle" });
      await page.waitForSelector("#je-narration");
      assert.equal(await page.getByText(JOURNAL_BANNER).count(), 0, "the draft came back after Discard");
    },
  },
  {
    id: "journal-restored-but-unsaved-is-offered-again",
    title: "a draft that was restored and not saved is still there on the next reload",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await dirtyJournal(page);
      await page.reload({ waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Restore draft" }).click();
      await waitForDraft(page);
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText(JOURNAL_BANNER).waitFor();
    },
  },
  {
    id: "journal-save-clears-the-draft",
    title: "a successful save clears the draft; a refused one keeps it",
    async run(env) {
      const { page, stub } = env;
      await openJournal(env);
      await page.fill("#je-narration", "Being cash sale");
      await pick(page, page.locator("#je-account-l0"), "Cash in Hand");
      await page.locator('input[aria-label="Debit"]').first().fill("125000");
      await pick(page, page.locator("#je-account-l1"), "Sales");
      await waitForDraft(page);
      // Refused first: the work is not saved, so the draft has to survive it.
      stub.route({ method: "POST", re: /accounting\/journal$/, ...refuse("Refused for the drive") });
      await page.getByRole("button", { name: "Post Entry" }).click();
      await page.getByText("Refused for the drive").first().waitFor({ timeout: 6000 });
      assert.equal((await DRAFT_KEYS(page)).length, 1, "a REFUSED save cleared the draft: the typed work is gone");
      // Then accepted.
      stub.route({ method: "POST", re: /accounting\/journal$/, reply: () => ok({ id: "j-1" }) });
      await page.getByRole("button", { name: "Post Entry" }).click();
      await page.waitForFunction(
        () => !Object.keys(sessionStorage).some((k) => k.startsWith("ps:draft:v1")), null, { timeout: 8000 });
    },
  },
  {
    id: "journal-clean-form-raises-no-prompt",
    title: "reloading a form nobody typed in raises no leave-site prompt",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await page.waitForTimeout(500);
      await page.reload({ waitUntil: "networkidle" });
      assert.deepEqual(env.natives, [], "a clean form asked the person to confirm leaving");
      assert.deepEqual(await DRAFT_KEYS(page), []);
    },
  },
  {
    id: "bill-reload-offers-restore",
    title: "a reload over a dirty purchase bill warns, then offers the draft; Restore refills the fields",
    async run(env) {
      const { page } = env;
      await openBill(env);
      await dirtyBill(page);
      await page.reload({ waitUntil: "networkidle" });
      assert.ok(env.natives.includes("beforeunload"), "reloading a dirty bill raised no leave-site prompt");
      await page.getByText(BILL_BANNER).waitFor();
      assert.equal(await page.inputValue('input[placeholder="INV-001"]'), "", "the draft was APPLIED on load");
      await page.getByRole("button", { name: "Restore draft" }).click();
      assert.equal(await page.inputValue('input[placeholder="INV-001"]'), "GS/2026/114");
    },
  },
  {
    id: "bill-discard-really-discards",
    title: "Discard it removes the bill draft: the next reload offers nothing",
    async run(env) {
      const { page } = env;
      await openBill(env);
      await dirtyBill(page);
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText(BILL_BANNER).waitFor();
      await page.getByRole("button", { name: "Discard it" }).click();
      await page.reload({ waitUntil: "networkidle" });
      await page.waitForSelector('button[aria-label="Vendor"]');
      assert.equal(await page.getByText(BILL_BANNER).count(), 0, "the bill draft came back after Discard");
    },
  },
  {
    id: "bill-save-clears-the-draft",
    title: "a saved purchase bill clears its draft; a refused save keeps it",
    async run(env) {
      const { page, stub } = env;
      await openBill(env);
      await dirtyBill(page);
      await pick(page, page.locator('button[aria-label="Line 1 product or service"]'), "Consulting");
      stub.route({ method: "POST", re: /purchase-bills\/$/, ...refuse("Bill refused for the drive") });
      await page.getByRole("button", { name: "Save Draft" }).click();
      await page.getByText("Bill refused for the drive").first().waitFor({ timeout: 6000 });
      assert.equal((await DRAFT_KEYS(page)).length, 1, "a REFUSED save cleared the bill draft");
      stub.route({ method: "POST", re: /purchase-bills\/$/, reply: () => ok({ id: "b-new" }) });
      await page.getByRole("button", { name: "Save Draft" }).click();
      await page.waitForFunction(
        () => !Object.keys(sessionStorage).some((k) => k.startsWith("ps:draft:v1")), null, { timeout: 8000 });
    },
  },
];
