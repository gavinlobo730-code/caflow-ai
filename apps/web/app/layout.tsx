import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { AuthGuard } from "@/lib/auth/AuthGuard";
import { AppShell } from "@/components/AppShell";
import { Toaster } from "@/components/ui/toaster";
import { ConfirmDialogHost } from "@/components/ui/confirm-dialog";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "PracticeSync AI",
  description: "AI-powered operating system for modern accounting and advisory firms",
  manifest: "/manifest.json",
  // NO `themeColor` HERE. Next 14 moved it out of `metadata`, so this key was
  // silently DROPPED — the built page emits the <meta> below and nothing else,
  // which is how a second, contradictory chrome colour (#2563EB, a generic
  // blue that is this product's brand nowhere) sat in the file unnoticed. One
  // colour, declared in the two places that actually read it: the <meta> tag
  // below and public/manifest.json.
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="manifest" href="/manifest.json" />
        <link rel="icon" type="image/svg+xml" href="/logo.svg" />
        {/* `ps.ink` (#0D1635) exactly. A <meta> takes no class, so this and
            the manifest are the only two places a token has to be written
            out — and both were TWO off it, so the browser chrome and the app
            disagreed about the darkest ink by an amount nobody chose. */}
        <meta name="theme-color" content="#0D1635" />
        <script
          dangerouslySetInnerHTML={{
            __html: `if ('serviceWorker' in navigator) { window.addEventListener('load', function() { navigator.serviceWorker.register('/sw.js'); }); }`,
          }}
        />
      </head>
      <body className={inter.className}>
        <AuthProvider>
          <AuthGuard>
            <AppShell>{children}</AppShell>
          </AuthGuard>
        </AuthProvider>
        <Toaster />
        <ConfirmDialogHost />
      </body>
    </html>
  );
}
