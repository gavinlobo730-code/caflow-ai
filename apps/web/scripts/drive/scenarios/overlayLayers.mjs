/**
 * Group: overlay-layers. The dark layer behind a dialog covers the whole window (PRE-A-022).
 *
 * The shared dialog's layer is `fixed inset-0`, and the Team page rendered it inside a container spaced with
 * `space-y-6`: the 24 px top margin reached the fixed layer, so it started 24 px below the top of the window and
 * cut the navy bar in two through the PracticeSync name (the owner's screenshot of 15-11-2026). The shared dialog,
 * side panel and confirm box now draw their layer in the document body. This opens one of each that a page
 * renders inside a spaced container and measures the layer in Chromium: it must start at the top of the window,
 * end at its bottom, and hang from the body.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";

export const group = "overlay-layers";

/** The window-covering layer that holds the open dialog, measured. */
async function measureLayer(page) {
  return page.evaluate(() => {
    const dialogs = document.querySelectorAll('[role="dialog"]');
    const dialog = dialogs[dialogs.length - 1];
    if (!dialog) return null;
    let layer = dialog.parentElement;
    while (layer && !(getComputedStyle(layer).position === "fixed")) layer = layer.parentElement;
    if (!layer) return { found: false };
    const r = layer.getBoundingClientRect();
    return { found: true, top: r.top, bottom: r.bottom, left: r.left, right: r.right,
             height: innerHeight, width: innerWidth,
             inBody: layer.parentElement === document.body || layer.parentElement?.parentElement === document.body };
  });
}

function assertCovers(m, what) {
  assert.ok(m && m.found, `${what}: no fixed layer holds the dialog`);
  assert.strictEqual(m.top, 0, `${what}: the layer starts ${m.top}px below the top of the window`);
  assert.strictEqual(m.bottom, m.height, `${what}: the layer ends at ${m.bottom}px of ${m.height}`);
  assert.strictEqual(m.left, 0, `${what}: the layer starts ${m.left}px from the left`);
  assert.strictEqual(m.right, m.width, `${what}: the layer ends at ${m.right}px of ${m.width}`);
  assert.ok(m.inBody, `${what}: the layer is not drawn in the document body`);
}

export const scenarios = [
  {
    id: "the-team-invite-dialog-covers-the-whole-window",
    title: "the Team page's Invite Member dialog, rendered inside a spaced container, covers the window",
    async run(env) {
      const { page } = env;
      await page.goto(env.base + "/team/", { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /Invite Member/ }).first().click();
      await page.getByRole("dialog").waitFor();
      assertCovers(await measureLayer(page), "the invite dialog");
    },
  },
  {
    id: "the-add-asset-panel-covers-the-whole-window",
    title: "the fixed-asset register's Add Asset side panel covers the window",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("fixed_assets", []);
      stub.route({ method: "GET", re: /fixed-assets\/categories/, reply: () => ok([]) });
      await page.goto(env.at("/fixed-assets/"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Add Asset" }).first().click();
      await page.getByRole("dialog").waitFor();
      assertCovers(await measureLayer(page), "the Add Asset panel");
    },
  },
  {
    id: "a-dialog-opened-from-a-higher-panel-is-in-front-of-it",
    title: "Sales > invoice > Add Product/Service > New Product/Service: the dialog opened from the manager panel (drawn above it) is the thing in front and takes a click",
    async run(env) {
      const { page } = env;
      await page.goto(env.at("/sales/invoices/new/edit/"), { waitUntil: "networkidle" });
      await page.click('button[aria-label="Line 1 product or service"]');
      await page.locator("[role=listbox] [role=option]", { hasText: "Add Product/Service" }).first().click();
      await page.getByRole("button", { name: "New Product/Service" }).click();
      const dialog = page.getByRole("dialog", { name: "New Product/Service" });
      await dialog.waitFor();
      // What a pointer at the middle of the dialog's own box lands on: inside the dialog, not the panel behind it.
      const inFront = await page.evaluate(() => {
        const all = document.querySelectorAll('[role="dialog"]');
        const d = all[all.length - 1];
        const r = d.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(40, r.height / 2));
        return { title: d.getAttribute("aria-labelledby") ? document.getElementById(d.getAttribute("aria-labelledby"))?.textContent : null,
                 inside: !!hit && d.contains(hit) };
      });
      assert.ok(inFront.inside, `a click at the New Product/Service dialog lands on something else (the panel that opened it is in front)`);
      await dialog.getByPlaceholder("e.g. Statutory Audit, Steel Rod").fill("Copier paper");
      assertCovers(await measureLayer(page), "the New Product/Service dialog over the manager panel");
    },
  },
];
