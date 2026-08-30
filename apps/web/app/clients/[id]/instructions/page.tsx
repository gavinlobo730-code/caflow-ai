"use client";

import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { ClientInstructions } from "@/components/knowledge/ClientInstructions";

export default function ClientInstructionsPage() {
  const { clientId } = useClientNav();
  return (
    <div className="p-6 max-w-3xl mx-auto">
      <ClientInstructions clientId={clientId} />
    </div>
  );
}
