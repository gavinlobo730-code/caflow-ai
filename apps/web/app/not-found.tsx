"use client";

import { useEffect, useState } from "react";
import { FrontDoor, type FrontDoorName } from "@/components/FrontDoor";
import { isOutsideTheShell } from "@/components/AppShell";
import { StuckLoadingNotice } from "@/components/ui/stuck-loading-notice";

export default function NotFound() {
  const [redirecting, setRedirecting] = useState(false);
  // An unknown address under a signed-out page (`/portal/…`, `/login/…`) is drawn as a front door, the way the pages
  // around it are; one inside the product is drawn inside the shell, beside the navigation, with no wash behind it
  // (POST-A-446). Decided at the first render, so the in-product page never flashes first: the exported 404.html holds
  // the session check's splash (AuthGuard renders it while the session loads), so this component first renders in the
  // browser, never from build-time HTML, and `window` is there to read. The client portal's and the engagement letter's
  // addresses take the portal's name, as their own pages do.
  const [outside] = useState(() => typeof window !== "undefined" && isOutsideTheShell(window.location.pathname));
  const [name] = useState<FrontDoorName>(() =>
    typeof window !== "undefined" && /^\/(portal|sign)(\/|$)/.test(window.location.pathname) ? "PracticeSync" : "PracticeSync AI");

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
      <div className="flex items-center justify-center h-screen bg-ps-bg">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-brand border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-ps-label">Loading workspace…</p>
          {/* After eight seconds it says so and offers Reload (POST-A-491): this page once sat here with no end. */}
          <StuckLoadingNotice />
        </div>
      </div>
    );
  }

  if (outside) {
    return (
      <FrontDoor name={name}>
        <div data-not-found="" className="text-center space-y-3">
          <p className="text-base font-semibold text-ps-ink">Page not found</p>
          <p className="text-sm text-ps-label">There is no page at this address.</p>
          {/* A full page load: the start page sends a signed-out person to the sign-in they need. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a
            href="/"
            className="inline-flex items-center text-sm font-medium text-brand hover:text-brand/70 underline underline-offset-4"
          >
            Go to the start page
          </a>
        </div>
      </FrontDoor>
    );
  }

  return (
    <div data-not-found="" className="flex items-center justify-center h-screen bg-ps-bg">
      <div className="text-center space-y-3">
        <p className="text-5xl font-bold text-brand/10">404</p>
        <p className="text-base font-semibold text-brand">Page not found</p>
        <p className="text-sm text-ps-label">The page you&apos;re looking for doesn&apos;t exist.</p>
        {/* A full page load, as the redirects above are: a 404 served for an unknown address leaves it whole rather than
            through the client router. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a
          href="/"
          className="inline-flex items-center text-sm font-medium text-brand hover:text-brand/70 underline underline-offset-4"
        >
          Go to dashboard
        </a>
      </div>
    </div>
  );
}
