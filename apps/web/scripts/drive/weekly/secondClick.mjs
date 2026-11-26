/**
 * THE BUTTONS THAT WERE LEFT UNGUARDED IGNORE A SECOND CLICK NOW (POST-A-144), driven in a browser.
 *
 * Seventy-six buttons on thirty-eight screens started a write from a raw `<button>`: their guard, where they had one, was React
 * state, which lags the click by a render, so two clicks inside one tick both passed. Each is the guarded Button now, with the look
 * the screen gave it. The source test holds all seventy-six; this drives a few of them the way the journal's Post Entry is driven
 * (`double-dispatch`): pressed twice inside one tick, against a server that holds the write, and the writes the SERVER saw counted.
 *
 *   1. the client's own signing page: Accept & Sign pressed twice signs the engagement letter once;
 *   2. a new cost centre: Save pressed twice creates one centre;
 *   3. a cost centre whose creation the server refuses, and one whose request gets no answer, says so beside the form and leaves
 *      what was typed (the handler had no answer for a request that threw);
 *   4. retiring a centre pressed twice sends one change, and a refused one is said above the list (it used to change nothing and
 *      say nothing).
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { expectWrites, sameTickDouble, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "second-click";

const LETTER = {
  engagement_number: "EL-2026-0001", title: "Engagement letter", content: "<p>Terms of the engagement.</p>", status: "Sent", recipient_name: "Asha Rao",
  firm_name: "Rao & Co", signed_at: null, signed_by_name: null, rejected_at: null, expired: false,
};
const LETTER_ROUTE = /api\/public\/engagement-letters\/abc$/;
const SIGN = /api\/public\/engagement-letters\/abc\/sign$/;

const CENTRES = /\/api\/cost-centres\?/;
const CENTRE_CREATE = /\/api\/cost-centres$/;
const CENTRE_ONE = /\/api\/cost-centres\/cc-1\?/;
const ALLOCATION = /\/api\/cost-centres\/allocation\?/;
const FACTORY = { id: "cc-1", code: "FACTORY", name: "Factory", is_active: true };

/** The client's Cost Centres tab, with `centres` on file. */
async function costCentres(env, centres) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: ALLOCATION, reply: () => ok({ centres: [], centres_with_no_activity: [], notes: [], unallocated: null }) });
  stub.route({ method: "GET", re: CENTRES, reply: () => ok({ cost_centres: centres }) });
  await page.goto(env.at("/accounting/?tab=cost-centres"), { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Cost centres", exact: true }).waitFor({ timeout: 15000 });
}

async function typeANewCentre(page) {
  await page.getByRole("button", { name: "New cost centre" }).click();
  await page.getByRole("textbox", { name: "Code", exact: true }).fill("godown");
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Godown");
  return page.getByRole("button", { name: "Save", exact: true });
}

export const scenarios = [
  {
    id: "the-signing-page-accept-and-sign-pressed-twice-signs-once",
    title: "The client's signing page: Accept & Sign pressed twice inside one tick sends ONE signature",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: LETTER_ROUTE, reply: () => ok(LETTER) });
      stub.route({ method: "POST", re: SIGN, delay: 700, reply: () => ok({ ...LETTER, status: "Signed", signed_at: "2026-11-22T10:00:00Z", signed_by_name: "Asha Rao" }) });
      await page.goto(`${env.base}/sign/?t=abc`, { waitUntil: "networkidle" });
      await page.getByLabel("Full name (your electronic signature)", { exact: true }).fill("Asha Rao");
      await page.getByRole("checkbox").check();
      stub.forgetWrites();
      await sameTickDouble(page.getByRole("button", { name: "Accept & Sign", exact: true }));
      await expectWrites(stub, SIGN, 1, "Accept & Sign pressed twice", "POST");
    },
  },
  {
    id: "a-new-cost-centre-saved-twice-is-created-once",
    title: "Accounting > Cost Centres > New cost centre: Save pressed twice inside one tick creates ONE centre",
    async run(env) {
      const { page, stub } = env;
      await costCentres(env, []);
      stub.route({ method: "POST", re: CENTRE_CREATE, delay: 700, reply: () => ok({ id: "cc-2", code: "GODOWN", name: "Godown", is_active: true }) });
      const save = await typeANewCentre(page);
      stub.forgetWrites();
      await sameTickDouble(save);
      await expectWrites(stub, CENTRE_CREATE, 1, "Save pressed twice on a new cost centre", "POST");
    },
  },
  {
    id: "a-cost-centre-that-could-not-be-created-says-why-and-keeps-what-was-typed",
    title: "Accounting > Cost Centres > New cost centre: a refusal is shown in the server's words, a request with no answer is said too, and the form keeps what was typed",
    async run(env) {
      const { page, stub } = env;
      await costCentres(env, []);
      const save = await typeANewCentre(page);
      stub.route({ method: "POST", re: CENTRE_CREATE, ...refuse("A cost centre with the code GODOWN already exists for this client.") });
      await save.click();
      await page.getByText("A cost centre with the code GODOWN already exists for this client.").waitFor({ timeout: 6000 });
      assert.equal(await page.getByRole("textbox", { name: "Code", exact: true }).inputValue(), "godown", "the code typed was lost with the refusal");
      // A request that gets no answer at all: the handler used to have no catch, so the press did nothing a person could see.
      stub.route({ method: "POST", re: CENTRE_CREATE, status: 502, reply: () => "<html>Bad gateway</html>" });
      await save.click();
      await until(async () => {
        const said = await page.locator("p.text-state-problem").allInnerTexts();
        return said.some((s) => s.trim() && !s.includes("already exists"));
      }, "a request with no usable answer to be said beside the form", 8000);
      assert.equal(await page.getByRole("textbox", { name: "Name", exact: true }).inputValue(), "Godown", "the name typed was lost");
      assert.equal(await save.isDisabled(), false, "Save stayed held after the request failed");
    },
  },
  {
    id: "retiring-a-cost-centre-twice-sends-one-change-and-a-refusal-is-said",
    title: "Accounting > Cost Centres: Retire pressed twice inside one tick sends ONE change, and a refused change is said above the list where it used to change nothing and say nothing",
    async run(env) {
      const { page, stub } = env;
      await costCentres(env, [FACTORY]);
      stub.route({ method: "PATCH", re: CENTRE_ONE, delay: 700, reply: () => ok({ ...FACTORY, is_active: false }) });
      const retire = page.getByRole("button", { name: "Retire", exact: true });
      await retire.waitFor({ timeout: 8000 });
      stub.forgetWrites();
      await sameTickDouble(retire);
      await expectWrites(stub, CENTRE_ONE, 1, "Retire pressed twice", "PATCH");

      stub.route({ method: "PATCH", re: CENTRE_ONE, ...refuse("This cost centre has lines in a closed year and cannot be retired.") });
      await page.reload({ waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Retire", exact: true }).click();
      const said = page.locator("[data-cost-centre-status-error]");
      await said.waitFor({ timeout: 6000 });
      assert.equal((await said.innerText()).trim(), "This cost centre has lines in a closed year and cannot be retired.");
      assert.equal(await said.getAttribute("role"), "alert");
    },
  },
];
