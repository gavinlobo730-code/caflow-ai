// The browser error tracker's options (ops-09). Run with:
//   node --experimental-strip-types --test lib/monitoring/options.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { DROPPED_INTEGRATIONS, buildSentryOptions } from "./options.ts";
import { EventBudget } from "./scrub.ts";
import type { LooseEvent } from "./scrub.ts";

const DSN = "https://publickey@o123.ingest.sentry.io/456";

test("with no DSN built in nothing starts", () => {
  assert.equal(buildSentryOptions({}), null);
  assert.equal(buildSentryOptions({ dsn: "" }), null);
  assert.equal(buildSentryOptions({ dsn: "   " }), null);
  assert.equal(buildSentryOptions({ release: "abc", environment: "production" }), null);
});

test("a DSN, a release and an environment reach the options, and production is the default environment", () => {
  const o = buildSentryOptions({ dsn: ` ${DSN} `, release: " 9f8e7d6 ", environment: "preview" });
  assert.equal(o?.dsn, DSN);
  assert.equal(o?.release, "9f8e7d6");
  assert.equal(o?.environment, "preview");
  assert.equal(buildSentryOptions({ dsn: DSN })?.environment, "production");
  assert.equal(buildSentryOptions({ dsn: DSN, release: "" })?.release, undefined, "an empty release is not a release called ''");
});

test("it is an error-reporting install: no tracing key of any kind", () => {
  const o = buildSentryOptions({ dsn: DSN }) as unknown as Record<string, unknown>;
  // ABSENT, not zero. A defined tracesSampleRate of 0 still switches tracing on in the SDK, installs the
  // browser-tracing integration and adds sentry-trace / baggage headers to outgoing requests.
  for (const key of ["tracesSampleRate", "tracesSampler", "tracePropagationTargets", "enableTracing"]) {
    assert.ok(!(key in o), `${key} is set`);
  }
});

test("it records no screens: no replay key of any kind", () => {
  const o = buildSentryOptions({ dsn: DSN }) as unknown as Record<string, unknown>;
  for (const key of ["replaysSessionSampleRate", "replaysOnErrorSampleRate", "replayIntegration"]) {
    assert.ok(!(key in o), `${key} is set`);
  }
});

test("default PII is off and every distinct error is sent, the budget being what stops a loop", () => {
  const o = buildSentryOptions({ dsn: DSN });
  assert.equal(o?.sendDefaultPii, false);
  assert.equal(o?.sampleRate, 1);
});

test("the default integrations lose every tracing, replay and recording one, and keep the error handlers", () => {
  const o = buildSentryOptions({ dsn: DSN });
  const defaults = [
    "InboundFilters", "FunctionToString", "BrowserApiErrors", "Breadcrumbs", "GlobalHandlers", "LinkedErrors",
    "Dedupe", "HttpContext", "BrowserTracing", "Replay", "ReplayCanvas", "Feedback", "GraphQLClient",
    "BrowserProfiling", "CaptureConsole", "Console", "BrowserSession",
  ].map((name) => ({ name }));
  const kept = (o?.integrations(defaults) ?? []).map((i) => i.name);
  // Named here, not read from DROPPED_INTEGRATIONS: a test that loops the list it is testing passes when
  // someone deletes an entry from it, which is the regression this exists to catch.
  const mustDrop = ["BrowserTracing", "Replay", "ReplayCanvas", "Feedback", "BrowserProfiling", "BrowserSession", "Console", "CaptureConsole"];
  for (const name of mustDrop) assert.ok(!kept.includes(name), `${name} survived`);
  for (const name of DROPPED_INTEGRATIONS) assert.ok(!kept.includes(name), `${name} survived`);
  for (const name of ["GlobalHandlers", "LinkedErrors", "BrowserApiErrors", "Dedupe"]) {
    assert.ok(kept.includes(name), `${name} was dropped and is how an uncaught error is seen`);
  }
});

test("beforeSend scrubs an event and then spends the budget", () => {
  const o = buildSentryOptions({ dsn: DSN }, new EventBudget(2, 1));
  const event = (value: string): LooseEvent => ({
    exception: { values: [{ type: "Error", value }] },
    request: { url: "https://caflow-ai.pages.dev/sign/?t=secrettoken123" },
  });
  const first = o?.beforeSend(event("pan ABCDE1234F failed"));
  assert.ok(first);
  assert.ok(!JSON.stringify(first).includes("ABCDE1234F"));
  assert.ok(!JSON.stringify(first).includes("secrettoken123"));
  assert.equal(o?.beforeSend(event("pan ABCDE1234F failed")), null, "the same error a second time");
  assert.ok(o?.beforeSend(event("a different failure")));
  assert.equal(o?.beforeSend(event("a third failure")), null, "the cap of two");
});

test("beforeBreadcrumb is the scrubber", () => {
  const o = buildSentryOptions({ dsn: DSN });
  assert.equal(o?.beforeBreadcrumb({ category: "console", message: "x" }), null);
  assert.deepEqual(o?.beforeBreadcrumb({ category: "fetch", data: { url: "/a?b=c" } })?.data, { url: "/a" });
});

test("noise that would spend the quota on nothing actionable is ignored", () => {
  const o = buildSentryOptions({ dsn: DSN });
  const ignored = (message: string) => o?.ignoreErrors.some((p) => (typeof p === "string" ? message.includes(p) : p.test(message)));
  assert.ok(ignored("ResizeObserver loop completed with undelivered notifications"));
  assert.ok(ignored("Script error."));
  assert.ok(!ignored("TypeError: Cannot read properties of undefined (reading 'map')"));
  const denied = (url: string) => o?.denyUrls.some((p) => p.test(url));
  assert.ok(denied("chrome-extension://abc/content.js"));
  assert.ok(!denied("https://caflow-ai.pages.dev/_next/static/chunks/main.js"));
});
