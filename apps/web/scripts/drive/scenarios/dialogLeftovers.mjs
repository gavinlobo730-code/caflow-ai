/**
 * Group: the dialog, control and wording leftovers of the date drive (POST-A-395), each driven in a browser.
 *
 *   1. the engagement template dialog holds Close and Cancel while its Save is out, and the engagement detail dialog holds its Close and the
 *      open step's Cancel while Confirm Signed is out: a press of either used to close the dialog over a request that then landed on nothing;
 *   2. (a source guard, not here: the page's JSON helper is bounded at 45 seconds, `lib/api`'s bound, so a hung answer frees them);
 *   3. the icon-only buttons have names a screen reader says: the template and detail dialogs' Close, a band's remove on the statutory values screen;
 *   4. the New lot card scrolls, so on a window 320 pixels tall its Create button is on the screen;
 *   5. the GST and MCA trackers' Add Filing forms keep Save on a window 700 pixels tall (measured, where the ledger had it from the CSS);
 *   6. a bulk Mark Filed on Deadlines holds its Cancel while the filings are out, and one that fails for one row comes back narrowed to that row, with the
 *      server's sentence and the date it was tried with (the date was found kept already: the row holds it);
 *   7. the advance-tax register says a date's sentence once after Save, not twice;
 *   9. a recurring journal's history opens the generated entry, not the client's whole journal list;
 *  10. a client's MCA page prints its dates through the one date module (15 Apr 2024), never the stored 2024-04-15;
 *  11. the supplier form's Cancel and a row's Edit are held while its Save is out;
 *  13. a row menu near the foot of the window opens upwards, so its Edit is on the screen.
 *
 * Point 8 (the date box takes in a value its parent changes before the paint) is held by components/ui/date-input.test.ts and by the whole
 * date group, which is what it changes under; point 12 was closed by POST-A-381 and has its rows in dates.mjs.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID, VENDOR } from "../fixtures.mjs";
import {
  atClientMca, openAdvanceTaxRegister, openGstTracker, openMcaTracker, openNewEngagementLetter, openStatutoryValues, openStockLocations, typeAndLeave,
} from "./dates.mjs";

export const group = "dialog-leftovers";

const overlayWith = (page, heading) => page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: heading }) }).last();

/** Whether the whole of `locator` is inside the window (a button cut off at the foot is not a button anyone can press without scrolling). */
async function insideTheWindow(page, locator) {
  const box = await locator.boundingBox();
  const view = page.viewportSize();
  return Boolean(box && view && box.y >= 0 && box.y + box.height <= view.height && box.x >= 0 && box.x + box.width <= view.width);
}

const SENT_LETTER = {
  id: "en-9", engagement_number: "ENG-0009", title: "Statutory audit FY 2026-27", status: "Sent", fee_amount_paise: 15000000, recipient_name: "Acme Traders",
  recipient_email: "accounts@acme.example", lead_id: null, client_id: null, template_id: null, content: "", start_date: null, expiry_date: null,
  sent_at: "2026-10-01T05:00:00Z", last_sent_at: "2026-10-01T05:00:00Z", resend_count: 0, signed_at: null, signed_by_name: null, rejected_at: null,
  rejection_notes: null, sign_token: null, created_at: "2026-09-30T05:00:00Z",
};

export const scenarios = [
  {
    id: "the-engagement-template-dialog-holds-close-and-cancel-while-its-save-is-out",
    title: "Engagements > Templates > New Template: while Save is out, Close (named) and Cancel are held and Escape does not close it; it closes when the answer lands",
    async run(env) {
      const { page, stub } = env;
      await openNewEngagementLetter(env);
      await page.keyboard.press("Escape");
      stub.route({ method: "POST", re: /api\/engagement-letters\/templates$/, reply: (_req, raw) => ok({ template: { id: "t-1", ...JSON.parse(raw), is_default: false } }) });
      await page.getByRole("button", { name: "Templates", exact: true }).click();
      await page.getByRole("button", { name: "New Template", exact: true }).first().click();
      const dialog = overlayWith(page, "New Template");
      await dialog.getByLabel("Template Name", { exact: true }).fill("Standard GST letter");
      await dialog.getByLabel("Template Content", { exact: true }).fill("Dear {{client_name}}, ...");
      await dialog.getByRole("button", { name: "Save Template" }).click();
      const close = dialog.getByRole("button", { name: "Close", exact: true });
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await until(async () => (await close.isDisabled()) && (await cancel.isDisabled()), "Close and Cancel to be held while Save is out", 3000);
      await page.keyboard.press("Escape");
      assert.equal(await dialog.count(), 1, "Escape closed the dialog over a Save still in flight");
      await stub.quiet();
      await until(async () => (await page.getByRole("heading", { name: "New Template" }).count()) === 0, "the dialog to close when the Save was answered");
      assert.equal(stub.writesTo(/engagement-letters\/templates$/, "POST").length, 1, "the template was not written exactly once");
    },
  },
  {
    id: "the-engagement-detail-dialog-holds-its-close-while-a-step-is-out",
    title: "Engagements > a sent letter > Mark as Signed > Confirm Signed: while it is out, the dialog's Close (named) and the step's Cancel are held",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { engagements: ["read", "write"], engagement: ["read", "write"], billing: ["read", "write"] } }) });
      stub.route({ method: "GET", re: /api\/engagement-letters$/, reply: () => ok({ engagements: [SENT_LETTER] }) });
      stub.route({ method: "GET", re: /api\/engagement-letters\/templates$/, reply: () => ok({ templates: [] }) });
      stub.route({ method: "POST", re: /api\/engagement-letters\/en-9\/sign$/, reply: () => ok({ engagement: { ...SENT_LETTER, status: "Signed", signed_at: "2026-10-08T06:00:00Z" } }) });
      await page.goto(`${env.base}/engagements/`, { waitUntil: "networkidle" });
      await page.getByText("Statutory audit FY 2026-27").first().click();
      const dialog = overlayWith(page, "Statutory audit FY 2026-27");
      await dialog.getByRole("button", { name: /Mark as Signed/ }).click();
      await dialog.getByRole("button", { name: /Confirm Signed/ }).click();
      const close = dialog.getByRole("button", { name: "Close", exact: true });
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await until(async () => (await close.isDisabled()) && (await cancel.isDisabled()), "the dialog's Close and the step's Cancel to be held while Confirm Signed is out", 3000);
      await stub.quiet();
      assert.equal(stub.writesTo(/en-9\/sign$/, "POST").length, 1, "the signing was not recorded exactly once");
      await until(async () => !(await close.isDisabled()), "Close to be offered again once the answer landed");
    },
  },
  {
    id: "a-bands-remove-button-on-the-statutory-values-screen-has-a-name",
    title: "Settings > Statutory values > Record a notification: each band's remove button is named for its band",
    async run(env) {
      const { page } = env;
      await openStatutoryValues(env);
      await page.getByRole("button", { name: "+ band", exact: true }).click();
      assert.equal(await page.getByRole("button", { name: "Remove band 1", exact: true }).count(), 1, "the first band's remove button has no name");
      assert.equal(await page.getByRole("button", { name: "Remove band 2", exact: true }).count(), 1, "the second band's remove button has no name");
      assert.equal(await page.getByRole("button", { name: "Close", exact: true }).count(), 1, "the dialog's close has no name");
    },
  },
  {
    id: "the-new-lot-card-scrolls-so-its-buttons-are-on-a-short-window",
    title: "Inventory > Add lot on a window 320 pixels tall: the card is bounded by the window and Create and Cancel are on the screen",
    async run(env) {
      const { page } = env;
      await page.setViewportSize({ width: 1440, height: 320 });
      await openStockLocations("lot")(env);
      const dialog = overlayWith(page, "New lot");
      for (const name of ["Create", "Cancel"]) {
        assert.ok(await insideTheWindow(page, dialog.getByRole("button", { name, exact: true })), `the New lot dialog's ${name} is off the screen on a window 320 pixels tall`);
      }
    },
  },
  ...[
    { tracker: "GST", open: openGstTracker("add"), heading: "Add GST Filing", save: "Save Filing" },
    { tracker: "MCA", open: openMcaTracker("add"), heading: "Add MCA Filing", save: "Add Filing" },
  ].map((t) => ({
    id: `the-${t.tracker.toLowerCase()}-trackers-add-filing-keeps-save-on-a-700-pixel-window`,
    title: `${t.tracker} tracker > Add Filing on a window 700 pixels tall: Save and Cancel are on the screen without scrolling the card, and the close is named`,
    async run(env) {
      const { page } = env;
      await page.setViewportSize({ width: 1440, height: 700 });
      await t.open(env);
      const dialog = overlayWith(page, t.heading);
      for (const name of [t.save, "Cancel"]) {
        assert.ok(await insideTheWindow(page, dialog.getByRole("button", { name, exact: true }).last()), `${t.tracker}: the Add Filing form's ${name} is off the screen on a window 700 pixels tall`);
      }
      assert.equal(await dialog.getByRole("button", { name: "Close", exact: true }).count(), 1, `${t.tracker}: the Add Filing form's close has no name`);
    },
  })),
  {
    id: "a-bulk-mark-filed-that-fails-for-one-row-comes-back-with-the-date-it-was-tried-with",
    title: "Deadlines > two rows > Mark Filed, one refused: Cancel is held while it is out, the prompt comes back for that row with the server's sentence and the date typed, and Confirm sends it again",
    async run(env) {
      const { page, stub } = env;
      const ob = (id, label) => ({ id, client_id: CLIENT_ID, compliance_type: "GSTR-3B", obligation_type: "GSTR3B", status: "Ready To File", period_start: "2026-09-01",
        period_end: "2026-09-30", due_date: "2026-10-20", filed_date: null, acknowledgement_no: null, notes: null, period_label: label });
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { compliance: ["read", "write", "approve"] } }) });
      stub.route({ method: "GET", re: /compliance\/reopenable-types$/, reply: () => ok({ obligation_types: [], max_reason_chars: 500 }) });
      stub.route({ method: "GET", re: /compliance\/obligations(\?|$)/, reply: () => ok({ obligations: [ob("ob-1", "GSTR-3B September 2026"), ob("ob-2", "GSTR-1 September 2026")], total: 2 }) });
      stub.route({ method: "POST", re: /compliance\/obligations\/ob-1\/mark-filed$/, reply: () => ok({ id: "ob-1", status: "Filed" }) });
      stub.route({ method: "POST", re: /compliance\/obligations\/ob-2\/mark-filed$/, ...refuse("This return is already recorded as filed on another obligation.") });
      await page.goto(`${env.base}/deadlines/`, { waitUntil: "networkidle" });
      const boxes = page.locator("tbody tr input[type=checkbox]");
      await boxes.first().waitFor({ timeout: 6000 }).catch(async () => {
        throw new Error(`no row to tick; the page says ${(await page.locator("main").innerText()).replace(/\s+/g, " ").slice(0, 600)}`);
      });
      await boxes.nth(0).check();
      await boxes.nth(1).check();
      await page.getByRole("button", { name: "Mark Filed", exact: true }).first().click();
      const prompt = page.getByRole("dialog").last();
      await typeAndLeave(prompt.locator("#mark-filed-date"), "07/10/2026");
      await prompt.getByRole("button", { name: "Confirm Filed", exact: true }).click();
      // The prompt's Cancel is held while the filings are out: pressed, it closed the prompt over requests that then landed on nothing.
      await until(async () => await prompt.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), "the prompt's Cancel to be held while Confirm Filed is out", 3000);
      await stub.quiet();
      await until(async () => (await page.getByRole("dialog").last().getByText("This return is already recorded as filed on another obligation.").count()) > 0,
        "the narrowed prompt to say the server's sentence");
      const again = page.getByRole("dialog").last();
      assert.match(await again.innerText(), /Mark 1 filed/, "the prompt was not narrowed to the row that failed");
      assert.equal(await again.locator("#mark-filed-date").inputValue(), "07/10/2026", "the narrowed prompt came back with an empty date box");
      stub.forgetWrites();
      await again.getByRole("button", { name: "Confirm Filed", exact: true }).click();
      await stub.quiet();
      const retried = stub.writesTo(/compliance\/obligations\/ob-\d\/mark-filed$/, "POST");
      assert.deepEqual(retried.map((w) => w.path.split("/").at(-2)), ["ob-2"], `the retry did not send the failed row alone: ${retried.map((w) => w.path).join(", ")}`);
      assert.equal(JSON.parse(retried[0].body).filed_date, "2026-10-07", "the retry did not send the date it was tried with");
    },
  },
  {
    id: "the-advance-tax-register-says-a-dates-sentence-once-after-save",
    title: "Income tax > Advance tax: an unreadable paid-on date, then Save: its sentence is drawn once, not by both the working and the save",
    async run(env) {
      const { page, stub } = env;
      await openAdvanceTaxRegister(env);
      const box = page.getByLabel("Instalment 1 paid on");
      await typeAndLeave(box, "31/02/2026");
      await page.getByRole("button", { name: /^Save/ }).first().click();
      const sentence = "Feb 2026 has only 28 days.";
      await page.getByText(sentence).first().waitFor({ timeout: 4000 });
      // The box says it under itself (an alert of its own) and the page says it once in its message line: two alerts. The live working's copy
      // and Save's used to be drawn one above the other, which made three.
      await stub.quiet();
      const alerts = await page.locator("[role=alert]").filter({ hasText: sentence }).count();
      assert.equal(alerts, 2, `the date's sentence was drawn in ${alerts} alerts (the box's own and the page's one message line are two)`);
    },
  },
  {
    id: "a-recurring-journals-history-opens-the-generated-entry",
    title: "Accounting > Recurring journals > History: Open goes to the journal entry the occurrence generated, not the client's journal list",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
      stub.route({ method: "GET", re: /api\/recurring-journals(\?|$)/, reply: () => ok([{
        id: "rj-1", client_id: CLIENT_ID, name: "Monthly office rent", narration: "Rent", debit_account_id: "ca-1", credit_account_id: "ca-2", amount_paise: 12500000,
        frequency: "monthly", day_of_month: 1, start_date: "2026-04-01", end_date: null, next_run_date: "2026-11-01", status: "active",
        lines: [{ account_id: "ca-1", debit_paise: 12500000, credit_paise: 0 }, { account_id: "ca-2", debit_paise: 0, credit_paise: 12500000 }] }]) });
      stub.route({ method: "GET", re: /api\/recurring-journals\/rj-1\/history$/, reply: () => ok([
        { id: "run-1", template_id: "rj-1", occurrence_date: "2026-10-01", status: "generated", journal_entry_id: "je-77", detail: null }]) });
      stub.route({ method: "GET", re: /api\/recurring-journals\/rj-1\/preview/, reply: () => ok({ template_id: "rj-1", occurrences: ["2026-11-01"] }) });
      await page.goto(`${env.base}/accounting/recurring/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /History/ }).first().click();
      const open = page.getByRole("link", { name: /Open/ }).first();
      await open.waitFor();
      // The export writes links with a trailing slash.
      assert.match(await open.getAttribute("href") ?? "", new RegExp(`^/clients/${CLIENT_ID}/accounting/journal/je-77/edit/?$`), "the history's Open does not name the generated entry");
    },
  },
  {
    id: "a-clients-mca-page-prints-its-dates-through-the-one-date-module",
    title: "A client's MCA page: the incorporation, appointment, due and filed dates are printed 15 Apr 2024, never as the stored ISO text",
    async run(env) {
      const { page, stub } = env;
      await atClientMca(env);
      stub.setTable("mca_companies", [{ id: "mc-1", company_name: "Acme Traders Pvt Ltd", cin: "U74999MH2020PTC123456", incorp_date: "2020-06-15", company_category: "Private Limited",
        authorized_capital_paise: 250000000, paid_up_capital_paise: 100000000, registered_office: null }]);
      env.made.directors.push({ id: "d-1", client_id: CLIENT_ID, din: "01234567", name: "Asha Rao", designation: "Director", date_of_appointment: "2024-04-15", pan: null, kyc_status: "active" });
      env.made.filings.push({ id: "mf-1", client_id: CLIENT_ID, category: "annual", form_type: "AOC-4", financial_year: "2025-26", due_date: "2026-10-30", status: "filed",
        srn: "SRN12345678", filed_date: "2026-10-05" });
      stub.route({ method: "GET", re: /mca-workspace\/filing-history\?client_id=/, reply: () => ok([
        { id: "mf-1", form_type: "AOC-4", financial_year: "2025-26", srn: "SRN12345678", filed_date: "2026-10-05", status: "filed" }]) });
      await page.reload({ waitUntil: "networkidle" });
      const tabs = [["Company Master", "15 Jun 2020", "2020-06-15"], ["Directors", "15 Apr 2024", "2024-04-15"], ["Annual Filings", "30 Oct 2026", "2026-10-30"], ["Filing History", "05 Oct 2026", "2026-10-05"]];
      for (const [tab, shown, stored] of tabs) {
        await page.getByRole("button", { name: tab, exact: true }).click();
        await page.getByText(shown).first().waitFor({ timeout: 5000 }).catch(async () => {
          throw new Error(`${tab}: ${shown} is not printed; the page says ${(await page.locator("main").innerText()).replace(/\s+/g, " ").slice(0, 400)}`);
        });
        assert.equal(await page.locator("main").getByText(stored, { exact: true }).count(), 0, `${tab}: the stored ${stored} is printed as it is stored`);
      }
    },
  },
  {
    id: "the-supplier-forms-cancel-and-a-rows-edit-are-held-while-its-save-is-out",
    title: "Purchases > Vendors > Add Vendor > Save: while it is out, Cancel and Add Vendor are held and a row's Edit does not swap the form",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("vendors", [VENDOR]);
      stub.route({ method: "POST", re: /api\/vendors\/$/, reply: () => ok({ id: "v-new" }) });
      await page.goto(env.at("/purchases/?tab=vendors"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /Add Vendor/ }).first().click();
      await page.getByLabel("Name", { exact: true }).fill("Delta Traders").catch(async (e) => {
        throw new Error(`${String(e.message).split("\n")[0]} | the page says ${(await page.locator("main").innerText()).replace(/\s+/g, " ").slice(0, 600)}`);
      });
      // The form's own Save is also named Add Vendor, as is the toggle above the list: scoped to the form.
      const form = page.locator("div.rounded-xl").filter({ has: page.getByRole("heading", { name: "New Vendor" }) }).last();
      await form.getByRole("button", { name: "Add Vendor", exact: true }).click();
      const cancel = form.getByRole("button", { name: "Cancel", exact: true });
      await cancel.waitFor({ timeout: 3000 }).catch(async (e) => {
        throw new Error(`${String(e.message).split("\n")[0]} | the page says ${(await page.locator("main").innerText()).replace(/\s+/g, " ").slice(0, 900)}`);
      });
      await until(async () => (await cancel.isDisabled()) && (await form.getByRole("button", { name: "Close", exact: true }).isDisabled()),
        "the form's Cancel and its named Close to be held while Save is out", 3000);
      await page.locator("tr", { hasText: "Gamma Supplies" }).getByRole("button").last().click();
      const edit = page.getByRole("button", { name: "Edit", exact: true });
      assert.ok(await edit.isDisabled(), "a row's Edit was offered while the form's Save was out");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/vendors\/$/, "POST").length, 1, "the vendor was not written exactly once");
    },
  },
  {
    id: "a-row-menu-near-the-foot-of-the-window-opens-upwards",
    title: "Purchases > Vendors on a short window: the last row's menu opens above its button, so Edit is on the screen",
    async run(env) {
      const { page, stub } = env;
      await page.setViewportSize({ width: 1440, height: 520 });
      stub.setTable("vendors", Array.from({ length: 12 }, (_, i) => ({ ...VENDOR, id: `v${i + 1}`, name: `Supplier ${String(i + 1).padStart(2, "0")}` })));
      await page.goto(env.at("/purchases/?tab=vendors"), { waitUntil: "networkidle" });
      // The last row the window shows, without scrolling anything: the one whose menu would open below the foot.
      const rows = page.locator("tbody tr");
      await rows.first().waitFor();
      const view = page.viewportSize();
      let target = null;
      for (let i = (await rows.count()) - 1; i >= 0; i--) {
        const b = await rows.nth(i).boundingBox();
        if (b && b.y + b.height <= view.height) { target = rows.nth(i); break; }
      }
      assert.ok(target, "no vendor row is on the screen");
      const button = target.getByRole("button").last();
      const at = await button.boundingBox();
      assert.ok(view.height - (at.y + at.height) < 240, `the chosen row is not near the foot (its button ends ${Math.round(at.y + at.height)} of ${view.height}): the scenario measures nothing`);
      await button.click();
      const edit = page.getByRole("button", { name: "Edit", exact: true });
      await edit.waitFor();
      assert.ok(await insideTheWindow(page, edit), "the row menu's Edit is below the window");
    },
  },
];
