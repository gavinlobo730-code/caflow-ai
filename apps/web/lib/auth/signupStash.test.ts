// node --experimental-strip-types --test lib/auth/signupStash.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  SIGNUP_STASH_KEY, clearSignupStash, newFirmSignupStarted, readSignupStash, writeSignupStash, type StashStorage,
} from "./signupStash.ts";

function fake(initial: Record<string, string> = {}): StashStorage & { data: Record<string, string> } {
  const data = { ...initial };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = v; }, removeItem: (k) => { delete data[k]; } };
}

test("the stash carries the firm name, the person's name and the address the link was sent to", () => {
  const s = fake();
  writeSignupStash(s, { firmName: "Sharma & Associates", fullName: "CA Ravi Sharma", email: "ravi@example.test" });
  assert.deepEqual(readSignupStash(s), { firmName: "Sharma & Associates", fullName: "CA Ravi Sharma", email: "ravi@example.test" });
  assert.equal(newFirmSignupStarted(readSignupStash(s)), true);
});

test("a stash written before the address was kept still reads, without an address", () => {
  const s = fake({ [SIGNUP_STASH_KEY]: JSON.stringify({ firmName: "A", fullName: "B" }) });
  assert.deepEqual(readSignupStash(s), { firmName: "A", fullName: "B" });
});

test("nothing, unreadable text and values that are not strings are no stash", () => {
  assert.deepEqual(readSignupStash(null), {});
  assert.deepEqual(readSignupStash(fake()), {});
  assert.deepEqual(readSignupStash(fake({ [SIGNUP_STASH_KEY]: "not json" })), {});
  assert.deepEqual(readSignupStash(fake({ [SIGNUP_STASH_KEY]: "null" })), {});
  assert.deepEqual(readSignupStash(fake({ [SIGNUP_STASH_KEY]: JSON.stringify({ firmName: 5, fullName: "", email: "   " }) })), {});
  assert.equal(newFirmSignupStarted({}), false);
});

test("clearing removes it, and storage that throws is a convenience that failed", () => {
  const s = fake();
  writeSignupStash(s, { email: "a@b.test" });
  clearSignupStash(s);
  assert.deepEqual(s.data, {});
  const throwing: StashStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  assert.deepEqual(readSignupStash(throwing), {});
  writeSignupStash(throwing, { email: "a@b.test" });
  clearSignupStash(throwing);
});
