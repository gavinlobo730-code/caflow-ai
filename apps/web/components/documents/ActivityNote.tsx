"use client";

/**
 * The note under a document's activity list when the server said older entries exist than the window holds. Renders nothing
 * for a complete list and for one that could not be read (the empty-state line says that case).
 */
import { ListWindowNotice } from "@/components/lists/ListWindowNotice";
import { windowDescription } from "@/lib/lists/window";
import type { ActivityStatus } from "@/lib/documents/activity";

export function ActivityNote({ status }: { status: ActivityStatus }) {
  if (!status.read || !status.hasMore) return null;
  return (
    <ListWindowNotice
      hasMore
      what={windowDescription(status.limit, "activity entries", "latest")}
      limit={status.limit}
      maxLimit={status.maxLimit}
    />
  );
}
