/**
 * Group N: the two forms that record a TDS deduction and a TDS challan send ONE request when their save button is pressed twice in
 * the same moment (PRE-A-015; the first run of this group is what found out whether they do).
 *
 * Both forms save with a plain button held by a `saving` flag in React state. State reaches the page a render after the click, so two
 * clicks dispatched back to back both see "not saving" (the defect the shared single-click Button exists to stop, and the one that
 * made eleven journals out of one click). A duplicate deduction doubles the tax the register says was withheld; a duplicate challan
 * doubles what the register says was deposited, and each is a statutory record a CA then has to find and retract.
 */
import { expectWrites, sameTickDouble } from "../kit.mjs";
import { openTdsChallanForm, openTdsDeductionForm } from "../flows.mjs";

export const group = "tds-records";

export const scenarios = [
  {
    id: "two-clicks-on-add-deduction-record-one-deduction",
    title: "a same-tick double click on Add Deduction sends one request",
    async run(env) {
      const { stub } = env;
      const form = await openTdsDeductionForm(env);
      await form.locator("#tds-payment-date").fill("15/07/2026");
      await form.locator("#tds-payment-date").press("Tab");
      await sameTickDouble(form.getByRole("button", { name: "Add Deduction", exact: true }));
      await expectWrites(stub, /tds-workspace\/deductions$/, 1, "two same-tick clicks on Add Deduction");
    },
  },
  {
    id: "two-clicks-on-add-challan-record-one-challan",
    title: "a same-tick double click on Add (the challan form) sends one request",
    async run(env) {
      const { stub } = env;
      const form = await openTdsChallanForm(env);
      await form.locator("#tds-challan-date").fill("15/07/2026");
      await form.locator("#tds-challan-date").press("Tab");
      await sameTickDouble(form.getByRole("button", { name: "Add", exact: true }));
      await expectWrites(stub, /tds-workspace\/challans$/, 1, "two same-tick clicks on Add (challan)");
    },
  },
];
