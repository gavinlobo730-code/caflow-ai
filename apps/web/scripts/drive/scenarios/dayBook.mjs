/**
 * Group I: the Day Book is the server's page, says when it stopped, and its files are for the period (POST-A-091).
 *
 * The screen used to read `journal_entries` in the browser with every entry's lines embedded. It now asks
 * `GET /api/accounting/day-book` for a page the database cuts, shows it through the shared list window and offers
 * the PDF and the Excel file of the same function for the WHOLE period. A source guard can read that the call is
 * there; this drives what a CA sees: the rows, the sentence saying the window is cut short, "Show more" asking for a
 * bigger one, a file request for the period on screen and not for the window, and a failed read said in words
 * where an empty list would say "nothing posted".
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "daybook";

const ENTRIES = [
  { entry_id: "d3", entry_date: "2026-09-14", reference_no: "INV-0003", narration: "Sale to Beta Stores",
    entry_type: "Journal", source_type: "sales_invoice", source_id: "s3", debit_paise: 118000, credit_paise: 118000 },
  { entry_id: "d2", entry_date: "2026-09-02", reference_no: "JNL-0002", narration: "Accrue rent",
    entry_type: "Journal", source_type: "manual", source_id: null, debit_paise: 50000, credit_paise: 50000 },
  { entry_id: "d1", entry_date: "2026-04-01", reference_no: null, narration: "Opening",
    entry_type: "Journal", source_type: null, source_id: null, debit_paise: 25000, credit_paise: 25000 },
];

function page(limit, { hasMore = true } = {}) {
  return {
    start_date: "2026-04-01", end_date: "2027-03-31", entries: ENTRIES, total_entries: 1234,
    total_debit_paise: 0, total_credit_paise: 0,
    sources: [{ source_type: "manual", entries: 1 }, { source_type: "sales_invoice", entries: 1 },
              { source_type: null, entries: 1 }],
    newest_first: true, limit, offset: 0, returned: ENTRIES.length, has_more: hasMore, max_limit: 1000,
  };
}

/** `waitForLoadState("networkidle")` resolves at once for a document that has already been idle, so it cannot wait for a read a
 *  click starts afterwards: a scenario waits for the request itself, and then for the screen to have drawn the answer. */
async function until(condition, what) {
  for (let i = 0; i < 100; i += 1) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.fail(`timed out waiting for ${what}`);
}

/** Answer the Day Book and remember every request, so a scenario can read what the screen asked for. */
function stubDayBook(env, reply) {
  const asked = [];
  env.stub.route({
    method: "GET", re: /accounting\/day-book/,
    reply: (req, body, url) => {
      const limit = Number(url.searchParams.get("limit") || 500);
      asked.push({ search: url.search, params: Object.fromEntries(url.searchParams) });
      return reply(limit, asked.length);
    },
  });
  return asked;
}

async function openDayBook(env) {
  await env.page.goto(env.at("/accounting/?tab=day-book"), { waitUntil: "networkidle" });
}

export const scenarios = [
  {
    id: "the-page-is-the-servers-and-says-it-is-cut-short",
    title: "the Day Book shows the server's page, names where each posting came from, and says the window stopped",
    async run(env) {
      const { page: pg } = env;
      const asked = stubDayBook(env, (limit) => ok(page(limit)));
      await openDayBook(env);
      await pg.getByText("INV-0003").waitFor();

      assert.equal(asked.length, 1, `the screen should read the page once, it read ${asked.length} times`);
      const q = asked[0].params;
      assert.equal(q.client_id, CLIENT_ID, "the read was not for this client");
      assert.equal(q.newest_first, "true", "the Day Book opens newest first");
      assert.match(q.start_date, /^\d{4}-\d{2}-\d{2}$/);
      assert.match(q.end_date, /^\d{4}-\d{2}-\d{2}$/);

      const body = await pg.locator("body").innerText();
      assert.match(body, /Sales invoice/, "the Source column names the document behind a posting");
      assert.match(body, /Manual/, "and a typed entry says so");
      assert.match(body, /Showing the latest 500 entries, of 1,234 posted in this period\. More exist that are not shown here\./,
        "a cut-short Day Book must say so, with how many the period holds");
      assert.ok(await pg.getByRole("button", { name: "Show more" }).count() === 1, "the window can be grown");
      assert.equal(await pg.getByRole("columnheader", { name: "Status" }).count(), 0,
        "a Day Book lists posted entries only, so it carries no Status column");
      assert.ok(await pg.getByRole("button", { name: "PDF" }).count() >= 1, "no PDF button");
      assert.ok(await pg.getByRole("button", { name: "Excel" }).count() >= 1, "no Excel button");
    },
  },
  {
    id: "show-more-asks-the-server-for-a-bigger-window",
    title: "Show more reads again with a larger limit, and a window that is not cut short says nothing",
    async run(env) {
      const { page: pg } = env;
      const asked = stubDayBook(env, (limit, n) => ok(page(limit, { hasMore: n < 2 })));
      await openDayBook(env);
      await pg.getByText("INV-0003").waitFor();
      await pg.getByRole("button", { name: "Show more" }).click();
      await until(() => asked.length >= 2, "the second read");
      await pg.getByText("More exist that are not shown here").waitFor({ state: "detached" });
      assert.equal(asked.length, 2, `Show more should read once more, the screen read ${asked.length} times`);
      assert.equal(asked[1].params.limit, "600", "the next window is one step larger, up to the server's ceiling");
      assert.equal(await pg.getByText("More exist that are not shown here").count(), 0,
        "the server said nothing more exists, so the notice goes away");
    },
  },
  {
    id: "a-new-period-starts-from-the-servers-window-with-one-read",
    title: "after Show more, choosing another period reads that period once, from the server's own window",
    async run(env) {
      const { page: pg } = env;
      const asked = stubDayBook(env, (limit) => ok(page(limit)));
      await openDayBook(env);
      await pg.getByText("INV-0003").waitFor();
      await pg.getByRole("button", { name: "Show more" }).click();
      await until(() => asked.length >= 2, "the second read");
      assert.equal(asked[1].params.limit, "600");

      const select = pg.getByLabel("Date range");
      const current = await select.inputValue();
      const other = (await select.locator("option").evaluateAll((os) => os.map((o) => o.value)))
        .find((v) => v !== current && v !== "custom");
      assert.ok(other, "the picker offers another period");
      await select.selectOption(other);
      await until(() => asked.length >= 3, "the read for the new period");
      // An effect that reset the grown limit AFTER the range changed read the new period a second time a moment later.
      await new Promise((resolve) => setTimeout(resolve, 600));

      assert.equal(asked.length, 3, `choosing a period should read once, the screen read ${asked.length - 2} times`);
      assert.notEqual(asked[2].params.start_date + asked[2].params.end_date, asked[1].params.start_date + asked[1].params.end_date,
        "the period really changed");
      assert.equal(asked[2].params.limit, undefined, "a new period starts from the server's window, not the grown one");
    },
  },
  {
    id: "a-failed-read-takes-the-last-periods-window-notice-down",
    title: "when the read after a good one fails, the sentence about the earlier window is not left above the error",
    async run(env) {
      const { page: pg } = env;
      stubDayBook(env, (limit, n) => (n === 1
        ? ok(page(limit))
        : { success: false, data: null, error: "The Day Book could not be read. Please try again." }));
      await openDayBook(env);
      await pg.getByText("INV-0003").waitFor();
      assert.equal(await pg.getByText(/Showing the latest 500 entries/).count(), 1);
      await pg.getByRole("button", { name: "Show more" }).click();
      await pg.getByText("The Day Book could not be read. Please try again.").waitFor();
      assert.equal(await pg.getByText(/Showing the latest 500 entries/).count(), 0,
        "the notice still described the window before the failed read");
    },
  },
  {
    id: "the-file-is-for-the-period-and-not-the-window",
    title: "PDF and Excel ask the server's export for the period on screen, the same one the table was read for",
    async run(env) {
      const { page: pg } = env;
      const reads = stubDayBook(env, (limit) => ok(page(limit)));
      const files = [];
      env.stub.route({
        method: "GET", re: /report-exports\/day-book/,
        reply: (req, body, url) => { files.push(Object.fromEntries(url.searchParams)); return ok({}); },
      });
      await openDayBook(env);
      await pg.getByText("INV-0003").waitFor();
      await pg.getByRole("button", { name: "PDF" }).first().click();
      await until(() => files.length >= 1, "the PDF request");
      await pg.getByRole("button", { name: "Excel" }).first().click();
      await until(() => files.length >= 2, "the Excel request");

      assert.equal(files.length, 2, `two files were asked for, the screen asked for ${files.length}`);
      assert.deepEqual(files.map((f) => f.format), ["pdf", "xlsx"]);
      for (const f of files) {
        assert.equal(f.client_id, CLIENT_ID);
        assert.equal(f.start_date, reads[0].params.start_date, "the file is for the period the table shows");
        assert.equal(f.end_date, reads[0].params.end_date);
        assert.equal(f.limit, undefined, "a file is never for the window");
      }
    },
  },
  {
    id: "a-failed-read-is-said-and-is-never-an-empty-book",
    title: "a Day Book that could not be read says so, and does not say nothing was posted",
    async run(env) {
      const { page: pg } = env;
      stubDayBook(env, () => ({ success: false, data: null, error: "The Day Book could not be read. Please try again." }));
      await openDayBook(env);
      await pg.getByText("The Day Book could not be read. Please try again.").waitFor();
      assert.equal(await pg.getByText("Nothing posted in this period").count(), 0,
        "a failed read was shown as an empty book");
    },
  },
];
