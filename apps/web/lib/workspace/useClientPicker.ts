"use client";

import { useEffect, useState } from "react";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

/**
 * Shared client-list + selected-client-id state for the global tool pages
 * that live outside /clients/[id]/* (ClientNavContext only covers that
 * client-scoped tree — see R3.6). Each of those pages previously duplicated
 * its own clients/selectedId/loading useState trio plus its own
 * `sb.from("clients")` fetch; this centralizes the fetch onto the shared
 * getClients() helper every other page already uses.
 *
 * Does not auto-select a first client — callers that filter/act on a single
 * client (cash-flow forecast, TDS return computation) require an explicit
 * pick, so clientId starts empty and only changes via setClientId.
 */
export function useClientPicker() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getClients()
      .then((rows) => { if (!cancelled) setClients(rows); })
      .catch(() => { if (!cancelled) setClients([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { clients, clientId, setClientId, loading };
}
