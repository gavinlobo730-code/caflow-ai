/**
 * A CLIENT'S UNBILLED TIME BECOMES ONE DRAFT INVOICE, AND THE SCREEN WORKS NOTHING OUT (POST-B-194), driven in a browser.
 *
 * Against a stubbed server, in Chromium, as a Partner on Time, Unbilled work:
 *
 *   1. "Bill this time" on a client's row opens the dialog; the entries are the server's, each with its worth; an entry the
 *      server says cannot be billed is shown with the server's reason and has no tick; the lines and the total are the
 *      server's preview of exactly the ticked entries; unticking one asks for a new preview and the old total is not shown
 *      as the new one; the GST box starts from the rate recorded against the practice's service; the request that makes
 *      the draft carries the ticked ids, the layout, the service and the rate, and nothing worked out; the dialog then
 *      says a draft was made and links to it;
 *   2. the draft cannot be made without a rate of GST (a service with none recorded leaves the box empty), a rate that is
 *      not a number is refused in words and unsent, and a refusal from the server is shown in the server's words.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "bill-time";

const ENTRIES = /\/api\/billing\/unbilled-work\/entries/;
const UNBILLED = /\/api\/billing\/unbilled-work(\?.*)?$/;
const SERVICES = /\/api\/billing\/service-options$/;
const PREVIEW = /\/api\/billing\/time-invoices\/preview$/;
const CREATE = /\/api\/billing\/time-invoices$/;

const entry = (id, minutes, value, over = {}) => ({ id, day: "2026-11-10", user_id: "u-1", user_name: "Asha Rao", task_id: "t-1",
  task_title: "GST returns", description: `Work ${id}`, minutes, rate_paise: 150000, value_paise: value, blocked: null, ...over });
const ROWS = [
  entry("e-1", 60, 150000),
  entry("e-2", 50, 125000, { task_title: "Books review" }),
  entry("e-3", 30, null, { rate_paise: null, blocked: "It has no rate. Set its rate first." }),
];

function serve(env, { services, refuse: refusal } = {}) {
  const seen = { previews: [], created: [] };
  env.stub.route({ method: "GET", re: ENTRIES, reply: () => ok({ client_id: env.clientId, entries: ROWS, billable_count: 2,
    billable_minutes: 110, billable_value_paise: 275000, groupings: ["single", "by_task", "by_person", "by_entry"], max_lines: 100 }) });
  env.stub.route({ method: "GET", re: UNBILLED, reply: () => ok({
    by_client: { [env.clientId]: { minutes: 110, value_paise: 275000, count: 2 } }, by_work_item: {}, total_value_paise: 275000,
    priced_minutes: 110, total_minutes: 140, no_rate: { count: 1, minutes: 30, by_client: {}, entries: [] } }) });
  env.stub.route({ method: "GET", re: SERVICES, reply: () => ok({ internal_client_id: "c-practice",
    services: services ?? [{ id: "svc-fees", name: "Professional fees", hsn_sac: "998211", default_rate_paise: null, gst_rate_bps: 1800 }] }) });
  env.stub.route({ method: "POST", re: PREVIEW, reply: (req, body) => {
    const sent = JSON.parse(body);
    seen.previews.push(sent);
    const chosen = ROWS.filter((r) => sent.entry_ids.includes(r.id));
    const total = chosen.reduce((n, r) => n + r.value_paise, 0);
    return ok({ lines: chosen.map((r) => ({ description: `${r.task_title}: ${r.minutes} min`, minutes: r.minutes, value_paise: r.value_paise })),
      entries: chosen.length, minutes: chosen.reduce((n, r) => n + r.minutes, 0), value_paise: total });
  } });
  env.stub.route({ method: "POST", re: CREATE, reply: (req, body) => {
    seen.created.push(JSON.parse(body));
    if (refusal) return { success: false, data: null, error: refusal };
    return ok({ invoice_id: "inv-77", invoice_no: "DRAFT-ABCDEF1234", practice_client_id: "c-practice", entries_billed: 2, minutes: 110, value_paise: 275000, lines: [] });
  } });
  return seen;
}

async function open(env) {
  const { page } = env;
  await page.goto(`${env.base}/time/`, { waitUntil: "networkidle" });
  await page.getByRole("tab", { name: "Unbilled work" }).click();
  await page.getByRole("button", { name: "Bill this time" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("[data-bill-time]").waitFor();
  return dialog;
}

export const scenarios = [
  {
    id: "a-clients-time-becomes-one-draft-and-the-screen-works-nothing-out",
    title: "Bill this time: the server's entries, worths, lines and total; an unbillable entry has no tick; the request carries what was ticked and typed; the dialog links to the draft",
    async run(env) {
      const seen = serve(env);
      const dialog = await open(env);
      await dialog.locator('[data-entry="e-1"]').waitFor();
      // The entry with no rate says why, has no worth and cannot be ticked.
      const blocked = dialog.locator('[data-entry="e-3"]');
      assert.match(await blocked.innerText(), /It has no rate\. Set its rate first\./);
      assert.match(await blocked.innerText(), /—/);
      assert.equal(await blocked.locator("input").isDisabled(), true);
      assert.equal(await blocked.locator("input").isChecked(), false);
      // The preview is the server's, of exactly the two ticked entries.
      const total = dialog.locator("[data-bill-time-total]");
      await until(async () => (await total.count()) === 1, "the preview");
      assert.match(await total.innerText(), /2,750\.00/);
      assert.deepEqual(seen.previews.at(-1), { client_id: env.clientId, entry_ids: ["e-1", "e-2"], group_by: "by_task" });

      // Unticking one asks again, and the total that follows is the server's new one.
      await dialog.locator('[data-entry="e-2"] input').uncheck();
      await until(async () => seen.previews.at(-1).entry_ids.length === 1 && /1,500\.00/.test(await total.innerText().catch(() => "")), "the new preview");
      await dialog.locator('[data-entry="e-2"] input').check();
      await dialog.getByLabel("On the invoice").selectOption("single");
      await until(async () => seen.previews.at(-1).group_by === "single" && (await total.count()) === 1, "the preview of the new layout");

      // One service in the practice's catalogue: it is chosen, and the GST box starts from the rate recorded against it.
      assert.equal(await dialog.getByLabel(/Billed as/).inputValue(), "svc-fees");
      assert.equal(await dialog.getByLabel("GST rate (%)").inputValue(), "18");
      await dialog.getByRole("button", { name: "Make the draft invoice" }).click();
      await dialog.locator("[data-bill-time-made]").waitFor();
      assert.deepEqual(seen.created, [{ client_id: env.clientId, entry_ids: ["e-1", "e-2"], group_by: "single", service_id: "svc-fees", gst_rate_percent: 18 }]);
      assert.match(await dialog.locator("[data-bill-time-made]").innerText(), /A draft invoice was made for ₹2,750\.00 before GST, billing 2 time entries/);
      const link = dialog.getByRole("link", { name: "Open the draft invoice" });
      assert.match(await link.getAttribute("href"), /\/clients\/c-practice\/.*invoice=inv-77/);
    },
  },
  {
    id: "no-draft-without-a-rate-of-gst-and-a-refusal-is-the-servers-words",
    title: "Bill this time: a service with no rate recorded leaves the GST box empty and the button off; a rate that is not a number is refused unsent; the server's refusal is shown as worded",
    async run(env) {
      const seen = serve(env, {
        services: [{ id: "svc-a", name: "Advice", hsn_sac: "998211", default_rate_paise: null, gst_rate_bps: null },
                   { id: "svc-b", name: "Audit", hsn_sac: "998221", default_rate_paise: null, gst_rate_bps: 1800 }],
        refuse: "Some of this time was billed by somebody else a moment ago, so no invoice was made. Reload the list and choose again.",
      });
      const dialog = await open(env);
      const make = dialog.getByRole("button", { name: "Make the draft invoice" });
      await until(async () => (await dialog.locator("[data-bill-time-total]").count()) === 1, "the preview");
      // Two services: none is chosen for the person, and nothing can be made yet.
      assert.equal(await dialog.getByLabel(/Billed as/).inputValue(), "");
      assert.equal(await make.isDisabled(), true);
      await dialog.getByLabel(/Billed as/).selectOption("svc-a");
      assert.equal(await dialog.getByLabel("GST rate (%)").inputValue(), "", "a rate was put in the box that nobody recorded");
      assert.equal(await make.isDisabled(), true, "a draft can be made with no rate of GST");
      await dialog.getByLabel("GST rate (%)").fill("18%");
      assert.match(await dialog.innerText(), /Enter the rate as a number between 0 and 100\./);
      assert.equal(await make.isDisabled(), true);
      assert.equal(seen.created.length, 0);
      await dialog.getByLabel("GST rate (%)").fill("5");
      await make.click();
      await dialog.getByRole("alert").filter({ hasText: "billed by somebody else a moment ago" }).waitFor();
      assert.equal(seen.created.at(-1).gst_rate_percent, 5);
      assert.equal(await dialog.locator("[data-bill-time-made]").count(), 0);
    },
  },
];
