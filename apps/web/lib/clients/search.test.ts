// Regression tests for the null-safe Clients search (BUG 001 — search crashed
// with "Cannot read properties of null (reading 'toLowerCase')" once PAN became
// nullable in migration 133). Run with:
//   node --experimental-strip-types --test lib/clients/search.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { filterClients, clientMatchesQuery } from "./search.ts";

// Build a Client-shaped object; `as any` lets us inject null/undefined fields
// that the (stricter) TS type would otherwise forbid — exactly the runtime
// shape the API returns now that several columns are nullable.
function mk(over = {}) {
  return {
    id: "c1",
    client_name: "Acme Industries Pvt Ltd",
    entity_type: "Private Limited",
    pan: "AABCU9603R",
    gstin: "27ZZZZZ0000Z1ZX",      // intentionally does NOT embed the PAN (avoids fixture cross-matches)
    email: "contact@example.com",  // intentionally does NOT contain "acme"
    mobile: "9876543210",
    city: "Mumbai",
    state: "Maharashtra",
    pincode: "400001",
    gst_filing_frequency: "monthly",
    status: "active",
    created_at: "2026-01-01",
    ...over,
  } as any;
}

// ── The exact crash repro ──────────────────────────────────────────────────────

test("BUG 001: searching a PAN does not crash when a client has NULL pan", () => {
  const clients = [
    mk({ id: "no-pan", pan: null, client_name: "No PAN Co" }),
    mk({ id: "has-pan", pan: "AABCU9603R", client_name: "Has PAN Co" }),
  ];
  // Pasting a PAN must not throw, and must match the client that has it.
  let result;
  assert.doesNotThrow(() => { result = filterClients(clients, "AABCU9603R"); });
  assert.deepEqual(result.map((c) => c.id), ["has-pan"]);
});

// ── Null / undefined / empty fields are ignored, never thrown on ───────────────

test("client with NULL pan is searchable by other fields", () => {
  const clients = [mk({ pan: null })];
  assert.equal(filterClients(clients, "acme").length, 1);   // matched by name
  assert.equal(filterClients(clients, "mumbai").length, 1); // matched by city
});

test("client with NULL gstin does not crash", () => {
  const clients = [mk({ gstin: null })];
  assert.doesNotThrow(() => filterClients(clients, "27AABCU"));
  assert.equal(filterClients(clients, "27AABCU").length, 0);
  assert.equal(filterClients(clients, "acme").length, 1);
});

test("client with MANY null/undefined/empty fields never throws", () => {
  const clients = [mk({
    pan: null, gstin: undefined, email: null, mobile: "",
    city: null, state: undefined, pincode: null, address_line1: null,
  })];
  for (const q of ["AABCU9603R", "27GST", "owner@", "9876", "mumbai", "xyz"]) {
    assert.doesNotThrow(() => filterClients(clients, q), `query ${q} threw`);
  }
  // Still findable by its (required, non-null) name.
  assert.equal(filterClients(clients, "acme").length, 1);
});

test("non-string field values are ignored, not coerced or thrown", () => {
  // Defensive: even a stray number/object in a field must not break search.
  const clients = [mk({ pan: 12345, city: { weird: true } })];
  assert.doesNotThrow(() => filterClients(clients, "123"));
  assert.equal(filterClients(clients, "123").length, 0);
});

// ── Query behaviours ───────────────────────────────────────────────────────────

test("empty search returns all clients", () => {
  const clients = [mk({ id: "a" }), mk({ id: "b", pan: null })];
  assert.deepEqual(filterClients(clients, "").map((c) => c.id), ["a", "b"]);
});

test("whitespace-only search is treated as empty (returns all)", () => {
  const clients = [mk({ id: "a" }), mk({ id: "b" })];
  assert.equal(filterClients(clients, "   ").length, 2);
});

test("partial, case-insensitive match on name", () => {
  const clients = [mk({ client_name: "Acme Industries" }), mk({ client_name: "Beta Corp" })];
  assert.equal(filterClients(clients, "ACME").length, 1);
  assert.equal(filterClients(clients, "indus").length, 1);
});

test("PAN search matches case-insensitively and partially", () => {
  const clients = [mk({ pan: "AABCU9603R" }), mk({ pan: "ZZZZZ1111Z" })];
  assert.equal(filterClients(clients, "aabcu9603r").length, 1);
  assert.equal(filterClients(clients, "AABCU").length, 1);
});

test("GSTIN search works", () => {
  const clients = [mk({ gstin: "27AABCU9603R1ZX" }), mk({ gstin: "29ZZZZZ1111Z1ZX" })];
  assert.equal(filterClients(clients, "27aabcu").length, 1);
});

test("email and phone are searchable", () => {
  const clients = [mk({ email: "cfo@beta.in", mobile: "9000000001" })];
  assert.equal(filterClients(clients, "cfo@beta").length, 1);
  assert.equal(filterClients(clients, "9000000001").length, 1);
});

test("random text matches nothing and does not throw", () => {
  const clients = [mk(), mk({ pan: null, gstin: null })];
  assert.equal(filterClients(clients, "no-such-client-xyz").length, 0);
});

test("clientMatchesQuery is null-safe at the single-client level", () => {
  const c = mk({ pan: null, gstin: null, email: null });
  assert.doesNotThrow(() => clientMatchesQuery(c, "AABCU9603R"));
  assert.equal(clientMatchesQuery(c, "AABCU9603R"), false);
  assert.equal(clientMatchesQuery(c, "acme"), true);
  assert.equal(clientMatchesQuery(c, ""), true);   // empty query always matches
});
