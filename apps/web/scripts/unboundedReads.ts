/**
 * Find the browser reads that nothing bounds: a from-call followed by a select chain with no `.limit`, `.range`, `.single`, count-only
 * head request, id lookup or pager around it. PostgREST answers such a read with at most its row ceiling (~1000) and says
 * nothing when it cut the answer short, so a list or total drawn from one goes quietly wrong once a book grows (POST-A-135).
 *
 * Not a TypeScript parser. A chain runs from the from-call to the first `;` at bracket depth zero, or to the bracket
 * that closes the enclosing call, and is classified by what it contains. A read is PAGED when it sits inside a `selectAll(` or
 * `selectAllKeyset(` call whose bracket has not closed before the `.from(`. Comments are stripped first so a sentence that
 * explains why a read is bounded cannot make it look bounded.
 *
 * Not a `.test.ts` file on purpose: a helper that two tests import from a third is how a test grows a second job.
 */
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

export interface UnboundedRead {
  file: string;       // relative to apps/web, with forward slashes
  line: number;
  table: string;
  chain: string;      // the chain, whitespace collapsed, truncated
}

const ROOTS = ["app", "components", "lib"];

function walk(dir: string, out: string[]): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
}

/** True when the character at `at` sits inside an unclosed `selectAll(` / `selectAllKeyset(` call. */
function insidePager(src: string, at: number): boolean {
  const back = src.slice(Math.max(0, at - 700), at);
  const openers: { index: number; length: number }[] = [];
  const opener = /selectAll(?:Keyset)?\s*(?:<[^>()]*>)?\s*\(/g;
  for (let hit = opener.exec(back); hit; hit = opener.exec(back)) openers.push({ index: hit.index, length: hit[0].length });
  for (let k = openers.length - 1; k >= 0; k--) {
    const from = openers[k].index + openers[k].length;
    let depth = 1;
    for (let i = from; i < back.length; i++) {
      const c = back[i];
      if (c === "(" || c === "[" || c === "{") depth++;
      else if (c === ")" || c === "]" || c === "}") { depth--; if (depth === 0) break; }
    }
    if (depth > 0) return true;
  }
  return false;
}

export function findUnboundedReads(webRoot: string): UnboundedRead[] {
  const found: UnboundedRead[] = [];
  const files: string[] = [];
  for (const r of ROOTS) if (fs.existsSync(path.join(webRoot, r))) walk(path.join(webRoot, r), files);
  for (const file of files.sort()) {
    const src = stripComments(fs.readFileSync(file, "utf8"));
    const fromCall = /\.from\(\s*(["'`])([a-z_0-9]+)\1\s*\)/g;
    for (let m = fromCall.exec(src); m; m = fromCall.exec(src)) {
      const table = m[2];
      const start = m.index + m[0].length;
      let depth = 0;
      let end = start;
      while (end < src.length && end - start < 2500) {
        const c = src[end];
        if (c === "(" || c === "[" || c === "{") depth++;
        else if (c === ")" || c === "]" || c === "}") { depth--; if (depth < 0) break; }
        else if (c === ";" && depth === 0) break;
        end++;
      }
      const chain = src.slice(start, end);
      if (!/\.select\(/.test(chain)) continue;                                  // insert / update / delete / upsert only
      if (/\.(limit|range)\(/.test(chain)) continue;
      if (/\.(single|maybeSingle|maybe_single)\(/.test(chain)) continue;
      if (/count\s*:\s*["']exact["']/.test(chain) && /head\s*:\s*true/.test(chain)) continue;
      if (/\.eq\(\s*["']id["']/.test(chain)) continue;
      if (insidePager(src, m.index)) continue;
      found.push({
        file: path.relative(webRoot, file).split(path.sep).join("/"),
        line: src.slice(0, m.index).split("\n").length,
        table,
        chain: chain.replace(/\s+/g, " ").trim().slice(0, 160),
      });
    }
  }
  return found;
}
