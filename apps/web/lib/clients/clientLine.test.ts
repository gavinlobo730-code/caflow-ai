// Run with: node --experimental-strip-types --test lib/clients/clientLine.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { clientIdentityLine, clientSearchFields } from "./clientLine.ts";

test("the line carries the entity type, the PAN and the GSTIN in that order", () => {
  assert.equal(
    clientIdentityLine({ entity_type: "Private Limited", pan: "AABCU9603R", gstin: "27AABCU9603R1ZX" }),
    "Private Limited · AABCU9603R · 27AABCU9603R1ZX",
  );
});

test("an identifier the client does not have is left out and never drawn as a value", () => {
  assert.equal(clientIdentityLine({ entity_type: "Proprietorship", pan: "ABCDE1234F", gstin: null }), "Proprietorship · ABCDE1234F");
  assert.equal(clientIdentityLine({ entity_type: null, pan: "  ", gstin: "" }), undefined);
  assert.equal(clientIdentityLine({}), undefined);
});

test("two clients with one name are told apart by the line", () => {
  const a = clientIdentityLine({ client_name: "Sharma Enterprises", entity_type: "Partnership", pan: "AAAFS1111A" });
  const b = clientIdentityLine({ client_name: "Sharma Enterprises", entity_type: "Partnership", pan: "AAAFS2222B" });
  assert.notEqual(a, b);
});

test("the search reads the name, the PAN, the GSTIN and the entity type, and skips what is absent", () => {
  assert.deepEqual(
    clientSearchFields({ client_name: "Sharma Enterprises", entity_type: "LLP", pan: "AAAFS1111A", gstin: "27AAAFS1111A1Z5" }),
    ["Sharma Enterprises", "AAAFS1111A", "27AAAFS1111A1Z5", "LLP"],
  );
  assert.deepEqual(clientSearchFields({ client_name: "Plain Co" }), ["Plain Co"]);
});
