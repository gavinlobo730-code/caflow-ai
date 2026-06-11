"use client";

import { useEffect, useState } from "react";

export default function NotFound() {
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    const path = window.location.pathname;

    // Handle /clients/:id — redirect to overview
    const clientRoot = path.match(/^\/clients\/([^/]+)\/?$/);
    if (clientRoot && clientRoot[1] !== "_placeholder") {
      setRedirecting(true);
      window.location.replace(`/clients/${clientRoot[1]}/overview/`);
      return;
    }

    // Handle /clients/:id/:section — redirect to _placeholder equivalent
    const clientSection = path.match(/^\/clients\/([^/]+)(\/.*)/);
    if (clientSection && clientSection[1] !== "_placeholder") {
      setRedirecting(true);
      window.location.replace(`/clients/_placeholder${clientSection[2]}`);
      return;
    }
  }, []);

  if (redirecting) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#0a0a12]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-white/40">Loading workspace…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-screen bg-[#0a0a12]">
      <div className="text-center space-y-2">
        <p className="text-4xl font-bold text-white/20">404</p>
        <p className="text-sm text-white/40">Page not found</p>
        <a href="/" className="text-sm text-violet-400 hover:text-violet-300 underline">
          Go home
        </a>
      </div>
    </div>
  );
}
