// The classification controls reach the API — a call-site test, on purpose.
//
//   node --experimental-strip-types --test lib/invoices/classificationWiring.test.ts
//
// WHY THIS FILE EXISTS AT ALL
//     classification.test.ts proves the module is right. That is exactly what
//     was already true of domain/gst/classifier.py: complete, correct, and never
//     reached. Migration 268 gave client_sales_invoices the three columns and
//     the API accepted them for a whole release while no screen set any of them,
//     so every invoice was filed as an ordinary domestic taxable sale.
//
//     A unit test on the helper cannot see that. This one reads InvoiceEditor's
//     actual request bodies and asserts the fields are in them — and, just as
//     importantly, that they are ABSENT from the one request that must not
//     carry them.
//
//     Same shape as scripts/loading-flags.test.ts and private-components.test.ts:
//     walk the source, assert a structural fact the type system cannot.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EDITOR = path.join(__dirname, "../../components/invoices/InvoiceEditor.tsx");

const source = fs.readFileSync(EDITOR, "utf8");

/**
 * Blank out comments, preserving length so offsets stay comparable.
 *
 * THIS IS NOT INCIDENTAL. The first version of this file scanned the raw source,
 * and the apostrophe in a `// the server's ...` comment inside one of the
 * request bodies read as the start of a string literal — so the brace matcher
 * ran past that body's closing brace and returned the wrong object. The draft
 * test then passed while asserting against the create payload, and a mutation
 * that deleted the draft's classification failed nothing.
 *
 * That is the same defect this file exists to catch, one level up. Comments go
 * before anything is matched.
 */
function stripComments(src: string): string {
  let out = "";
  let i = 0;
  let quote: string | null = null;
  while (i < src.length) {
    const c = src[i];
    const d = src[i + 1];
    if (quote) {
      if (c === "\\") { out += "  "; i += 2; continue; }
      out += c;
      if (c === quote) quote = null;
      i++;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; out += c; i++; continue; }
    if (c === "/" && d === "/") {
      while (i < src.length && src[i] !== "\n") { out += " "; i++; }
      continue;
    }
    if (c === "/" && d === "*") {
      const end = src.indexOf("*/", i + 2);
      const stop = end === -1 ? src.length : end + 2;
      for (let k = i; k < stop; k++) out += src[k] === "\n" ? "\n" : " ";
      i = stop;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

/** The editor with comments blanked — everything structural is matched on this. */
const code = stripComments(source);

/**
 * Extract the balanced `{...}` object literal that starts at or after `from`.
 * Counts braces and skips string literals; comments are already gone.
 */
function objectLiteralAt(src: string, from: number): string {
  const start = src.indexOf("{", from);
  assert.ok(start !== -1, "no object literal found");
  let depth = 0;
  let quote: string | null = null;
  for (let i = start; i < src.length; i++) {
    const c = src[i];
    if (quote) {
      if (c === "\\") { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  assert.fail("unbalanced object literal in InvoiceEditor request body");
}

/** Every `apiCall(<url>, <method>, {...})` body in the editor, by call. */
function requestBodies(): { url: string; method: string; body: string }[] {
  const out: { url: string; method: string; body: string }[] = [];
  const re = /apiCall\(\s*([`"'][^`"']*[`"'])\s*,\s*"(POST|PATCH|PUT)"\s*,/g;
  for (const m of code.matchAll(re)) {
    const after = m.index! + m[0].length;
    // Calls with no body (`undefined`) have no literal to read.
    const nextBrace = code.indexOf("{", after);
    const nextComma = code.indexOf(",", after);
    if (nextBrace === -1) continue;
    if (nextComma !== -1 && nextComma < nextBrace && !code.slice(after, nextComma).includes("{")) continue;
    out.push({ url: m[1], method: m[2], body: objectLiteralAt(code, after) });
  }
  return out;
}

const bodies = requestBodies();

test("the three request bodies are found, and are distinct", () => {
  // The guard on everything below: if the scan silently returned the same
  // object three times, or missed one, every assertion after this is theatre.
  const create = bodies.filter((b) => b.method === "POST" && b.body.includes("client_id"));
  const draft = bodies.filter((b) => b.method === "PATCH" && b.body.includes("lines: linePayload"));
  const issued = bodies.filter((b) => b.method === "PATCH" && b.body.includes("line_units") && !b.body.includes("lines: linePayload"));
  assert.equal(create.length, 1, "expected exactly one create request");
  assert.equal(draft.length, 1, "expected exactly one draft-update request");
  assert.equal(issued.length, 1, "expected exactly one issued-invoice soft update");
  assert.equal(new Set([create[0].body, draft[0].body, issued[0].body]).size, 3,
    "the scanner returned the same object literal for different requests");
});

function createBody(): string {
  const hit = bodies.find((b) => b.method === "POST" && b.url.includes("/api/sales-invoices/") && b.body.includes("client_id"));
  assert.ok(hit, "could not find the sales-invoice create request in InvoiceEditor");
  return hit.body;
}

function draftUpdateBody(): string {
  // The draft PATCH is the one that replaces lines wholesale.
  const hit = bodies.find((b) => b.method === "PATCH" && b.body.includes("lines: linePayload"));
  assert.ok(hit, "could not find the draft-update request in InvoiceEditor");
  return hit.body;
}

function issuedUpdateBody(): string {
  // The issued PATCH is the soft one — it sends line_units, never a line replace.
  const hit = bodies.find((b) => b.method === "PATCH" && b.body.includes("line_units") && !b.body.includes("lines: linePayload"));
  assert.ok(hit, "could not find the issued-invoice soft-update request in InvoiceEditor");
  return hit.body;
}

// ── the editor is wired to the module at all ─────────────────────────────────

test("the editor imports the classification helpers rather than inlining values", () => {
  // Inlined string literals would drift from migration 268's CHECK constraints
  // with nothing to catch it — classification.test.ts only guards the module.
  assert.match(source, /from "@\/lib\/invoices\/classification"/);
  assert.match(source, /toClassificationPayload/);
  assert.match(source, /classificationFrom/);
});

test("the editor renders a control for each of the three fields", () => {
  assert.match(source, /SUPPLY_TYPES\.map/, "no supply type dropdown");
  assert.match(source, /INVOICE_TYPES\.map/, "no invoice type dropdown");
  assert.match(source, /checked=\{isReverseCharge\}/, "no reverse charge checkbox");
});

test("a loaded invoice rehydrates its stored classification", () => {
  // Without this an edit of an SEZ draft would silently save it back as Regular.
  assert.match(source, /classificationFrom\(existing \?\? duplicateSeed\)/);
});

// ── the fields actually leave the browser ────────────────────────────────────

test("creating an invoice sends the classification", () => {
  assert.match(
    createBody(),
    /\.\.\.toClassificationPayload\(/,
    "the create request does not carry supply_type / invoice_type / is_reverse_charge — "
    + "this is the exact gap task #156 exists to close",
  );
});

test("saving a draft sends the classification", () => {
  assert.match(
    draftUpdateBody(),
    /\.\.\.toClassificationPayload\(/,
    "a draft edit would discard the classification the CA just picked",
  );
});

// ── and are correctly withheld from the one request that forbids them ────────

test("the issued-invoice update does NOT send the classification", () => {
  // The server's _SOFT_UPDATE_FIELDS rejects anything outside reference_no,
  // notes, due_date and credit_days with a 422. Sending these would break every
  // save of a note on an issued invoice — changing which GSTR-1 table an issued
  // invoice belongs to needs a credit note (CGST Act §34), not a silent edit.
  const body = issuedUpdateBody();
  assert.doesNotMatch(body, /toClassificationPayload/);
  assert.doesNotMatch(body, /supply_type/);
  assert.doesNotMatch(body, /invoice_type/);
  assert.doesNotMatch(body, /is_reverse_charge/);
});

test("the controls are disabled once the invoice is issued", () => {
  // The UI has to agree with the server, or the CA edits a dropdown and gets a
  // 422 they cannot act on.
  const supply = code.slice(code.indexOf('id="inv-supply-type"'), code.indexOf('id="inv-invoice-type"'));
  assert.match(supply, /disabled=\{isLocked\}/);
  const invoice = code.slice(code.indexOf('id="inv-invoice-type"'));
  assert.match(invoice.slice(0, 600), /disabled=\{isLocked\}/);
});

// ── unsaved-change tracking ──────────────────────────────────────────────────

test("changing a classification counts as an unsaved change", () => {
  // Otherwise the CA picks SEZ, navigates away, and is not warned that the pick
  // is about to be thrown away.
  assert.match(source, /currentSnapshot = \{[^}]*supplyType[^}]*invoiceType[^}]*isReverseCharge/s);
  assert.match(source, /initialSnapshot = useRef\(\{[\s\S]*?supplyType:[\s\S]*?\}\)/);
});
