// A CLICKABLE TABLE ROW IS OPERABLE FROM THE KEYBOARD (frontend_ux-16).
//   node --experimental-strip-types --test scripts/a-clickable-table-row-is-operable-from-the-keyboard.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// A clickable DataTable row was `<tr onClick>` with `cursor-pointer` and nothing
// else: no tab stop, no Enter or Space, no ring. Nine screens pass `onRowClick`,
// including the ledger drill-through that opens the document behind a journal
// line (ACC-22), so a keyboard user could not open a row at all.
//
// ─────────────────────────────────────────────────────────────────────────────
// WHAT THIS RUNS
// ─────────────────────────────────────────────────────────────────────────────
// The rule (which key does what, which clicks belong to a control) is unit-tested
// in lib/table/rowKeyboard.test.ts. This renders the REAL components/ui/data-
// table.tsx through scripts/tsxHarness.ts and takes the props it put on each <tr>,
// then calls the `onKeyDown` / `onClick` it attached the way a browser would. It
// proves the wiring a key press reaches. It does not prove focus moves or that a
// ring is painted — a server render has neither — and a Playwright run (Tab to a
// ledger row, Enter, the source document opens; arrows move between rows) is still
// owed to a machine with a browser.
import test from "node:test";
import assert from "node:assert/strict";
import { hostElements, loadModule, requireFromWeb, startRecording } from "./tsxHarness.ts";

const React = requireFromWeb("react") as typeof import("react");
const { renderToStaticMarkup } = requireFromWeb("react-dom/server") as typeof import("react-dom/server");
const { DataTable } = loadModule<{ DataTable: React.ComponentType<Record<string, unknown>> }>("components/ui/data-table");

interface Row { id: string; name: string; canOpen: boolean }
const ROWS: Row[] = [
  { id: "a", name: "Alpha", canOpen: true },
  { id: "b", name: "Bravo", canOpen: false },
  { id: "c", name: "Charlie", canOpen: true },
];
const COLUMNS = [
  { key: "name", header: "Name", accessor: (r: Row) => r.name },
];

type TrProps = {
  tabIndex?: number;
  className?: string;
  onClick?: (e: unknown) => void;
  onKeyDown?: (e: unknown) => void;
  "data-row-clickable"?: string;
};

/** Render a table and return the props of its BODY rows, in order. */
function bodyRows(extra: Record<string, unknown> = {}): TrProps[] {
  startRecording();
  renderToStaticMarkup(React.createElement(DataTable, {
    data: ROWS, columns: COLUMNS, getRowId: (r: Row) => r.id, ...extra,
  }));
  // The header row is the first <tr>; the body rows are the next ROWS.length.
  const trs = hostElements("tr").map((t) => t.props as TrProps);
  return trs.slice(1, 1 + ROWS.length);
}

/** A keydown on the row itself, with the bits the handler reads. */
function key(k: string, over: Record<string, unknown> = {}, rows: FakeRow[] = []) {
  const current = rows[0] ?? fakeRow();
  const ev = {
    key: k, ctrlKey: false, metaKey: false, altKey: false, defaultPrevented: false,
    prevented: false,
    preventDefault() { this.prevented = true; },
    ...over,
  } as Record<string, unknown> & { prevented: boolean };
  ev.target = (over.target as unknown) ?? current;
  ev.currentTarget = current;
  return ev;
}

interface FakeRow {
  focused: number;
  focus(): void;
  parentElement: { querySelectorAll(sel: string): FakeRow[] };
}
/** `n` clickable rows sharing a parent, as the DOM would have them. */
function fakeRows(n: number): FakeRow[] {
  const rows: FakeRow[] = [];
  const parent = { querySelectorAll: () => rows };
  for (let i = 0; i < n; i++) {
    rows.push({ focused: 0, focus() { this.focused++; }, parentElement: parent });
  }
  return rows;
}
const fakeRow = (): FakeRow => fakeRows(1)[0];

// ═════════════════════════════════════════════════════════════════════════════
// THE MARKUP
// ═════════════════════════════════════════════════════════════════════════════

test("a clickable row is a tab stop with a visible focus ring", () => {
  const rows = bodyRows({ onRowClick: () => {} });
  for (const r of rows) {
    assert.equal(r.tabIndex, 0, "tabIndex=0 puts the row in the Tab order");
    assert.equal(r["data-row-clickable"], "true");
    assert.match(String(r.className), /focus-visible:ring-2/, "a ring says which row has focus");
    assert.match(String(r.className), /focus-visible:ring-inset/,
      "inset: the table sits in an overflow-x-auto wrapper that would clip an outer ring");
    assert.equal(typeof r.onKeyDown, "function");
  }
});

test("a row that is NOT clickable is not a tab stop and has no handlers", () => {
  const rows = bodyRows({ onRowClick: () => {}, rowClickable: (r: Row) => r.canOpen });
  assert.equal(rows[0].tabIndex, 0);
  assert.equal(rows[1].tabIndex, undefined, "a row that opens nothing must not invite a key press");
  assert.equal(rows[1].onKeyDown, undefined);
  assert.equal(rows[1].onClick, undefined);
  assert.equal(rows[1]["data-row-clickable"], undefined);
  assert.equal(rows[2].tabIndex, 0);
});

test("a table with no onRowClick has no tab stops at all", () => {
  for (const r of bodyRows()) {
    assert.equal(r.tabIndex, undefined);
    assert.equal(r.onKeyDown, undefined);
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// THE KEYS
// ═════════════════════════════════════════════════════════════════════════════

test("Enter and Space on the row open it, and stop the page scrolling", () => {
  const opened: string[] = [];
  const rows = bodyRows({ onRowClick: (r: Row) => opened.push(r.id) });
  for (const k of ["Enter", " "]) {
    const ev = key(k);
    rows[2].onKeyDown!(ev);
    assert.equal(ev.prevented, true, `${JSON.stringify(k)} must not also scroll`);
  }
  assert.deepEqual(opened, ["c", "c"], "the row whose handler it is, not the first");
});

test("a key that bubbled up from a control inside the row does not open it", () => {
  const opened: string[] = [];
  const rows = bodyRows({ onRowClick: (r: Row) => opened.push(r.id) });
  const checkbox = { id: "a checkbox inside a cell" };
  for (const k of ["Enter", " ", "ArrowDown"]) {
    const ev = key(k, { target: checkbox });
    rows[0].onKeyDown!(ev);
    assert.equal(ev.prevented, false, `${JSON.stringify(k)} belongs to the control`);
  }
  assert.deepEqual(opened, []);
});

test("Ctrl+Enter and Alt+Down are left alone", () => {
  const opened: string[] = [];
  const rows = bodyRows({ onRowClick: (r: Row) => opened.push(r.id) });
  rows[0].onKeyDown!(key("Enter", { ctrlKey: true }));
  rows[0].onKeyDown!(key("ArrowDown", { altKey: true }));
  assert.deepEqual(opened, []);
});

test("an ordinary key does nothing and is not swallowed", () => {
  const rows = bodyRows({ onRowClick: () => { throw new Error("must not open"); } });
  const ev = key("a");
  rows[0].onKeyDown!(ev);
  assert.equal(ev.prevented, false);
});

test("ArrowDown and ArrowUp focus the next and previous CLICKABLE row, clamped at the ends", () => {
  const rows = bodyRows({ onRowClick: () => {}, rowClickable: (r: Row) => r.canOpen });
  // The DOM holds only the two clickable rows (the middle one has no
  // data-row-clickable), in document order.
  const dom = fakeRows(2);
  const focused = () => dom.map((r) => r.focused);
  /** A keydown that the browser dispatched on `row` (target and currentTarget). */
  const keyOn = (k: string, row: FakeRow) => {
    const ev = key(k, {}, [row]);
    (ev as Record<string, unknown>).currentTarget = row;
    (ev as Record<string, unknown>).target = row;
    return ev;
  };

  const down = keyOn("ArrowDown", dom[0]);
  rows[0].onKeyDown!(down);
  assert.equal(down.prevented, true, "an arrow must not scroll the table's wrapper");
  assert.deepEqual(focused(), [0, 1], "down from the first focuses the second — skipping the row that opens nothing");

  rows[2].onKeyDown!(keyOn("ArrowUp", dom[1]));
  assert.deepEqual(focused(), [1, 1], "up from the second focuses the first");

  rows[0].onKeyDown!(keyOn("ArrowUp", dom[0]));
  assert.deepEqual(focused(), [2, 1], "up from the first stays on the first");

  rows[2].onKeyDown!(keyOn("ArrowDown", dom[1]));
  assert.deepEqual(focused(), [2, 2], "down from the last stays on the last");
});

// ═════════════════════════════════════════════════════════════════════════════
// THE MOUSE
// ═════════════════════════════════════════════════════════════════════════════

/** An event target whose `closest` says whether it is, or sits in, a control. */
function target(interactive: boolean, row: unknown) {
  const control = { closest: () => (interactive ? control : null), contains: () => true };
  return { target: control, currentTarget: Object.assign(row as object, { contains: (o: unknown) => o === control }) };
}

test("a click on the row's own cell opens it", () => {
  const opened: string[] = [];
  const rows = bodyRows({ onRowClick: (r: Row) => opened.push(r.id) });
  rows[0].onClick!(target(false, { closest: () => null }));
  assert.deepEqual(opened, ["a"]);
});

test("a click that began on a link, button or checkbox inside the row opens nothing", () => {
  const opened: string[] = [];
  const rows = bodyRows({ onRowClick: (r: Row) => opened.push(r.id) });
  rows[0].onClick!(target(true, { closest: () => null }));
  assert.deepEqual(opened, [], "opening the document AND following the link is two actions from one gesture");
});
