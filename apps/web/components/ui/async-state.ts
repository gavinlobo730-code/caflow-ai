/**
 * Pure decision for which async UI state to show, in priority order:
 *   error → loading → empty → content
 * Kept in a plain .ts module (no JSX) so it is unit-testable and reusable by
 * any page that wants the same precedence without importing React components.
 */
export type AsyncState = "error" | "loading" | "empty" | "content";

export function resolveAsyncState({
  loading,
  error,
  isEmpty = false,
}: {
  loading: boolean;
  error?: string | null;
  isEmpty?: boolean;
}): AsyncState {
  if (error) return "error";
  if (loading) return "loading";
  if (isEmpty) return "empty";
  return "content";
}
