// node --experimental-strip-types --test lib/auth/latestWins.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { latestWins } from "./latestWins.ts";

test("an older answer landing after a newer one does not overwrite it", () => {
  const gate = latestWins();
  let state: string | null = "unset";
  const aal1 = gate.begin<string | null>((v) => { state = v; });
  const aal2 = gate.begin<string | null>((v) => { state = v; });
  aal2("map");   // the aal2 request answers first
  aal1(null);    // the 403 from before enrolment arrives late
  assert.equal(state, "map");
});

test("answers arriving in order both apply, the latest last", () => {
  const gate = latestWins();
  const seen: string[] = [];
  const first = gate.begin<string>((v) => seen.push(v));
  first("a");
  const second = gate.begin<string>((v) => seen.push(v));
  second("b");
  assert.deepEqual(seen, ["a", "b"]);
});

test("the latest request's answer applies even when it is a failure", () => {
  // The gate orders requests; it does not judge answers. A newer failure is
  // newer information, and keeping an older map over it is a different rule.
  const gate = latestWins();
  let state: string | null = "old";
  const only = gate.begin<string | null>((v) => { state = v; });
  only(null);
  assert.equal(state, null);
});

test("two gates are independent", () => {
  const a = latestWins();
  const b = latestWins();
  let x = 0;
  let y = 0;
  const fromA = a.begin<number>((v) => { x = v; });
  b.begin<number>((v) => { y = v; });
  fromA(1);
  assert.equal(x, 1);
  assert.equal(y, 0);
});
