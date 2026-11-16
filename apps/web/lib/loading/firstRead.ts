/**
 * A screen blocks with "Loading…" for its FIRST read only, and stays drawn while it reads again (POST-A-400).
 *
 * WHY. A screen whose loader raised its loading flag on every read and returned "Loading…" in place of itself
 * unmounted every child it had drawn whenever it read again. A child that saved something and asked the screen to read
 * again (`onSaved={load}`, `onChanged={load}`, `onDone={load}`) was unmounted by the read it asked for, so its own
 * confirmation, an open form and anything it had chosen were lost, and the person saw the screen blank and come back
 * without being told the save had worked. The sales cycle tab was fixed this way first (POST-A-385, its `loadedFor` ref);
 * this is that rule as one helper, so the next screen does not write a sixth copy of it.
 *
 * THE RULE.
 *   - The first read of a KEY (the client, the employee, the firm) blocks; a later read of the same key does not.
 *   - A read that came back marks the key read. A read that failed does not, so "Try again" after a failed first read
 *     blocks again and never shows lists that were never read as empty ones.
 *   - A new key blocks again, so a screen reused for another client never shows the last client's figures while the
 *     new ones load.
 *   - The latest QUESTION wins: a reload asked for while an earlier one is in flight makes the earlier answer stale, and
 *     a stale answer neither fills the screen nor ends the blocking.
 *
 * `FirstReadGate` is the rule with no React in it, so it is tested as plain code; `useFirstRead` is the screen's door.
 */
import { useMemo, useRef, useState } from "react";

export class FirstReadGate {
  private readFor: string | null = null;
  private latest = 0;

  /** Starts a read of `key`: its number, and whether the screen should block while it runs. */
  begin(key: string): { read: number; blocks: boolean } {
    const read = ++this.latest;
    return { read, blocks: this.readFor !== key };
  }

  /** Whether `read` is still the latest one asked for: only its answer may fill the screen. */
  isLatest(read: number): boolean {
    return read === this.latest;
  }

  /** `read` came back: its key counts as read, unless a later read has been asked for since. */
  landed(read: number, key: string): void {
    if (read === this.latest) this.readFor = key;
  }

  /** `read` failed: the next read blocks again. A stale failure changes nothing. */
  failed(read: number): void {
    if (read === this.latest) this.readFor = null;
  }
}

/**
 * The screen's door to the rule: `loading` (true until the first read settles) and `reader`, which is stable for a key
 * (so a loader that lists it in its dependencies is not re-made by every render). A loader calls `reader.begin()` first,
 * `reader.isLatest(read)` before it fills the screen, `reader.landed(read)` or `reader.failed(read)`, and
 * `reader.settled(read)` in its `finally`.
 */
export function useFirstRead(key: string) {
  const [loading, setLoading] = useState(true);
  const gate = useRef(new FirstReadGate());
  const reader = useMemo(() => ({
    begin(): number {
      const { read, blocks } = gate.current.begin(key);
      if (blocks) setLoading(true);
      return read;
    },
    isLatest: (read: number) => gate.current.isLatest(read),
    landed: (read: number) => gate.current.landed(read, key),
    failed: (read: number) => gate.current.failed(read),
    settled: (read: number) => { if (gate.current.isLatest(read)) setLoading(false); },
  }), [key]);
  return { loading, reader };
}
