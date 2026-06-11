"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ClientRootPage() {
  const router = useRouter();

  useEffect(() => {
    const m = window.location.pathname.match(/^\/clients\/([^/]+)/);
    const id = m ? decodeURIComponent(m[1]) : null;
    if (id && id !== "_placeholder") {
      router.replace(`/clients/${id}/overview/`);
    } else if (id === "_placeholder") {
      router.replace("/clients");
    }
  }, [router]);

  return (
    <div className="flex items-center justify-center h-full">
      <div className="flex flex-col items-center gap-3">
        <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-white/40">Loading workspace…</p>
      </div>
    </div>
  );
}
