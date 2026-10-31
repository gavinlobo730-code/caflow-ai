/**
 * Group K: a screen that shows an answer the server made says it in the server's words, says when it could not count, and never
 * draws an unread count as a nil (POST-A-097 and POST-A-267, driven in a browser).
 *
 * The Schedule III mapping screen used to say "37 of 53 accounts mapped", a count of the chart. It now also shows how many
 * balances the statements present on an "Other" line because nobody mapped them, as the server counts them. A source guard
 * (`the-mapping-screen-says-how-many-balances-sit-on-an-other-line.test.ts`) reads that the panel hangs off the server's answer;
 * this drives what a CA sees in the three states the panel has: a count, a nil that was read, and a count that could not be read.
 */
import assert from "node:assert/strict";
import { ok, refuse } from "../stub.mjs";
import { until } from "../kit.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "server-counts";

const CAPTIONS = {
  sections: [
    { heading: "Assets", items: ["Cash & Cash Equivalents", "Other Current Assets"] },
    { heading: "Liabilities", items: ["Other Current Liabilities"] },
  ],
  residual: ["Other Current Assets", "Other Current Liabilities", "Other Expenses"],
};

const MAPPING_ACCOUNTS = [
  { id: "m1", account_code: "1900", account_name: "Security Deposit - Landlord", account_type: "Asset", tax_category: null, schedule_iii_mapping: null, is_active: true, client_id: null },
  { id: "m2", account_code: "1100", account_name: "HDFC Bank", account_type: "Asset", tax_category: null, schedule_iii_mapping: "Cash & Cash Equivalents", is_active: true, client_id: null },
];

const STATEMENTS_ROUTE = /accounting\/schedule-iii(\?|$)/;

function arrange(env, statements) {
  env.stub.setTable("chart_of_accounts", MAPPING_ACCOUNTS);
  env.stub.route({ method: "GET", re: /accounting\/schedule-iii\/captions/, reply: () => ok(CAPTIONS) });
  env.stub.route({ method: "GET", re: STATEMENTS_ROUTE, ...statements });
}

const text = (page) => page.locator("body").innerText();

export const scenarios = [
  {
    id: "the-mapping-screen-says-how-many-balances-sit-on-an-other-line-and-where",
    title: "the mapping screen shows the server's count of balances on an Other line, split by caption, and says it is read from the statements",
    async run(env) {
      const { page } = env;
      arrange(env, {
        reply: () => ok({
          period: { fy_start: "2026-04-01", fy_end: "2027-03-31" },
          residual_balances: {
            accounts: 3, absolute_paise: 840_000_00, unjudged_lines: 0,
            by_caption: {
              "Other Current Assets": { accounts: 1, absolute_paise: 500_000_00 },
              "Other Current Liabilities": { accounts: 1, absolute_paise: 300_000_00 },
              "Other Expenses": { accounts: 1, absolute_paise: 40_000_00 },
            },
          },
        }),
      });
      await page.goto(`${env.base}/accounting/schedule-iii-mapping/`, { waitUntil: "networkidle" });
      await page.getByText("Security Deposit - Landlord").waitFor();
      await until(async () => /3 accounts .* sit on an “Other” line because nobody has mapped them/.test(await text(page)),
        "the count of balances on an Other line");
      const body = await text(page);
      assert.match(body, /Other Current Assets: 1 account,/, "the split by caption is missing");
      assert.match(body, /Other Current Liabilities: 1 account,/);
      assert.match(body, /Other Expenses: 1 account,/);
      assert.match(body, /Read from the statements for/, "the count does not say where it was read from");
      assert.doesNotMatch(body, /No balance sits on an “Other” line by default/, "a count of three was also called a nil");
    },
  },
  {
    id: "a-read-nil-is-said",
    title: "a count the server read as nothing says so, in a sentence of its own",
    async run(env) {
      const { page } = env;
      arrange(env, {
        reply: () => ok({
          period: { fy_start: "2026-04-01", fy_end: "2027-03-31" },
          residual_balances: { accounts: 0, absolute_paise: 0, by_caption: {}, unjudged_lines: 0 },
        }),
      });
      await page.goto(`${env.base}/accounting/schedule-iii-mapping/`, { waitUntil: "networkidle" });
      await page.getByText("Security Deposit - Landlord").waitFor();
      await until(async () => /No balance sits on an “Other” line by default/.test(await text(page)), "the read nil to be said");
      assert.doesNotMatch(await text(page), /Could not count/, "a nil that was read was also called unread");
    },
  },
  {
    id: "an-unread-count-is-never-drawn-as-a-nil",
    title: "when the statements cannot be built the screen says no figure is shown, and does not say nothing sits on an Other line",
    async run(env) {
      const { page } = env;
      arrange(env, { ...refuse("The statements could not be built.", 500) });
      await page.goto(`${env.base}/accounting/schedule-iii-mapping/`, { waitUntil: "networkidle" });
      await page.getByText("Security Deposit - Landlord").waitFor();
      await until(async () => /Could not count the balances that sit on an “Other” line by default just now, so no figure is shown\./
        .test(await text(page)), "the unread sentence");
      assert.doesNotMatch(await text(page), /No balance sits on an “Other” line by default/, "an unread count was drawn as a nil");
    },
  },
  // ── POST-A-267: saving the advance-tax register says what became of the calendar's obligations ───────────────────────────
  {
    id: "saving-the-advance-tax-register-shows-the-servers-words-about-the-calendar",
    title: "saving the register shows each of the server's sentences about the calendar as written, and Dismiss takes them away",
    async run(env) {
      const { page } = env;
      const CLOSED = "The 15% instalment (due 15-06-2026) is closed on the compliance calendar as filed on 12-06-2026, challan CH-1. Check it against the challan.";
      const OPEN = "The 45% instalment (due 15-09-2026) is still open: the tax paid by that date is short of the 45% of the estimate.";
      env.stub.route({
        method: "POST", re: /api\/income-tax\/advance-tax(\?|$)/,
        reply: () => ok({
          installments: [],
          compliance_obligations: [
            { state: "closed", closed: true, instalment: 1, message: CLOSED, needs_action: false },
            { state: "not_closed", closed: false, instalment: 2, message: OPEN, needs_action: true },
          ],
        }),
      });
      await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
      await page.getByPlaceholder("Enter tax amount").fill("100000");
      await page.getByRole("button", { name: "Save" }).click();
      await page.getByText(CLOSED).waitFor();
      const body = await text(page);
      assert.ok(body.includes(OPEN), "the instalment the server left open was not shown");
      assert.match(body, /Saved\. What became of the advance-tax obligations on the compliance calendar:/);
      await page.getByRole("button", { name: "Dismiss" }).click();
      await until(async () => !(await text(page)).includes(CLOSED), "the answer to go when dismissed");
    },
  },
  {
    id: "an-advance-tax-save-with-no-calendar-answer-shows-no-panel",
    title: "a save whose answer carries nothing about the calendar says Saved and shows no calendar panel",
    async run(env) {
      const { page } = env;
      env.stub.route({ method: "POST", re: /api\/income-tax\/advance-tax(\?|$)/, reply: () => ok({ installments: [], compliance_obligations: [] }) });
      await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
      await page.getByPlaceholder("Enter tax amount").fill("100000");
      await page.getByRole("button", { name: "Save" }).click();
      await page.getByText("Saved", { exact: true }).waitFor();
      assert.doesNotMatch(await text(page), /What became of the advance-tax obligations/, "an empty answer drew a panel");
    },
  },
  // ── the §234A / §234B answer: a reply without its parts took the whole screen down (found by driving the typed-date rows) ────────────
  {
    id: "an-interest-answer-without-its-parts-is-refused-and-the-advance-tax-screen-stands",
    title: "a §234A/§234B answer that lacks its blocks is refused in a sentence and the instalment table stays on the screen",
    async run(env) {
      const { page } = env;
      // `{}` is what a server behind this screen, or an error envelope carried in a 200, looks like to the page: an object, so a
      // plain truthiness check passes it, and then the panel reads `.itr_due_date.due_date` of nothing.
      env.stub.route({ method: "POST", re: /api\/income-tax\/interest\/234ab$/, reply: () => ok({}) });
      await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
      await page.getByPlaceholder("Enter tax amount").fill("100000");
      await until(async () => /The §234A \/ §234B answer came back in a shape this screen cannot read, so no figure is shown\./.test(await text(page)),
        "the refusal sentence");
      assert.ok(await page.getByLabel("Instalment 1 paid on").count() > 0, "the screen was replaced instead of standing");
      assert.doesNotMatch(await text(page), /could not be displayed/i, "the error boundary took the screen");
    },
  },
];
