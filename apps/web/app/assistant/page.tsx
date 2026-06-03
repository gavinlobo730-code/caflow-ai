"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AssistantRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/ai-assistant"); }, [router]);
  return null;
}
