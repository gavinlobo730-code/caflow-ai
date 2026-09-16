"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/ui/states";

/**
 * What a module segment renders when something below it throws.
 *
 * WHY THIS EXISTS. Until 16 September 2026 there was not one `error.tsx`,
 * `loading.tsx` or `global-error.tsx` anywhere in 160 routes. In the App
 * Router a render throw with no boundary unmounts to the root, so the plan's
 * containment promise for the redesign — "one PR per module; if something
 * breaks it is one module and one diff" — was false at runtime: a throw in a
 * converted module took the whole page, shell and navigation with it.
 *
 * It is also the half of the safety net the smoke walk cannot see on its own.
 * `scripts/smoke-walk.mjs` only asserted the body was non-empty, and an error
 * page has a body — so the walk reported green on exactly the failure a
 * boundary would have contained. THE MARKER BELOW IS THE INTERLOCK: the walk
 * looks for `data-module-error`, and a route that renders one FAILS the run
 * instead of passing it. Do not rename it without changing the walk; a test
 * pins the pair.
 *
 * THE DIGEST IS SHOWN ON PURPOSE. A static export has no server log a CA can
 * be asked to check, and React replaces a production error message with a
 * hash. Printing it is the only way a user can tell us WHICH failure they hit;
 * the message itself is deliberately not rendered, since it can carry a query
 * shape or an id and this screen may be over a client's shoulder.
 */
export default function ModuleErrorBoundary({
  error,
  reset,
  moduleName,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  moduleName?: string;
}) {
  useEffect(() => {
    // The browser console is where the smoke walk and a developer both look.
    // console.error is what `pageerror`/`console` handlers in the walk record.
    console.error(`[module error]${moduleName ? ` ${moduleName}:` : ""}`, error);
  }, [error, moduleName]);

  return (
    <div
      data-module-error={moduleName || "unknown"}
      className="flex min-h-[60vh] items-center justify-center p-6"
    >
      <div className="w-full max-w-md">
        <ErrorState
          title={
            moduleName
              ? `${moduleName} could not be displayed`
              : "This page could not be displayed"
          }
          message={
            "The rest of the application is still working — use the navigation to " +
            "carry on. If it keeps happening, quote the reference below." +
            (error.digest ? ` Reference: ${error.digest}` : "")
          }
          onRetry={reset}
        />
      </div>
    </div>
  );
}
