// What may leave the browser in an error report (ops-09). Run with:
//   node --experimental-strip-types --test lib/monitoring/scrub.test.ts
//
// Every case below is a value this product genuinely holds: an engagement-letter link carries a bearer
// token in its query, Supabase returns a session in the URL fragment, and a message thrown from a
// payroll or bank screen can carry a PAN, an account number or an amount.
import test from "node:test";
import assert from "node:assert/strict";
import {
  EventBudget,
  routeShape,
  scrubBreadcrumb,
  scrubEvent,
  scrubText,
  scrubUrl,
} from "./scrub.ts";
import type { LooseEvent } from "./scrub.ts";

// ── URLs ───────────────────────────────────────────────────────────────────────

test("a URL loses its query, where an engagement-letter token lives", () => {
  assert.equal(scrubUrl("https://caflow-ai.pages.dev/sign/?t=9f8e7d6c5b4a39281706f5e4d3c2b1a0"), "https://caflow-ai.pages.dev/sign/");
});

test("a URL loses its fragment, where Supabase returns a session", () => {
  assert.equal(
    scrubUrl("https://caflow-ai.pages.dev/auth/callback/#access_token=eyJhbGciOi.eyJzdWIi.c2ln&refresh_token=abc"),
    "https://caflow-ai.pages.dev/auth/callback/",
  );
});

test("a relative URL keeps its path and nothing else, and does not grow an origin", () => {
  assert.equal(scrubUrl("/clients/?pan=ABCDE1234F#x"), "/clients/");
});

test("a string that is not a URL is cut at the first ? or # rather than passed through", () => {
  const out = scrubUrl("http://[broken?token=secret");
  assert.ok(!out.includes("secret"), out);
});

test("a non-string is an empty string, not a throw", () => {
  assert.equal(scrubUrl(undefined as unknown as string), "");
  assert.equal(scrubText(null as unknown as string), "");
});

test("a route shape groups every client on one screen into one issue", () => {
  assert.equal(
    routeShape("https://caflow-ai.pages.dev/clients/3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab/payroll/?tab=slips#x"),
    "/clients/:id/payroll/",
  );
  assert.equal(routeShape("/invoices/1234/"), "/invoices/:id/");
  assert.equal(routeShape(""), "/");
});

// ── text ───────────────────────────────────────────────────────────────────────

const cases: Array<[string, string, string]> = [
  ["a PAN", "Could not save deductee ABCDE1234F", "ABCDE1234F"],
  ["a GSTIN", "Invalid supplier 27AAPFU0939F1ZV on bill", "27AAPFU0939F1ZV"],
  ["an IFSC code", "Bank HDFC0001234 rejected", "HDFC0001234"],
  ["a bank account number", "Account 123456789012 not found", "123456789012"],
  ["an amount in paise", "Net pay 12500000 does not match", "12500000"],
  ["an amount grouped the Indian way", "Total 1,25,000 exceeds limit", "1,25,000"],
  ["an email address", "Invite failed for ca.partner@example.com", "ca.partner@example.com"],
  ["a JWT", "Bad token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl", "eyJhbGciOiJIUzI1NiJ9"],
  ["a bearer header", "Sent Authorization: Bearer abcDEF123-secret", "abcDEF123-secret"],
  ["a row id", "No row for 3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab", "3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab"],
  ["an AI key behind an underscore", "Groq said gsk_abc123def456ghi789jkl012", "abc123def456ghi789jkl012"],
  ["a URL's query inside a message", "Failed to fetch https://api.example.com/x?pan=ABCDE1234F&t=tok", "pan=ABCDE1234F"],
];
for (const [name, input, secret] of cases) {
  test(`scrubText removes ${name}`, () => {
    const out = scrubText(input);
    assert.ok(!out.includes(secret), `"${secret}" survived: ${out}`);
  });
}

test("scrubText keeps what a developer needs to read the failure", () => {
  for (const message of [
    "TypeError: Cannot read properties of undefined (reading 'map')",
    "ChunkLoadError: Loading chunk 4 failed.",
    "Failed to execute 'fetch' on 'Window'",
    "Hydration failed because the initial UI does not match",
  ]) {
    assert.equal(scrubText(message), message);
  }
});

test("a URL inside a message keeps its path, which is what says where it failed", () => {
  const out = scrubText("Failed to fetch https://practicesync-api.onrender.com/api/clients/?pan=ABCDE1234F");
  assert.ok(out.includes("https://practicesync-api.onrender.com/api/clients/"), out);
});

// ── breadcrumbs ────────────────────────────────────────────────────────────────

test("a console breadcrumb is dropped whole, since console.log(pan) is how a value reaches one", () => {
  assert.equal(scrubBreadcrumb({ category: "console", message: "pan ABCDE1234F" }), null);
});

test("a navigation or request breadcrumb keeps its path and loses its query", () => {
  const out = scrubBreadcrumb({
    category: "fetch",
    data: { url: "https://practicesync-api.onrender.com/api/tds/?pan=ABCDE1234F", method: "GET", status_code: 200 },
  });
  assert.deepEqual(out?.data, { url: "https://practicesync-api.onrender.com/api/tds/", method: "GET", status_code: 200 });

  const nav = scrubBreadcrumb({ category: "navigation", data: { from: "/sign/?t=secrettoken123", to: "/login/#access_token=x" } });
  assert.deepEqual(nav?.data, { from: "/sign/", to: "/login/" });
});

test("an object value in breadcrumb data is dropped rather than walked", () => {
  const out = scrubBreadcrumb({ category: "xhr", data: { body: { pan: "ABCDE1234F" }, status_code: 200 } });
  assert.deepEqual(out?.data, { status_code: 200 });
});

test("a breadcrumb is not mutated in place", () => {
  const crumb = { category: "ui.click", message: "button ABCDE1234F" };
  scrubBreadcrumb(crumb);
  assert.equal(crumb.message, "button ABCDE1234F");
});

// ── events ─────────────────────────────────────────────────────────────────────

function payrollCrash(): LooseEvent {
  return {
    message: "Slip for ABCDE1234F failed",
    exception: {
      values: [{ type: "TypeError", value: "Net 12500000 for AAPFU0939F on 3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab", stacktrace: { frames: [] } }],
    },
    request: {
      url: "https://caflow-ai.pages.dev/clients/3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab/payroll/?tab=slips#access_token=abc",
      headers: { Cookie: "sb-access-token=secret", Authorization: "Bearer secret", "User-Agent": "x" },
      query_string: "tab=slips",
      data: { pan: "ABCDE1234F" },
    },
    user: { email: "ca@example.com", ip_address: "203.0.113.9" },
    extra: { form: { basic: 4500000 } },
    transaction: "/clients/3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab/payroll/",
    breadcrumbs: [
      { category: "console", message: "basic 4500000" },
      { category: "fetch", data: { url: "https://x.test/api/payroll/?pan=ABCDE1234F" } },
    ],
    release: "abc1234",
    environment: "production",
  };
}

test("an event carries the error, the route shape and the build — and nothing from the screen", () => {
  const out = scrubEvent(payrollCrash());
  const serialised = JSON.stringify(out);
  for (const secret of ["ABCDE1234F", "AAPFU0939F", "12500000", "4500000", "ca@example.com", "203.0.113.9", "secret", "access_token"]) {
    assert.ok(!serialised.includes(secret), `"${secret}" survived: ${serialised}`);
  }
  // A bare row id in a MESSAGE is replaced; the id in the URL's PATH is kept, because it is how a developer
  // finds the row and it is not a value anybody typed into a field.
  assert.ok(!(out.exception?.values?.[0]?.value ?? "").includes("3f2b8c1e-aaaa"));
  assert.equal(out.exception?.values?.[0]?.type, "TypeError");
  assert.ok(out.exception?.values?.[0]?.stacktrace, "the stack is the point and is kept");
  assert.equal(out.request?.url, "https://caflow-ai.pages.dev/clients/3f2b8c1e-aaaa-4bbb-8ccc-0123456789ab/payroll/");
  assert.deepEqual(Object.keys(out.request ?? {}), ["url"]);
  assert.equal(out.tags?.route, "/clients/:id/payroll/");
  assert.equal(out.transaction, "/clients/:id/payroll/");
  assert.equal(out.release, "abc1234");
  assert.equal(out.breadcrumbs?.length, 1, "the console breadcrumb is gone, the request one stays");
});

test("an event is not mutated in place", () => {
  const event = payrollCrash();
  scrubEvent(event);
  assert.equal(event.message, "Slip for ABCDE1234F failed");
  assert.ok(event.user);
});

test("an event with no request, no exception and no breadcrumbs still scrubs", () => {
  const out = scrubEvent({ message: "Account 123456789012" });
  assert.equal(out.message, "Account [id]");
  assert.deepEqual(out.tags, {});
});

// ── the budget ─────────────────────────────────────────────────────────────────

test("one error repeated stops being sent after three, so a render loop is one issue and not the quota", () => {
  const budget = new EventBudget(20, 3);
  const event: LooseEvent = { exception: { values: [{ type: "TypeError", value: "x is undefined" }] } };
  const allowed = Array.from({ length: 60 }, () => budget.allow(event)).filter(Boolean).length;
  assert.equal(allowed, 3);
});

test("a session stops sending at its cap even when every error is different", () => {
  const budget = new EventBudget(20, 3);
  const allowed = Array.from({ length: 50 }, (_, i) =>
    budget.allow({ exception: { values: [{ type: "Error", value: `failure ${i}` }] } }),
  ).filter(Boolean).length;
  assert.equal(allowed, 20);
});

test("a dropped event does not spend the session's cap", () => {
  const budget = new EventBudget(5, 1);
  const a: LooseEvent = { message: "a" };
  assert.equal(budget.allow(a), true);
  for (let i = 0; i < 10; i++) assert.equal(budget.allow(a), false);
  for (const m of ["b", "c", "d", "e"]) assert.equal(budget.allow({ message: m }), true);
  assert.equal(budget.allow({ message: "f" }), false, "five distinct events is the cap");
});
