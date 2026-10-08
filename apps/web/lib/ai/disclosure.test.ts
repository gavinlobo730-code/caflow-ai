// What a screen tells the CA before it sends content to an AI provider (PRE-A-006).
// Run with: node --experimental-strip-types --test lib/ai/disclosure.test.ts
//
// This holds the WORDS. That the providers listed are the ones the backend really
// calls is held from the Python side
// (apps/api/tests/test_the_ai_disclosure_names_the_providers_the_code_calls.py),
// and that every screen which sends content renders one is held by
// scripts/a-screen-that-sends-content-to-ai-names-the-provider.test.ts.
import test from "node:test";
import assert from "node:assert/strict";
import {
  AI_DISCLOSURES,
  AI_PROVIDER_NAMES,
  type AiProvider,
} from "./disclosure.ts";

const SURFACES = Object.keys(AI_DISCLOSURES) as (keyof typeof AI_DISCLOSURES)[];
const PROVIDERS = Object.keys(AI_PROVIDER_NAMES) as AiProvider[];

/** The vocabulary of a claim about what a provider does AFTER receiving the
 *  content: training, keeping, deleting, privacy, security. Whether any is true is
 *  the provider-terms question (PRE-B-013, Decision 5) and is not settled, so no
 *  sentence on a screen may say one. "Sent" and "replaced" are the only verbs a
 *  disclosure here has earned. */
const CLAIM_ABOUT_WHAT_THE_PROVIDER_DOES_NEXT =
  /\b(train\w*|retain\w*|retention|stor(?:e|es|ed|ing|age)|kept|keep(?:s|ing)?|delet\w*|erase\w*|purge\w*|private|privacy|confidential\w*|secur(?:e|ed|ely|ity)|safe(?:ly)?|safety|protect\w*|encrypt\w*|anonymi[sz]\w*|never (?:used|shared|logged))\b/i;

test("every surface names a provider, and the provider ids are the ones the backend uses", () => {
  assert.deepEqual([...PROVIDERS].sort(), ["gemini", "groq"]);
  assert.ok(SURFACES.length >= 5, "invoice, statement scan, notice, assistant, copilot");
  for (const s of SURFACES) {
    const { providers } = AI_DISCLOSURES[s];
    assert.ok(providers.length > 0, `${s} names no provider`);
    assert.equal(new Set(providers).size, providers.length, `${s} repeats a provider`);
    for (const p of providers) assert.ok(PROVIDERS.includes(p), `${s}: unknown provider ${p}`);
  }
});

test("a sentence names each provider it lists, by the name a person is shown", () => {
  for (const s of SURFACES) {
    const { providers, sentence } = AI_DISCLOSURES[s];
    for (const p of providers) {
      assert.ok(sentence.includes(AI_PROVIDER_NAMES[p]),
        `${s}: the sentence does not say ${AI_PROVIDER_NAMES[p]}`);
    }
  }
});

test("a sentence does not name a provider that does not receive the content", () => {
  // Naming a second provider "just in case" would tell the CA the content goes
  // somewhere it does not, which is as wrong as leaving a real one out.
  for (const s of SURFACES) {
    const { providers, sentence } = AI_DISCLOSURES[s];
    for (const p of PROVIDERS.filter((q) => !providers.includes(q))) {
      assert.ok(!sentence.includes(AI_PROVIDER_NAMES[p]),
        `${s}: names ${AI_PROVIDER_NAMES[p]}, which is not one of its providers`);
      if (p === "gemini") assert.ok(!/\b(gemini|google)\b/i.test(sentence), `${s}: mentions Google`);
      if (p === "groq") assert.ok(!/\bgroq\b/i.test(sentence), `${s}: mentions Groq`);
    }
  }
});

test("every sentence says the content leaves India", () => {
  // The fact the public site already states (an AI provider outside India),
  // pinned in tests/test_the_facts_behind_the_marketing_claims.py.
  for (const s of SURFACES) {
    assert.match(AI_DISCLOSURES[s].sentence, /outside India/, `${s} does not say where it goes`);
  }
});

test("no sentence makes a claim about training, retention or security", () => {
  for (const s of SURFACES) {
    const { sentence } = AI_DISCLOSURES[s];
    const hit = sentence.match(CLAIM_ABOUT_WHAT_THE_PROVIDER_DOES_NEXT);
    assert.equal(hit, null, `${s} says "${hit?.[0]}" — a claim about what the provider does next, which is unsettled`);
  }
});

test("the detector for that vocabulary is not vacuous", () => {
  for (const claim of [
    "Your file is never used to train a model.",
    "Groq does not retain what you send.",
    "The pages are stored for 30 days.",
    "Your data is kept private.",
    "Sent over a secure connection.",
    "The file is deleted afterwards.",
    "Names are anonymised first.",
    "Your content is encrypted in transit.",
    "It is safe to send.",
    "Nothing is retained.",
  ]) {
    assert.match(claim, CLAIM_ABOUT_WHAT_THE_PROVIDER_DOES_NEXT, claim);
  }
  // …and does not catch what a disclosure legitimately says.
  assert.doesNotMatch(
    "Extract sends the file to Groq, an AI provider outside India; a PDF with readable text is not sent as an image.",
    CLAIM_ABOUT_WHAT_THE_PROVIDER_DOES_NEXT);
});

test("a sentence is one plain sentence-case line a person can read", () => {
  for (const s of SURFACES) {
    const { sentence } = AI_DISCLOSURES[s];
    assert.equal(sentence, sentence.trim());
    assert.ok(!/\n/.test(sentence), `${s} spans lines`);
    assert.ok(/[.]$/.test(sentence), `${s} does not end in a full stop`);
    assert.ok(sentence.length >= 60 && sentence.length <= 400, `${s}: ${sentence.length} characters`);
  }
});

test("what is said about identifiers matches what the redactor does", () => {
  // domain/ai/redaction replaces a PAN or GSTIN shape and does NOT replace a name.
  // The two chat surfaces say so; the two document readers are exempt by name (the
  // supplier's GSTIN is printed on the invoice being read) and must not claim a
  // replacement they do not make.
  for (const chat of ["assistant", "copilot"] as const) {
    assert.match(AI_DISCLOSURES[chat].sentence, /PAN or a GSTIN is replaced/);
    assert.match(AI_DISCLOSURES[chat].sentence, /as written/, `${chat}: what is typed is sent as written`);
  }
  assert.doesNotMatch(AI_DISCLOSURES.invoice_extraction.sentence, /replaced/);
  assert.match(AI_DISCLOSURES.invoice_extraction.sentence, /GSTIN/);
  assert.doesNotMatch(AI_DISCLOSURES.notice_extraction.sentence, /replaced/);
  assert.match(AI_DISCLOSURES.notice_extraction.sentence, /as written/);
});
