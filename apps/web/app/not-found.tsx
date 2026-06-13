"use client";

import { useEffect, useState } from "react";

export default function NotFound() {
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    const path = window.location.pathname;

    const clientRoot = path.match(/^\/clients\/([^/]+)\/?$/);
    if (clientRoot && clientRoot[1] !== "_placeholder") {
      setRedirecting(true);
      window.location.replace(`/clients/${clientRoot[1]}/overview/`);
      return;
    }

    const clientSection = path.match(/^\/clients\/([^/]+)\/.+/);
    if (clientSection && clientSection[1] !== "_placeholder") {
      const canonical = path.endsWith("/") ? path : path + "/";
      if (canonical !== path) {
        window.location.replace(canonical);
      }
    }
  }, []);

  if (redirecting) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#F8FAFC]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-[#182350] border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-gray-400">Loading workspace…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-screen bg-[#F8FAFC]">
      <div className="text-center space-y-3">
        <p className="text-5xl font-bold text-[#182350]/10">404</p>
        <p className="text-base font-semibold text-[#182350]">Page not found</p>
        <p className="text-sm text-gray-400">The page you're looking for doesn't exist.</p>
        <a
          href="/"
          className="inline-flex items-center text-sm font-medium text-[#182350] hover:text-[#182350]/70 underline underline-offset-4"
        >
          Go to dashboard
        </a>
      </div>
    </div>
  );
}
