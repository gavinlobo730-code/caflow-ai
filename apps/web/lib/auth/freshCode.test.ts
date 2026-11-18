// node --experimental-strip-types --test lib/auth/freshCode.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { FRESH_CODE_SENTENCE, isFreshCodeRefusal, sixDigitCode } from "./freshCode.ts";

test("the API's sentence for a stale code is recognised, with or without the framework's words around it", () => {
  assert.equal(isFreshCodeRefusal(FRESH_CODE_SENTENCE), true);
  assert.equal(isFreshCodeRefusal(`API error 403: ${FRESH_CODE_SENTENCE}`), true);
  assert.equal(isFreshCodeRefusal("Multi-factor authentication is required for this action. Enrol at Settings → Security."), false);
  assert.equal(isFreshCodeRefusal(null), false);
  assert.equal(isFreshCodeRefusal(""), false);
});

test("a typed code is six digits once spaces and dashes are taken out, and nothing else", () => {
  assert.equal(sixDigitCode("123456"), "123456");
  assert.equal(sixDigitCode("123 456"), "123456");
  assert.equal(sixDigitCode("123-456"), "123456");
  assert.equal(sixDigitCode(" 0 1 2 3 4 5 "), "012345");
  for (const bad of ["", "12345", "1234567", "12345a", "abcdef", "123,456"]) assert.equal(sixDigitCode(bad), null, bad);
});
