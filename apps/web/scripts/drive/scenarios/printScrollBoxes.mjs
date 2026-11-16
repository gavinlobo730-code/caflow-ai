/**
 * Group: print-scroll-boxes. A list held to a height with its own scroll bar prints every row (POST-A-217).
 *
 * Forty-four files hold a list to a height (`max-h-* overflow-y-auto`). Paper has nothing to scroll, so a box that kept its height printed
 * its first screenful and cut the rest off with no sign anything was missing. The print block of the app's own stylesheet now draws such a
 * box in full. These scenarios load the built app, put a long list in a box classed the way the screens class theirs, and read it in print
 * media: every row is inside the box's drawn height. On screen the same box still scrolls.
 */
import assert from "node:assert/strict";

export const group = "print-scroll-boxes";

/** A box the way the screens draw one: a height limit, the scroll class, sixty rows. */
async function plantBox(page, classes) {
  await page.locator("main").first().waitFor();
  await page.evaluate((cls) => {
    const box = document.createElement("div");
    box.id = "planted-scroll-box";
    box.className = cls;
    box.style.maxHeight = "120px";
    for (let i = 1; i <= 60; i += 1) {
      const row = document.createElement("div");
      row.textContent = `Row ${i}`;
      row.style.height = "20px";
      box.appendChild(row);
    }
    document.querySelector("main")?.appendChild(box);
  }, classes);
}

async function measure(page) {
  return page.evaluate(() => {
    const box = document.getElementById("planted-scroll-box");
    const last = box.lastElementChild.getBoundingClientRect();
    const rect = box.getBoundingClientRect();
    return { scroll: box.scrollHeight, client: box.clientHeight, lastInside: last.bottom <= rect.bottom + 1, maxHeight: getComputedStyle(box).maxHeight };
  });
}

export const scenarios = ["overflow-y-auto", "overflow-auto"].map((cls) => ({
  id: `a-${cls}-list-prints-every-row`,
  title: `a list held to a height with ${cls} prints all sixty rows, and still scrolls on screen`,
  async run({ page, base }) {
    await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
    await plantBox(page, `${cls} rounded border`);
    const screen = await measure(page);
    assert.ok(screen.scroll > screen.client + 1, `premise: on screen the box scrolls (scroll ${screen.scroll}, drawn ${screen.client})`);
    await page.emulateMedia({ media: "print" });
    const paper = await measure(page);
    assert.equal(paper.maxHeight, "none", `on paper the box kept its height limit (${paper.maxHeight})`);
    assert.ok(paper.lastInside && paper.scroll <= paper.client + 1,
      `on paper the box cut its rows off: it is drawn ${paper.client}px tall and holds ${paper.scroll}px`);
    await page.emulateMedia({ media: "screen" });
    const back = await measure(page);
    assert.ok(back.scroll > back.client + 1, "back on screen the box no longer scrolls");
  },
}));
