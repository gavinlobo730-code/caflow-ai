/**
 * Keep only the ids a list is still holding.
 *
 * A selection is a Set of row ids; rows leave a list without going through a
 * bulk action all the time (a button above the table, a reload after a
 * row action, a filter), and a set nobody revisits then names rows that are
 * not there — the bar reads "13 selected" over an empty table. Every place
 * that keeps a selection calls this whenever its rows change, so the
 * sentence and the rows never disagree. Returns the SAME set when nothing
 * has to go, so a React state update with it is a no-op.
 */
export function pruneSelection(selected: Set<string>, heldIds: Iterable<string>): Set<string> {
  if (selected.size === 0) return selected;
  const held = new Set(heldIds);
  let changed = false;
  const next = new Set<string>();
  selected.forEach((id) => { if (held.has(id)) next.add(id); else changed = true; });
  return changed ? next : selected;
}
