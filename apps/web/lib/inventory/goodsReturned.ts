/** The answer a credit or debit note gives to "did the goods come back?" (POST-A-371): TRUE yes, FALSE a price, rate or discount correction,
 *  null not stated. The server stores it and obeys it; the browser only carries it and words it. */
export type GoodsReturned = boolean | null;

/** The stored answer in words, for a read-only view of a note. "Not stated" is a real third state: every note written before the column. */
export function goodsReturnedWords(value: boolean | null | undefined): string {
  if (value === true) return "Yes";
  if (value === false) return "No (a price, rate or discount correction)";
  return "Not stated";
}
