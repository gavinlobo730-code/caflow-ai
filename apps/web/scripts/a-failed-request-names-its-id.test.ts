// A server-side failure names the request it was, so a CA can quote it (ops-11). Run with:
//   node --experimental-strip-types --test scripts/a-failed-request-names-its-id.test.ts
//
// The API puts X-Request-ID on every response and the same id on the one JSON log line it writes for the
// request. A CA reading "Internal server error" off a screen could not be traced; one reading "(reference
// 3f2a9c1b8d3e7a60)" can. These tests hold the browser's half: the reference is added for a 5xx and only a 5xx,
// only when the id has the shape the server issues, never twice, and `errorMessage` is what adds it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { requestIdOf, withReference } from "../lib/api/requestReference.ts";

const WEB = join(import.meta.dirname, "..");

const headers = (map: Record<string, string>) => ({
  get: (name: string) => map[name] ?? map[name.toLowerCase()] ?? null,
});

test("a server-side failure gets the id from the header", () => {
  const h = headers({ "X-Request-ID": "3f2a9c1b8d3e7a60" });
  assert.equal(withReference("Internal server error", 500, h), "Internal server error (reference 3f2a9c1b8d3e7a60)");
  assert.equal(withReference("Bad gateway", 502, h), "Bad gateway (reference 3f2a9c1b8d3e7a60)");
  assert.equal(withReference("Could not verify your account just now.", 503, h).endsWith("(reference 3f2a9c1b8d3e7a60)"), true);
});

test("a refusal the CA can act on is left alone", () => {
  const h = headers({ "X-Request-ID": "3f2a9c1b8d3e7a60" });
  for (const status of [200, 400, 401, 403, 404, 409, 422, 429]) {
    assert.equal(withReference("GSTR-3B covering this date was filed.", status, h), "GSTR-3B covering this date was filed.");
  }
});

test("a message that already names the id is not given it twice", () => {
  const h = headers({ "X-Request-ID": "3f2a9c1b8d3e7a60" });
  const said = "Internal server error (reference 3f2a9c1b8d3e7a60)";
  assert.equal(withReference(said, 500, h), said);
});

test("no header, an unreadable header and an id that is not the server's shape add nothing", () => {
  assert.equal(withReference("x", 500, headers({})), "x");
  assert.equal(withReference("x", 500, undefined), "x");
  assert.equal(withReference("x", 500, null), "x");
  assert.equal(withReference("x", 500, { get: () => { throw new Error("blocked by CORS"); } }), "x");
  for (const hostile of ["short", "has space in it", "a".repeat(65), "<script>alert(1)</script>", "id\nwith-break-1", "abcdefgh\n", "a".repeat(64) + "\n"]) {
    assert.equal(requestIdOf(headers({ "X-Request-ID": hostile })), null, hostile);
  }
  assert.equal(requestIdOf(headers({ "X-Request-ID": "req-2026-10-01-1105" })), "req-2026-10-01-1105");
});

test("errorMessage is what adds it, so every screen that goes through lib/api shows it", () => {
  const src = readFileSync(join(WEB, "lib/api/index.ts"), "utf8");
  const at = src.indexOf("export async function errorMessage(");
  assert.ok(at >= 0, "errorMessage moved: move this assertion with it");
  const body = src.slice(at, src.indexOf("\n}\n", at));
  assert.match(body, /withReference\(/, "errorMessage no longer adds the request reference");
  assert.match(body, /res\.status/, "the reference is decided on the status");
  assert.match(src, /from "@\/lib\/api\/requestReference"/);
});
