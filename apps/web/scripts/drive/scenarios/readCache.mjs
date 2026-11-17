/**
 * Group: the shared read cache paints the Clients list from the last answer, says so, and is cleared by the person's own write (POST-A-124).
 *
 * With the server held for three seconds, a SECOND open of the client list (by in-app navigation, which keeps the page's memory) paints the list inside a
 * second, says when the painted list was read, and replaces the line once the real read lands. A first open, with nothing to paint, shows the loading
 * placeholder; archiving a client forgets the cached list, so the next open is not painted from before the write.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "read-cache";

const NOTICE = /Showing the list as it was read at/;

async function openClients(env) {
  const { page, stub } = env;
  stub.setTable("clients", [CLIENT_ROW]);
  await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
  await page.getByText("Acme Traders Pvt Ltd").first().waitFor({ timeout: 15000 });
}
/** Leave the list and come back by the app's own links, so the page's memory (and the cache) survives. */
async function leaveAndReturn(page) {
  await page.getByRole("link", { name: /Pipeline/ }).first().click();
  await page.waitForURL(/\/pipeline/);
  await page.locator('a[href="/clients"], a[href="/clients/"]').first().click();
  await page.waitForURL(/\/clients\/?$/);
}

export const scenarios = [
  {
    id: "a-second-open-of-the-client-list-paints-at-once-and-says-when-it-was-read",
    title: "Clients: with the server held 3 s, coming back to the list paints it within a second under a line saying when it was read, and the line goes when the real read lands",
    async run(env) {
      const { page, stub } = env;
      await openClients(env);
      assert.equal(await page.getByText(NOTICE).count(), 0, "a first open claimed to show an older list");
      stub.setReadDelay("clients", 3000);
      const t0 = Date.now();
      await leaveAndReturn(page);
      await page.getByText("Acme Traders Pvt Ltd").first().waitFor({ timeout: 1500 });
      const painted = Date.now() - t0;
      await page.getByText(NOTICE).waitFor({ timeout: 1500 });
      assert.ok(painted < 2500, `the list took ${painted} ms to come back, against a 3 s server`);
      await until(async () => (await page.getByText(NOTICE).count()) === 0, "the 'as it was read' line to go once the real read landed", 8000);
      await page.getByText("Acme Traders Pvt Ltd").first().waitFor();
    },
  },
  {
    id: "archiving-a-client-forgets-the-cached-list",
    title: "Clients: after archiving, coming back to the list is NOT painted from the answer read before the write",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: /api\/clients\/[^/]+\/archive$/, reply: () => ok({}) });
      // The Archive control is offered only to someone the route admits (client:write), so the caller is given that.
      stub.route({ method: "GET", re: /api\/identity\/permissions/, reply: () => ok({ permissions: { client: ["read", "write", "delete"] } }) });
      await openClients(env);
      await page.getByTitle("More actions").first().click({ force: true });
      await page.getByRole("button", { name: /^Archive$/ }).first().click();
      await page.getByRole("button", { name: /^Archive$/ }).last().click();
      await until(async () => stub.writesTo(/api\/clients\/[^/]+\/archive$/, "POST").length === 1, "the archive to be sent");
      stub.setTable("clients", []);
      stub.setReadDelay("clients", 2500);
      await leaveAndReturn(page);
      await new Promise((r) => setTimeout(r, 700));
      assert.equal(await page.getByText(NOTICE).count(), 0, "the list was painted from before the archive");
      assert.equal(await page.getByText("Acme Traders Pvt Ltd").count(), 0, "the archived client was shown from the cache");
    },
  },
];
