// A dialog that holds Close and Cancel while its request is out is freed when that request is given up on (POST-A-395).
//   node --experimental-strip-types --test scripts/a-dialog-that-holds-close-is-freed-by-a-bounded-request.test.ts
//
// The engagement letters page's two dialogs hold Close and Cancel while a save or a step is out (driven in
// scripts/drive/scenarios/dialogLeftovers.mjs). Held over a request that never answers, they stayed held until the browser
// gave up, which can be minutes: the page's own JSON helper called `fetch` with no bound, where every JSON call through
// `lib/api` is aborted at 45 seconds. A held dialog is only safe over a request that ends, so the helper is bounded the same.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const page = readFileSync(join(WEB, "app/engagements/page.tsx"), "utf8");
const api = readFileSync(join(WEB, "lib/api/index.ts"), "utf8");

test("the engagement letters page's requests are bounded at lib/api's 45 seconds", () => {
  const bound = page.match(/const JSON_ABORT_MS = ([\d_]+);/);
  assert.ok(bound, "the page names no bound for its requests");
  assert.equal(Number(bound[1].replace(/_/g, "")), 45_000, "the page's bound is not 45 seconds");
  assert.match(api, /setTimeout\(\(\) => controller\.abort\(\), 45_000\)/, "lib/api's own bound moved: this page's must follow it");
  const helper = page.slice(page.indexOf("async function apiFetch("), page.indexOf("// Types"));
  assert.match(helper, /signal: AbortSignal\.timeout\(JSON_ABORT_MS\),\s*\.\.\.opts,/, "the JSON helper sends without a bound (or lets nothing override it)");
  const pdf = page.slice(page.indexOf("async function doDownloadPdf("), page.indexOf("async function doDownloadPdf(") + 900);
  assert.match(pdf, /signal: AbortSignal\.timeout\(JSON_ABORT_MS\)/, "the PDF download, which holds Close too, is not bounded");
});

test("each dialog's Close and Cancel are held while its request is out", () => {
  const template = page.slice(page.indexOf("function TemplateModal("), page.indexOf("function DetailModal("));
  assert.match(template, /onClick=\{onClose\} disabled=\{saving\} aria-label="Close"/, "the template dialog's Close is not held or not named");
  assert.match(template, /onClick=\{onClose\}\s*disabled=\{saving\}/, "the template dialog's Cancel is not held");
  const detail = page.slice(page.indexOf("function DetailModal("), page.indexOf("function EngagementsPageInner("));
  assert.match(detail, /onClick=\{onClose\} disabled=\{actionLoading\} aria-label="Close"/, "the detail dialog's Close is not held or not named");
  const cancels = detail.match(/onClick=\{\(\) => setShow\w+\(false\)\}( disabled=\{actionLoading\})?/g) ?? [];
  assert.ok(cancels.length >= 5, `the detail dialog's step Cancels were not found (${cancels.length})`);
  assert.deepEqual(cancels.filter((c) => !c.includes("disabled={actionLoading}")), [], "a step's Cancel is live while the step is out");
});
