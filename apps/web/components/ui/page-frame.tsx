import * as React from "react";
import { cn } from "@/lib/utils";
import {
  CardGridSkeleton,
  FormSkeleton,
  ListSkeleton,
  LoadingRegion,
  MetricCardSkeleton,
  Skeleton,
  TableSkeleton,
} from "@/components/ui/skeleton";

/**
 * WHERE A SCREEN SITS ON THE PAGE, AND WHAT IT DRAWS WHILE ITS FIRST READ IS OUT (POST-A-530).
 *
 * The owner, walking the live site on 20-11-2026: inside a client's workspace a screen is laid out and waits with placeholders;
 * outside it Billing Schedules hugged the left edge with the right half of the window empty, and waited as one line of text.
 * Neither was a decision. The width rule already existed (D11 and the `max-w-ps-data` token in tailwind.config.ts: a screen of
 * data fills up to 1600px and is centred; a form or a page of prose keeps a narrow measure) and ninety wrappers follow it by
 * hand, but a wrapper typed by hand can leave the centring out, and thirty did: `p-6 max-w-4xl` caps a page and leaves it
 * against the rail. And a screen with no placeholder of its own shape wrote "Loading…" because writing one was easier than
 * composing three skeletons.
 *
 * So the two things a hand-typed wrapper gets wrong are one component each:
 *
 *   PageFrame        the screen's own container. `width` is the ROLE, not a number: "data" (a register, a dashboard, anything
 *                    with a table or a grid of figures) or "form" (a form, a settings page, a page that is read). Padding and
 *                    centring are not options: a frame that could be un-centred is the defect this exists to end.
 *   PagePlaceholder  what the screen draws while its first read is out: the frame, a title bar, and blocks in the screen's own
 *                    coarse shape (a table, cards, a form, a list). It is a `LoadingRegion`, so it carries the role, the label
 *                    and the slow-server notice the shared skeletons carry, and a screen swaps its "Loading…" line for one tag.
 *
 * WHAT THIS DOES NOT DO. It is not the client workspace's frame (those screens run edge to edge under their own tab bar and
 * scroll inside it), and it sets no vertical rhythm beyond a default gap: a screen that needs another passes `className`.
 * It does not decide WHEN a screen is loading (`lib/loading/firstRead.ts` does: a screen blocks for its first read only).
 *
 * THE RULE THAT HOLDS IT is a measurement, not a spelling: the browser walk (`scripts/smoke-walk.mjs --frame`) opens every
 * screen at a wide window and reports the ones whose container has far more room on its right than its left, and the ones
 * that wait as words alone. `scripts/a-page-that-caps-its-width-centres-it.test.ts` is the cheap half that runs on every
 * pull request.
 */
export type PageWidth = "data" | "form";

const WIDTH: Record<PageWidth, string> = {
  data: "max-w-ps-data",
  form: "max-w-3xl",
};

/** The classes of the frame, for the rare caller that cannot render the component (a `LoadingRegion` of its own shape). */
export function pageFrameClass(width: PageWidth = "data", className?: string): string {
  return cn("mx-auto w-full p-6", WIDTH[width], className);
}

export function PageFrame({
  width = "data",
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { width?: PageWidth }) {
  return (
    <div data-page-frame={width} className={pageFrameClass(width, cn("space-y-5", className))} {...props}>
      {children}
    </div>
  );
}

export type PlaceholderShape = "table" | "cards" | "form" | "list" | "dashboard";

function Shape({ shape, rows, cols }: { shape: PlaceholderShape; rows: number; cols: number }) {
  switch (shape) {
    case "cards":
      return <CardGridSkeleton count={rows} />;
    case "form":
      return <FormSkeleton fields={rows} />;
    case "list":
      return <ListSkeleton rows={rows} />;
    case "dashboard":
      return (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
          </div>
          <TableSkeleton rows={rows} cols={cols} />
        </>
      );
    default:
      return <TableSkeleton rows={rows} cols={cols} />;
  }
}

export function PagePlaceholder({
  label,
  shape = "table",
  width = "data",
  rows,
  cols = 5,
  action = true,
  className,
}: {
  /** What is loading, read to a screen reader ("Loading billing schedules"). Never drawn. */
  label: string;
  shape?: PlaceholderShape;
  width?: PageWidth;
  /** Rows of a table or a list, cards of a grid, fields of a form. Defaults to what suits the shape. */
  rows?: number;
  cols?: number;
  /** Whether the screen's header carries a primary action, so the title bar is drawn with one. */
  action?: boolean;
  className?: string;
}) {
  const count = rows ?? (shape === "form" ? 5 : shape === "cards" ? 6 : 6);
  return (
    <LoadingRegion label={label} className={pageFrameClass(width, cn("space-y-5", className))}>
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-3 w-72 max-w-full" />
        </div>
        {action && <Skeleton className="h-9 w-32 shrink-0" />}
      </div>
      <Shape shape={shape} rows={count} cols={cols} />
    </LoadingRegion>
  );
}
