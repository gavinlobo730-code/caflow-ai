/**
 * What a half-typed journal entry keeps in the tab, and how it comes back
 * (frontend_ux-23). Pure — no React, no storage — so the rules are tested by
 * plain `node --test`; `lib/drafts/unsentDraft.ts` stores it and
 * `components/journal/JournalEditor.tsx` offers it.
 *
 * RAW FIELDS ONLY. The draft is the five header fields, the supporting links
 * and, per line, the account picked and the two amounts AS TYPED (a string —
 * `"12."` is on its way to being an amount and `"0.00"` is not text that fails
 * to parse). Not kept: the totals, the balanced verdict, the account's name or
 * code, anything the server returned. All of that is recomputed from the
 * fields, and what the server trusts on save is what the request carries — so a
 * draft edited by hand can only put text in a box the CA is about to read.
 */
import { readField } from "../drafts/unsentDraft.ts";

export interface JournalDraftLine {
  account_id: string;
  debit: string;
  credit: string;
  narration: string;
}

export interface JournalDraftFields {
  entryDate: string;
  entryType: string;
  referenceNo: string;
  narration: string;
  lines: JournalDraftLine[];
  attachments: { name: string; url: string }[];
}

/** A voucher with more lines than this is not one being typed by hand. */
export const MAX_DRAFT_LINES = 200;
export const MAX_DRAFT_ATTACHMENTS = 20;

function lineOf(raw: unknown): JournalDraftLine | null {
  const r = readField.record(raw);
  if (!r) return null;
  const account_id = readField.string(r.account_id, 100);
  const debit = readField.string(r.debit, 40);
  const credit = readField.string(r.credit, 40);
  const narration = readField.string(r.narration, 500);
  if (account_id === undefined || debit === undefined || credit === undefined || narration === undefined) {
    return null;
  }
  return { account_id, debit, credit, narration };
}

/** Rebuild a draft from whatever JSON came back, or `null`. A single bad line
 *  discards the whole draft rather than quietly dropping a leg of the voucher:
 *  an entry restored with a line missing is one the CA might post without
 *  noticing, and "balanced" would still read true if the missing leg were the
 *  balancing one. */
export function validateJournalDraft(raw: unknown): JournalDraftFields | null {
  const r = readField.record(raw);
  if (!r) return null;
  const entryDate = readField.string(r.entryDate, 20);
  const entryType = readField.string(r.entryType, 40);
  const referenceNo = readField.string(r.referenceNo, 200);
  const narration = readField.string(r.narration, 2_000);
  const rawLines = readField.list(r.lines, MAX_DRAFT_LINES);
  const rawAttachments = readField.list(r.attachments, MAX_DRAFT_ATTACHMENTS);
  if (entryDate === undefined || entryType === undefined || referenceNo === undefined ||
      narration === undefined || !rawLines || !rawAttachments) return null;

  const lines: JournalDraftLine[] = [];
  for (const l of rawLines) {
    const line = lineOf(l);
    if (!line) return null;
    lines.push(line);
  }
  const attachments: { name: string; url: string }[] = [];
  for (const a of rawAttachments) {
    const rec = readField.record(a);
    const name = rec ? readField.string(rec.name, 300) : undefined;
    const url = rec ? readField.string(rec.url, 2_000) : undefined;
    if (name === undefined || url === undefined) return null;
    attachments.push({ name, url });
  }
  return { entryDate, entryType, referenceNo, narration, lines, attachments };
}

/** What a restore puts into the form, checked against what this client's chart
 *  holds NOW. An account that has since been deactivated or deleted is not
 *  left selected — the picker would show it blank while the state still
 *  carried the id, and the server would refuse the post with an id the CA
 *  cannot see. The line stays, with its amounts, and the CA picks again. */
export function applyJournalDraft(
  draft: JournalDraftFields,
  accountIds: ReadonlySet<string>,
  entryTypes: readonly string[],
): { fields: JournalDraftFields; accountsDropped: number } {
  let accountsDropped = 0;
  const lines = draft.lines.map((l) => {
    if (l.account_id && !accountIds.has(l.account_id)) {
      accountsDropped++;
      return { ...l, account_id: "" };
    }
    return l;
  });
  return {
    fields: {
      ...draft,
      entryType: entryTypes.includes(draft.entryType) ? draft.entryType : (entryTypes[0] ?? draft.entryType),
      lines,
    },
    accountsDropped,
  };
}
