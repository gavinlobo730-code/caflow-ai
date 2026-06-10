"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ClientRootPage() {
  const router = useRouter();

  useEffect(() => {
    const m = window.location.pathname.match(/^\/clients\/([^/]+)/);
    const id = m ? decodeURIComponent(m[1]) : null;
    if (id) router.replace(`/clients/${id}/overview`);
  }, [router]);

  return null;
}
