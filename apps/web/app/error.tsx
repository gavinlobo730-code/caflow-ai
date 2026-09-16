"use client";

// The catch-all below the root layout: any route without a closer boundary
// lands here. The per-module files are what keep a failure inside one module;
// this one keeps it inside the page. See components/ModuleErrorBoundary.tsx.

import ModuleErrorBoundary from "@/components/ModuleErrorBoundary";

export default function Error(props: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ModuleErrorBoundary {...props} />;
}
