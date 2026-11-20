// POST-A-501: the public signing page read a response body with `r.json().catch(() => null)`, so a request that ended while its body was still
// arriving (the bound `fetchBounded` puts on it, 45 seconds) was told as "not the product's own answer", the sentence for a gateway's page, where the
// cause is that the answer did not finish. Both reads (the letter's load and the acceptance) go through `jsonPlain` now, which says a timeout as a
// timeout (lib/api/failureSentence.test.ts holds the behaviour against a body that fails midway). This pins the page to it. Run with:
//   node --experimental-strip-types --test scripts/the-signing-page-reads-its-body-through-the-bounded-reader.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const src = fs.readFileSync(path.join(import.meta.dirname, "..", "app/sign/page.tsx"), "utf8");
const code = src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

test("the signing page reads neither body through a bare .json().catch", () => {
  assert.doesNotMatch(code, /\.json\(\)\s*\.catch\(/, "a body read that swallows why there was no body is back");
});

test("the letter's load and the acceptance each read their body through jsonPlain, with the right kind of request", () => {
  assert.match(code, /jsonPlain<UntypedJson>\(r, "read"\)/);
  assert.match(code, /jsonPlain<UntypedJson>\(r, "write"\)/);
});

test("a body of literal null is still not an answer about the link, on both reads", () => {
  assert.match(code, /if \(j === null\) throw new PlainFailure\("not_ours", notOursSentence\("read"\)\)/);
  assert.match(code, /if \(j === null\) throw new PlainFailure\("not_ours", notOursSentence\("write"\)\)/);
});
