"use client";

/**
 * The one chrome both portals wear.
 *
 * WHY IT EXISTS. `apps/web/app/portal/` is the ONLY surface a CA's own client
 * and their employees ever see, and it was rendered outside the staff shell
 * with almost none of the shared primitives — 62 raw `gray-*` classes, its own
 * `Panel`, its own `Table`, its own empty and error states. So the product
 * visibly had two designs and the outside world saw the older one.
 *
 * 2.6 settled the staff side by making `AppShell` return exactly one of two
 * shells on every branch, so a wrong path answer can never leave somebody with
 * no navigation. This is that decision applied to the portal: the client
 * dashboard and the employee portal render through here, so signing out, the
 * product's name and the identity on screen exist in ONE place rather than
 * twice with a drift between them.
 *
 * IT IS NOT `AppShell`, and that is deliberate. A portal principal is not
 * staff — `core/portal_auth` resolves two of them and neither has an RBAC role
 * — so there is no client switcher for a firm's book, no search over the
 * practice, no Settings. Rendering the staff rail here would offer a client
 * links their own principal is refused at, which is worse than a plain header.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { LogOut } from "lucide-react";

import { getSupabaseClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function PortalShell({
  title,
  subtitle,
  identity,
  actions,
  children,
}: {
  /** What this portal IS, not what the reader should do. */
  title: string;
  subtitle?: string;
  /** Who is signed in. Shown so somebody sharing a screen can see whose
   *  figures these are — a client portal is opened on a phone in a shop. */
  identity?: string | null;
  /** The one control a portal screen may put in the header (a client
   *  switcher). Anything else belongs in the page. */
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    try {
      await getSupabaseClient().auth.signOut();
    } finally {
      // Navigates whether or not the sign-out call succeeded: a session this
      // browser can no longer use is worse left on screen than cleared, and
      // the login page re-checks.
      router.replace("/portal/login");
    }
  }

  return (
    <div className="min-h-screen bg-ps-bg">
      <header className="border-b border-ps-border bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ps-ink">{title}</p>
            {subtitle && (
              <p className="truncate text-xs text-ps-label">{subtitle}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {actions}
            {identity && (
              <span className="hidden truncate text-xs text-ps-label sm:inline max-w-[14rem]">
                {identity}
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={signOut}
              disabled={signingOut}
              className="gap-1.5"
            >
              <LogOut size={13} />
              {signingOut ? "Signing out…" : "Sign out"}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">{children}</main>

      <footer className="mx-auto max-w-5xl px-4 pb-8 sm:px-6">
        <p className="text-3xs text-ps-hint">
          PracticeSync · Figures reflect your account with your accountant. For
          anything that looks off, message them.
        </p>
      </footer>
    </div>
  );
}

/** A section of a portal page. One border, one heading, one place to change. */
export function PortalPanel({
  title,
  action,
  children,
  className,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border border-ps-border bg-white", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-ps-border px-4 py-2.5">
        <h2 className="text-sm font-semibold text-ps-ink">{title}</h2>
        {action}
      </div>
      <div className="overflow-x-auto p-3">{children}</div>
    </section>
  );
}

/** A portal table. `head` is the column list; children are the rows. */
export function PortalTable({
  head,
  children,
}: {
  head: string[];
  children: React.ReactNode;
}) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="text-2xs uppercase tracking-wide text-ps-hint">
          {head.map((h, i) => (
            <th key={i} className="px-3 py-1.5 font-medium">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

export function PortalRow({ children }: { children: React.ReactNode }) {
  return <tr className="border-t border-ps-border">{children}</tr>;
}

/** Nothing to show, said in the client's words rather than "No data". */
export function PortalEmpty({ label }: { label: string }) {
  return <p className="p-4 text-sm text-ps-hint">{label}</p>;
}

/** A link out of the portal, used by the two activation pages. */
export function PortalLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="text-sm font-medium text-brand-dark hover:underline">
      {children}
    </Link>
  );
}
