"use client";

// Contains a render failure to this module instead of unmounting the whole
// app. See components/ModuleErrorBoundary.tsx for why this file exists and
// why the smoke walk fails on it rather than passing.

import ModuleErrorBoundary from "@/components/ModuleErrorBoundary";

export default function Error(props: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ModuleErrorBoundary {...props} moduleName="Documents" />;
}
