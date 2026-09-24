"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { HubTile } from "@/lib/api";
import { arrayOrEmpty } from "@/lib/api/shape";
import { NO_FIGURE, formatPaise } from "@/lib/money/format";

/**
 * The hub — the fifteen tiles of decision D1, at firm or client scope.
 *
 * Every figure comes from `GET /api/hub` in ONE request; `domain/hub/tiles.py`
 * decides what each tile asks and `services/hub_service.py` knows which table
 * answers it. Nothing is computed here. That is not a style rule: the same
 * fifteen questions are asked at two scopes, and a browser that re-derived one
 * of them would be a second authority on what "unfiled" means.
 *
 * LOWER IS BETTER ON EVERY TILE, which is why one visual rule serves all
 * fifteen and a CA never has to ask which way a number reads. Every figure is
 * what is still OUTSTANDING, so a hub of zeros is a practice with nothing to
 * do — and zero is rendered as a finished state rather than as a small number.
 *
 * THREE RENDERINGS, NOT ONE, and the backend is what tells them apart:
 *
 *   signal 0,    answerable       → the finished state
 *   signal null, NOT answerable   → the reason, in place of a figure
 *   signal null, answerable       → this one tile could not be read
 *
 * The third exists because one slow table must not empty the hub; the second
 * because a nil meaning "there is nothing to do" and a nil meaning "nobody can
 * tell" are different facts, and a tile showing 0 for the second is the stub
 * this whole feature is defined against.
 *
 * A TILE WITH NO `href` AT THIS SCOPE IS NOT A LINK. Five modules have no
 * firm-level screen (question G3), and one of the five — Fixed Assets — has a
 * page that renders "this moved to the client workspace", which is worse than
 * a 404 because it looks like it works. The server answers `href: null` for
 * those, and a card with no href renders as a card, not as something to click.
 */
export function Hub({ clientId }: { clientId?: string }) {
  const [tiles, setTiles] = useState<HubTile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api.hub
      .get(clientId)
      .then((res) => {
        if (!live) return;
        // The GST workspace router answers refusals as HTTP 200, so the
        // envelope is checked before the payload — and the payload before it
        // is treated as a list (lib/api/shape.ts).
        if (!res?.success) {
          setError(res?.error || "Could not load the hub.");
          return;
        }
        setTiles(arrayOrEmpty<HubTile>(res.data?.tiles));
      })
      .catch((e) => {
        if (live) setError(e instanceof Error ? e.message : "Could not load the hub.");
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [clientId]);

  if (loading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 15 }).map((_, i) => (
          <div key={i} className="h-24 rounded-lg border border-ps-border bg-white animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="rounded-lg border border-state-problem-border bg-state-problem-surface p-4">
        <p className="text-sm font-medium text-state-problem">{error}</p>
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {tiles.map((t) => (
        <HubCard key={t.id} tile={t} />
      ))}
    </div>
  );
}

function figure(tile: HubTile): string {
  if (tile.signal === null) return NO_FIGURE;
  // `formatPaise` ALREADY carries the ₹ — `Intl.NumberFormat("en-IN", {style:
  // "currency"})` emits it — so a template that adds one renders "₹₹4,23,517".
  // That is exactly what the first draft of this file did, on all three money
  // tiles, and `the-hub-renders-three-states.test.ts` pins it now.
  //
  // `formatPaise` rather than `formatWhole`: the latter's own docstring is
  // about a figure the SERVER has already rounded to whole rupees for a
  // statutory payload, and it renders paise where it finds them precisely so
  // an unrounded row stands out. A hub tile is neither — it is a real balance
  // that will rarely be a whole rupee — so it shows the true figure, and the
  // browser rounds nothing.
  return tile.unit === "paise" ? formatPaise(tile.signal) : String(tile.signal);
}

function HubCard({ tile }: { tile: HubTile }) {
  const nothingToDo = tile.answerable && tile.signal === 0;
  const unreadable = tile.answerable && tile.signal === null;

  const body = (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-ps-ink truncate">{tile.label}</span>
      </div>
      <div
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          // Zero is the FINISHED state on every tile, not a small number — the
          // whole grid reads lower-is-better, so it is drawn as calm rather
          // than as an absence.
          nothingToDo ? "text-state-ready" : "text-ps-ink",
          !tile.answerable || unreadable ? "text-ps-hint" : null,
        )}
      >
        {tile.answerable ? figure(tile) : "—"}
      </div>
      <p className="mt-1 text-2xs leading-snug text-ps-label">{tile.question}</p>
      {!tile.answerable && tile.no_signal_because && (
        <p className="mt-1.5 text-3xs leading-snug text-ps-hint">{tile.no_signal_because}</p>
      )}
      {unreadable && (
        <p className="mt-1.5 text-3xs leading-snug text-state-attention">
          This figure could not be read just now. The others are current.
        </p>
      )}
    </>
  );

  const shell = "rounded-lg border border-ps-border bg-white p-3 min-w-0";

  // No destination at this scope — a card, not a link. See the module note.
  if (!tile.href) {
    return <div className={shell}>{body}</div>;
  }
  return (
    <Link
      href={tile.href}
      className={cn(shell, "block transition-colors hover:border-brand focus:outline-none focus:ring-2 focus:ring-brand")}
    >
      {body}
    </Link>
  );
}
