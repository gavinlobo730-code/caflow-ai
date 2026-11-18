// node --experimental-strip-types --test lib/auth/passwordRules.test.ts
//
// POST-A-477. The rules the screens show are the ones the sign-in service
// enforces: the live log of 18-11-2026 recorded a password update refused for
// lacking a character group while every screen said only "At least 10
// characters".
import test from "node:test";
import assert from "node:assert/strict";
import { PASSWORD_MIN_LENGTH, PASSWORD_SYMBOLS, joinWithAnd, passwordProblem, passwordRules } from "./passwordRules.ts";

test("the five rules are listed in the order the screen shows them, each with a line and a sentence form", () => {
  const rules = passwordRules("");
  assert.deepEqual(rules.map((r) => r.id), ["length", "lower", "upper", "digit", "symbol"]);
  for (const r of rules) {
    assert.ok(r.label.length > 0 && r.need.length > 0);
    assert.equal(r.met, false);
  }
  assert.equal(PASSWORD_MIN_LENGTH, 10);
});

test("a password with every group and enough characters meets every rule and has no problem", () => {
  assert.ok(passwordRules("Abcdefgh1!").every((r) => r.met));
  assert.equal(passwordProblem("Abcdefgh1!"), null);
});

test("the password the tester would naturally type — long enough, no symbol — is told it needs a symbol, and nothing else", () => {
  assert.equal(passwordProblem("Password12345"), "Your password still needs a symbol (for example ! @ # $ %).");
});

test("each rule is judged on its own, so the sentence names exactly what is missing", () => {
  assert.equal(passwordProblem("abcdefghij"), "Your password still needs a capital letter, a digit and a symbol (for example ! @ # $ %).");
  assert.equal(passwordProblem("ABCDEFGHIJ"), "Your password still needs a lowercase letter, a digit and a symbol (for example ! @ # $ %).");
  assert.equal(passwordProblem("Abcdefghij"), "Your password still needs a digit and a symbol (for example ! @ # $ %).");
  assert.equal(passwordProblem("A1!"), "Your password still needs at least 10 characters and a lowercase letter.");
  assert.equal(passwordProblem(""), "Your password still needs at least 10 characters, a lowercase letter, a capital letter, a digit and a symbol (for example ! @ # $ %).");
});

test("nine characters is one short and ten is enough", () => {
  assert.equal(passwordRules("Abcdefg1!")[0].met, false);
  assert.equal(passwordRules("Abcdefgh1!")[0].met, true);
});

test("every symbol the sign-in service lists counts, and a space or a letter does not", () => {
  for (const ch of PASSWORD_SYMBOLS) {
    assert.equal(passwordRules(`Abcdefgh1${ch}`)[4].met, true, `symbol ${ch}`);
  }
  assert.equal(passwordRules("Abcdefgh1 ")[4].met, false);
  assert.equal(passwordRules("Abcdefgh1é")[4].met, false);
});

test("the symbol list is the one the live refusal named", () => {
  assert.equal(PASSWORD_SYMBOLS, "!@#$%^&*()_+-=[]{};'\\:\"|<>?,./`~");
});

test("joinWithAnd reads as a sentence", () => {
  assert.equal(joinWithAnd([]), "");
  assert.equal(joinWithAnd(["a"]), "a");
  assert.equal(joinWithAnd(["a", "b"]), "a and b");
  assert.equal(joinWithAnd(["a", "b", "c"]), "a, b and c");
});
