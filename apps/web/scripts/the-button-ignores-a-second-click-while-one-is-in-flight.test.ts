// THE BUTTON PRIMITIVE IGNORES A SECOND CLICK WHILE ONE IS IN FLIGHT (frontend_ux-09).
//   node --experimental-strip-types --test scripts/the-button-ignores-a-second-click-while-one-is-in-flight.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// One click on Post Entry produced eleven journals. The guard on every posting
// screen was `disabled={saving}` — React state — and state reaches the DOM a
// render after the click that set it, so two clicks dispatched back to back both
// run with `saving === false`. Three files had added a ref by hand; 192 flags
// and 100 async handlers had not.
//
// ─────────────────────────────────────────────────────────────────────────────
// WHAT THIS ACTUALLY RUNS
// ─────────────────────────────────────────────────────────────────────────────
// There is no browser in this repository, so this loads the REAL components/ui/
// button.tsx through scripts/tsxHarness.ts, renders it with react-dom/server,
// takes the `onClick` the component attached to its <button> and CALLS it twice
// on one synchronous tick — what a double-click is. It proves the logic a click
// reaches. It does not prove a browser dispatches one: a Playwright double-click
// on Post Entry (one POST, aria-busy while it runs) is still owed to a machine
// with a browser.
import test from "node:test";
import assert from "node:assert/strict";
import { hostElements, loadModule, requireFromWeb, startRecording } from "./tsxHarness.ts";

const React = requireFromWeb("react") as typeof import("react");
const { renderToStaticMarkup } = requireFromWeb("react-dom/server") as typeof import("react-dom/server");
const { Button } = loadModule<{ Button: React.ComponentType<Record<string, unknown>> }>("components/ui/button");
const { createSingleFlight } = loadModule<{
  createSingleFlight: () => { busy(): boolean; getState(): { busy: boolean; owner: string | null } };
}>("lib/async/singleFlight");

const h = React.createElement;
const tick = () => new Promise<void>((r) => setImmediate(r));

interface FakeEvent {
  currentTarget: object; prevented: boolean; stopped: boolean;
  preventDefault(): void; stopPropagation(): void;
}
const click = (): FakeEvent => ({
  currentTarget: {}, prevented: false, stopped: false,
  preventDefault() { this.prevented = true; },
  stopPropagation() { this.stopped = true; },
});

type Handler = (e: FakeEvent) => void;
function deferred() {
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/** Render `node`, return its markup and the props of every <button> it made. */
function render(node: React.ReactElement) {
  startRecording();
  const html = renderToStaticMarkup(node);
  return { html, buttons: hostElements("button").map((b) => b.props) };
}

/** The unhandled rejections raised while `fn` runs. node:test fails a test on
 *  one, so its own listeners are set aside for the duration — and put back. */
async function unhandledDuring(fn: () => Promise<void> | void): Promise<unknown[]> {
  const saved = process.listeners("unhandledRejection");
  process.removeAllListeners("unhandledRejection");
  const seen: unknown[] = [];
  process.on("unhandledRejection", (e) => { seen.push(e); });
  try {
    await fn();
    await tick();
    await tick();
  } finally {
    process.removeAllListeners("unhandledRejection");
    saved.forEach((l) => process.on("unhandledRejection", l as (...a: unknown[]) => void));
  }
  return seen;
}

// ═════════════════════════════════════════════════════════════════════════════
// THE GUARD
// ═════════════════════════════════════════════════════════════════════════════

test("a second click on the same tick is ignored, and is stopped from submitting a form", () => {
  let calls = 0;
  const d = deferred();
  const { buttons } = render(h(Button, { onClick: () => { calls++; return d.promise; } }, "Post Entry"));
  const onClick = buttons[0].onClick as Handler;

  const first = click();
  const second = click();           // no await, no render: the double-click
  onClick(first);
  onClick(second);

  assert.equal(calls, 1, "the handler ran once");
  assert.equal(first.prevented, false, "the first click is an ordinary click");
  assert.equal(first.stopped, false);
  assert.equal(second.prevented, true,
    "an ignored click must not fall through to the form's own submit");
  assert.equal(second.stopped, true,
    "nor bubble to a clickable row: the first click's handler stopped propagation, and the ignored one never runs it");
  d.resolve();
});

test("the ignored click is not queued", async () => {
  let calls = 0;
  const d = deferred();
  const { buttons } = render(h(Button, { onClick: () => { calls++; return d.promise; } }, "Post"));
  const onClick = buttons[0].onClick as Handler;
  onClick(click()); onClick(click()); onClick(click());
  d.resolve();
  await tick();
  assert.equal(calls, 1, "a queued second Post would write the same voucher again");
});

test("the guard is released when the promise resolves", async () => {
  let calls = 0;
  const d = deferred();
  const { buttons } = render(h(Button, {
    onClick: () => { calls++; return calls === 1 ? d.promise : undefined; },
  }, "Post"));
  const onClick = buttons[0].onClick as Handler;
  onClick(click());
  d.resolve();
  await tick();
  const again = click();
  onClick(again);
  assert.equal(calls, 2);
  assert.equal(again.prevented, false);
});

test("the guard is released when the promise REJECTS, so the CA can retry — and the error is not swallowed", async () => {
  let calls = 0;
  const failing = deferred();
  const { buttons } = render(h(Button, {
    onClick: () => { calls++; return calls === 1 ? failing.promise : Promise.resolve(); },
  }, "Post"));
  const onClick = buttons[0].onClick as Handler;

  const surfaced = await unhandledDuring(async () => {
    onClick(click());
    failing.reject(new Error("server refused"));
  });
  assert.equal(surfaced.length, 1, "a raw async onClick that threw raised an unhandled rejection; so does this");
  assert.match(String((surfaced[0] as Error).message), /server refused/);

  onClick(click());
  assert.equal(calls, 2, "the failed save can be retried");
});

test("a handler that throws synchronously releases the guard", () => {
  let calls = 0;
  const { buttons } = render(h(Button, {
    onClick: () => { calls++; if (calls === 1) throw new Error("sync"); },
  }, "Post"));
  const onClick = buttons[0].onClick as Handler;
  assert.throws(() => onClick(click()), /sync/);
  onClick(click());
  assert.equal(calls, 2);
});

test("a synchronous handler is never held: two ordinary clicks both run", () => {
  let calls = 0;
  const { buttons } = render(h(Button, { onClick: () => { calls++; } }, "Add line"));
  const onClick = buttons[0].onClick as Handler;
  onClick(click()); onClick(click());
  assert.equal(calls, 2);
});

test("a handler that DROPS its promise is not held — the screen must return it", () => {
  // Asserted so the limit is on the record: the primitive can only hold what it
  // is handed. The ratchet (the-conversion-guard) is what stops a screen
  // swapping to <Button> and keeping `() => { save(); }`.
  let calls = 0;
  const { buttons } = render(h(Button, {
    onClick: () => { calls++; void new Promise(() => {}); },
  }, "Post"));
  const onClick = buttons[0].onClick as Handler;
  onClick(click()); onClick(click());
  assert.equal(calls, 2);
});

test("`loading` ignores clicks without the button having started anything", () => {
  let calls = 0;
  const { buttons } = render(h(Button, { loading: true, onClick: () => { calls++; } }, "Post"));
  const ev = click();
  (buttons[0].onClick as Handler)(ev);
  assert.equal(calls, 0);
  assert.equal(ev.prevented, true);
});

// ═════════════════════════════════════════════════════════════════════════════
// ONE FLIGHT, SEVERAL CONTROLS
// ═════════════════════════════════════════════════════════════════════════════

test("two buttons sharing a flight exclude each other — Save Draft then Post Entry on one tick is ONE voucher", () => {
  const flight = createSingleFlight();
  const calls: string[] = [];
  const d = deferred();
  const tree = () => h(React.Fragment, null,
    h(Button, { flight, onClick: () => { calls.push("draft"); return d.promise; } }, "Save Draft"),
    h(Button, { flight, onClick: () => { calls.push("post"); return d.promise; } }, "Post Entry"));
  const { buttons } = render(tree());

  (buttons[0].onClick as Handler)(click());
  const second = click();
  (buttons[1].onClick as Handler)(second);

  assert.deepEqual(calls, ["draft"], "the second control's handler never ran");
  assert.equal(second.prevented, true);
  d.resolve();
});

test("while one control works its sibling is disabled but only the pressed one is aria-busy", () => {
  const flight = createSingleFlight();
  const d = deferred();
  const tree = () => h(React.Fragment, null,
    h(Button, { flight, onClick: () => d.promise }, "Save Draft"),
    h(Button, { flight, onClick: () => d.promise }, "Post Entry"));
  const idle = render(tree());
  assert.doesNotMatch(idle.html, /aria-busy="/);
  assert.doesNotMatch(idle.html, /\sdisabled=""/);

  (idle.buttons[0].onClick as Handler)(click());          // press the first
  const busy = render(tree());
  const [draft, post] = busy.html.split("</button>");
  assert.match(draft, /aria-busy="true"/, "the pressed control says it is working");
  assert.match(draft, /\sdisabled=""/);
  assert.doesNotMatch(post, /aria-busy="/, "its sibling is not the one working");
  assert.match(post, /\sdisabled=""/, "but it cannot be pressed");
  d.resolve();
});

// ═════════════════════════════════════════════════════════════════════════════
// WHAT IT RENDERS
// ═════════════════════════════════════════════════════════════════════════════

test("`loading` renders disabled, aria-busy and a spinner", () => {
  const { html } = render(h(Button, { loading: true }, "Post Entry"));
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /disabled=""/);
  assert.match(html, /animate-spin/, "the spinner");
  assert.match(html, /Post Entry/, "the label stays");
});

test("an idle button is not busy and not disabled", () => {
  const { html } = render(h(Button, { onClick: () => {} }, "Post Entry"));
  assert.doesNotMatch(html, /aria-busy="/);
  assert.doesNotMatch(html, /\sdisabled=""/);
  assert.doesNotMatch(html, /animate-spin/);
});

test("`spinner={false}` and `icon` shape what shows while it works", () => {
  assert.doesNotMatch(render(h(Button, { loading: true, spinner: false }, "x")).html, /animate-spin/);
  const swapped = render(h(Button, { loading: true, icon: h("i", { id: "send" }) }, "Send")).html;
  assert.doesNotMatch(swapped, /id="send"/, "the icon is swapped for the spinner, not shown beside it");
  assert.match(render(h(Button, { icon: h("i", { id: "send" }) }, "Send")).html, /id="send"/);
});

test("the plain variant adds no classes of its own, so a converted button keeps its look", () => {
  const plain = render(h(Button, {
    variant: "plain", size: "none", className: "text-xs px-4 py-2 bg-brand text-white", onClick: () => {},
  }, "Post"));
  const cls = /class="([^"]*)"/.exec(plain.html)?.[1] ?? "";
  assert.equal(cls, "text-xs px-4 py-2 bg-brand text-white aria-busy:cursor-progress",
    "no inline-flex, no rounded-md, no h-10 — only the caller's classes and the busy cursor");

  const styled = render(h(Button, { onClick: () => {} }, "Post"));
  assert.match(/class="([^"]*)"/.exec(styled.html)?.[1] ?? "", /inline-flex .*h-10/,
    "the shadcn default is unchanged for the 112 existing <Button> uses");
});

test("a disabled prop is still honoured", () => {
  assert.match(render(h(Button, { disabled: true, onClick: () => {} }, "Post")).html, /disabled=""/);
});
