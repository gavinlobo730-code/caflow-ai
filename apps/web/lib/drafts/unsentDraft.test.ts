// An unsent draft kept in the tab (frontend_ux-23). Run with:
//   node --experimental-strip-types --test lib/drafts/unsentDraft.test.ts
//
// What is held: it is a per-viewer convenience that can never hurt — every
// storage call survives a storage that throws, a draft is offered only if it is
// still plausible, and what comes back is rebuilt through a validator rather
// than trusted.
import test from "node:test";
import assert from "node:assert/strict";
import {
  DRAFT_PREFIX, MAX_DRAFT_AGE_MS, MAX_DRAFT_CHARS, clearAllDrafts, clearDraft, draftKey,
  readDraft, readField, saveDraft, type DraftStorage,
} from "./unsentDraft.ts";

class MemoryStorage implements DraftStorage {
  private m = new Map<string, string>();
  get length() { return this.m.size; }
  key(i: number) { return Array.from(this.m.keys())[i] ?? null; }
  getItem(k: string) { return this.m.has(k) ? (this.m.get(k) as string) : null; }
  setItem(k: string, v: string) { this.m.set(k, v); }
  removeItem(k: string) { this.m.delete(k); }
}

/** A storage that throws on every call — Safari private mode, a full quota. */
const BROKEN: DraftStorage = {
  length: 0,
  key() { throw new Error("SecurityError"); },
  getItem() { throw new Error("SecurityError"); },
  setItem() { throw new Error("QuotaExceededError"); },
  removeItem() { throw new Error("SecurityError"); },
};

const asString = (raw: unknown): string | null => (typeof raw === "string" ? raw : null);
const SCOPE = { userId: "u1", kind: "journal" as const, clientId: "c1", entityId: "new" };

test("a key names the person, kind, client and entity", () => {
  assert.equal(draftKey(SCOPE), `${DRAFT_PREFIX}u1:journal:c1:new`);
  assert.notEqual(draftKey(SCOPE), draftKey({ ...SCOPE, clientId: "c2" }), "another client's entry is not offered here");
  assert.notEqual(draftKey(SCOPE), draftKey({ ...SCOPE, userId: "u2" }), "nor to another person on the same tab");
  assert.notEqual(draftKey(SCOPE), draftKey({ ...SCOPE, entityId: "e9" }));
});

test("no key — so no draft — until every part is known", () => {
  assert.equal(draftKey({ ...SCOPE, userId: null }), null);
  assert.equal(draftKey({ ...SCOPE, clientId: "" }), null);
  assert.equal(draftKey({ ...SCOPE, entityId: undefined }), null);
  assert.equal(draftKey({ ...SCOPE, clientId: "_placeholder" }), null,
    "the static export's placeholder id would offer one client's draft into every client");
});

test("two scopes cannot collide through the separator", () => {
  assert.notEqual(
    draftKey({ ...SCOPE, clientId: "a:b", entityId: "c" }),
    draftKey({ ...SCOPE, clientId: "a", entityId: "b:c" }));
});

test("a saved draft round-trips through its validator", () => {
  const s = new MemoryStorage();
  const key = draftKey(SCOPE);
  assert.equal(saveDraft(s, key, "narration text", 1_000_000), "saved");
  const read = readDraft(s, key, asString, 1_000_000 + 5_000);
  assert.deepEqual(read, { fields: "narration text", savedAt: new Date(1_000_000).toISOString() });
});

test("every storage call survives a storage that throws", () => {
  const key = draftKey(SCOPE);
  assert.equal(saveDraft(BROKEN, key, "x"), "unavailable");
  assert.equal(readDraft(BROKEN, key, asString), null);
  assert.doesNotThrow(() => clearDraft(BROKEN, key));
  assert.doesNotThrow(() => clearAllDrafts(BROKEN));
  assert.equal(saveDraft(null, key, "x"), "unavailable", "no storage at all (SSR, blocked site data)");
  assert.equal(readDraft(null, key, asString), null);
  assert.equal(saveDraft(new MemoryStorage(), null, "x"), "unavailable", "and no key");
});

test("a draft that fails the validator is dropped, not trusted, and not re-read", () => {
  const s = new MemoryStorage();
  const key = draftKey(SCOPE) as string;
  s.setItem(key, JSON.stringify({ v: 1, savedAt: new Date().toISOString(), fields: { not: "a string" } }));
  assert.equal(readDraft(s, key, asString), null);
  assert.equal(s.getItem(key), null, "removed, so it is not offered on every visit");
});

test("malformed JSON, a wrong version and a missing timestamp are all dropped", () => {
  const s = new MemoryStorage();
  const key = draftKey(SCOPE) as string;
  for (const bad of ["{not json", "null", "42", JSON.stringify({ v: 2, savedAt: new Date().toISOString(), fields: "x" }),
    JSON.stringify({ v: 1, fields: "x" }), JSON.stringify({ v: 1, savedAt: "yesterday-ish", fields: "x" })]) {
    s.setItem(key, bad);
    assert.equal(readDraft(s, key, asString), null, bad);
    assert.equal(s.getItem(key), null, `${bad} is removed`);
  }
});

test("a draft older than a working day is not offered", () => {
  const s = new MemoryStorage();
  const key = draftKey(SCOPE) as string;
  saveDraft(s, key, "x", 0);
  assert.notEqual(readDraft(s, key, asString, MAX_DRAFT_AGE_MS - 1), null);
  assert.equal(readDraft(s, key, asString, MAX_DRAFT_AGE_MS + 1), null);
  assert.equal(s.getItem(key), null);
});

test("a draft stamped in the future is not offered either (a clock that was wrong)", () => {
  const s = new MemoryStorage();
  const key = draftKey(SCOPE) as string;
  saveDraft(s, key, "x", 10 * 60_000);
  assert.equal(readDraft(s, key, asString, 0), null);
});

test("a draft too large to be a form is dropped, and an earlier smaller one is not left to be offered", () => {
  const s = new MemoryStorage();
  const key = draftKey(SCOPE) as string;
  saveDraft(s, key, "small");
  assert.equal(saveDraft(s, key, "x".repeat(MAX_DRAFT_CHARS + 1)), "too_large");
  assert.equal(s.getItem(key), null, "the stale small draft would otherwise read as the latest");
});

test("clearing one draft leaves the others; clearing all removes only this module's", () => {
  const s = new MemoryStorage();
  const a = draftKey(SCOPE) as string;
  const b = draftKey({ ...SCOPE, clientId: "c2" }) as string;
  saveDraft(s, a, "a"); saveDraft(s, b, "b");
  s.setItem("practicesync.table.x", "keep me");
  clearDraft(s, a);
  assert.equal(s.getItem(a), null);
  assert.notEqual(s.getItem(b), null);
  clearAllDrafts(s);
  assert.equal(s.getItem(b), null);
  assert.equal(s.getItem("practicesync.table.x"), "keep me", "sign-out must not wipe the table preferences");
});

test("the field readers refuse a wrong type instead of coercing it", () => {
  assert.equal(readField.string(7), undefined);
  assert.equal(readField.string("a".repeat(11), 10), undefined, "and an over-long one");
  assert.equal(readField.string(""), "", "an empty string is a value");
  assert.equal(readField.boolean("true"), undefined);
  assert.equal(readField.finiteNumber(NaN), undefined);
  assert.equal(readField.record([]), undefined, "an array is not a record");
  assert.equal(readField.record(null), undefined);
  assert.equal(readField.list({ length: 1 }), undefined);
  assert.equal(readField.list(new Array(501).fill(0)), undefined, "and a list beyond its cap");
});
