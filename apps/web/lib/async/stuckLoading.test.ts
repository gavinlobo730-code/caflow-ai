// Run with: node --experimental-strip-types --test lib/async/stuckLoading.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { STUCK_AFTER_MS, isPageCodeFailure, mayReloadForPageCode, PAGE_CODE_RELOAD_WINDOW_MS } from "./stuckLoading.ts";

class Memory {
  private m = new Map<string, string>();
  getItem(k: string) { return this.m.get(k) ?? null; }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

test("the entry screens speak after eight seconds", () => {
  assert.equal(STUCK_AFTER_MS, 8000);
});

test("a page's own files failing to load is recognised in every browser's words", () => {
  assert.equal(isPageCodeFailure({ name: "ChunkLoadError", message: "x" }), true);
  assert.equal(isPageCodeFailure(new Error("Loading chunk 123 failed.\n(error: https://x/_next/static/chunks/123.js)")), true);
  assert.equal(isPageCodeFailure(new TypeError("Failed to fetch dynamically imported module: https://x/a.js")), true);
  assert.equal(isPageCodeFailure(new TypeError("Importing a module script failed.")), true);
  assert.equal(isPageCodeFailure(new Error("error loading dynamically imported module: https://x/a.js")), true);
});

test("a render error in the page's own logic is not one, and is never reloaded away", () => {
  assert.equal(isPageCodeFailure(new Error("Cannot read properties of undefined (reading 'map')")), false);
  assert.equal(isPageCodeFailure(new TypeError("x is not a function")), false);
  assert.equal(isPageCodeFailure(null), false);
  assert.equal(isPageCodeFailure("Loading chunk 1 failed"), false);
});

test("the page reloads itself once, and a second failure inside the minute is left to say so", () => {
  const mem = new Memory();
  assert.equal(mayReloadForPageCode(mem, 1_000_000), true);
  assert.equal(mayReloadForPageCode(mem, 1_000_000 + 5_000), false);
  assert.equal(mayReloadForPageCode(mem, 1_000_000 + PAGE_CODE_RELOAD_WINDOW_MS - 1), false);
  assert.equal(mayReloadForPageCode(mem, 1_000_000 + PAGE_CODE_RELOAD_WINDOW_MS), true);
});

test("a memory that cannot be used never reloads, because it could repeat for ever", () => {
  assert.equal(mayReloadForPageCode(null, 1_000_000), false);
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.equal(mayReloadForPageCode(broken, 1_000_000), false);
});
