// Which native form controls in a TSX source have no programmatic name (POST-A-127). Found with the TypeScript parser, not a regex.
//
// A CONTROL is a JSX `<input>`, `<select>` or `<textarea>`. It HAS A NAME when any of these holds:
//   * it carries `aria-label` or `aria-labelledby`;
//   * a `<label>` is its ancestor in the JSX tree (an implicit label);
//   * it has an `id` and a `<label>` in the same file has an `htmlFor` with the same expression text (an explicit label), where the text is a
//     string literal's value or the source text of the expression, so `id={id}` pairs with `htmlFor={id}` and `id="x"` with `htmlFor="x"`;
//   * it is the child of a `Field` (components/ui/field.tsx ties its label and control itself);
//   * it is a `type="hidden"`, `"submit"`, `"button"`, `"reset"` or `"image"` input, which is named by its value or has none.
//   * it spreads props (`{...props}`), because a wrapper that forwards them is named by whoever calls the wrapper. Counted separately, so
//     a spread is never mistaken for a named control and the number of them can be seen.
// A `placeholder` or a `title` is NOT a name here: a placeholder vanishes as soon as the field has a value, which is the moment a reader
// returns to it.
//
// WHAT IT DOES NOT SEE: a control inside a component that is not a JSX element in this file (a primitive that renders an `<input>` is
// judged in its own file), a label whose `htmlFor` is computed away from the expression it was written as, and a `<label>` in another
// file than the control.
import ts from "typescript";

const CONTROL_TAGS = new Set(["input", "select", "textarea"]);
const UNNAMED_TYPES = new Set(["hidden", "submit", "button", "reset", "image"]);

export interface Control {
  tag: string;
  line: number;
  verdict: "named" | "spread" | "unnamed";
  via?: string;
}

type Opening = ts.JsxOpeningElement | ts.JsxSelfClosingElement;

const tagName = (el: Opening) => el.tagName.getText();

function attrs(el: Opening): ts.JsxAttribute[] {
  return el.attributes.properties.filter((p): p is ts.JsxAttribute => ts.isJsxAttribute(p));
}

function attr(el: Opening, name: string): ts.JsxAttribute | undefined {
  return attrs(el).find((a) => a.name.getText() === name);
}

/** The text a value is compared by: a string literal's value, or the expression's source text; null when the attribute has no value. */
function valueText(a: ts.JsxAttribute | undefined): string | null {
  if (!a || !a.initializer) return null;
  const init = a.initializer;
  if (ts.isStringLiteral(init)) return init.text;
  if (ts.isJsxExpression(init) && init.expression) {
    const e = init.expression;
    if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) return e.text;
    return e.getText();
  }
  return null;
}

export function findControls(source: string, fileName = "x.tsx"): Control[] {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const labelFor = new Set<string>();
  const openings: Opening[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) {
      openings.push(n);
      if (tagName(n) === "label") {
        const v = valueText(attr(n, "htmlFor"));
        if (v !== null) labelFor.add(v);
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);

  const out: Control[] = [];
  for (const el of openings) {
    const tag = tagName(el);
    if (!CONTROL_TAGS.has(tag)) continue;
    const line = sf.getLineAndCharacterOfPosition(el.getStart()).line + 1;
    const type = valueText(attr(el, "type"));
    if (tag === "input" && type !== null && UNNAMED_TYPES.has(type)) { out.push({ tag, line, verdict: "named", via: `type=${type}` }); continue; }
    if (attr(el, "aria-label") || attr(el, "aria-labelledby")) { out.push({ tag, line, verdict: "named", via: "aria" }); continue; }
    // The element itself is the opening's parent, or the self-closing node; walk up through its JSX ancestors for a label or a Field.
    const self: ts.Node = ts.isJsxOpeningElement(el) ? el.parent : el;
    let inside: string | null = null;
    for (let p: ts.Node | undefined = self.parent; p; p = p.parent) {
      if (ts.isJsxElement(p)) {
        const t = tagName(p.openingElement);
        if (t === "label") { inside = "label"; break; }
        if (t === "Field") { inside = "Field"; break; }
      }
    }
    if (inside) { out.push({ tag, line, verdict: "named", via: `inside ${inside}` }); continue; }
    const id = valueText(attr(el, "id"));
    if (id !== null && labelFor.has(id)) { out.push({ tag, line, verdict: "named", via: "id+htmlFor" }); continue; }
    if (el.attributes.properties.some((p) => ts.isJsxSpreadAttribute(p))) { out.push({ tag, line, verdict: "spread" }); continue; }
    out.push({ tag, line, verdict: "unnamed" });
  }
  return out;
}
