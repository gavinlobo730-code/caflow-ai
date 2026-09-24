"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { HubWorklistPayload } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/money/format";

/**
 * A firm-level module worklist — which clients need work here (D22, G3).
 *
 * ⚠️ WHAT THIS REPLACED. Five of D1's fifteen hub tiles had no firm-level
 * destination, and two of the five landed on a `MovedToClientWorkspace`
 * TOMBSTONE — a page whose whole content is "this moved" — which is worse than
 * a 404 because it renders. So the firm hub showed "7 assets with depreciation
 * outstanding" with nowhere to click.
 *
 * The tombstones are a deliberate earlier decision ("firm-level accounting
 * screens have been retired; accounting flows through the client workspace"),
 * so this is NOT a rebuilt firm-level register — that is the duplicate they
 * exist to prevent. It is the question a bureau actually asks on the 3rd of the
 * month: which of my clients needs work in this module. A QUEUE, not a
 * register. Every row opens that client's own section, which is the model the
 * retirement decision set, reached in one click.
 *
 * ONE COMPONENT, FOUR ROUTES. `/accounting/banking`, `/accounting/purchases`,
 * `/accounting/fixed-assets` and `/accounting/year-end` are four thin pages
 * over this, because four copies of a table would be four places for the
 * figure's meaning to drift from the tile it breaks down.
 *
 * NOTHING IS COMPUTED HERE. The figure, its unit, the column heading and the
 * question all come from `GET /api/hub/worklist`, which reads
 * `domain/hub/worklist.py` over `domain/hub/tiles.py`. A browser that
 * re-derived "a bank line still needing a person" would be a second authority
 * on the number the tile already shows — and a CA who clicks 7 and counts 5
 * stops trusting both.
 *
 * AN EMPTY QUEUE IS THREE DIFFERENT FACTS and `clients_examined` is what tells
 * them apart: zero rows over forty clients is *nothing outstanding*, zero rows
 * over zero clients is *you are assigned to no clients*, and a failed fetch is
 * an error. The hub's own three-state discipline, applied to a list.
 *
 * ⚠️ AND THERE IS A FOURTH, WHICH THE FIRST SMOKE SHOT OF THIS SCREEN CAUGHT:
 * the envelope says `success` and the payload is not an object, so `loading`
 * is false, `error` is null and `data` is null — and the first draft rendered
 * the heading over NOTHING. `objectWithLists` answering null is the helper
 * working (`lib/api/shape.ts`), not an absence to ignore; the four states are
 * exhaustive below and a payload that cannot be read says so.
 *
 * `heading` is the page's own H1 and is not taken from the payload, because it
 * has to be right BEFORE the fetch lands — a screen titled "Worklist" until
 * the server answers reads as a broken page. It is pinned to the tile's own
 * label by `tests/test_the_firm_hub_tiles_land_somewhere.py`, so the two
 * cannot drift.
 */
export function ModuleWorklist({ tile, heading }: { tile: string; heading: string }) {
  const [data, setData] = useState<HubWorklistPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api.hub
      .worklist(tile)
      .then((res) => {
        if (!live) return;
        if (!res?.success) {
          // A tile with no firm-level worklist answers 422 with the REASON —
          // `inventory` is the one — so the sentence is shown rather than an
          // empty table that would read as "no client needs work".
          setError(res?.error || "Could not load the worklist.");
          return;
        }
        setData(objectWithLists<HubWorklistPayload>(res.data, "rows"));
      })
      .catch(() => live && setError("Could not load the worklist."))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [tile]);

  const rows = data?.rows ?? [];

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ps-ink">{heading}</h1>
        <p className="text-xs text-ps-hint mt-1">
          {data?.question ?? "Which clients need work here"} · across every
          client you can see
        </p>
      </div>

      {loading && (
        <p className="text-xs text-ps-hint">Loading…</p>
      )}

      {!loading && (error || !data) && (
        <div className="bg-white rounded-xl border border-ps-muted p-6">
          <p className="text-xs text-ps-label leading-relaxed">
            {error ??
              "This worklist could not be read. The figures on the hub are " +
                "unaffected — open a client to work the module directly."}
          </p>
        </div>
      )}

      {!loading && !error && data && rows.length === 0 && (
        <div className="bg-white rounded-xl border border-ps-muted p-8 text-center space-y-2">
          <p className="text-sm font-semibold text-ps-ink">
            {data.clients_examined > 0
              ? "Nothing outstanding"
              : "No clients to examine"}
          </p>
          <p className="text-xs text-ps-hint max-w-md mx-auto">
            {data.clients_examined > 0
              ? `${data.question} — none, across ${data.clients_examined} ` +
                `${data.clients_examined === 1 ? "client" : "clients"}.`
              : "You are not assigned to any client, so there is nothing to " +
                "show here. A Partner assigns clients from Team → Assignments."}
          </p>
        </div>
      )}

      {!loading && !error && data && rows.length > 0 && (
        <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-ps-muted bg-ps-bg">
                <th className="text-left font-semibold text-ps-label px-4 py-2.5">
                  Client
                </th>
                <th className="text-right font-semibold text-ps-label px-4 py-2.5">
                  {data.column}
                </th>
                <th className="px-4 py-2.5 w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.client_id}
                  className="border-b border-ps-muted last:border-0 hover:bg-ps-bg"
                >
                  <td className="px-4 py-2.5">
                    <Link
                      href={`/clients/${r.client_id}/${data.opens_section}`}
                      className="font-medium text-ps-ink hover:text-brand"
                    >
                      {/* A row whose name could not be read is STILL listed,
                          with its id — a queue that silently omits a client is
                          the failure this screen exists to prevent. */}
                      {r.client_name ?? r.client_id}
                    </Link>
                    {r.entity_type && (
                      <span className="ml-2 text-3xs text-ps-hint">
                        {r.entity_type}
                      </span>
                    )}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-2.5 text-right font-semibold text-ps-ink",
                      "tabular-nums",
                    )}
                  >
                    {/* The unit is the TILE's, served rather than guessed from
                        the value — "₹4,20,000" and "7" are different questions
                        and a screen that inferred one from the other would
                        render a count of 42000 as money the day a tile moved. */}
                    {data.unit === "paise"
                      ? formatPaise(r.signal)
                      : r.signal.toLocaleString("en-IN")}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <Link
                      href={`/clients/${r.client_id}/${data.opens_section}`}
                      className="text-ps-hint hover:text-brand inline-flex"
                      aria-label={`Open ${r.client_name ?? "this client"}`}
                    >
                      <ArrowRight size={13} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center gap-1.5 px-4 py-2 border-t border-ps-muted bg-ps-bg">
            <Users size={11} className="text-ps-hint" />
            <p className="text-3xs text-ps-hint">
              {rows.length} of {data.clients_examined}{" "}
              {data.clients_examined === 1 ? "client" : "clients"} need work
              here. Lower is better on every figure.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
