"use client";

/**
 * The client's entity type, for the screens that must gate on it
 * (lib/entityObligations.ts is where the gating RULES live; this only fetches
 * the value they are applied to).
 *
 * A one-row primary-key read on `clients`, RLS-scoped to the firm — the same
 * shape and the same guard ClientHeader already uses to show the entity-type
 * badge. It is deliberately not on ClientNavContext: that context carries the
 * client id and nothing else, and the last time a shared mutable value was
 * parked there (the financial year) it ended up read by eleven pages and
 * ignored by the rest.
 */

import { useEffect, useState } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";

export interface ClientEntityTypeState {
  /** `clients.entity_type` as stored, or null while loading / on failure. */
  entityType: string | null;
  loading: boolean;
  /** Non-null when the row could not be read — NOT the same as "no entity
   *  type", which is why the caller cannot just test `entityType`. */
  error: string | null;
}

export function useClientEntityType(clientId: string): ClientEntityTypeState {
  const [state, setState] = useState<ClientEntityTypeState>({
    entityType: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    // Never send the static-export placeholder id (or an empty one) to
    // PostgREST: `id=eq.` against a uuid column is SQLSTATE 22P02, a request
    // that could never have succeeded. Same guard ClientHeader carries.
    if (!clientId || clientId === "_placeholder") {
      setState({ entityType: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState({ entityType: null, loading: true, error: null });
    // try/catch around an await, not .then().catch(): the PostgREST builder is
    // a PromiseLike, so it has no .catch(). The catch matters — offerWhenKnown()
    // fails open only once this settles, so a rejection that left `loading`
    // true forever would withhold a company's own MCA workspace indefinitely.
    (async () => {
      try {
        const { data, error } = await getSupabaseClient()
          .from("clients")
          .select("entity_type")
          .eq("id", clientId)
          .single();
        if (cancelled) return;
        if (error || !data) {
          setState({
            entityType: null,
            loading: false,
            error: error?.message ?? "Couldn't read this client's entity type.",
          });
          return;
        }
        const row = data as { entity_type?: string | null };
        setState({ entityType: row.entity_type ?? null, loading: false, error: null });
      } catch (err) {
        if (cancelled) return;
        setState({
          entityType: null,
          loading: false,
          error: err instanceof Error
            ? err.message
            : "Couldn't read this client's entity type.",
        });
      }
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  return state;
}

/**
 * Should a capability be OFFERED, given what we know about the entity type?
 *
 * The fail-open policy lives here so every gate shares one answer:
 *   - while the entity type is still loading, offer nothing — a control that
 *     appears and then vanishes reads as a bug;
 *   - if the row could not be read, offer it. This gate is an affordance, not
 *     an access control, and a transient PostgREST failure must not lock a
 *     company's CA out of its own MCA workspace. Being wrong here costs a
 *     screen that says "no companies registered"; being wrong the other way
 *     costs a statutory filing.
 */
export function offerWhenKnown(
  state: ClientEntityTypeState,
  applies: (entityType: string | null) => boolean,
): boolean {
  if (state.error !== null) return true;
  if (state.loading) return false;
  return applies(state.entityType);
}
