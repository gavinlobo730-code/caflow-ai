import { test } from "node:test";
import assert from "node:assert/strict";
import { scoreBasisLine } from "./scoreBasis.ts";

test("every client scored: the mean, and how old the oldest is", () => {
  assert.equal(scoreBasisLine({ scored: 8, clients: 8, oldest_calculated_on: "2026-10-18" }),
    "Mean of 8 clients' stored scores, the oldest calculated on 18 Oct 2026.");
});

test("some clients scored: says how many, so one client's score is not read as the firm's", () => {
  assert.equal(scoreBasisLine({ scored: 2, clients: 8, oldest_calculated_on: "2026-10-18" }),
    "Mean of 2 clients' stored scores (2 of 8 clients scored), the oldest calculated on 18 Oct 2026.");
  assert.equal(scoreBasisLine({ scored: 1, clients: 8, oldest_calculated_on: "2026-10-20" }),
    "The score of 1 client (1 of 8 clients scored), the oldest calculated on 20 Oct 2026.");
});

test("a score with no recorded time is not given a day", () => {
  assert.equal(scoreBasisLine({ scored: 3, clients: 3, oldest_calculated_on: null }), "Mean of 3 clients' stored scores.");
});

test("nobody scored says so in words, and a firm with no clients says that", () => {
  assert.equal(scoreBasisLine({ scored: 0, clients: 8, oldest_calculated_on: null }), "None of 8 clients has been scored yet.");
  assert.equal(scoreBasisLine({ scored: 0, clients: 1, oldest_calculated_on: null }), "None of 1 client has been scored yet.");
  assert.equal(scoreBasisLine({ scored: 0, clients: 0, oldest_calculated_on: null }), "No clients yet.");
});

test("a payload with no basis (a server one deploy behind) says nothing", () => {
  assert.equal(scoreBasisLine(undefined), null);
  assert.equal(scoreBasisLine(null), null);
  assert.equal(scoreBasisLine({ scored: "3" as unknown as number, clients: 3, oldest_calculated_on: null }), null);
});

test("scores that could not be read are not 'none scored'", () => {
  assert.equal(scoreBasisLine({ scored: 0, clients: 8, oldest_calculated_on: null, unreadable: true }),
    "The stored scores could not be read just now.");
  assert.equal(scoreBasisLine({ scored: 0, clients: 8, oldest_calculated_on: null, unreadable: false }),
    "None of 8 clients has been scored yet.");
});

test("a count that is not a number says nothing, whichever count it is", () => {
  assert.equal(scoreBasisLine({ scored: 3, clients: null as unknown as number, oldest_calculated_on: null }), null);
  assert.equal(scoreBasisLine({ scored: null as unknown as number, clients: 3, oldest_calculated_on: null }), null);
});
