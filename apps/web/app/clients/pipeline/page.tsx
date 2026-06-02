"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function PipelineRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/pipeline"); }, [router]);
  return null;
}
