// GST-17 — the GST screens let the CA CHOOSE the registration, and say what the
// choice does and does not do.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-gst-screens-let-the-ca-choose-the-registration.test.ts
//
// WHAT WAS WRONG
//     A client may hold several GSTINs (GST-20) and the API has taken `gstin` on
//     every compute call since. No screen sent one, so only the primary could be
//     built from the UI, and "New GSTR-1" / "New GSTR-3B" asked the CA to TYPE
//     fifteen characters. On the firm-level screens the return was downloaded
//     under the client's PRIMARY GSTIN whichever registration it was built for,
//     and approving a return updated every registration's return for the period.
//
// THE RULE, NOT A SPELLING OF IT
//     Every screen that asks the server to build a GSTR-1 or GSTR-3B lets the CA
//     choose the registration and sends the choice; none asks for a GSTIN to be
//     typed; the choice is the server's list, and the caveat shown beside it is
//     the server's sentence.
//
//     GSTR-2B is DELIBERATELY not one of them. The upload names its own
//     recipient GSTIN (gst-09) and the server reads it off the file, so a picker
//     there would be a second answer to a question the document already
//     answers — and one that could disagree with it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

const CLIENT_PAGE = path.join("app", "clients", "[id]", "compliance", "gst", "page.tsx");
const FIRM_GSTR1 = path.join("app", "gst", "gstr1", "page.tsx");
const FIRM_GSTR3B = path.join("app", "gst", "gstr3b", "page.tsx");
const PICKER = path.join("components", "gst", "RegistrationPicker.tsx");
const CHOICE = path.join("lib", "gst", "registrationChoice.ts");

/** The body of one top-level function in a source file. */
function fnBody(src: string, name: string): string {
  const at = src.indexOf(`function ${name}(`);
  assert.ok(at >= 0, `${name} not found`);
  const next = src.indexOf("\nfunction ", at + 10);
  return src.slice(at, next < 0 ? undefined : next);
}

test("the two client tabs choose from the server's list and render the picker", () => {
  const src = code(CLIENT_PAGE);
  for (const tab of ["GSTR1Tab", "GSTR3BTab"]) {
    const body = fnBody(src, tab);
    assert.match(body, /useRegistrationChoice\(clientId\)/, `${tab} does not read the registrations`);
    assert.match(body, /<RegistrationPicker\b/, `${tab} renders no picker`);
  }
});

test("no screen asks the CA to TYPE a GSTIN for a return", () => {
  const src = code(CLIENT_PAGE);
  for (const tab of ["GSTR1Tab", "GSTR3BTab"]) {
    const body = fnBody(src, tab);
    assert.doesNotMatch(body, /placeholder="GSTIN"/,
      `${tab} still has a free-text GSTIN box — a typed GSTIN is how a return is saved under one the client does not hold`);
    assert.doesNotMatch(body, /useState\(""\);[\s\S]{0,40}setGstin|const \[gstin, setGstin\]/,
      `${tab} still holds a typed GSTIN in state`);
  }
});

test("every compute call on the client tabs carries the choice", () => {
  const src = code(CLIENT_PAGE);
  for (const endpoint of ["/api/gst/gstr1/from-books", "/api/gst/gstr3b/from-books"]) {
    const at = src.indexOf(endpoint);
    assert.ok(at >= 0, `${endpoint} is no longer called from the client tab`);
    const call = src.slice(at, at + 420);
    assert.match(call, /withRegistration\(/,
      `${endpoint} is called without the chosen registration — only the primary can be built`);
  }
});

test("a refusal is read where the CA chose, before any request is sent", () => {
  const src = code(CLIENT_PAGE);
  for (const tab of ["GSTR1Tab", "GSTR3BTab"]) {
    const body = fnBody(src, tab);
    assert.match(body, /if \(reg\.choice\.refused\)/,
      `${tab} sends a compute for a registration the client does not hold`);
  }
});

test("changing the registration discards a result built for the other one", () => {
  const src = code(CLIENT_PAGE);
  const compute = src.match(/<RegistrationPicker[^>]*id="gstr[13][b]?-compute-registration"[\s\S]*?\/>/g) ?? [];
  assert.equal(compute.length, 2, "both compute panels carry a picker");
  for (const el of compute) {
    assert.match(el, /onChange=\{\(\) => \{ setComputeResult\(null\)/,
      "a result built for one registration must not stay on screen under another's name");
  }
});

test("the firm-level screens choose, send the choice and act on the GSTIN the SERVER built", () => {
  for (const rel of [FIRM_GSTR1, FIRM_GSTR3B]) {
    const src = code(rel);
    assert.match(src, /useRegistrationChoice\(clientId \|\| null\)/, `${rel} reads no registrations`);
    assert.match(src, /<RegistrationPicker\b/, `${rel} renders no picker`);
    assert.match(src, /reg\.choice\.gstin/, `${rel} does not send the choice`);
    assert.match(src, /if \(reg\.choice\.refused\)/, `${rel} does not refuse a GSTIN the client does not hold`);
    // The download is named by the registration the return was BUILT for.
    assert.match(src, /result\.gstin \|\| client\?\.gstin/,
      `${rel} names the download by the client's primary GSTIN whichever registration it was built for`);
  }
  // Approval and filing act on THE RETURN SHOWN, not on every return for the period.
  assert.match(code(FIRM_GSTR1), /approveGSTR1\(.*result\.gstin\)/);
  assert.match(code(FIRM_GSTR1), /markGSTR1Filed\(.*result\?\.gstin\)/);
  assert.match(code(FIRM_GSTR3B), /approveGSTR3B\(.*result\.gstin\)/);
  assert.match(code(FIRM_GSTR3B), /markGSTR3BFiled\(.*result\?\.gstin\)/);
});

test("the data layer takes the registration on every call that reads or writes one return", () => {
  const gst = code(path.join("lib", "data", "gst.ts"));
  for (const fn of ["computeGSTR3B", "getGSTR3BReturn", "getGSTR1Return",
                    "approveGSTR1", "approveGSTR3B", "markGSTR1Filed", "markGSTR3BFiled"]) {
    const at = gst.indexOf(`export async function ${fn}(`);
    assert.ok(at >= 0, `${fn} missing`);
    assert.match(gst.slice(at, at + 700), /gstin\??: string/,
      `${fn} cannot be asked about one registration — with two, an approval updates both returns`);
  }
  const build = gst.slice(gst.indexOf("export async function buildGSTR1("));
  assert.match(build.slice(0, 500), /gstin\?: string/);
  assert.match(build.slice(0, 1800), /options\.gstin/);
  // `.maybeSingle()` on two rows is an ERROR, so a read by (client, period)
  // alone is wrong for any client that holds a second registration.
  assert.match(gst.slice(gst.indexOf("export async function getGSTR3BReturn(")).slice(0, 900),
    /\.eq\("gstin"/);
});

test("the picker shows the server's caveat and decides nothing statutory", () => {
  const src = code(PICKER) + code(CHOICE);
  assert.match(src, /documents_not_split_caveat/, "the caveat is the server's sentence");
  assert.doesNotMatch(src, /This client holds/,
    "composing the caveat here would be a second wording that could disagree with the return's");
  // Which registrations file the ordinary pair, and what the rest file instead,
  // are `domain/gst/registrations`' answers — never a string in the browser.
  assert.doesNotMatch(src, /CMP-08|GSTR-6|GSTR-8|GSTR-4/);
  assert.doesNotMatch(src, /"composition"|"tcs_collector"|"input_service_distributor"/);
  assert.match(src, /files_gstr1_and_3b/);
  assert.match(src, /other_return_form/);
});

test("the picker does not pretend to filter the documents", () => {
  // Choosing a registration changes which GSTIN the return is filed under and
  // NOT which documents it contains (attributing each document to a
  // registration is open work). So the screen has to be
  // able to say so, and the sentence it says is carried with the choice.
  const src = code(PICKER);
  assert.match(src, /caveatFor\(/);
  assert.match(src, /state-attention/, "the caveat is shown in the attention palette, beside the choice");
});

test("a payload is not a list until something has checked", () => {
  assert.match(code(PICKER), /arrayOrEmpty<ClientGstRegistration>\(res\.data\)/);
});

test("GSTR-2B is not given a picker: the file names its own GSTIN", () => {
  const body = fnBody(code(CLIENT_PAGE), "GSTR2BTab");
  assert.doesNotMatch(body, /<RegistrationPicker\b/);
  assert.match(body, /gstr2b\/inspect/, "the server reads the GSTIN off the file");
  assert.match(body, /inspection\.registration/);
});
