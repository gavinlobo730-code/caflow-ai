/**
 * Group T: recording a delivery challan's goods as back, driven in a browser (POST-A-126, the last native date box).
 *
 * The box used to be `<input type="date">` whose CHANGE was the write: picking a date sent the PATCH that stops the s.143 clock for the whole
 * challan, so a date chosen by mistake was a write and a half-typed one was too. It is a typed date and a "Record goods back" button now.
 * The source guards hold that no native date input remains and that the button is the shared single-click one; this proves in Chromium,
 * against a stubbed server:
 *
 *   1. a date typed as 15/07/2026 and a press of the button send ONE PATCH carrying 2026-07-15, and nothing is sent by typing alone;
 *   2. the button pressed twice in one tick sends ONE request;
 *   3. a date that does not exist (31/02/2026) is refused in words and nothing is sent, and a blank box is refused in words too;
 *   4. a refusal from the server is shown as the server wrote it, the typed date stays, and the next press sends a second request.
 */
import assert from "node:assert/strict";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "goods-back";

const PATCH = /api\/sales-cycle\/challans\/ch-1\?/;
const CHALLAN = {
  id: "ch-1", document_no: "DC/26-27/0001", document_date: "2026-07-01", reason: "job_work", reason_label: "Job work", status: "issued",
  received_back_on: null, total_paise: 5_000_000, clock: { applies: true, due_back_by: "2027-06-30", overdue: false, gaps: [] },
};

async function atTheChallan(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /sales-cycle\/vocabulary/, reply: () => ok({ challan_reasons: [], goods_kinds: [], quote_kinds: [] }) });
  stub.route({ method: "GET", re: /sales-cycle\/quotations\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/orders\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/challans\?/, reply: () => ok([CHALLAN]) });
  stub.route({ method: "GET", re: /\/customers/, reply: () => ok([]) });
  await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Delivery Challans" }).click();
  await page.getByText("Mark a whole challan back at once").waitFor();
}

const dateBox = (page) => page.getByLabel(`Date the goods came back, challan ${CHALLAN.document_no}`);
const recordButton = (page) => page.getByRole("button", { name: "Record goods back", exact: true });
const sent = (stub) => stub.writesTo(PATCH, "PATCH").map((w) => JSON.parse(w.body));

export const scenarios = [
  {
    id: "typing-a-date-sends-nothing-and-the-button-sends-it-once-as-iso",
    title: "15/07/2026 typed and the button pressed sends ONE PATCH carrying 2026-07-15; typing alone sends nothing",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: PATCH, reply: () => ok({ ...CHALLAN, received_back_on: "2026-07-15" }) });
      await atTheChallan(env);
      await dateBox(page).fill("15/07/2026");
      await dateBox(page).blur();
      await expectWrites(stub, PATCH, 0, "typing a date and leaving the box", "PATCH");
      await recordButton(page).click();
      await expectWrites(stub, PATCH, 1, "pressing Record goods back", "PATCH");
      assert.deepStrictEqual(sent(stub)[0], { received_back_on: "2026-07-15" }, `the body sent was ${JSON.stringify(sent(stub)[0])}`);
    },
  },
  {
    id: "two-presses-of-record-goods-back-in-one-tick-send-one-request",
    title: "Record goods back pressed twice in the same tick sends ONE request (it stops the s.143 clock for the whole challan)",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: PATCH, reply: () => ok({ ...CHALLAN, received_back_on: "2026-07-15" }) });
      await atTheChallan(env);
      await dateBox(page).fill("15/07/2026");
      // A real press moves focus to the button first, which commits the box; a same-tick dispatch does not, so the box is left as a person leaves it.
      await dateBox(page).blur();
      await sameTickDouble(recordButton(page));
      await expectWrites(stub, PATCH, 1, "two same-tick presses on Record goods back", "PATCH");
    },
  },
  {
    id: "a-date-that-is-not-one-and-a-blank-box-are-refused-in-words-with-nothing-sent",
    title: "31/02/2026 and an empty box are each refused in a sentence and nothing is sent",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: PATCH, reply: () => ok({ ...CHALLAN, received_back_on: "2026-07-15" }) });
      await atTheChallan(env);

      await recordButton(page).click();
      await page.getByText(`Enter the date the goods on ${CHALLAN.document_no} came back.`).waitFor();

      await dateBox(page).fill("31/02/2026");
      await dateBox(page).blur();
      await recordButton(page).click();
      await page.getByText(/Date back, DC\/26-27\/0001:/).waitFor();
      await expectWrites(stub, PATCH, 0, "a blank box and a date that does not exist", "PATCH");
    },
  },
  {
    id: "a-server-refusal-is-shown-the-typed-date-stays-and-the-next-press-sends-again",
    title: "a refusal is shown as the server wrote it, the typed date stays in the box, and the next press sends a second request",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "That date is before the challan was issued.";
      stub.route({ method: "PATCH", re: PATCH, ...refuse(REFUSED, 422) });
      await atTheChallan(env);
      await dateBox(page).fill("15/07/2026");
      await recordButton(page).click();
      await page.getByText(REFUSED).waitFor();
      assert.strictEqual(await dateBox(page).inputValue(), "15/07/2026", "the typed date was lost on a refusal");
      await expectWrites(stub, PATCH, 1, "the refused press", "PATCH");

      stub.route({ method: "PATCH", re: PATCH, reply: () => ok({ ...CHALLAN, received_back_on: "2026-07-15" }) });
      await recordButton(page).click();
      await until(() => sent(stub).length === 2, "the second request to arrive");
    },
  },
];
