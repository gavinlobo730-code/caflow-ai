/**
 * The pure half of `useNamesGoods` (POST-A-378), kept apart so that it can be tested without React or a Supabase client.
 *
 * A credit note raised from an invoice and a debit note raised from a bill copy the document's lines, and a line carries only the id of its catalogue item. Whether the note names a good is
 * a question put to the catalogue, once per SET of ids; these two functions are the two decisions in it.
 */

/** The set of items as one key: each id once, in one order, blanks left out, so the same set is the same question however the lines list it. "" is no question. */
export function itemsKey(itemIds: readonly (string | null | undefined)[]): string {
  return Array.from(new Set(itemIds.filter((id): id is string => !!id))).sort().join(",");
}

/**
 * What a catalogue read says about whether any of the items is a good. A read that FAILED is not an answer and is not "a good" (the client hands a failed read back as `error` and does not
 * throw), and neither is a read that found nothing: the choice is then not shown, the draft is saved without an answer as before, and the editor (or the issue) asks later. Never true by guess.
 */
export function namesGoodsFrom(read: { data: ReadonlyArray<{ kind?: string | null }> | null | undefined; error?: unknown }): boolean {
  return !read.error && (read.data ?? []).some((item) => item.kind === "good");
}
