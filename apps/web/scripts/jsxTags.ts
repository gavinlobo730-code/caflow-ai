// A brace-aware reader of JSX opening tags, for the guards that ask "does this
// element carry this prop". A regex over `<Tag ...>` stops at the first `>`, and the
// first `>` in a real opening tag is usually the one in `=>` or inside a string
// (`emptyDescription={a > b ? ... }`), which cuts the tag in half and reports a prop
// that is further along as missing. It tracks quotes and brace depth instead, so
// the tag ends where the tag ends. Comments must be stripped first
// (scripts/stripComments.ts).

type Scan = { end: number };

function scanTag(src: string, from: number): Scan | null {
  let depth = 0;
  let quote: string | null = null;
  for (let i = from; i < src.length; i++) {
    const c = src[i];
    if (quote) {
      if (c === "\\") { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") depth--;
    else if (c === ">" && depth === 0) return { end: i };
  }
  return null;
}

/** Every opening tag of `<tag …>` in `src`, whole, from `<` to its closing `>`. */
export function openingTags(src: string, tag: string): string[] {
  const out: string[] = [];
  const re = new RegExp(`<${tag}(?=[\\s/>])`, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    const scan = scanTag(src, m.index + m[0].length);
    if (!scan) break;
    out.push(src.slice(m.index, scan.end + 1));
    re.lastIndex = scan.end + 1;
  }
  return out;
}

/** The prop names a tag carries at its own level: nothing inside a `{…}` value or a string. */
export function topLevelProps(tagSource: string, tag: string): string[] {
  const names: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  for (let i = 1 + tag.length; i < tagSource.length; i++) {
    const c = tagSource[i];
    if (quote) {
      if (c === "\\") { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "{") { depth++; continue; }
    if (c === "}") { depth--; continue; }
    if (depth === 0 && /[A-Za-z_]/.test(c) && /\s/.test(tagSource[i - 1] ?? "")) {
      const m = /^[A-Za-z_][\w:-]*/.exec(tagSource.slice(i));
      if (m) {
        names.push(m[0]);
        i += m[0].length - 1;
      }
    }
  }
  return names;
}
