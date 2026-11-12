// A delivery challan is issued by one button, and the box for the day the goods came back lists issued challans only (POST-A-398). Run with:
//   node --experimental-strip-types --test scripts/a-challan-is-issued-by-one-button-and-goods-come-back-only-on-an-issued-one.test.ts
//
// WHY THIS EXISTS
//     `create_challan` wrote a draft and nothing ever issued one, so a job-work challan made in the product was not on FORM GST ITC-04 and a draft was offered "Record goods back". The server has one
//     door that issues (`POST /api/sales-cycle/challans/{id}/issue`) and refuses to give goods back to a draft; this holds the screen's half, from the source:
//       * the API wrapper reaches that door by POST, for one challan and one client, and nothing else in the browser reaches it;
//       * the tab calls the wrapper from one function, the button shows for a draft's detail only, and a refusal is said beside it as an alert;
//       * the box for the day the goods came back lists ISSUED challans only, and a draft is told it has not left.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const sourceFiles = (dir: string): string[] => {
  const out: string[] = [];
  for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(rel));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !/\.d\.ts$/.test(entry.name)) out.push(rel);
  }
  return out;
};

const TAB = "components/sales/SalesCycleTab.tsx";

test("the API wrapper issues one challan of one client by POST, and nothing else in the browser reaches the issue route", () => {
  const api = read("lib/api/index.ts");
  const at = api.indexOf("issueChallan:");
  assert.ok(at > 0, "the wrapper has no issueChallan");
  const wrapper = api.slice(at, at + 420);
  assert.match(wrapper, /\/api\/sales-cycle\/challans\/\$\{id\}\/issue\?client_id=\$\{encodeURIComponent\(clientId\)\}/, "the wrapper does not name the challan and the client");
  assert.match(wrapper, /method: "POST"/, "the wrapper does not POST");
  assert.ok(!/body:/.test(wrapper.slice(0, wrapper.indexOf("}),") + 3)), "the issue door takes no body: what it needs is on the challan");
  const reachers = [];
  for (const dir of ["app", "components", "lib"]) {
    for (const rel of sourceFiles(dir)) {
      if (rel === "lib/api/index.ts") continue;
      if (/challans\/[^"'`]*\/issue/.test(read(rel))) reachers.push(rel);
    }
  }
  assert.deepEqual(reachers, [], "something other than the wrapper reaches the challan issue route");
});

test("the tab issues from one function, from the draft's detail only, and says a refusal beside the button", () => {
  const src = read(TAB);
  assert.equal((src.match(/api\.salesCycle\.issueChallan\(/g) ?? []).length, 1, "the tab issues a challan from more than one place, or from none");
  assert.match(src, /async function issue\(challan: DeliveryChallan\)/, "the one place is not the function named issue");
  // the button is drawn inside the block that is shown for a DRAFT's detail, and calls that function
  const block = /\{detail\.challan && detail\.challan\.status === "draft" && \([\s\S]*?\n              \)\}/.exec(src)?.[0] ?? "";
  assert.ok(block.length > 200, "the draft's block was not found");
  assert.match(block, /<Button[^>]*onClick=\{\(\) => issue\(detail\.challan as DeliveryChallan\)\}/, "the button does not call issue");
  assert.match(block, /Issue challan/, "the button is not labelled Issue challan");
  // the sentence about the period (its end, and whether it is already past) is the server's, shown in the draft's own panel: the screen words none of it
  assert.match(block, /\{detail\.clock\.consequence && <p[^>]*>\{detail\.clock\.consequence\}<\/p>\}/, "the server's sentence about the period is not shown in the draft's panel");
  assert.match(block, /role="alert"[^>]*>\{issueAnswer\.text\}/, "a refusal is not said as an alert beside the button");
  assert.equal((src.match(/>\s*Issue challan\s*</g) ?? []).length, 1, "the label is drawn in more than one place");
  // a refusal is the server's sentence: the screen words none of what issuing asks
  assert.ok(!/cannot be issued yet|only a draft is issued|so there are no goods to send on it|which has not come: the goods/.test(src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "")), "the screen words a refusal the server owns");
});

test("what the tab says about an issue is not stale: the refusal is cleared when a challan is opened, closed or the tab changed, and the refreshed detail replaces only its own challan's", () => {
  const src = read(TAB);
  assert.match(src, /setTab\(id\); setShowForm\(false\); setDetail\(null\); setIssueAnswer\(null\); setCancelAnswer\(null\); setCorrecting\(false\)/, "a refusal to an earlier press, or an open correction form, survives a change of tab");
  assert.match(src, /aria-label="Close the challan" onClick=\{\(\) => \{ setDetail\(null\); setIssueAnswer\(null\); setCancelAnswer\(null\); setCorrecting\(false\); \}\}/, "a refusal to an earlier press, or an open correction form, survives closing the challan");
  assert.match(src, /onRow=\{\(i\) => \{\s*setIssueAnswer\(null\);[^}]*?setCancelAnswer\(null\);\s*setCorrecting\(false\);/, "a refusal to an earlier press, or an open correction form, comes back when a challan is opened");
  // the re-read is ONE function (`reopen`), asked after an issue and after a correction, and it replaces only the detail of the challan it was asked for
  assert.match(src, /async function reopen\(challanId: string\)[\s\S]*?setDetail\(\(open\) => \(open && open\.challan\?\.id === challanId \? fresh : open\)\)/, "the detail read after an issue can overwrite a challan the person has opened since");
  assert.match(src, /await reopen\(challan\.id\)/, "an issue does not read the detail again");
  assert.match(src, /role=\{msg\.type === "ok" \? "status" : "alert"\}/, "the page's message line is not a live region: a success is not announced and the focus is lost with the button");
});

test("the challan form asks for the place of supply of an inter-State movement, sends it, and says what Rule 55(1) asks and where a draft is corrected", () => {
  const src = read(TAB);
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  // a challan made with the tick and no place of supply could never be issued (Rule 55(1)(viii)), and no screen could add one afterwards
  assert.match(code, /\{tab === "challans" && form\.is_inter_state && \(\s*<div[^>]*>[\s\S]*?<StateLookup placeOfSupply value=\{form\.place_of_supply\}[\s\S]*?ariaLabel="Place of supply"/, "the form has no place of supply for an inter-State movement");
  // the box writes the code it is given into the form and can be cleared again (a place chosen by mistake is taken back, and the payload then sends none)
  assert.match(code, /<StateLookup placeOfSupply value=\{form\.place_of_supply\} onChange=\{\(code\) => setForm\(\{ \.\.\.form, place_of_supply: code \}\)\}[\s\S]*?ariaLabel="Place of supply" clearable \/>/, "the place of supply box does not write the form's place, or cannot be cleared");
  assert.match(code, /place_of_supply: form\.is_inter_state && form\.place_of_supply \? form\.place_of_supply : null/, "the place of supply is not sent, or is sent for a movement that is not inter-State");
  // what Rule 55(1) asks is the Rule's list (HSN of every line, the consignee, the place of supply of an inter-State movement); what a job-work challan sends is the product's own need (the period under s.143), and is not put on the Rule
  assert.match(code, /CGST Rule 55\(1\) asks for the HSN code of every line, the consignee and, for an inter-State movement, the place of supply\./, "the form does not say what Rule 55(1) asks");
  assert.ok(!/Rule 55\(1\) asks for[^.]*what a job-work challan sends/.test(code.replace(/\s+/g, " ")), "the form puts what a job-work challan sends on Rule 55(1), which does not ask for it");
  assert.match(code.replace(/\s+/g, " "), /A job-work challan also says what it sends, because the period under s\.143 depends on it\./, "the form does not say that a job-work challan says what it sends, or why");
  assert.match(code.replace(/\s+/g, " "), /a draft saved without one of these is corrected from its panel \(open it from the list\) before it is issued\./, "the form does not say where a draft is corrected");
  // and the sentence that said it could not be is gone from the whole tab: a draft IS edited on this screen now (POST-A-417)
  assert.ok(!/not edited on this screen/.test(code), "the tab still says a draft is not edited on this screen");
});

test("the draft line is drawn only where a draft exists, and the card a row opens sits above the ITC-04 panel, next to the list", () => {
  const src = read(TAB);
  assert.match(src, /\{challans\.some\(\(c\) => c\.status === "draft"\) && \(\s*<p[^>]*>\s*\{challans\.filter\(\(c\) => c\.status === "draft"\)\.length\} in draft\./, "the line about drafts is drawn without a draft, or does not count them");
  assert.ok(src.indexOf("{detail && (") > 0 && src.indexOf("{detail && (") < src.indexOf("<Itc04Panel"), "the challan a row opens is below the ITC-04 panel, out of sight of its button");
});

test("a list row of the tab opens from the keyboard: its first cell is a button, so the Issue challan inside the detail is reachable without a mouse", () => {
  const src = read(TAB);
  const table = src.slice(src.indexOf("function Table("));
  assert.ok(table.length > 100, "the tab's table was not found");
  assert.match(table, /onRow && j === 0 \? \(\s*(\/\/[^\n]*\n\s*)?<button type="button"[^>]*onClick=\{\(e\) => \{ e\.stopPropagation\(\); onRow\(i\); \}\}/, "the first cell of a row is not a button that opens it");
});

test("the box for the day the goods came back lists challans the goods have left on, and a draft is told what it is without being told its goods have not left", () => {
  const src = read(TAB);
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.equal((src.match(/\(c\.status === "issued" \|\| c\.status === "received_back"\) && c\.clock\?\.applies && !c\.received_back_on/g) ?? []).length, 2,
    "the box (its condition and its list) is not limited to challans the goods have left on (a recorded-received-back row with no day is one: the box is its way to be given one)");
  assert.ok(!/challans\.(some|filter)\(\(c\) => c\.clock\?\.applies && !c\.received_back_on\)/.test(src), "an unfiltered list of challans for the day the goods came back is back");
  assert.match(src, /A draft is not recorded as issued: no period runs on it here and it is not on FORM GST ITC-04\.\s+If the goods on a\s+draft have left, open it and issue it\./, "a draft is not told what it is");
  // the product cannot know that the goods on a draft have not left, and a period counts from the challan's date, not from the press
  assert.ok(!/(has|have|had) not left|period starts|starts when|starts then/.test(code), "the screen says as fact that the goods of a draft have not left, or that a period starts when a challan is issued");
  assert.match(code, /Issuing records that the goods left on \{formatDate\(detail\.challan\.document_date\)\}, the challan&apos;s date/, "the draft's panel does not say which day issuing records, written by the one date module");
});

/** The arguments of every call of `name(` in `text`, each as the source text between the commas at the top level of the parentheses. */
function callsOf(text: string, name: string): string[][] {
  const out: string[][] = [];
  for (let at = text.indexOf(`${name}(`); at >= 0; at = text.indexOf(`${name}(`, at + 1)) {
    let depth = 0;
    let start = at + name.length;
    const args: string[] = [];
    for (let i = start; i < text.length; i++) {
      const ch = text[i];
      if (ch === "(" || ch === "{" || ch === "[") depth++;
      else if (ch === ")" || ch === "}" || ch === "]") {
        depth--;
        if (depth === 0) { args.push(text.slice(start + 1, i)); break; }
      } else if (ch === "," && depth === 1) { args.push(text.slice(start + 1, i)); start = i; }
    }
    out.push(args.map((a) => a.trim()));
  }
  return out;
}

test("the tab never asks the amendment door for a status: a challan becomes issued by Issue challan and by nothing else", () => {
  let calls = 0;
  for (const dir of ["app", "components", "lib"]) {
    for (const rel of sourceFiles(dir)) {
      for (const args of callsOf(read(rel), "updateChallan")) {
        calls++;
        // an inline object literal, so the keys can be read here: a body held in a variable is a status this rule cannot see
        assert.equal(args.length, 3, `${rel}: updateChallan is not called with an id, a client and a body`);
        assert.ok(args[2].startsWith("{"), `${rel}: the body of updateChallan is not an inline object, so what it carries cannot be read (${args[2].slice(0, 40)})`);
        assert.ok(!/\.\.\./.test(args[2]), `${rel}: the body of updateChallan spreads another object, which can carry a status this rule cannot see`);
        assert.ok(!/\bstatus\b/.test(args[2]), `${rel}: the amendment door is asked for a status`);
      }
    }
  }
  assert.ok(calls >= 1, "no call of updateChallan was found: the rule is vacuous");
});

test("the call reader sees a body held in a variable, a spread and a nested status, and passes the one inline call the tab makes", () => {
  assert.deepEqual(callsOf("api.updateChallan(a, b, { received_back_on: on })", "updateChallan"), [["a", "b", "{ received_back_on: on }"]]);
  assert.ok(!callsOf("api.updateChallan(a, b, body)", "updateChallan")[0][2].startsWith("{"), "a body in a variable");
  assert.match(callsOf("api.updateChallan(a, b, { ...rest })", "updateChallan")[0][2], /\.\.\./, "a spread is shown to the rule, which refuses it");
  assert.match(callsOf("api.updateChallan(a, b, { x: { status: 1 } })", "updateChallan")[0][2], /\bstatus\b/, "a nested status");
});
