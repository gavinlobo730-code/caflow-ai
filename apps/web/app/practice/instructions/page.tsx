"use client";

import { useState, useEffect } from "react";
import { api, type ApiResp } from "@/lib/api";
import { PartnerGuard } from "@/components/practice/PartnerGuard";
import { ClientInstructions } from "@/components/knowledge/ClientInstructions";
import { PagePlaceholder, pageFrameClass } from "@/components/ui/page-frame";

function PracticeInstructions() {
  const [internalId, setInternalId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Distinguishes "practice genuinely not set up yet" from "the fetch
  // failed" — the fetch failure previously rendered the same misleading
  // "Set up the Practice first" message even when the practice WAS set up.
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.practice.get() as ApiResp<{ internal_client_id: string | null }>;
        if (r.success) {
          setInternalId(r.data?.internal_client_id ?? null);
        } else {
          setLoadError(r.error ?? "Couldn't load your practice.");
        }
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : "Couldn't load your practice. Please try again.");
      } finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <PagePlaceholder label="Loading the practice's instructions" shape="list" width="form" />;
  if (loadError) return <div className="p-8 text-sm text-red-600">{loadError}</div>;
  if (!internalId) return <div className="p-8 text-sm text-gray-500">Set up the Practice first (Overview).</div>;
  // The internal client is the PRACTICE's own books, not a client of it, so the
  // component's default "Client Instructions" heading misdescribed this list.
  // A client's instructions live on that client's own Instructions tab.
  return (
    <div className={pageFrameClass("form")}>
      <ClientInstructions
        clientId={internalId}
        title="Practice standing instructions (the firm's own books)"
      />
    </div>
  );
}

export default function PracticeInstructionsPage() {
  return <PartnerGuard><PracticeInstructions /></PartnerGuard>;
}
