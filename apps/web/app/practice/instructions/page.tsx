"use client";

import { useState, useEffect } from "react";
import { api, type ApiResp } from "@/lib/api";
import { PartnerGuard } from "@/components/practice/PartnerGuard";
import { ClientInstructions } from "@/components/knowledge/ClientInstructions";

function PracticeInstructions() {
  const [internalId, setInternalId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.practice.get() as ApiResp<{ internal_client_id: string | null }>;
        setInternalId(r.data?.internal_client_id ?? null);
      } finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading…</div>;
  if (!internalId) return <div className="p-8 text-sm text-gray-500">Set up the Practice first (Overview).</div>;
  return (
    <div className="p-6 max-w-3xl">
      <ClientInstructions clientId={internalId} />
    </div>
  );
}

export default function PracticeInstructionsPage() {
  return <PartnerGuard><PracticeInstructions /></PartnerGuard>;
}
