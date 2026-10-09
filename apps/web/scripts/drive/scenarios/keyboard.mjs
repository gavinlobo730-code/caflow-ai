/**
 * Group B: the ledger is operable from the keyboard (frontend_ux-16).
 *
 * A clickable row was a `<tr onClick>` with no tab stop, no key handling and no focus ring, and nine screens
 * use one, the journal list and the ledger drill-through among them. `lib/table/rowKeyboard` is the rule and
 * `DataTable` renders it; the render tests prove the attributes are on the row. These drive the thing a keyboard
 * user does: Tab until a row has focus, move with the arrows, open with Enter or Space, and press a key in a
 * control INSIDE a row without opening the row.
 *
 * The list is shown newest first, so the scenarios read the order off the page and never assume which entry is
 * on top: what is held is "the arrow moves to the NEXT row on the screen", not a particular reference.
 */
import assert from "node:assert/strict";

export const group = "keyboard";

async function openJournalList({ page, at }) {
  await page.goto(at("/accounting/?tab=journal"), { waitUntil: "networkidle" });
  await page.waitForSelector("tr[data-row-clickable]");
}

/** The reference numbers of the clickable rows, top to bottom. */
function listOrder(page) {
  return page.locator("tr[data-row-clickable]").evaluateAll(
    (rows) => rows.map((r) => (r.innerText.match(/JNL-\d+/) || [""])[0]));
}

/** Which journal row has focus, by reference number, or null when focus is not on a clickable row. */
function focusedRow(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el.tagName !== "TR" || !el.hasAttribute("data-row-clickable")) return null;
    return (el.innerText.match(/JNL-\d+/) || [null])[0];
  });
}

/** Press Tab from the top of the page until a clickable row has focus, as a person who cannot use a mouse does. */
async function tabToFirstRow(page) {
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  for (let hops = 1; hops <= 120; hops += 1) {
    await page.keyboard.press("Tab");
    if (await focusedRow(page)) return hops;
  }
  throw new Error("120 presses of Tab never reached a clickable row: a row is not a tab stop");
}

/** The journal entry id behind a reference (the fixtures name them JNL-00n and e n). */
const entryIdOf = (ref) => `e${Number(ref.replace(/\D/g, ""))}`;

export const scenarios = [
  {
    id: "tab-reaches-a-row",
    title: "Tab reaches a ledger row, and the row is a tab stop",
    async run(env) {
      await openJournalList(env);
      const order = await listOrder(env.page);
      assert.ok(order.length >= 3, `the fixtures should give three rows, the page shows ${order.length}`);
      assert.equal(await env.page.locator("tr[data-row-clickable]").first().getAttribute("tabindex"), "0",
        "a clickable row must be a tab stop");
      await tabToFirstRow(env.page);
      assert.equal(await focusedRow(env.page), order[0], "the first row to take focus is the top row of the list");
    },
  },
  {
    id: "arrows-move-and-clamp",
    title: "ArrowDown and ArrowUp move between rows and stop at the ends",
    async run(env) {
      await openJournalList(env);
      const order = await listOrder(env.page);
      await tabToFirstRow(env.page);
      await env.page.keyboard.press("ArrowUp");
      assert.equal(await focusedRow(env.page), order[0], "ArrowUp on the first row stays on it (no wrap to the last)");
      await env.page.keyboard.press("ArrowDown");
      assert.equal(await focusedRow(env.page), order[1]);
      for (let i = 0; i < order.length + 2; i += 1) await env.page.keyboard.press("ArrowDown");
      assert.equal(await focusedRow(env.page), order[order.length - 1],
        "ArrowDown past the last row stays on it (no wrap to the first)");
      await env.page.keyboard.press("ArrowUp");
      assert.equal(await focusedRow(env.page), order[order.length - 2]);
    },
  },
  {
    id: "enter-opens-the-row",
    title: "Enter on a focused row opens its entry",
    async run(env) {
      await openJournalList(env);
      const order = await listOrder(env.page);
      await tabToFirstRow(env.page);
      await env.page.keyboard.press("ArrowDown");
      await env.page.keyboard.press("Enter");
      await env.page.waitForURL(new RegExp(`/accounting/journal/${entryIdOf(order[1])}/edit/?`));
    },
  },
  {
    id: "space-opens-the-row",
    title: "Space on a focused row opens its entry",
    async run(env) {
      await openJournalList(env);
      const order = await listOrder(env.page);
      await tabToFirstRow(env.page);
      await env.page.keyboard.press("ArrowDown");
      await env.page.keyboard.press("ArrowDown");
      await env.page.keyboard.press("Space");
      await env.page.waitForURL(new RegExp(`/accounting/journal/${entryIdOf(order[2])}/edit/?`));
    },
  },
  {
    id: "a-key-in-a-control-inside-a-row-does-not-open-the-row",
    title: "Space on a checkbox inside a row ticks the checkbox and leaves the row shut",
    async run(env) {
      await openJournalList(env);
      const box = env.page.locator("tr[data-row-clickable]").first().locator('input[type="checkbox"]').first();
      assert.ok(await box.count(), "the journal list rows carry no checkbox: this scenario needs a control inside a row");
      const before = env.page.url();
      await box.focus();
      await env.page.keyboard.press("Space");
      assert.equal(await box.isChecked(), true, "Space on the checkbox did not tick it");
      await env.page.waitForTimeout(400);
      assert.equal(env.page.url(), before, "a key pressed in a control inside the row opened the row");
    },
  },
];
