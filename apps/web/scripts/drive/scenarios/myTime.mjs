/**
 * Group: the time screen's hour tiles are the server's sums for a period of Indian days (POST-A-156, driven in a browser).
 *
 * The tiles used to total the entries the screen listed (at most 500, no period at all). They now show what
 * `GET /api/time-entries/summary/me` sums for a period the server turns into days: this week by default, this month, or a range
 * of two days. This drives what a person sees: the figures and the days they cover, the timers still running named apart, the
 * period sent as the person chose it, the server's refusal of a backwards range said in its words with no figure left behind,
 * and a typed day that is not one refused before anything is asked.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "my-time";

const WEEK = {
  period: "week", date_from: "2026-10-05", date_to: "2026-10-11",
  total_minutes: 155, billable_minutes: 125, non_billable_minutes: 30, entries_count: 4, running: 1,
  by_client: [{ client_id: "c1", minutes: 155, billable_minutes: 125 }],
};
const MONTH = {
  ...WEEK, period: "month", date_from: "2026-10-01", date_to: "2026-10-31",
  total_minutes: 1260, billable_minutes: 900, non_billable_minutes: 360, entries_count: 21, running: 0,
};

async function typeAndLeave(box, text) {
  await box.fill("");
  await box.pressSequentially(text);
  await box.press("Tab");
}

async function atMyTime(env, { weekDelay = 0, wait = true } = {}) {
  const { page, stub } = env;
  const asked = [];
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Executive", permissions: { time_entry: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/time-entries\/running\/me$/, reply: () => ok({ running: null }) });
  stub.route({
    method: "GET", re: /api\/time-entries\/summary\/me\?period=week/, delay: weekDelay,
    reply: (req, body, url) => { asked.push(url.search); return ok(WEEK); },
  });
  stub.route({
    method: "GET", re: /api\/time-entries\/summary\/me\?(?!period=week)/,
    status: (req, body, url) => (url.searchParams.get("period") === "range"
      && url.searchParams.get("date_from") > url.searchParams.get("date_to") ? 422 : 200),
    reply: (req, body, url) => {
      const period = url.searchParams.get("period");
      asked.push(url.search);
      if (period === "month") return ok(MONTH);
      if (period === "range") {
        const from = url.searchParams.get("date_from"), to = url.searchParams.get("date_to");
        if (from > to) return { detail: "The first day of the range is after its last day." };
        return ok({ ...WEEK, period: "range", date_from: from, date_to: to, total_minutes: 60, billable_minutes: 60, non_billable_minutes: 0, entries_count: 1, running: 0 });
      }
      return ok(WEEK);
    },
  });
  if (!wait) {
    await page.goto(`${env.base}/time/`, { waitUntil: "domcontentloaded" });
    return asked;
  }
  await page.goto(`${env.base}/time/`, { waitUntil: "networkidle" });
  await page.getByTestId("time-total").filter({ hasText: /h|m/ }).waitFor();
  return asked;
}

const tile = (page, id) => page.getByTestId(id).innerText();

export const scenarios = [
  {
    id: "the-tiles-are-the-servers-sums-for-this-week-and-say-which-days-they-cover",
    title: "this week's tiles show the server's figures, the days they cover, and the running timer that is not counted",
    async run(env) {
      const { page } = env;
      const asked = await atMyTime(env);
      assert.equal(await tile(page, "time-total"), "2h 35m");
      assert.equal(await tile(page, "time-billable"), "2h 5m");
      assert.equal(await tile(page, "time-non-billable"), "30m");
      const window = await page.getByTestId("time-summary-window").innerText();
      assert.match(window, /Your own finished time from 05 Oct 2026 to 11 Oct 2026, by the day each entry started, in India \(the entries listed below may include other members'\)\. 1 timer is still running and not counted\./);
      assert.match(await page.locator("body").innerText(), /4 finished entries/);
      assert.ok(asked.length >= 1 && new URLSearchParams(asked[0]).get("period") === "week", `asked ${asked.join(" | ")}`);
    },
  },
  {
    id: "choosing-this-month-asks-the-server-for-the-month",
    title: "This month is asked for as period=month and its figures replace the week's",
    async run(env) {
      const { page } = env;
      const asked = await atMyTime(env);
      await page.getByLabel("Your hours for").selectOption("month");
      await until(async () => (await tile(page, "time-total")) === "21h", "the month's total");
      assert.ok(asked.some((q) => new URLSearchParams(q).get("period") === "month"), `asked ${asked.join(" | ")}`);
      assert.match(await page.getByTestId("time-summary-window").innerText(), /01 Oct 2026 to 31 Oct 2026/);
    },
  },
  {
    id: "a-backwards-range-is-refused-in-the-servers-words-and-no-figure-is-left",
    title: "a range whose first day is after its last is refused in the server's sentence and the tiles show a dash",
    async run(env) {
      const { page } = env;
      await atMyTime(env);
      await page.getByLabel("Your hours for").selectOption("range");
      await typeAndLeave(page.getByLabel("Hours from"), "10/10/2026");
      await typeAndLeave(page.getByLabel("Hours to"), "01/10/2026");
      await page.getByRole("button", { name: "Show hours" }).click();
      await page.getByRole("alert").filter({ hasText: "The first day of the range is after its last day." }).waitFor();
      assert.equal(await tile(page, "time-total"), "—", "the week's figure was left on screen under a refused range");
    },
  },
  {
    id: "a-chosen-range-is-sent-as-two-days-and-its-figures-shown",
    title: "a range of 06/10/2026 to 07/10/2026 is sent as two ISO days with period=range, and its figures are shown",
    async run(env) {
      const { page } = env;
      const asked = await atMyTime(env);
      await page.getByLabel("Your hours for").selectOption("range");
      await typeAndLeave(page.getByLabel("Hours from"), "06/10/2026");
      await typeAndLeave(page.getByLabel("Hours to"), "07/10/2026");
      await page.getByRole("button", { name: "Show hours" }).click();
      await until(async () => (await tile(page, "time-total")) === "1h", "the range's total");
      const q = new URLSearchParams(asked[asked.length - 1]);
      assert.deepEqual([q.get("period"), q.get("date_from"), q.get("date_to")], ["range", "2026-10-06", "2026-10-07"]);
      assert.match(await page.getByTestId("time-summary-window").innerText(), /06 Oct 2026 to 07 Oct 2026/);
    },
  },
  {
    id: "a-typed-day-that-is-not-one-is-refused-before-anything-is-asked",
    title: "31/02/2026 in the range is refused on the screen and no range is asked for",
    async run(env) {
      const { page } = env;
      const asked = await atMyTime(env);
      await page.getByLabel("Your hours for").selectOption("range");
      await typeAndLeave(page.getByLabel("Hours from"), "31/02/2026");
      await typeAndLeave(page.getByLabel("Hours to"), "07/10/2026");
      const show = page.getByRole("button", { name: "Show hours" });
      if (!(await show.isDisabled())) await show.click();
      await until(async () => (await page.getByRole("alert").count()) > 0 || (await show.isDisabled()), "the bad day refused or Show held");
      assert.ok(!asked.some((q) => new URLSearchParams(q).get("period") === "range"), `a range was asked for: ${asked.join(" | ")}`);
    },
  },
  {
    id: "a-slow-answer-for-an-earlier-period-does-not-land-over-a-later-one",
    title: "the week's answer arrives after the month was chosen, and the tiles keep the month's figures",
    async run(env) {
      const { page } = env;
      // The week's answer is held 2.5 s; waiting for the RESPONSE (not the request, which the stub logs on arrival) proves it landed.
      const weekAnswered = page.waitForResponse((r) => r.url().includes("summary/me?period=week"), { timeout: 15_000 });
      await atMyTime(env, { weekDelay: 2500, wait: false });
      await page.getByLabel("Your hours for").selectOption("month");
      await until(async () => (await tile(page, "time-total")) === "21h", "the month's total");
      await weekAnswered;
      await page.waitForTimeout(300);
      assert.equal(await tile(page, "time-total"), "21h", "the late week answer replaced the month's figures");
      assert.match(await page.getByTestId("time-summary-window").innerText(), /01 Oct 2026 to 31 Oct 2026/);
    },
  },
  {
    id: "choosing-a-range-blanks-the-tiles-until-its-days-are-shown",
    title: "A range of days shows a dash and asks for the days, rather than the previous period's figures",
    async run(env) {
      const { page } = env;
      await atMyTime(env);
      await page.getByLabel("Your hours for").selectOption("range");
      await page.getByText("Choose the first and the last day, then Show hours.").waitFor();
      assert.equal(await tile(page, "time-total"), "—");
    },
  },
];
