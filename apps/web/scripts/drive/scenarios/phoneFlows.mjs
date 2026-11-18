/**
 * Group: the flows a CA does away from the desk, at the width of a phone (POST-A-131).
 *
 * Each scenario sets a 390 x 844 window (whatever `--width` the run was given) and drives one flow the way a person does:
 *   1. Deadlines: the list is read, and Mark Filed on an open obligation opens its prompt with its confirm button on the screen;
 *   2. Approvals: a pending request's Approve is on the screen and asks before it acts;
 *   3. a client's invoices: the list is read, a draft invoice opens, and Issue is on the screen;
 *   4. a client's outstanding: the Sales tab's Outstanding figure is on the screen.
 * Every one also asserts the PAGE does not scroll sideways: a table may scroll inside its own box (a person swipes it), the page may not.
 * "On the screen" is measured after the element is scrolled into view the way a click would scroll it: its box lies inside the window.
 *
 * NOT PROVED: a real phone (touch, the on-screen keyboard, iOS Safari), which the owner's list holds.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { CLIENT_ROW, invoiceRow } from "../fixtures.mjs";
import { openInvoiceDrawer } from "../flows.mjs";

export const group = "phone-flows";
const PHONE = { width: 390, height: 844 };

/** How far the page scrolls sideways: the document, and every area of the shell that scrolls the page up and down (the client
 *  workspace's content area is one), since a phone's swipe scrolls those as it scrolls a page. */
const sideways = (page) => page.evaluate(() => {
  let worst = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  for (const el of document.querySelectorAll("main, main .overflow-y-auto")) worst = Math.max(worst, el.scrollWidth - el.clientWidth);
  return worst;
});

/** What crosses the window's right edge or spills out of its own box, outside any box that scrolls sideways (a table or a tab strip
 *  may be swiped; the page may not hide a control past its edge, which `overflow-x: hidden` on the shell would otherwise do silently). */
const spilled = (page) => page.evaluate(() => {
  // Only a box MADE to scroll sideways (a table's wrapper, a tab strip) is one a person is meant to swipe. A box that scrolls up and down
  // also computes `overflow-x: auto`, which is how the page's own scrolling area hid its sideways scroll from the first version of this.
  const scrollsSideways = (el) => {
    for (let a = el.parentElement; a; a = a.parentElement) {
      const made = /(^|\s)overflow-x-(auto|scroll)(\s|$)/.test(a.className?.toString?.() ?? "") || a.getAttribute("role") === "tablist";
      if (made && a.scrollWidth > a.clientWidth) return true;
    }
    return false;
  };
  const out = [];
  for (const el of document.querySelectorAll("main input, main select, main button, main a, main p, main span, main h1, main h2, main h3")) {
    const r = el.getBoundingClientRect();
    // Not drawn for the person (a closed menu's contents): judged when it is opened.
    if (r.width === 0 || r.height === 0 || !el.checkVisibility({ visibilityProperty: true, contentVisibilityAuto: true }) || scrollsSideways(el)) continue;
    const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.tagName).trim().slice(0, 40);
    if (r.right > window.innerWidth + 0.5 || r.left < -0.5) out.push(`${el.tagName.toLowerCase()} "${name}" at ${Math.round(r.left)}..${Math.round(r.right)}`);
    // Text wider than its own box (a figure spilling out of its tile), unless the box cuts it off on purpose with an ellipsis.
    else if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0 && getComputedStyle(el).textOverflow !== "ellipsis"
             && getComputedStyle(el).overflowX === "visible" && !["INPUT", "SELECT"].includes(el.tagName)) {
      out.push(`${el.tagName.toLowerCase()} "${name}" is ${el.scrollWidth} px of text in a ${el.clientWidth} px box`);
    }
  }
  return out;
});

async function noSidewaysScroll(page, where) {
  const by = await sideways(page);
  assert.ok(by <= 0, `${where}: the page scrolls sideways by ${by} px at ${PHONE.width} px`);
  const out = await spilled(page);
  assert.deepEqual(out, [], `${where}: drawn past the window's edge or out of its own box at ${PHONE.width} px`);
}

/** The element is scrolled into view as a click would, and then lies wholly inside the window. */
async function onScreen(locator, what) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  assert.ok(box, `${what} is not drawn`);
  assert.ok(box.x >= 0 && box.x + box.width <= PHONE.width + 0.5 && box.y >= 0 && box.y + box.height <= PHONE.height + 0.5,
    `${what} is not inside the ${PHONE.width} x ${PHONE.height} window: ${JSON.stringify(box)}`);
}

const OBLIGATION = {
  id: "ob-7", client_id: CLIENT_ROW.id, compliance_type: "GSTR3B", obligation_type: "GSTR3B", status: "Ready To File",
  period_start: "2026-10-01", period_end: "2026-10-31", due_date: "2026-11-20", filed_date: null, acknowledgement_no: null,
  notes: null, period_label: "GSTR-3B October 2026",
};

const PENDING = {
  id: "apr-7", request_type: "role_change", status: "pending", summary: "Change a role",
  requested_by_email: "x@firm.in", created_at: new Date().toISOString(), payload: {},
};

export const scenarios = [
  {
    id: "deadlines-and-an-approval-are-reachable-at-390-px",
    title: "Deadlines and Approvals at 390 px: no page scrolls sideways, Mark Filed and its prompt's confirm, and a request's Approve and Reject, are on the screen",
    async run(env) {
      const { page, stub } = env;
      await page.setViewportSize(PHONE);
      stub.route({ method: "GET", re: /compliance\/obligations(\?|$)/, reply: () => ok({ obligations: [OBLIGATION], total: 1 }) });
      await page.goto(`${env.base}/deadlines/`, { waitUntil: "networkidle" });
      await page.getByText("Open Client").first().waitFor();
      await noSidewaysScroll(page, "Deadlines");
      await page.getByText("Columns", { exact: true }).click();
      await noSidewaysScroll(page, "Deadlines with the Columns menu open");
      await page.getByText("Columns", { exact: true }).click();
      const markFiled = page.getByRole("button", { name: "Mark Filed" }).first();
      await onScreen(markFiled, "Mark Filed");
      await markFiled.click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await noSidewaysScroll(page, "Deadlines with the Mark Filed prompt open");
      await onScreen(dialog.getByRole("button", { name: /Cancel/ }).first(), "the prompt's Cancel");
      const confirm = dialog.getByRole("button", { name: /Mark (as )?Filed|Confirm|Save/ }).last();
      await onScreen(confirm, "the prompt's confirm button");
      await dialog.getByRole("button", { name: /Cancel/ }).first().click();
      // ...then the Approvals screen, in the same window.
      {
      const { page, stub } = env;
      await page.setViewportSize(PHONE);
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { approval: ["read", "request", "approve"] } }) });
      stub.route({ method: "GET", re: /\/api\/approvals(\?.*)?$/, reply: () => ok({ requests: [PENDING] }) });
      await page.goto(`${env.base}/approvals/`, { waitUntil: "networkidle" });
      const approve = page.getByRole("button", { name: "Approve", exact: true }).first();
      await approve.waitFor();
      await noSidewaysScroll(page, "Approvals");
      await onScreen(approve, "Approve");
      await onScreen(page.getByRole("button", { name: "Reject", exact: true }).first(), "Reject");
      }
    },
  },
  {
    id: "a-clients-invoices-and-outstanding-are-reachable-at-390-px",
    title: "a client's invoices at 390 px: a draft opens and its Issue is on the screen, and the Sales tab's Outstanding figure is too, with no sideways scroll",
    async run(env) {
      const { page } = env;
      await page.setViewportSize(PHONE);
      const drawer = await openInvoiceDrawer(env, "draft");
      await noSidewaysScroll(page, "the invoice drawer over the Sales tab");
      const box = await drawer.boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= PHONE.width + 0.5, `the invoice drawer is wider than the screen: ${JSON.stringify(box)}`);
      await onScreen(drawer.getByRole("button", { name: "Issue", exact: true }).first(), "the draft's Issue");
      // ...then the client's outstanding, on the Sales tab itself.
      {
      const { page, stub, at } = env;
      await page.setViewportSize(PHONE);
      stub.setTable("client_sales_invoices", [invoiceRow("issued", "inv-9")]);
      await page.goto(at("/sales/"), { waitUntil: "networkidle" });
      const tile = page.getByText(/^Outstanding — /).first();
      await tile.waitFor();
      await noSidewaysScroll(page, "the Sales tab");
      await onScreen(tile, "the Outstanding figure's label");
      }
    },
  },
];
