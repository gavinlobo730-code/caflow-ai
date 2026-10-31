/**
 * The computation screen names each brought-forward loss by its RECORD, and shows what the server did with the figure (POST-A-073).
 *
 * WHAT WAS WRONG
 *   The screen read `brought_forward_losses` itself and sent the figure it held, `remaining_amount_paise`, with no id. Once a filed return
 *   writes the loss's use back (migration 567), "what is left" is not what a computation for a year may use: a return already filed for
 *   THIS year has used part of it, and a revised return must be offered that part back. The server knows; the browser, holding only the
 *   total, does not.
 *
 * WHAT THIS HOLDS
 *   - every loss goes to /compute with its record's `id`, so the server can read the record;
 *   - the losses sent are those ever recorded (`original_amount_paise > 0`), not those with something left, because a fully used loss may
 *     be one this very year used;
 *   - the server's sentence for a figure it changed (`offered_from_record`) is shown, so a CA is never told a figure the screen did not send
 *     without being told why.
 * The rule itself is the server's: `domain/income_tax/loss_utilisation.py`, held by its own tests.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/clients/[id]/tax/computation/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map(line => line.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const code = withoutComments(fs.readFileSync(PAGE, "utf8"));
const block = (() => {
  const at = code.indexOf("brought_forward_losses: bfLosses");
  assert.ok(at >= 0, "the screen no longer sends brought_forward_losses");
  return code.slice(at, code.indexOf("})),", at) + 4);
})();

test("each loss goes to the server with its record's id", () => {
  assert.match(block, /\bid:\s*l\.id\b/, "a loss is sent without the id of its record");
});

test("every loss ever recorded is sent, a fully used one included", () => {
  assert.match(block, /\.filter\(l => \(l\.original_amount_paise \?\? 0\) > 0\)/);
  assert.ok(!/remaining_amount_paise \?\? 0\) > 0/.test(block), "the screen filters on what is left, which hides the loss this year used");
});

test("the server's sentence for a figure it changed is shown", () => {
  assert.match(code, /offered_from_record\s*\?\?\s*\[\]\)\.map\(/, "the notes the server sends are not rendered");
});
