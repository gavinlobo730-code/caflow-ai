"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PartnerGuard } from "@/components/practice/PartnerGuard";

// The firm Knowledge Base lives in the dedicated Knowledge workspace; the Practice
// "Knowledge Base" tab routes there to avoid duplicating the surface.
function PracticeKnowledgeRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/knowledge"); }, [router]);
  return <div className="p-8 text-sm text-gray-500">Opening Knowledge Base…</div>;
}

export default function PracticeKnowledgePage() {
  return <PartnerGuard><PracticeKnowledgeRedirect /></PartnerGuard>;
}
