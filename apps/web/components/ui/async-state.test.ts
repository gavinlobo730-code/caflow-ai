// Tests for the shared async-state precedence used by AsyncBoundary. Run with:
//   node --experimental-strip-types --test components/ui/async-state.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { resolveAsyncState } from "./async-state.ts";

test("error wins over everything (even while loading/empty)", () => {
  assert.equal(resolveAsyncState({ loading: true, error: "boom", isEmpty: true }), "error");
  assert.equal(resolveAsyncState({ loading: false, error: "boom" }), "error");
});

test("loading wins over empty and content when there is no error", () => {
  assert.equal(resolveAsyncState({ loading: true, isEmpty: true }), "loading");
  assert.equal(resolveAsyncState({ loading: true, isEmpty: false }), "loading");
});

test("empty shows only when not loading, no error, and isEmpty", () => {
  assert.equal(resolveAsyncState({ loading: false, isEmpty: true }), "empty");
});

test("content shows when settled with data", () => {
  assert.equal(resolveAsyncState({ loading: false, isEmpty: false }), "content");
  assert.equal(resolveAsyncState({ loading: false }), "content"); // isEmpty defaults to false
});

test("null/empty-string error is not treated as an error", () => {
  assert.equal(resolveAsyncState({ loading: false, error: null }), "content");
  assert.equal(resolveAsyncState({ loading: true, error: "" }), "loading");
});
