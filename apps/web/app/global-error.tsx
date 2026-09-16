"use client";

/**
 * The last resort: a throw in the ROOT layout itself.
 *
 * At this point `app/layout.tsx` has not rendered, so there is no AppShell, no
 * fonts and no globals.css — Next.js replaces the whole document, which is why
 * this file must supply its own <html> and <body> and must not import anything
 * that expects the app's providers. Styles are inline for the same reason.
 *
 * It carries the same `data-module-error` marker as every other boundary so
 * the smoke walk fails on it rather than photographing it as a rendered
 * screen, and it deliberately reloads rather than calling `reset()` alone: if
 * the root layout threw, re-rendering the same tree usually throws again.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        data-module-error="root layout"
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#F8FAFC",
          color: "#0F172A",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          padding: 24,
        }}
      >
        <div style={{ maxWidth: 420, textAlign: "center" }}>
          <p style={{ fontSize: 15, fontWeight: 600, margin: "0 0 8px" }}>
            PracticeSync could not start
          </p>
          <p style={{ fontSize: 13, lineHeight: 1.5, color: "#475569", margin: "0 0 20px" }}>
            Something failed before the application loaded. Reloading usually
            clears it.
            {error.digest ? ` Reference: ${error.digest}` : ""}
          </p>
          <button
            onClick={() => {
              reset();
              window.location.reload();
            }}
            style={{
              border: "1px solid #CBD5E1",
              background: "#FFFFFF",
              borderRadius: 8,
              padding: "8px 16px",
              fontSize: 14,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      </body>
    </html>
  );
}
