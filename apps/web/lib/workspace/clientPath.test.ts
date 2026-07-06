// Regression guard for the "two sidebars" bug. Run with:
//   node --experimental-strip-types --test lib/workspace/clientPath.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { isClientWorkspacePath } from "./clientPath.ts";

const UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6";

test("a real-UUID client path (and sub-paths) is a client workspace", () => {
  assert.equal(isClientWorkspacePath(`/clients/${UUID}`), true);
  assert.equal(isClientWorkspacePath(`/clients/${UUID}/`), true);
  assert.equal(isClientWorkspacePath(`/clients/${UUID}/sales`), true);
  assert.equal(isClientWorkspacePath(`/clients/${UUID}/sales/invoices/new`), true);
  assert.equal(isClientWorkspacePath(`/clients/${UUID.toUpperCase()}/sales`), true);
});

test("firm-level pages under /clients are NOT client workspaces", () => {
  assert.equal(isClientWorkspacePath("/clients"), false);
  assert.equal(isClientWorkspacePath("/clients/"), false);
  assert.equal(isClientWorkspacePath("/clients/documents"), false);
});

test("the static-export placeholder is deliberately NOT a workspace", () => {
  // This is the crux of the two-sidebars regression: if navigation ever routed
  // to a "_placeholder" URL, AppShell would render its global rails on top of
  // the client layout's rails. Nav must always resolve a real id (useParams).
  assert.equal(isClientWorkspacePath("/clients/_placeholder/sales"), false);
  assert.equal(isClientWorkspacePath("/clients/_placeholder/sales/invoices/new"), false);
});
