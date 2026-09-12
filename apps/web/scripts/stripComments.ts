/**
 * Remove // and /* *\/ comments from TypeScript source, quote-aware.
 *
 * Every guard in scripts/ that greps the tree for a defect has the same
 * hazard: a COMMENT explaining why a thing is not done names the thing, and a
 * plain substring search cannot tell the explanation from the deed. Stripping
 * comments first is the fix, and it was written twice before this file
 * existed — once here (extracted from ids-come-from-location.test.ts) and once
 * as a pair of regexes in every-api-call-is-authenticated.test.ts.
 *
 * Deliberately NOT a TypeScript parser. What it does handle is the one case a
 * regex gets wrong: a "//" inside a string literal ("http://localhost:8000",
 * a `${API}//path` template) must not truncate the rest of the line. Newlines
 * inside a stripped comment are preserved so line numbers survive.
 *
 * Not exported from a .test.ts file on purpose — a helper two tests import
 * from a third is how a test file grows a second job.
 */
export function stripComments(src: string): string {
  let out = "";
  let i = 0;
  let inBlock = false;
  let inLine = false;
  let quote: string | null = null;
  while (i < src.length) {
    const c = src[i];
    const next = src[i + 1];
    if (inLine) {
      if (c === "\n") { inLine = false; out += c; }
      i++;
      continue;
    }
    if (inBlock) {
      if (c === "*" && next === "/") { inBlock = false; i += 2; continue; }
      if (c === "\n") out += c;
      i++;
      continue;
    }
    if (quote) {
      if (c === "\\") { out += src.slice(i, i + 2); i += 2; continue; }
      if (c === quote) quote = null;
      out += c;
      i++;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; out += c; i++; continue; }
    if (c === "/" && next === "/") { inLine = true; i += 2; continue; }
    if (c === "/" && next === "*") { inBlock = true; i += 2; continue; }
    out += c;
    i++;
  }
  return out;
}
