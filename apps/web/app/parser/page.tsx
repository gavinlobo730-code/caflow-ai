"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Document Parser merged into Doc Intelligence — single unified page
export default function ParserRedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace("/documents/intelligence"); }, [router]);
  return (
    <div className="min-h-screen flex items-center justify-center text-sm text-gray-400">
      Redirecting to Doc Intelligence…
    </div>
  );
}
