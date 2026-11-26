/**
 * Which of a row menu's actions a key moves focus to (POST-A-130). Pure, so the rule is tested without a browser; `components/ui/row-menu`
 * is its one caller.
 *
 * ArrowDown and ArrowUp wrap round (the menus are three to eight actions long, and the last is usually the destructive one a person
 * reaches for from the top with ArrowUp); Home and End go to the ends; with focus on the menu itself and on no action yet, ArrowDown takes
 * the first and ArrowUp the last. Any other key is not the menu's, and the answer is null.
 */
export function nextActionIndex(key: string, current: number, count: number): number | null {
  if (count <= 0) return null;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowDown") return current < 0 ? 0 : (current + 1) % count;
  if (key === "ArrowUp") return current < 0 ? count - 1 : (current - 1 + count) % count;
  return null;
}
