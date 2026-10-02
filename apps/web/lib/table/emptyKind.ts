/**
 * WHICH EMPTY A TABLE IS SHOWING (frontend_ux-24).
 *
 * A table with no rows is one of two different situations with two different next
 * steps, and `DataTable` used to say the same thing for both. Nothing recorded yet
 * is "add the first one" — the screen's own `emptyTitle`, `emptyDescription` and
 * `emptyAction`. A search or filter that hid every row is "widen it": the rows
 * exist, and telling a CA "Nothing is dated in this period — raise an invoice"
 * because they typed a customer's name wrongly is false, and the action offered
 * beside it is the wrong one. Offering "New Invoice" under a mistyped search was
 * not a risk before the screens had an action to offer; it is the reason this is
 * decided in one place now.
 *
 * THE TEST IS WHETHER THE TABLE WAS GIVEN ANY ROWS, not whether a filter is set.
 * The table's own search and filters can only remove rows it was handed, so when
 * it was handed some and shows none, they did it; when it was handed none, nothing
 * the reader typed is the cause. That is exact where "is a filter active" is not:
 * a screen that sets a DEFAULT filter (`initialFilters={{ status: "active" }}`)
 * would otherwise read as "filtered" on its very first, genuinely empty, load and
 * never show the first-run message that is the point of this.
 *
 * A SERVER-PAGED table is the one exception, because its `data` is one page and
 * says nothing about the rest — there the reader's own narrowing (a search, or any
 * filter set) is all that can be known, and "no rows on this page" under an
 * active filter is read as filtered.
 */
export type EmptyKind = "filtered" | "empty";

export type Narrowing = {
  /** Rows the table was GIVEN, before its own search and filters (`data.length`). */
  rowCount: number;
  /** Set for a server-paged table, where `rowCount` is one page and not the whole set. */
  serverPaged: boolean;
  activeFilterCount: number;
  search?: string | null;
};

export function emptyKind(n: Narrowing): EmptyKind {
  if (n.serverPaged) {
    const searched = (n.search ?? "").trim() !== "";
    return n.activeFilterCount > 0 || searched ? "filtered" : "empty";
  }
  return n.rowCount > 0 ? "filtered" : "empty";
}

/** The words for a table the reader's own search or filters have left with no rows. */
export const FILTERED_EMPTY = {
  title: "Nothing matches",
  description: "No row matches the search or filters you have set. Clear them to see everything.",
  clearLabel: "Clear search and filters",
} as const;
