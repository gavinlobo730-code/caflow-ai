/**
 * THE BOOKS EXPORT CARD, DRIVEN IN A BROWSER (POST-A-205, slice 1).
 *
 * The client's Reports hub offers a Partner one ZIP of CSV files of the books. Against a stubbed server, in Chromium:
 *
 *   1. a Partner presses the button and gets a download named by the server, exactly ONE request is made, and the card says it was downloaded and to read the manifest;
 *   2. when the server says the build found a problem in itself (the `X-Export-Problems` header) the card says so, in words, beside the download;
 *   3. a refusal (the client is too large to read in one request) is shown as the server's own sentence and nothing is reported as downloaded;
 *   4. a second press while the first is being answered makes no second request (the build holds a worker for up to ninety seconds);
 *   5. a Manager who has been GRANTED `firm:admin` does not see the card at all: the permission alone does not offer it, because the server asks for the Partner role too.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID, FAKE_USERS_ROW } from "../fixtures.mjs";

export const group = "books-export";

const ZIP = Buffer.from("PK\u0005\u0006" + "\u0000".repeat(18), "binary");   // an empty archive: the browser saves bytes, it does not open them
const CARD = '[data-testid="books-export-card"]';
const BUTTON = "Download books (CSV)";

const FILE = (headers = {}) => ({
  status: 200,
  reply: () => ({}),
  file: { body: ZIP, type: "application/zip", headers: { "content-disposition": 'attachment; filename="books-acme-traders-pvt-ltd-2026-11-12.zip"', ...headers } },
});

async function atTheReportsHub(env, { role = "Partner", route }) {
  const { page, stub } = env;
  let requests = 0;
  stub.setTable("users", [{ ...FAKE_USERS_ROW, role }]);
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role, permissions: { firm: ["read", "write", "admin"] } }) });
  if (route) stub.route({ method: "GET", re: /\/api\/data-export\/client-books\?client_id=/, ...route(() => { requests += 1; }) });
  await page.goto(`${env.base}/clients/${CLIENT_ID}/reports/`, { waitUntil: "networkidle" });
  return { requests: () => requests, card: page.locator(CARD) };
}

/** A route that counts the request, then answers as `answer` says. */
const answering = (answer, extra = {}) => (hit) => ({ ...answer, ...extra, reply: (...a) => { hit(); return answer.reply(...a); } });

export const scenarios = [
  {
    id: "a-partner-presses-the-button-and-gets-the-file-with-one-request",
    title: "Reports > Take this client's books with you: a Partner's press downloads the file the server named, makes ONE request, and the card says to read the manifest",
    async run(env) {
      const { page } = env;
      const at = await atTheReportsHub(env, { route: (hit) => answering(FILE())(hit) });
      await at.card.waitFor({ timeout: 10000 });
      const [download] = await Promise.all([page.waitForEvent("download"), at.card.getByRole("button", { name: BUTTON, exact: true }).click()]);
      assert.equal(download.suggestedFilename(), "books-acme-traders-pvt-ltd-2026-11-12.zip", "the file was not named by the server");
      await at.card.getByText("Downloaded. Check manifest.json inside the file before relying on it.").waitFor();
      assert.equal(at.requests(), 1, `expected ONE request, saw ${at.requests()}`);
      assert.equal(await at.card.getByRole("alert").count(), 0, "the card showed an alert for a clean download");
      const says = await at.card.innerText();
      for (const promise of ["Not in it yet:", "payroll", "the bank", "the audit log", "not a snapshot"]) {
        assert.ok(says.includes(promise), `the card does not say "${promise}"`);
      }
    },
  },
  {
    id: "a-problem-the-build-found-in-itself-is-said-beside-the-download",
    title: "Reports > the books export: when the server's header says the build found a problem in itself, the card says so in words and points at the manifest",
    async run(env) {
      const { page } = env;
      const problem = "1 problem(s) found; see manifest.json inside the file";
      const at = await atTheReportsHub(env, { route: (hit) => answering(FILE({ "x-export-problems": problem }))(hit) });
      await at.card.waitFor({ timeout: 10000 });
      await Promise.all([page.waitForEvent("download"), at.card.getByRole("button", { name: BUTTON, exact: true }).click()]);
      const alert = at.card.getByRole("alert");
      await alert.waitFor();
      const text = await alert.innerText();
      assert.ok(text.includes("The export found a problem in itself:") && text.includes(problem) && text.includes("manifest.json"), `the problem was not said: ${text}`);
    },
  },
  {
    id: "a-refusal-is-the-servers-own-sentence-and-nothing-is-reported-downloaded",
    title: "Reports > the books export: a refusal (too large to read in one request) is shown as the server's sentence, and the card does not say it downloaded",
    async run(env) {
      const { page } = env;
      const sentence = "This client has 30,000 journal entries, more than the 25,000 the export reads in one request, so nothing was read.";
      const at = await atTheReportsHub(env, { route: (hit) => answering(refuse(sentence, 422))(hit) });
      await at.card.waitFor({ timeout: 10000 });
      await at.card.getByRole("button", { name: BUTTON, exact: true }).click();
      await at.card.getByRole("alert").filter({ hasText: sentence }).waitFor();
      assert.equal(await at.card.getByText("Downloaded.").count(), 0, "a refused export was reported as downloaded");
      assert.equal(await page.getByRole("button", { name: BUTTON, exact: true }).isEnabled(), true, "the button stayed disabled after a refusal");
    },
  },
  {
    id: "a-second-press-while-the-first-is-answered-makes-no-second-request",
    title: "Reports > the books export: a second press while the build is being answered makes no second request",
    async run(env) {
      const { page } = env;
      const at = await atTheReportsHub(env, { route: (hit) => answering(FILE(), { delay: 900 })(hit) });
      await at.card.waitFor({ timeout: 10000 });
      const button = at.card.getByRole("button", { name: BUTTON, exact: true });
      await button.click();
      await at.card.getByRole("button", { name: "Preparing the files…" }).waitFor();
      assert.equal(await at.card.getByRole("button", { name: "Preparing the files…" }).isDisabled(), true, "the button was not disabled while the file was being made");
      await page.waitForEvent("download");
      await until(() => at.requests() >= 1, "the request", 5000);
      assert.equal(at.requests(), 1, `a second press made a second request (${at.requests()})`);
    },
  },
  {
    id: "a-manager-granted-the-permission-is-not-offered-the-card",
    title: "Reports > the books export: a Manager who was granted firm:admin does not see the card, because the server asks for the Partner role as well",
    async run(env) {
      const { page } = env;
      const at = await atTheReportsHub(env, { role: "Manager" });
      await page.getByText("Financial statements", { exact: true }).first().waitFor({ timeout: 10000 });
      assert.equal(await at.card.count(), 0, "the card was offered to a Manager");
    },
  },
];
