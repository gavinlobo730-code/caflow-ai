/**
 * Group L: what the Profitability screen says when a cost cannot be known, and the Partner's box that sets what an hour
 * costs (POST-B-321, driven in a browser).
 *
 * The screen used to print `profit = revenue` as a margin for a client whose hours had no rate. It now draws a dash,
 * names who has hours with no cost rate, and puts a box for each person's cost per hour at the foot of the page. A source
 * guard (`the-profitability-screen-draws-an-unknown-as-a-dash.test.ts`) reads that nothing nullable is formatted as a number
 * and that the box goes through the one rate reader; this types into the box in Chromium and reads what reaches the server:
 * exact integer paise, a refusal of grouped text with nothing written, a cleared box sent as null, a typed 0 sent as a rate,
 * and one write for two clicks in the same tick.
 */
import assert from "node:assert/strict";
import { expectWrites, sameTickDouble, until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "cost-rates";

const MEMBERS = [
  { id: "u1", full_name: "Meera Shah", role: "Partner", is_active: true, cost_rate_paise: 60_000 },
  { id: "u2", full_name: "Asha Rao", role: "Executive", is_active: true, cost_rate_paise: null },
];

const PROFIT = {
  period: "November 2026",
  firm_metrics: {
    total_revenue_paise: 150_000_00, total_cost_paise: null, cost_is_complete: false, unrated_minutes: 300,
    profit_paise: null, profit_margin_pct: null, profit_on_known_paise: 0, clients_with_cost: 0, clients_without_cost: 1,
    num_clients_billed: 1, num_clients_not_billed: 0, avg_profit_per_client_paise: null, minutes_without_client: 0,
  },
  cost_rates_missing: [{ user_id: "u2", user_name: "Asha Rao", minutes: 300 }],
  not_measured: ["Revenue is the fee before GST on invoices that are issued, counted in the period of the invoice's own date."],
  by_client: [{
    client_id: "c1", client_name: "Kapoor Textiles", revenue_paise: 150_000_00, cost_paise: null, cost_is_complete: false,
    unrated_minutes: 300, effort_minutes: 300, profit_paise: null, profit_margin_pct: null, status: "unpriced",
  }],
};

/** Realization where five hours of billable time have no billing rate: nothing to divide by, so no figure (POST-A-426). */
const REALIZATION = {
  period: "November 2026", total_revenue_paise: 150_000_00, total_billable_minutes: 300, unpriced_minutes: 300,
  billable_time_value_paise: null, minutes_without_engagement: 0, avg_revenue_per_hour_paise: 30_000_00,
  revenue_without_time_paise: 0, revenue_without_engagement_paise: 0,
  realization_rate: null,
  by_client: [{
    client_id: "c1", client_name: "Kapoor Textiles", revenue_paise: 150_000_00, effort_minutes: 300, unpriced_minutes: 300,
    revenue_without_time_paise: 0, revenue_without_engagement_paise: 0, minutes_without_engagement: 0,
    billable_time_value_paise: null, revenue_per_hour_paise: 30_000_00, realization_rate: null,
  }],
  by_engagement: [],
  not_measured: ["Realization is the fee before GST invoiced on an engagement in the period, against what the billable time recorded on it is worth."],
};
/** The same book once the hours are priced, with fees on a fixed-fee engagement nobody timed, on an invoice naming no engagement and
 *  billable time naming none: what the ratio leaves out, named beside it (a firm that read 10.00× before it was taken on timed work only). */
const LEFT_OUT = {
  ...REALIZATION, unpriced_minutes: 0, billable_time_value_paise: 187_500_00, realization_rate: 0.8,
  revenue_without_time_paise: 900_000_00, revenue_without_engagement_paise: 40_000_00, minutes_without_engagement: 90,
  by_client: [{ ...REALIZATION.by_client[0], unpriced_minutes: 0, billable_time_value_paise: 187_500_00, realization_rate: 0.8,
    revenue_without_time_paise: 900_000_00, revenue_without_engagement_paise: 40_000_00, minutes_without_engagement: 90 }],
};
/** The same book once the hours are priced. */
const PRICED = {
  ...REALIZATION, unpriced_minutes: 0, billable_time_value_paise: 187_500_00, realization_rate: 0.8,
  by_client: [{ ...REALIZATION.by_client[0], unpriced_minutes: 0, billable_time_value_paise: 187_500_00, realization_rate: 0.8 }],
};
const CONCENTRATION = {
  period: "November 2026", shares: [], total_revenue_paise: 0, clients_billed: 0, largest_share_bps: 0, top_3_share_bps: 0,
  top_5_share_bps: 0, median_revenue_paise: null, median_margin_bps: null, icai_fee_dependence: "", not_measured: [],
};

async function arrange(env, members = MEMBERS, realization = REALIZATION) {
  /** How many times the figures were asked for (a saved rate must reload them), and with which window. */
  const asked = { profitability: 0, windows: [] };
  // The Partner may read and set the practice's fees: the panel is shown for `billing:write` alone.
  env.stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { billing: ["read", "write"], analytics: ["read"] } }) });
  env.stub.route({ method: "GET", re: /analytics\/profitability/, reply: (req, body, url) => { asked.profitability += 1; asked.windows.push(`profitability ${url.search}`); return ok(PROFIT); } });
  env.stub.route({ method: "GET", re: /analytics\/revenue-vs-effort/, reply: (req, body, url) => { asked.windows.push(`realization ${url.search}`); return ok(realization); } });
  env.stub.route({ method: "GET", re: /analytics\/concentration/, reply: (req, body, url) => { asked.windows.push(`concentration ${url.search}`); return ok(CONCENTRATION); } });
  env.stub.route({ method: "GET", re: /billing\/staff-cost-rates$/, reply: () => ok(members) });
  env.stub.route({ method: "PUT", re: /billing\/staff-cost-rates\/u\d$/, reply: () => ok({ user_id: "u2", cost_rate_paise: null }) });
  await env.page.goto(`${env.base}/practice/profitability/`, { waitUntil: "networkidle" });
  await env.page.getByRole("heading", { name: "What an hour costs the practice" }).waitFor();
  return asked;
}

const text = (page) => page.locator("body").innerText();
const boxOf = (page, name) => page.getByLabel(`Cost per hour for ${name}`, { exact: true });
const saveOf = (page, name) => page.getByRole("button", { name: `Save cost per hour for ${name}` });
const putBodies = (env) => env.stub.writesTo(/staff-cost-rates\/u\d$/).map((w) => JSON.parse(w.body));

export const scenarios = [
  {
    id: "a-cost-nobody-could-price-is-a-dash-and-says-who-has-no-rate",
    title: "a client whose hours have no cost rate shows a dash for its cost, profit and margin, names who to ask, and the person is listed first in the panel",
    async run(env) {
      const { page } = env;
      await arrange(env);
      const body = await text(page);
      assert.match(body, /The profit is not shown, because some of the cost is not known\./);
      assert.match(body, /5h recorded by Asha Rao has no cost rate, so it is in no client[’']s cost\./);
      assert.match(body, /Set the rates at the foot of this page\./);
      assert.match(body, /Hours with no cost rate/, "the client's row does not say why it has no margin");
      assert.match(body, /and 5h with no cost rate/);
      const tile = (label) => page.locator("div", { has: page.getByText(label, { exact: true }) }).filter({ hasText: /—/ }).first();
      await tile("Cost of delivery").waitFor();
      await tile("Profit").waitFor();
      assert.doesNotMatch(body, /₹\s?0\.00/, "an unknown cost was drawn as ₹0.00");
      const labels = await page.getByLabel(/^Cost per hour for /).evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")));
      assert.deepEqual(labels, ["Cost per hour for Asha Rao", "Cost per hour for Meera Shah"], "the member with no rate is not first");
      assert.equal(await boxOf(page, "Meera Shah").inputValue(), "600.00", "a stored 60,000 paise is ₹600");
    },
  },
  {
    id: "a-typed-cost-per-hour-reaches-the-server-as-exact-paise-and-the-person-stays-in-the-box",
    title: "₹650.50 is saved as 65050 paise, once, the saved line is said, and focus is back in the box that was edited",
    async run(env) {
      const { page } = env;
      const asked = await arrange(env);
      assert.equal(await saveOf(page, "Asha Rao").isDisabled(), true, "Save is live with nothing typed");
      await boxOf(page, "Asha Rao").fill("650.50");
      await saveOf(page, "Asha Rao").click();
      await expectWrites(env.stub, /staff-cost-rates\/u2$/, 1, "a cost per hour", "PUT");
      assert.equal(putBodies(env)[0].cost_rate_paise, 65050);
      await until(async () => /Saved the cost per hour for Asha Rao\./.test(await text(page)), "the saved line");
      await until(
        async () => (await page.evaluate(() => document.activeElement?.getAttribute("aria-label"))) === "Cost per hour for Asha Rao",
        "focus back in the box that was edited");
      await until(async () => asked.profitability >= 2, "the figures reloaded after the save");
    },
  },
  {
    id: "a-cost-per-hour-with-a-comma-is-refused-on-its-own-row-and-nothing-is-written",
    title: "'6,50' is refused in words on that person's row, marked invalid, and no request is sent; correcting it clears the sentence",
    async run(env) {
      const { page } = env;
      await arrange(env);
      await boxOf(page, "Asha Rao").fill("6,50");
      await saveOf(page, "Asha Rao").click();
      const problem = page.getByRole("alert").filter({ hasText: "without commas" });
      await problem.waitFor();
      assert.equal(await boxOf(page, "Asha Rao").getAttribute("aria-invalid"), "true");
      assert.equal(putBodies(env).length, 0, "a refused amount was still sent");
      await boxOf(page, "Asha Rao").fill("650");
      await problem.waitFor({ state: "detached" });
    },
  },
  {
    id: "an-emptied-box-clears-the-rate-and-a-typed-zero-is-a-rate",
    title: "an emptied box sends null and a typed 0 sends 0: the first takes the hours back to unknown, the second says they cost nothing",
    async run(env) {
      const { page } = env;
      await arrange(env);
      await boxOf(page, "Meera Shah").fill("");
      await saveOf(page, "Meera Shah").click();
      await expectWrites(env.stub, /staff-cost-rates\/u1$/, 1, "an emptied box", "PUT");
      assert.strictEqual(putBodies(env)[0].cost_rate_paise, null, "an emptied box was not sent as null");
      await boxOf(page, "Asha Rao").fill("0");
      await saveOf(page, "Asha Rao").click();
      await expectWrites(env.stub, /staff-cost-rates\/u2$/, 1, "a typed zero", "PUT");
      assert.strictEqual(putBodies(env).at(-1).cost_rate_paise, 0, "a typed 0 was not sent as 0");
    },
  },
  {
    id: "a-realization-nobody-could-price-is-a-dash-and-says-which-hours-have-no-rate",
    title: "billable hours with no billing rate give the firm and the client no realization, name the hours, and draw no 0.00×",
    async run(env) {
      const { page } = env;
      await arrange(env);
      const body = await text(page);
      assert.match(body, /5h of billable time has no billing rate/, "the firm's tile does not say why it has no figure");
      assert.match(body, /5h with no billing rate/, "the client's row does not name the hours");
      assert.doesNotMatch(body, /0\.00×/, "an unknown realization was drawn as 0.00×");
      assert.match(body, /Realization is the fee before GST invoiced on an engagement/, "the server's own footnote is not shown");
    },
  },
  {
    id: "the-firms-realization-tile-reads-the-key-the-server-sends",
    title: "a priced book shows its realization on the firm's tile and on the client's row (the tile read a key the server never sent)",
    async run(env) {
      const { page } = env;
      await arrange(env, MEMBERS, PRICED);
      const body = await text(page);
      assert.equal((body.match(/0\.80×/g) ?? []).length, 2, "the firm's tile and the client's row should each show 0.80×");
      assert.doesNotMatch(body, /has no billing rate/);
    },
  },
  {
    id: "what-the-ratio-leaves-out-is-named-beside-the-figure",
    title: "fees on work nobody timed, fees naming no engagement and billable time naming none are worded on the firm's tile and the client's row, with the figure kept",
    async run(env) {
      const { page } = env;
      await arrange(env, MEMBERS, LEFT_OUT);
      const body = await text(page);
      for (const note of [/₹9,00,000\.00 on work with no billable time is left out/, /₹40,000\.00 invoiced to no engagement is left out/, /1h 30m billable on no engagement is left out/]) {
        assert.equal((body.match(new RegExp(note.source, "g")) ?? []).length, 2, `${note} should be said on the firm's tile and on the client's row`);
      }
      assert.equal((body.match(/0\.80×/g) ?? []).length, 2, "the figure is kept beside what it leaves out");
    },
  },
  {
    id: "a-financial-year-is-asked-for-by-its-label-on-all-three-reads",
    title: "picking a past financial year sends period=fy and its label to profitability, realization and concentration, and the year that is running is offered first",
    async run(env) {
      const { page } = env;
      const asked = await arrange(env);
      const options = await page.getByLabel("Period").locator("option").evaluateAll((els) => els.map((e) => ({ value: e.value, label: e.textContent })));
      assert.deepEqual(options.slice(0, 3).map((o) => o.value), ["month", "quarter", "week"]);
      const years = options.slice(3);
      assert.equal(years.length, 3, "the running year and the two before it");
      assert.match(years[0].label, /^This financial year \(\d{4}-\d{2}\), to date$/);
      assert.match(years[1].label, /^Financial year \d{4}-\d{2}$/);
      assert.ok(years.every((o) => /^fy:\d{4}-\d{2}$/.test(o.value)), "a year's value is its label");
      asked.windows.length = 0;
      await page.getByLabel("Period").selectOption(years[1].value);
      const label = years[1].value.slice(3);
      await until(async () => asked.windows.length >= 3, "the three reads for the picked year");
      for (const kind of ["profitability", "realization", "concentration"]) {
        assert.ok(asked.windows.includes(`${kind} ?period=fy&financial_year=${label}`), `${kind} was not asked for ${label}: ${asked.windows.join(" | ")}`);
      }
    },
  },
  {
    id: "two-clicks-on-save-in-the-same-tick-write-once",
    title: "a double click on Save sends one request",
    async run(env) {
      const { page } = env;
      await arrange(env);
      await boxOf(page, "Asha Rao").fill("700");
      await sameTickDouble(saveOf(page, "Asha Rao"));
      await expectWrites(env.stub, /staff-cost-rates\/u2$/, 1, "a double click on Save", "PUT");
    },
  },
];
