/** The answer a credit or debit note gives to "did the goods come back?" (POST-A-371): TRUE yes, FALSE a price, rate or discount correction,
 *  null not stated. The server stores it and obeys it; the browser only carries it and words it. */
export type GoodsReturned = boolean | null;

/** The question, in the words of the note's own kind (POST-A-378): the goods of a credit note COME BACK to the client, the goods of a purchase debit note GO BACK TO THE SUPPLIER. The
 *  server's own question and its "stock was not moved" sentence use the same two verbs (`domain/inventory/note_goods.KINDS`). */
export function goodsReturnedQuestion(kind: "credit_note" | "debit_note"): string {
  return kind === "credit_note" ? "Did the goods come back?" : "Did the goods go back to the supplier?";
}

/** The stored answer in words, for a read-only view of a note. "Not stated" is a real third state: every note written before the column. */
export function goodsReturnedWords(value: boolean | null | undefined): string {
  if (value === true) return "Yes";
  if (value === false) return "No (a price, rate or discount correction)";
  return "Not stated";
}
