/**
 * Group U: the GST and MCA filing trackers print the word the one overdue rule gives, driven in a browser (POST-A-280).
 *
 * Both trackers used to work the word out from the due date and the filed date alone, so a filing recorded as NOT APPLICABLE with a past
 * date was printed Overdue (and counted in the Overdue tile), and a row somebody had moved to Overdue by hand with its date still ahead was
 * printed Pending. They call `filingTrackerStatus` now. The source guards hold that both pages call it and the function is pinned in
 * `lib/compliance/overdue.test.ts`; this proves what the PAGES print, in Chromium, against the stub's tables (the pages read their rows over
 * PostgREST, which the stub answers from a table map).
 *
 *   1. the GST tracker: a pending return past its date and a return moved to overdue by hand with its date ahead are both Overdue, a
 *      return recorded as not applicable says "Not applicable" (and offers no Mark as Filed), a filed one says Filed, and the Overdue
 *      tile counts two, not three;
 *   2. the MCA tracker: a not_started filing past its date is Overdue, one moved to overdue by hand with its date ahead is Overdue, one
 *      whose status is not_applicable says "Not applicable", and a filed one says Filed.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { CLIENT_ROW, FAKE_USERS_ROW } from "../fixtures.mjs";

export const group = "filing-trackers";

const CLIENT = { client_name: "Acme Traders", gstin: "27AAACA1234A1Z5" };
// Each row is its own client by name, because a row is found by its client: the form, period and due-date columns repeat each other's months.
const gstRow = (id, name, type, periodStart, due, status, filed = null) => ({
  id, firm_id: FAKE_USERS_ROW.firm_id, client_id: CLIENT_ROW.id, compliance_type: type, period_start: periodStart, period_end: periodStart,
  due_date: due, filing_status: status, filed_date: filed, created_at: "2026-01-01T00:00:00Z", clients: { ...CLIENT, client_name: name },
});
const mcaRow = (id, form, period, due, status, filed = null) => ({
  id, firm_id: FAKE_USERS_ROW.firm_id, client_id: CLIENT_ROW.id, client_name: "Acme Traders", company_cin: "U12345MH2020PTC123456", form_type: form,
  period, due_date: due, filed_date: filed, srn: null, status, notes: null,
});

/** A wait that names what the page said when it gave up, so a failed run says what was on the screen instead of only that a locator timed out. */
async function waitFor(page, locator) {
  try { await locator.waitFor({ timeout: 8000 }); }
  catch (e) { throw new Error(`${String(e.message).split("\n")[0]} | the page said: ${(await page.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 700)}`); }
}

const rowOf = (page, text) => page.locator("tr", { hasText: text }).first();
const allRows = async (page) => (await page.locator("tr").allInnerTexts()).map((t) => t.replace(/\s+/g, " ")).join(" || ");

export const scenarios = [
  {
    id: "the-gst-tracker-prints-not-applicable-and-a-hand-set-overdue-by-the-one-rule",
    title: "GST: pending past its date and overdue-by-hand with its date ahead print Overdue, not applicable prints so with no Mark as Filed, and the Overdue tile counts two",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("compliance_calendar", [
        gstRow("g-pending", "Pending Co", "GSTR3B", "2024-12-01", "2025-01-20", "pending"),
        gstRow("g-na", "NotApplicable Co", "GSTR1", "2024-11-01", "2024-12-11", "na"),
        gstRow("g-hand", "HandSet Co", "GSTR3B", "2099-10-01", "2099-11-20", "overdue"),
        gstRow("g-filed", "Filed Co", "GSTR1", "2024-10-01", "2024-11-11", "filed", "2024-11-09"),
      ]);
      await page.goto(`${env.base}/gst/`, { waitUntil: "networkidle" });
      await waitFor(page, page.locator("tr", { hasText: "Pending Co" }).first());

      const badge = async (period) => { try { return (await rowOf(page, period).innerText({ timeout: 4000 })).replace(/\s+/g, " "); } catch { throw new Error(`no row for ${period}; rows: ${await allRows(page)}`); } };
      const pending = await badge("Pending Co"), na = await badge("NotApplicable Co"), hand = await badge("HandSet Co"), filed = await badge("Filed Co");
      assert.match(pending, /Overdue/, `a pending return past its date should print Overdue: ${pending}`);
      assert.match(hand, /Overdue/, `a return moved to overdue by hand with its date ahead should print Overdue: ${hand}`);
      assert.match(na, /Not applicable/, `a not-applicable return should say so: ${na}`);
      assert.doesNotMatch(na, /Overdue|Pending/, `a not-applicable return must not read Overdue or Pending: ${na}`);
      assert.doesNotMatch(na, /Mark as Filed/, `a not-applicable return must offer no Mark as Filed: ${na}`);
      assert.match(filed, /Filed/);
      assert.match(pending, /Mark as Filed/, "an open return still offers Mark as Filed");

      const tile = page.locator("span", { hasText: /^Overdue$/ }).first().locator("xpath=ancestor::div[contains(@class,'rounded-xl')][1]").locator("p").first();
      assert.strictEqual((await tile.innerText()).trim(), "2", "the Overdue tile should count the two late returns, not the not-applicable one");
    },
  },
  {
    id: "the-mca-tracker-prints-not-applicable-and-a-hand-set-overdue-by-the-one-rule",
    title: "MCA: not_started past its date and overdue-by-hand with its date ahead print Overdue, a not_applicable filing says so, a filed one says Filed",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("mca_filings", [
        mcaRow("m-open", "AOC-4", "FY 2023-24", "2024-10-30", "not_started"),
        mcaRow("m-na", "MGT-7", "FY 2022-23", "2023-11-29", "not_applicable"),
        mcaRow("m-hand", "ADT-1", "FY 2099-00", "2099-10-15", "overdue"),
        mcaRow("m-filed", "DIR-3 KYC", "FY 2021-22", "2022-09-30", "filed", "2022-09-20"),
      ]);
      await page.goto(`${env.base}/mca/`, { waitUntil: "networkidle" });
      await waitFor(page, page.getByRole("button", { name: "Filings", exact: true }));
      await page.getByRole("button", { name: "Filings", exact: true }).click();
      await waitFor(page, page.locator("tr", { hasText: "Acme Traders" }).first());

      const line = async (form) => { try { return (await rowOf(page, form).innerText({ timeout: 4000 })).replace(/\s+/g, " "); } catch { throw new Error(`no row for ${form}; rows: ${await allRows(page)}`); } };
      const open = await line("AOC-4"), na = await line("MGT-7"), hand = await line("ADT-1"), filed = await line("DIR-3 KYC");
      assert.match(open, /Overdue/, `a not_started filing past its date should print Overdue: ${open}`);
      assert.match(hand, /Overdue/, `a filing moved to overdue by hand with its date ahead should print Overdue: ${hand}`);
      assert.match(na, /Not applicable/, `a not_applicable filing should say so: ${na}`);
      assert.doesNotMatch(na, /Overdue|Pending/, `a not-applicable filing must not read Overdue or Pending: ${na}`);
      assert.match(filed, /Filed/);
      await until(async () => !(await rowOf(page, "MGT-7").innerText()).includes("Mark Filed"), "the not-applicable filing to offer no Mark Filed");
    },
  },
];
