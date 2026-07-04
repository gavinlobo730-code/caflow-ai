"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { CLIENT_SECTIONS } from "@/lib/workspace/ClientNavContext";
import { getLastClientSection } from "@/lib/workspace/clientSectionHistory";

export default function ClientRootPage() {
  const router = useRouter();

  useEffect(() => {
    const m = window.location.pathname.match(/^\/clients\/([^/]+)/);
    const id = m ? decodeURIComponent(m[1]) : null;
    if (id && id !== "_placeholder") {
      // A bare /clients/{id} link doesn't specify a section, so resume
      // wherever this client was last left — falls back to Overview for a
      // client that's never been opened before. An explicit deep link
      // straight to a section (e.g. /clients/{id}/sales/) never reaches
      // this page at all, so it always wins over this resume logic.
      const lastSection = getLastClientSection(id);
      const target = CLIENT_SECTIONS.find((s) => s.id === lastSection);
      router.replace(target ? target.href(id) : `/clients/${id}/overview/`);
    } else if (id === "_placeholder") {
      router.replace("/clients");
    }
  }, [router]);

  return (
    <div className="flex items-center justify-center h-full">
      <div className="flex flex-col items-center gap-3">
        <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-[#64748B]">Loading workspace…</p>
      </div>
    </div>
  );
}
