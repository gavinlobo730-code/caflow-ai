"use client";

/**
 * React adapter for `singleFlight` (frontend_ux-09).
 *
 * `useSingleFlight()` returns ONE flight for the life of the component. Hand it
 * to every `<Button flight={flight}>` that starts the same action — Save Draft
 * and Post Entry, Save & Send and Save & Issue — so a click on one while the
 * other is working is ignored on the same tick, and read `pending` to disable
 * anything else on the screen that must wait.
 *
 * The state lives OUTSIDE React (a subscribable) and is read with
 * `useSyncExternalStore`, so a Button holding a shared flight re-renders when
 * the flight changes without its parent having to thread a flag down, and a
 * Button that unmounts mid-flight unsubscribes with nothing left to set.
 */
import { useState, useSyncExternalStore } from "react";
import {
  createSingleFlight, idleFlightState, type FlightState, type SingleFlight,
} from "@/lib/async/singleFlight";

/** Subscribe to a flight and read its state. Used by `useSingleFlight` and by
 *  `Button`, which may be handed a flight it did not create. */
export function useFlightState(flight: SingleFlight): FlightState {
  return useSyncExternalStore(flight.subscribe, flight.getState, idleFlightState);
}

export function useSingleFlight(): {
  /** The guard itself — stable for the life of the component. */
  flight: SingleFlight;
  /** A render-time view of "is something in flight". A HANDLER must ask
   *  `flight.busy()` instead: a handler runs before the next render. */
  pending: boolean;
  /** Which control started it (the `owner` it was run with), or null. */
  owner: string | null;
} {
  const [flight] = useState(createSingleFlight);
  const state = useFlightState(flight);
  return { flight, pending: state.busy, owner: state.owner };
}
