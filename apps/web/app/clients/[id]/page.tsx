"use client";

import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default function ClientRootPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();

  useEffect(() => {
    if (params?.id) {
      router.replace(`/clients/${params.id}/overview`);
    }
  }, [params?.id, router]);

  return null;
}
