/**
 * Group R: the Add Account drawer on a client's Chart of Accounts, driven in a browser (POST-A-123, the add-account row of what was
 * still missing).
 *
 * The drawer has no amount, so what matters here is WHOSE account it creates and that it is created once. A client's own chart is the
 * default and a firm-level account (shared by every client of the firm) is the exception the CA must ask for: "a stray firm-level
 * account from a client screen would appear on every OTHER client's chart too". The source guards hold the wording; this proves what
 * the request says, in Chromium, against a stubbed server:
 *
 *   1. by default the account is created FOR THIS CLIENT (the request carries the client), with the name, code and type typed;
 *   2. ticking "shared across every client" sends the request with NO client, and nothing else changes;
 *   3. two clicks on Add Account in the same tick send ONE create;
 *   4. a missing name or code is refused in words and nothing is sent;
 *   5. a refusal is shown as the server wrote it, the drawer keeps what was typed, and the next press sends a second create.
 */
import assert from "node:assert/strict";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "add-account";

const CREATE = /api\/accounting\/accounts(\?|$)/;
const NAME = "e.g. HDFC Bank — Current A/c";

async function atTheDrawer(env) {
  const { page } = env;
  await page.goto(env.at("/accounting/?tab=coa"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Add Account" }).first().click();
  await page.getByPlaceholder(NAME).waitFor();
}

const addButton = (page) => page.getByRole("button", { name: "Add Account", exact: true }).last();
const created = (stub) => stub.writesTo(CREATE, "POST");

async function fill(page, name = "Petty Cash — Branch", code = "1099") {
  await page.getByPlaceholder(NAME).fill(name);
  await page.getByPlaceholder("1001").fill(code);
}

export const scenarios = [
  {
    id: "an-account-is-created-for-this-client-by-default",
    title: "the request carries this client, the name, the code and the type, and the drawer closes",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "a-new" }) });
      await atTheDrawer(env);
      await fill(page);
      await addButton(page).click();
      await expectWrites(stub, CREATE, 1, "creating an account", "POST");
      const [write] = created(stub);
      assert.ok(new URLSearchParams(write.search).get("client_id") === CLIENT_ID, `the request does not name this client: ${write.path}${write.search}`);
      const body = JSON.parse(write.body);
      assert.strictEqual(body.name, "Petty Cash — Branch");
      assert.strictEqual(body.code, "1099");
      assert.strictEqual(body.account_type, "Asset");
      await page.getByPlaceholder(NAME).waitFor({ state: "detached" });
    },
  },
  {
    id: "ticking-shared-across-every-client-sends-no-client",
    title: "a firm-level account is created without a client, and only when it was asked for",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "a-new" }) });
      await atTheDrawer(env);
      await fill(page);
      await page.getByRole("checkbox").check();
      await addButton(page).click();
      await expectWrites(stub, CREATE, 1, "creating a firm-level account", "POST");
      const [write] = created(stub);
      assert.ok(!new URLSearchParams(write.search).has("client_id"), `a firm-level account was sent with a client: ${write.path}${write.search}`);
    },
  },
  {
    id: "two-clicks-on-add-account-in-one-tick-create-one-account",
    title: "Add Account pressed twice in the same tick sends ONE create",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "a-new" }) });
      await atTheDrawer(env);
      await fill(page);
      await sameTickDouble(addButton(page));
      await expectWrites(stub, CREATE, 1, "two same-tick clicks on Add Account", "POST");
    },
  },
  {
    id: "a-missing-name-or-code-is-refused-in-words-and-nothing-is-sent",
    title: "a blank name, then a blank code, are each refused in the drawer's own sentence with nothing created",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "a-new" }) });
      await atTheDrawer(env);
      await addButton(page).click();
      await page.getByText("Account name is required.").waitFor();
      await page.getByPlaceholder(NAME).fill("Petty Cash — Branch");
      await addButton(page).click();
      await page.getByText(/An account code is required/).waitFor();
      await expectWrites(stub, CREATE, 0, "an account with no name or code", "POST");
      assert.strictEqual(await addButton(page).isDisabled(), false, "the button stayed held after a refusal made in the browser");
    },
  },
  {
    id: "a-server-refusal-is-shown-and-the-next-press-creates-one-account",
    title: "a refusal is shown as the server wrote it, the drawer keeps what was typed, and the next press sends a second create",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "Account code 1099 is already used in this chart.";
      stub.route({ method: "POST", re: CREATE, ...refuse(REFUSED, 409) });
      await atTheDrawer(env);
      await fill(page);
      await addButton(page).click();
      await page.getByText(REFUSED).waitFor();
      assert.strictEqual(await page.getByPlaceholder("1001").inputValue(), "1099", "the typed code was lost on a refusal");
      assert.strictEqual(await addButton(page).isDisabled(), false, "the button stayed held after a server refusal");
      await expectWrites(stub, CREATE, 1, "the refused press", "POST");

      stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "a-new" }) });
      await addButton(page).click();
      await until(() => created(stub).length === 2, "the second create to arrive");
    },
  },
];
