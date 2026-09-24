// Regression guard for the "two sidebars" bug. Run with:
//   node --experimental-strip-types --test lib/workspace/clientPath.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { isClientWorkspacePath, switchClientPath } from "./clientPath.ts";

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

test("switching client carries the SECTION and never the document", () => {
  const OTHER = "11111111-2222-3333-4444-555555555555";
  // The point of the feature: same tab, different client.
  assert.equal(switchClientPath(`/clients/${UUID}/bank`, OTHER), `/clients/${OTHER}/bank/`);
  assert.equal(switchClientPath(`/clients/${UUID}/bank/`, OTHER), `/clients/${OTHER}/bank/`);
  // The trap: a document id belongs to the client you are LEAVING.
  assert.equal(
    switchClientPath(`/clients/${UUID}/sales/invoices/${OTHER}/edit`, OTHER),
    `/clients/${OTHER}/sales/`,
  );
  assert.equal(
    switchClientPath(`/clients/${UUID}/reports/ageing`, OTHER),
    `/clients/${OTHER}/reports/`,
  );
});

test("switching from somewhere with no section lands on overview", () => {
  const OTHER = "11111111-2222-3333-4444-555555555555";
  assert.equal(switchClientPath(`/clients/${UUID}`, OTHER), `/clients/${OTHER}/overview/`);
  assert.equal(switchClientPath(`/clients/${UUID}/`, OTHER), `/clients/${OTHER}/overview/`);
  // Not a client workspace at all — the firm-level list, or the placeholder.
  assert.equal(switchClientPath("/clients", OTHER), `/clients/${OTHER}/overview/`);
  assert.equal(switchClientPath("/clients/_placeholder/sales", OTHER), `/clients/${OTHER}/overview/`);
  assert.equal(switchClientPath("/accounting/journal", OTHER), `/clients/${OTHER}/overview/`);
});

test("the destination always carries a trailing slash", () => {
  // next.config.mjs sets trailingSlash: true. A bare path needs one of the 43
  // enumerated Cloudflare rules D10 protects; the slashed form is splat-covered.
  const OTHER = "11111111-2222-3333-4444-555555555555";
  for (const from of [`/clients/${UUID}/tax/computation`, `/clients/${UUID}`, "/clients"]) {
    assert.ok(switchClientPath(from, OTHER).endsWith("/"), `no trailing slash from ${from}`);
  }
});
