/**
 * Group: a client's Customers and Vendors lists are painted from the shared read cache, say so, and are forgotten by a write (POST-A-124).
 *
 * With the server held for three seconds, coming back to the tab (by the page's own tab buttons, which keep the page's memory) paints the
 * list inside a second and a half under a line saying when it was read, and the line goes when the real read lands. Deactivating a customer
 * forgets the cached list, so the next visit is not painted from before the write.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CUSTOMER, VENDOR } from "../fixtures.mjs";

export const group = "party-list-cache";
const NOTICE = /Showing the list as it was read at/;

/** Open a tab of a client page, leave it for another tab and come back, with the table held `ms` on the way back. */
async function backToTab(env, { path, table, tab, other, name, ms }) {
  const { page, stub } = env;
  await page.goto(env.at(path), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: tab, exact: true }).first().click();
  await page.getByText(name).first().waitFor({ timeout: 15000 });
  assert.equal(await page.getByText(NOTICE).count(), 0, "a first open claimed to show an older list");
  await page.getByRole("button", { name: other, exact: true }).first().click();
  stub.setReadDelay(table, ms);
  const t0 = Date.now();
  await page.getByRole("button", { name: tab, exact: true }).first().click();
  return t0;
}

const PERMS = () => ok({ role: "Partner", permissions: { client: ["read", "write", "delete"], accounting: ["read", "write"] } });

export const scenarios = [
  {
    id: "coming-back-to-customers-or-vendors-paints-at-once-says-when-it-was-read-and-a-deactivation-forgets-it",
    title: "Sales > Customers and Purchases > Vendors: with the server held 3 s, coming back to the tab paints the list at once under a line saying when it was read; and after a customer's deactivation it is NOT painted from the answer read before the write",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("customers", [CUSTOMER]);
      const t0 = await backToTab(env, { path: "/sales/", table: "customers", tab: "Customers", other: "Sales Invoices", name: CUSTOMER.name, ms: 3000 });
      await page.getByText(CUSTOMER.name).first().waitFor({ timeout: 1500 });
      await page.getByText(NOTICE).waitFor({ timeout: 1500 });
      assert.ok(Date.now() - t0 < 2500, `the list took ${Date.now() - t0} ms to come back, against a 3 s server`);
      await until(async () => (await page.getByText(NOTICE).count()) === 0, "the line to go once the real read landed", 8000);
      // ...and Purchases > Vendors, the same way.
      {
      
      stub.setTable("vendors", [VENDOR]);
      const t1 = await backToTab(env, { path: "/purchases/", table: "vendors", tab: "Vendors", other: "Purchase Bills", name: VENDOR.name, ms: 3000 });
      await page.getByText(VENDOR.name).first().waitFor({ timeout: 1500 });
      await page.getByText(NOTICE).waitFor({ timeout: 1500 });
      assert.ok(Date.now() - t1 < 2500, `the list took ${Date.now() - t1} ms to come back, against a 3 s server`);
      await until(async () => (await page.getByText(NOTICE).count()) === 0, "the line to go once the real read landed", 8000);
      }
      // ...and a deactivation forgets the cached list: a fresh page load (the cache is the page's memory), the holds above let go.
      {
      stub.setReadDelay("customers", 0);
      stub.setReadDelay("vendors", 0);
      stub.route({ method: "GET", re: /api\/identity\/permissions/, reply: PERMS });
      stub.setTable("customers", [CUSTOMER]);
      await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Customers", exact: true }).first().click();
      await page.getByLabel(`Actions for ${CUSTOMER.name}`).click();
      await page.getByRole("button", { name: "Deactivate", exact: true }).first().click();
      // The screen reads the list again after its write; that read is held long enough that the visit below comes back first, so what
      // the visit paints can only be what was cached before the write, unless the write forgot it.
      stub.setReadDelay("customers", 5000);
      await page.getByRole("button", { name: "Deactivate", exact: true }).last().click();
      await until(async () => stub.writesTo(/customers/, "PATCH").length === 1, "the deactivation to be sent");
      await page.getByRole("button", { name: "Sales Invoices", exact: true }).first().click();
      await page.getByRole("button", { name: "Customers", exact: true }).first().click();
      await new Promise((r) => setTimeout(r, 700));
      assert.equal(await page.getByText(NOTICE).count(), 0, "the list was painted from before the deactivation");
      }
    },
  },
];
