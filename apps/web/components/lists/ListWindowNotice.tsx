"use client";

/**
 * The notice under (or above) a list that stopped at a number.
 *
 * It renders nothing when the server said the window is the whole list, so a
 * screen can mount it unconditionally. When more exist it says what is shown,
 * offers "Show more" while the server's ceiling allows, and at the ceiling
 * says where the rest can be had (`elsewhere`) instead of offering a button
 * that does nothing. Wording lives in lib/lists/window; whether more exist and
 * how far the ceiling goes are the server's answers (core/list_window.py).
 */
import { Callout } from "@/components/ui/callout";
import { nextWindowLimit, windowSentence } from "@/lib/lists/window";

export interface ListWindowNoticeProps {
  /** The server's `has_more`. */
  hasMore: boolean;
  /** What is on screen, e.g. "the latest 100 time entries". */
  what: string;
  /** The limit this window was read with, and the server's ceiling. */
  limit: number;
  maxLimit: number;
  /** Ask for a bigger window. Omit for a list that cannot grow. */
  onShowMore?: (nextLimit: number) => void;
  busy?: boolean;
  /** Where the rest can be had once the ceiling is reached. */
  elsewhere?: string;
}

export function ListWindowNotice({
  hasMore, what, limit, maxLimit, onShowMore, busy, elsewhere,
}: ListWindowNoticeProps) {
  if (!hasMore) return null;
  const next = onShowMore ? nextWindowLimit(limit, maxLimit) : null;
  return (
    <Callout tone="note" className="my-3">
      <span>{windowSentence(what)}</span>
      {next !== null && onShowMore ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => onShowMore(next)}
          className="ml-2 text-xs font-medium underline disabled:opacity-50"
        >
          {busy ? "Loading…" : "Show more"}
        </button>
      ) : elsewhere ? (
        <span className="ml-1">{elsewhere}</span>
      ) : null}
    </Callout>
  );
}
