// What a request that failed outright says to a person (POST-A-406, POST-A-382). Run with:
//   node --experimental-strip-types --test lib/api/failureSentence.test.ts
//
// The engines' own words are fed in as they are: Chrome, Firefox, Safari and the engine under Node.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  NOT_OURS_READ, NOT_OURS_WRITE, NO_ANSWER_READ, NO_ANSWER_WRITE,
  PlainFailure, browserFailureOf, doingOf, errorPageSentence, failureSentence, fetchPlain, jsonPlain, looksLikeMarkup, modelSentence, plainFailure, stillNoAnswerSentence, timedOutSentence,
} from "./failureSentence.ts";

const NO_ANSWER_SPELLINGS: [string, unknown][] = [
  ["Chrome", new TypeError("Failed to fetch")],
  ["Firefox", new TypeError("NetworkError when attempting to fetch resource.")],
  ["Safari", new TypeError("Load failed")],
  ["Node", new TypeError("fetch failed")],
  ["a body that breaks half way (Chrome)", new TypeError("network error")],
  ["a body that breaks half way (Node)", new TypeError("terminated")],
  ["Safari offline", new TypeError("The Internet connection appears to be offline.")],
  ["Safari, older: the request timed out", new TypeError("The request timed out.")],
  ["Safari, older: no connection", new TypeError("Could not connect to the server.")],
  ["Safari, older: no such host", new TypeError("A server with the specified hostname could not be found.")],
  ["Safari: cancelled", new TypeError("cancelled")],
  // the Supabase client words a failed fetch "<name>: <message>" and the screens rethrow that as a plain Error
  ["the Supabase client, Chrome", new Error("TypeError: Failed to fetch")],
  ["the Supabase client, Safari", new Error("TypeError: Load failed")],
  ["the Supabase client, Firefox", new Error("TypeError: NetworkError when attempting to fetch resource.")],
  ["the Supabase client, a FetchError", new Error("FetchError: network error")],
  ["the same words in a plain Error a reader rethrew", new Error("Failed to fetch")],
  ["a request stopped before an answer", Object.assign(new Error("signal is aborted without reason"), { name: "AbortError" })],
  ["a timeout", Object.assign(new Error("The operation timed out."), { name: "TimeoutError" })],
  ["the auth client's own report", Object.assign(new Error("anything"), { name: "AuthRetryableFetchError" })],
];

const NOT_OURS_SPELLINGS: [string, unknown][] = [
  ["Chrome", new SyntaxError(`Unexpected token '<', "<html><bod"... is not valid JSON`)],
  ["Chrome, older", new SyntaxError("Unexpected token < in JSON at position 0")],
  ["Chrome, an empty body", new SyntaxError("Unexpected end of JSON input")],
  ["Firefox", new SyntaxError("JSON.parse: unexpected character at line 1 column 1 of the JSON data")],
  ["Safari", new SyntaxError("JSON Parse error: Unrecognized token '<'")],
  ["a reader's plain Error with the engine's words", new Error(`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`)],
  ["a SyntaxError in an engine's future wording", new SyntaxError("the JSON text could not be read")],
  ["Safari, older", new SyntaxError("The string did not match the expected pattern.")],
  ["the Supabase client", new Error("SyntaxError: Unexpected token '<', \"<html>\" is not valid JSON")],
];

test("a dropped connection is recognised in every engine's words", () => {
  for (const [engine, e] of NO_ANSWER_SPELLINGS) assert.equal(browserFailureOf(e), "no_answer", engine);
});

test("an answer that is not JSON is recognised in every engine's words", () => {
  for (const [engine, e] of NOT_OURS_SPELLINGS) assert.equal(browserFailureOf(e), "not_ours", engine);
});

test("nothing else is rewritten: a server's sentence, a programming error and a non-error pass through", () => {
  const others: unknown[] = [
    new Error("GSTR-3B covering this date was filed on 18 Jul 2026."),
    new Error("Not found"),
    new Error("API error 500"),
    new TypeError("Cannot read properties of undefined (reading 'rows')"),
    new TypeError("x.map is not a function"),
    new TypeError("Failed to construct 'URL': Invalid URL"),
    // common words are the browser's only when a TypeError (or a client prefix) carries them: the product's own Error("load failed") is its own
    new Error("load failed"),
    new Error("Load failed"),
    new Error("terminated"),
    new Error("cancelled"),
    new SyntaxError("The string did not match the expected pattern in the pasted file"),
    new Error("Error: Failed to fetch the list of filings for this client"),
    new SyntaxError("Unexpected identifier 'foo'"),
    new Error("The server is taking too long to respond (it may be waking up). Please retry in a moment."),
    new Error("Failed to fetch the list of filings for this client"),
    "Failed to fetch", null, undefined, 42, {},
  ];
  for (const e of others) assert.equal(browserFailureOf(e), null, String(e));
});

test("a read says that no result came back and a write says that it is not known whether it went through", () => {
  for (const [, e] of NO_ANSWER_SPELLINGS) {
    assert.equal(failureSentence(e, "x", "read"), NO_ANSWER_READ);
    assert.equal(failureSentence(e, "x", "write"), NO_ANSWER_WRITE);
  }
  for (const [, e] of NOT_OURS_SPELLINGS) {
    assert.equal(failureSentence(e, "x", "read"), NOT_OURS_READ);
    assert.equal(failureSentence(e, "x", "write"), NOT_OURS_WRITE);
  }
  // A write is the default: it is the more careful of the two.
  assert.equal(failureSentence(new TypeError("Failed to fetch"), "x"), NO_ANSWER_WRITE);
});

test("a write never claims that nothing was changed, and no sentence carries the browser's words", () => {
  for (const s of [NO_ANSWER_READ, NO_ANSWER_WRITE, NOT_OURS_READ, NOT_OURS_WRITE, errorPageSentence(502)]) {
    assert.doesNotMatch(s, /failed to fetch|json|unexpected token|networkerror|load failed/i, s);
  }
  for (const s of [NO_ANSWER_WRITE, NOT_OURS_WRITE, errorPageSentence(502)]) {
    assert.doesNotMatch(s, /nothing (was )?(saved|changed|recorded)|was not saved|not been saved/i, s);
    assert.match(s, /whether it/i, s);
  }
});

test("the server's own sentence is shown as it is, and the fallback only when there is none", () => {
  assert.equal(failureSentence(new Error("The year is locked."), "fallback"), "The year is locked.");
  assert.equal(failureSentence(new Error(""), "fallback"), "fallback");
  assert.equal(failureSentence(new Error("   "), "fallback"), "fallback");
  assert.equal(failureSentence("a string", "fallback"), "fallback");
  assert.equal(failureSentence(undefined, "fallback", "read"), "fallback");
  // An error-like object that is not an Error (a database error) is not read out: that is the screen's fallback, as it was.
  assert.equal(failureSentence({ message: "duplicate key value violates unique constraint" }, "fallback"), "fallback");
});

test("a request that timed out or got no answer twice says what it was", () => {
  assert.match(timedOutSentence("read"), /Please try again\./);
  assert.match(timedOutSentence("write"), /not known whether the request went through/);
  assert.doesNotMatch(timedOutSentence("write"), /Please try again|nothing (was )?(saved|changed|recorded)/i);
  assert.match(stillNoAnswerSentence("read"), /may be waking up/);
  assert.equal(stillNoAnswerSentence("write"), NO_ANSWER_WRITE);
});

test("a page under a failed status is worth another try only when it came from a gateway that may be waking", () => {
  assert.match(errorPageSentence(502), /Try again in a moment; if this was a change, reload the page/);
  assert.match(errorPageSentence(503), /\(error 503\)/);
  assert.match(errorPageSentence(413), /\(error 413\)/);
  assert.match(errorPageSentence(413), /trying again is unlikely to help/);
  assert.doesNotMatch(errorPageSentence(413), /Try again in a moment/);
  assert.doesNotMatch(errorPageSentence(403), /recorded/);
});

test("a method asks or may change", () => {
  assert.equal(doingOf(undefined), "read");
  assert.equal(doingOf(null), "read");
  assert.equal(doingOf("get"), "read");
  assert.equal(doingOf("HEAD"), "read");
  for (const m of ["POST", "PATCH", "put", "DELETE"]) assert.equal(doingOf(m), "write", m);
});

test("plainFailure keeps the browser's error as the cause and leaves every other error as it was", () => {
  const dropped = new TypeError("Failed to fetch");
  const plain = plainFailure(dropped, "write") as Error & { cause?: unknown };
  assert.ok(plain instanceof Error);
  assert.ok(plain instanceof PlainFailure, "a screen cannot tell it from an Error the server's answer made");
  assert.equal((plain as PlainFailure).kind, "no_answer");
  assert.equal(plain.message, NO_ANSWER_WRITE);
  assert.equal(plain.cause, dropped);
  assert.equal((plainFailure(new SyntaxError("Unexpected end of JSON input"), "read") as PlainFailure).kind, "not_ours");
  assert.equal(new Error("The year is locked.") instanceof PlainFailure, false);
  const ours = new Error("The year is locked.");
  assert.equal(plainFailure(ours, "write"), ours);
  const bug = new TypeError("x is not a function");
  assert.equal(plainFailure(bug, "read"), bug);
});

function withFetch<T>(impl: typeof fetch, run: () => Promise<T>): Promise<T> {
  const real = globalThis.fetch;
  globalThis.fetch = impl;
  return run().finally(() => { globalThis.fetch = real; });
}

test("fetchPlain says the plain sentence for a dropped connection, by what the request was, and hands an answer on", async () => {
  const dropped: typeof fetch = async () => { throw new TypeError("Failed to fetch"); };
  await withFetch(dropped, async () => {
    await assert.rejects(fetchPlain("https://api.test/x", { method: "POST" }, "write"), { message: NO_ANSWER_WRITE });
    await assert.rejects(fetchPlain("https://api.test/x", undefined, "read"), { message: NO_ANSWER_READ });
  });
  const answered: typeof fetch = async () => new Response("{}", { status: 200 });
  await withFetch(answered, async () => {
    const res = await fetchPlain("https://api.test/x", undefined, "read");
    assert.equal(res.status, 200);
  });
  const bug: typeof fetch = async () => { throw new TypeError("Failed to construct 'Request': Invalid URL"); };
  await withFetch(bug, async () => {
    await assert.rejects(fetchPlain("nope", undefined, "read"), { message: "Failed to construct 'Request': Invalid URL" });
  });
});

test("jsonPlain reads JSON, and says that a page is not the product's answer", async () => {
  assert.deepEqual(await jsonPlain<{ a: number }>(new Response('{"a":1}'), "read"), { a: 1 });
  await assert.rejects(jsonPlain(new Response("<html><body>Bad gateway</body></html>", { status: 200 }), "write"), { message: NOT_OURS_WRITE });
  await assert.rejects(jsonPlain(new Response("<html><body>Bad gateway</body></html>", { status: 200 }), "read"), { message: NOT_OURS_READ });
  await assert.rejects(jsonPlain(new Response("", { status: 200 }), "write"), { message: NOT_OURS_WRITE });
});

test("a body that opens as a document is a page and nothing else is", () => {
  for (const body of ["<!DOCTYPE html><html>", "  <html><body>Bad gateway</body></html>", "<?xml version='1.0'?><error/>", "<HTML>", "\n<head><title>502</title></head>"]) {
    assert.equal(looksLikeMarkup(body), true, body);
  }
  for (const body of ["", "   ", '{"detail":"Not found"}', "Internal Server Error", "API error", "a < b", "<3 you"]) {
    assert.equal(looksLikeMarkup(body), false, body);
  }
  assert.match(errorPageSentence(502), /\(error 502\)/);
});

test("the drive says the sentences the module says, word for word", () => {
  // The browser drive runs in plain node and cannot import a module of the app, so it spells the sentences it expects; this is what keeps the two from drifting.
  const drive = path.join(import.meta.dirname, "..", "..", "scripts", "drive", "scenarios");
  const spelled = (file: string, name: string): string => {
    const m = fs.readFileSync(path.join(drive, file), "utf8").match(new RegExp(`const ${name} = "((?:[^"\\\\]|\\\\.)*)";`));
    assert.ok(m, `${file} has no ${name}`);
    return JSON.parse(`"${m[1]}"`);
  };
  for (const file of ["complianceAnswers.mjs", "failedRequests.mjs"]) {
    assert.equal(spelled(file, "NOT_OURS_WRITE"), NOT_OURS_WRITE, file);
  }
  for (const file of ["heldBackStatement.mjs", "failedRequests.mjs"]) {
    assert.equal(spelled(file, "NOT_OURS_READ"), NOT_OURS_READ, file);
  }
  assert.equal(spelled("failedRequests.mjs", "ERROR_PAGE_502"), errorPageSentence(502));
});

test("a request model's sentence is shown without the framework's label", () => {
  assert.equal(modelSentence("Value error, The financial year must look like 2025-26."), "The financial year must look like 2025-26.");
  assert.equal(modelSentence("value error,   a date after today"), "a date after today");
  assert.equal(modelSentence("Assertion failed, the amounts do not add up"), "the amounts do not add up");
  // a sentence that merely contains the words, a built-in message and an empty one are left as they are
  assert.equal(modelSentence("A value error, as the label says, is not stripped from the middle."), "A value error, as the label says, is not stripped from the middle.");
  assert.equal(modelSentence("String should have at least 10 characters"), "String should have at least 10 characters");
  assert.equal(modelSentence(""), "");
});
