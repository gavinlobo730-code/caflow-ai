"use client";

import { useState, useEffect, useCallback } from "react";
import { clientRepository } from "@/lib/repositories/client.repository";
import type { Client, ClientWorkspace } from "@/lib/types";

export function useClients() {
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setClients(await clientRepository.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load clients");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return { clients, loading, error, reload: load };
}

export function useClientWorkspace(id: string) {
  const [workspace, setWorkspace] = useState<ClientWorkspace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    clientRepository.getWorkspace(id)
      .then(setWorkspace)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load workspace"))
      .finally(() => setLoading(false));
  }, [id]);

  return { workspace, loading, error };
}
