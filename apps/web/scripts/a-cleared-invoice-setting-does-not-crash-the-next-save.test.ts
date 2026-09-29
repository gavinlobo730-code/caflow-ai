/**
 * Settings > Invoice Settings: clearing Bank Name, UPI ID or Invoice Footer
 * Text to blank and saving crashed with "Cannot read properties of null
 * (reading 'trim')", and silently discarded the save — so once cleared, the
 * field could never be saved (cleared or otherwise) again.
 *
 * ROOT CAUSE
 *   `InvoiceSettings` declares seven text fields as `string`, but the server
 *   stores each one as NULL once a CA clears it and saves (`handleSave`'s own
 *   `.trim() || null`). `load()`'s `setForm({ ...DEFAULT, ...invoice_settings
 *   })` spread that literal `null` straight into React state, overriding
 *   DEFAULT's `""`. The next `handleSave()` then ran `form.bank_name.trim()`
 *   (or upi_id / footer_text) on that `null` unconditionally — every Save
 *   reads all seven fields, whether or not the CA touched them — and threw
 *   before the request ever went out.
 *
 * THE FIX HAS TWO HALVES, AND BOTH ARE ASSERTED
 *   1. load() coalesces each of the seven fields to "" so a null from the
 *      server can never enter `form` in the first place — this is the one
 *      place that matters, because `update()` only ever writes an input's own
 *      .value (always a string).
 *   2. handleSave()'s own seven `.trim()` calls are guarded too
 *      (`(form.field || "")`), belt-and-suspenders against the same crash.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/settings/invoice-settings/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PAGE, "utf8");
const code = withoutComments(raw);

// The seven fields the bug report names two of (Bank Name, UPI ID) plus
// Footer Text, and the two more that share the exact same shape
// (account_number, account_holder, ifsc_code) — a fix that missed any of
// these would leave the identical crash on a field nobody happened to test.
const FIELDS = [
  "bank_name", "account_number", "account_holder",
  "ifsc_code", "upi_id", "upi_qr_url", "footer_text",
] as const;

test("a cleared invoice setting does not crash the next save", async (t) => {
  await t.test("load() coalesces every nullable text field to \"\" before it reaches form state", () => {
    for (const f of FIELDS) {
      const pattern = new RegExp(
        `${f}:\\s*res\\.data\\.invoice_settings\\.${f}\\s*\\?\\?\\s*""`);
      assert.match(code, pattern,
        `load() does not coalesce ${f} — a server-side null reaches form state unguarded`);
    }
  });

  await t.test("handleSave()'s own .trim() calls are null-safe too", () => {
    // Scoped to the update() payload literal itself, not the whole file — the
    // ifsc_code format check earlier in handleSave also calls
    // `form.ifsc_code.trim()`, legitimately bare, because it sits behind its
    // own `form.ifsc_code && …` short-circuit and is never reached on a null.
    // That is a DIFFERENT, already-safe call; this test's job is the payload
    // handleSave sends, where every field is read unconditionally.
    const start = code.indexOf("api.invoiceSettings.update({");
    assert.notEqual(start, -1, "could not find the update() call to scope this test to");
    const end = code.indexOf("});", start);
    const payload = code.slice(start, end);

    for (const f of FIELDS) {
      // Guarded: (form.field || "").trim() — not the bare form.field.trim()
      // that crashed on a null.
      const guarded = new RegExp(`\\(form\\.${f}\\s*\\|\\|\\s*""\\)\\.trim\\(\\)`);
      assert.match(payload, guarded,
        `handleSave()'s ${f}.trim() is not guarded against a null`);
      // The exact unguarded shape that used to crash must be gone from HERE.
      const bare = new RegExp(`[^|)]\\bform\\.${f}\\.trim\\(\\)`);
      assert.ok(!bare.test(payload),
        `an unguarded form.${f}.trim() is still present in the payload sent to the server`);
    }
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /async function handleSave/);
  });
});
