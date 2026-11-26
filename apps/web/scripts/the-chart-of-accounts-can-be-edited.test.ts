// Accounting > Accounts (Chart of Accounts) had no way to add or edit an
// account anywhere in the UI, although POST /api/accounting/accounts and
// PATCH /api/accounting/accounts/{id} have taken real writes since they were
// built, and lib/api/index.ts's createAccount/updateAccount sat unused. Run
// with:
//   node --experimental-strip-types --test scripts/the-chart-of-accounts-can-be-edited.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

const ACCOUNTING_PAGE = "app/clients/[id]/accounting/page.tsx";
const API_FILE = "lib/api/index.ts";

function componentBody(code: string, name: string): string {
  const start = code.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `could not find function ${name}`);
  let parenDepth = 0, i = start;
  for (; i < code.length; i++) {
    if (code[i] === "(") parenDepth++;
    else if (code[i] === ")" && --parenDepth === 0) { i++; break; }
  }
  const braceStart = code.indexOf("{", i);
  let depth = 0;
  for (i = braceStart; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}") {
      depth--;
      if (depth === 0) return code.slice(braceStart, i + 1);
    }
  }
  throw new Error(`unterminated body for ${name}`);
}

const page = read(ACCOUNTING_PAGE);
const api = read(API_FILE);

test("the backend client carries a client_id through to createAccount, as a query param", () => {
  assert.match(api, /createAccount:\s*\(data:\s*unknown,\s*clientId\?:\s*string\)/,
    "createAccount must accept the client_id the backend's POST " +
    "/api/accounting/accounts reads as a query param — omitting it silently " +
    "creates a FIRM-LEVEL account shared by every client, which must be a " +
    "choice and never the accidental default for a client-scoped screen");
  assert.match(api, /client_id=\$\{encodeURIComponent\(clientId\)\}/,
    "client_id must actually reach the query string, not just the type signature");
});

test("ChartOfAccounts offers Add Account", () => {
  const body = componentBody(page, "ChartOfAccounts");
  assert.match(body, /<Plus size=\{12\} \/> Add Account/,
    "no Add Account button on the Chart of Accounts screen");
  assert.match(body, /<AddAccountModal clientId=\{clientId\}/,
    "the Add Account button must open AddAccountModal, scoped to this client");
});

test("AddAccountModal validates and posts through the real create endpoint", () => {
  const body = componentBody(page, "AddAccountModal");
  assert.match(body, /Account name is required/, "name is validated");
  assert.match(body, /An account code is required/, "code is validated — " +
    "the backend refuses a blank one too, and the reason is the same");
  assert.match(body, /await api\.accounting\.createAccount\(body, firmWide \? undefined : clientId\)/,
    "must call the real endpoint, client-scoped by default — a client's own " +
    "Chart of Accounts screen creating a firm-wide account by accident would " +
    "put it on every OTHER client's chart too");
  // Same double-submission-guard shape as AddAssetDrawer/CorrectAssetDrawer.
  assert.match(body, /const submittingRef = useRef\(false\)/);
  assert.match(body, /if \(submittingRef\.current\) return;/);
});

test("LedgerDrillDown offers Edit on the selected account", () => {
  const body = componentBody(page, "LedgerDrillDown");
  assert.match(body, /onClick=\{\(\) => setEditing\(true\)\}/,
    "no Edit action wired on the ledger drill-down's header");
  assert.match(body, /<EditAccountModal\s+account=\{selectedAccount\}/,
    "Edit must open EditAccountModal for the account currently being viewed");
});

test("LedgerDrillDown takes a refresh callback for after an edit", () => {
  // In the destructured-props type annotation, which sits BEFORE the
  // function's own body (componentBody only captures the body) — checked
  // against the whole file rather than the extracted body for that reason.
  assert.match(page, /onAccountUpdated:\s*\(\)\s*=>\s*void;/,
    "LedgerDrillDown must take a refresh callback so a save reaches the " +
    "chart behind it, not just this modal's own local state");
  assert.match(page, /onAccountUpdated=\{loadAccounts\}/,
    "the caller must wire it to the same loadAccounts the Chart of " +
    "Accounts screen already refreshes from — a second, independent fetch " +
    "here is how two copies of \"the chart\" come to disagree");
});

test("EditAccountModal cannot change account_type", () => {
  const body = componentBody(page, "EditAccountModal");
  // The backend's AccountUpdateIn has no account_type field at all (it
  // decides which side of the trial balance the account falls on), so the
  // form must not invite a CA to type a new one it knows will be refused —
  // or worse, silently dropped.
  assert.doesNotMatch(body, /account_type:\s*form\.account_type/,
    "the save payload must never include account_type — the backend has no " +
    "field for it and changing it after a posting would silently restate " +
    "every report");
  assert.match(body, /<Input value=\{account\.account_type\} disabled \/>/,
    "the Type field must be shown but disabled, with the reason visible, " +
    "not simply omitted — a CA should be told WHY rather than wonder where it went");
});

test("EditAccountModal sends only the fields that actually changed", () => {
  const body = componentBody(page, "EditAccountModal");
  assert.match(body, /if \(Object\.keys\(body\)\.length === 0\)/,
    "a save with nothing changed must not fire a PATCH with an empty body " +
    "(the backend 422s that with \"Nothing to change.\")");
});

test("the account editor over the ledger is the shared dialog, and neither keeps a layer or a key listener of its own", () => {
  // The editor used to be a hand-built layer that stopped every click, because it sat under the ledger's click-to-close backdrop in the
  // component tree. Both are the shared Modal now (POST-A-130): there is no backdrop of the ledger's above the editor, and the shared stack
  // gives Escape to the top dialog alone, so neither a stopped click nor a key listener is needed, and one left behind would read as the
  // thing doing the work. That a click inside the editor closes nothing is driven in a browser (weekly group `ledger-dialogs`).
  const editor = componentBody(page, "EditAccountModal");
  const ledger = componentBody(page, "LedgerDrillDown");
  for (const [name, body] of [["EditAccountModal", editor], ["LedgerDrillDown", ledger]] as const) {
    assert.match(body, /<Modal\s+title=/, `${name} is not drawn with the shared Modal`);
    assert.doesNotMatch(body, /fixed inset-0/, `${name} draws a window-covering layer of its own again`);
    assert.doesNotMatch(body, /addEventListener\("keydown"/, `${name} listens for keys itself again: the shared dialog owns Escape`);
  }
  // While its save is out the editor's close (Escape, a click beside it, its close button) is held (POST-A-395).
  assert.match(editor, /onClose=\{\(\) => \{ if \(!saving\) onClose\(\); \}\}/, "the account editor can be closed while its save is out");
  assert.match(ledger, /\{editing && selectedAccount && \(\s*<EditAccountModal/, "the ledger no longer opens the editor for the account being viewed");
});
