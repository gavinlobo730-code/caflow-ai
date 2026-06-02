"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function PortalRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/client-portal"); }, [router]);
  return null;
}
