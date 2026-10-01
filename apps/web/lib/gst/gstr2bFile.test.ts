// Reading the GSTR-2B file a CA chose (gst-09). Run with:
//   node --experimental-strip-types --test lib/gst/gstr2bFile.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { readGstr2bText } from "./gstr2bFile.ts";

// The shape the portal writes: data.gstin, data.rtnprd, data.docdata.b2b[].inv[].
const REAL_SHAPE = JSON.stringify({
  data: {
    gstin: "29AAACX1234C1ZP",
    rtnprd: "042025",
    gendt: "14-05-2025",
    docdata: {
      b2b: [{
        ctin: "29AAAAA1111A1Z5", trdnm: "Acme Supplies", supfildt: "10-05-2025",
        inv: [{ inum: "INV-001", dt: "24-04-2025", val: 1180.0, itcavl: "Y",
                items: [{ num: 1, rt: 18.0, txval: 1000.0, cgst: 90.0, sgst: 90.0, igst: 0 }] }],
      }],
    },
  },
});

test("a real-shape 2B is handed back whole, for the server to read", () => {
  const got = readGstr2bText(REAL_SHAPE);
  assert.equal(got.ok, true);
  if (!got.ok) return;
  assert.deepEqual(got.raw, JSON.parse(REAL_SHAPE));
});

test("the month and the GSTIN are NOT read here — the server reads them", () => {
  const got = readGstr2bText(REAL_SHAPE);
  assert.equal(got.ok, true);
  if (!got.ok) return;
  // Only the parsed file comes back; there is no period or GSTIN field to
  // pre-fill a box from, which is the point of the file chooser.
  assert.deepEqual(Object.keys(got), ["ok", "raw"]);
});

test("a byte-order mark does not turn a valid file into 'not valid JSON'", () => {
  const got = readGstr2bText(String.fromCharCode(0xfeff) + REAL_SHAPE);
  assert.equal(got.ok, true);
});

test("surrounding whitespace is ignored", () => {
  assert.equal(readGstr2bText(`\n  ${REAL_SHAPE}\n\n`).ok, true);
});

test("empty text is refused in words", () => {
  for (const text of ["", "   \n  "]) {
    const got = readGstr2bText(text);
    assert.equal(got.ok, false);
    if (!got.ok) assert.match(got.error, /empty/);
  }
});

test("text that is not JSON says what to choose instead", () => {
  for (const text of ["not json", "<html></html>", "{\"data\": ", "%PDF-1.7"]) {
    const got = readGstr2bText(text);
    assert.equal(got.ok, false, text);
    if (!got.ok) {
      assert.match(got.error, /not valid JSON/);
      assert.match(got.error, /\.json file the portal gives you/);
    }
  }
});

test("JSON that is not an object cannot be the request's raw_data and is refused", () => {
  for (const text of ["[]", "[{\"data\": {}}]", "42", "\"text\"", "null", "true"]) {
    const got = readGstr2bText(text);
    assert.equal(got.ok, false, text);
    if (!got.ok) assert.match(got.error, /top level is not an object/);
  }
});

test("an object that is not a GSTR-2B is still sent — the parser says why, not the browser", () => {
  const got = readGstr2bText(JSON.stringify({ invoices: [{ inum: "X" }] }));
  assert.equal(got.ok, true);
});
