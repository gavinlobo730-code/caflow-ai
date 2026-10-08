/**
 * What a screen tells the CA before it sends content to an AI provider (PRE-A-006).
 *
 * Until this module, no screen a CA uses to send a document or a question to a
 * model named the provider in its visible text: the invoice Extract box, the
 * statement scan opt-in and the AI Assistant said "AI" and nothing about who
 * receives the content or that it leaves India. A CA uploading a client's bill is
 * entitled to know that before pressing the button, and to be able to say so to
 * the client.
 *
 * THE SENTENCES ARE FACTS ABOUT THE BACKEND, NOT COPY. Each one says which provider
 * receives what, and is held to the code from the Python side
 * (apps/api/tests/test_the_ai_disclosure_names_the_providers_the_code_calls.py): the
 * `providers` list of a surface must equal the providers the backend module behind it
 * really calls, so a Gemini call added to the assistant, or Groq dropped from the
 * invoice reader, fails there until this is re-read. This file holds the words and
 * decides nothing; it is one module so the wording cannot differ between two screens
 * that send the same thing.
 *
 * WHAT IT DELIBERATELY DOES NOT SAY. Nothing about what a provider does with the
 * content afterwards: whether it trains on it, how long it keeps it, whether it is
 * secure. Those are the provider-terms questions (PRE-B-013, Decision 5) and are not
 * settled; a sentence here would be a claim nobody has checked, so the test beside
 * this file refuses the vocabulary of one. "Outside India" is the fact the public
 * site already states (the AI features send the text or image of a document to an AI
 * provider outside India), pinned by tests/test_the_facts_behind_the_marketing_claims.py.
 *
 * WHAT IT SAYS ABOUT IDENTIFIERS follows domain/ai/redaction: anything shaped like a
 * PAN or a GSTIN is replaced before a chat request leaves, a name is NOT, and a
 * document reader is exempt by name because the supplier's GSTIN is printed on the
 * invoice being read.
 *
 * Each entry is written as `providers: [...]` and `sentence: "<one string literal>"`
 * on purpose: the Python guard reads this file with a regular expression, so the
 * sentence stays a single literal and is never concatenated.
 */

export type AiProvider = "groq" | "gemini";

/** The names a person is shown. The keys are the provider ids the backend uses
 *  (`domain/ai/gateway`: Groq and Gemini; `lib/api` AiProviderName). */
export const AI_PROVIDER_NAMES: Record<AiProvider, string> = {
  groq: "Groq",
  gemini: "Google Gemini",
};

export type AiDisclosureSurface =
  | "invoice_extraction"
  | "statement_scan"
  | "notice_extraction"
  | "assistant"
  | "copilot";

export interface AiDisclosureEntry {
  /** Every provider the backend behind this screen can send the content to. */
  providers: readonly AiProvider[];
  /** What the CA reads before sending. A single string literal. */
  sentence: string;
}

export const AI_DISCLOSURES: Record<AiDisclosureSurface, AiDisclosureEntry> = {
  // routers/document_intelligence_v1.py: a PDF with a text layer is read by Groq as text;
  // a photo, or a PDF with no text layer (up to three pages), is read by Google Gemini as images.
  invoice_extraction: {
    providers: ["groq", "gemini"],
    sentence: "Extract sends the file to an AI provider outside India. A PDF with readable text is sent as text, to Groq. A photo, or a scanned PDF of up to three pages, is sent as images, to Google Gemini. What is on the invoice goes with it, supplier GSTIN, names and amounts included.",
  },

  // routers/banking.py with services/statement_vision.py: only when the box is ticked AND the
  // file is a photo or a PDF with no text layer; each page goes to Google Gemini as an image.
  statement_scan: {
    providers: ["gemini"],
    sentence: "Ticking this sends each page, as an image, to Google Gemini, an AI provider outside India. The account number and every name on the statement go with it. It applies only to a photo or to a PDF with no readable text: a CSV, an Excel file or a PDF with readable text is not sent.",
  },

  // routers/document_intelligence_v2.py: the pasted text is sent as written (redact=False).
  notice_extraction: {
    providers: ["groq"],
    sentence: "Extract sends the text you paste to Groq, an AI provider outside India. PANs and GSTINs in it are sent as written.",
  },

  // routers/assistant.py: the question, the conversation so far and, when a client is chosen, the
  // figures the hub computes for it (no name) go to Groq, with PAN and GSTIN shapes replaced.
  assistant: {
    providers: ["groq"],
    sentence: "Your questions and this conversation are sent to Groq, an AI provider outside India. Anything shaped like a PAN or a GSTIN is replaced before it is sent; names and amounts you type are sent as written.",
  },

  // domain/ai_copilot_service.py: the CA's messages and counts from the practice's own records go to Groq.
  copilot: {
    providers: ["groq"],
    sentence: "Your messages, and counts from your practice's own records, are sent to Groq, an AI provider outside India. No client name is added from our side. What you type is sent as written, except that anything shaped like a PAN or a GSTIN is replaced first.",
  },
};
