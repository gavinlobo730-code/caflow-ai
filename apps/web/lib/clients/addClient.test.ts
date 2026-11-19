// Run with: node --experimental-strip-types --test lib/clients/addClient.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { ADD_CLIENT_HREF, wantsToAddClient } from "./addClient.ts";

test("the link the other places use is the one the page answers", () => {
  const search = ADD_CLIENT_HREF.slice(ADD_CLIENT_HREF.indexOf("?"));
  assert.equal(wantsToAddClient(search), true);
  assert.ok(ADD_CLIENT_HREF.startsWith("/clients/"), "the export serves the slashed form");
});

test("only add=1 asks for the form", () => {
  assert.equal(wantsToAddClient("?add=1"), true);
  assert.equal(wantsToAddClient("?filter=archived&add=1"), true);
  assert.equal(wantsToAddClient(""), false);
  assert.equal(wantsToAddClient("?add=0"), false);
  assert.equal(wantsToAddClient("?add=true"), false);
  assert.equal(wantsToAddClient("?address=1"), false);
});
