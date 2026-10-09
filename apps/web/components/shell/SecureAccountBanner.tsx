"use client";

import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { MFA_SETUP_HREF, showsSecureAccountBanner } from "@/lib/auth/mfaEnrolment";
import { Callout } from "@/components/ui/callout";

/** Shown in the staff shell until a Partner or Manager the MFA policy covers
 *  has a verified authenticator — without one, mfa_guard refuses the
 *  administration screens and nothing else tells them why. */
export function SecureAccountBanner({ pathname }: { pathname: string }) {
  const { mustEnrolMfa } = useAuth();
  if (!showsSecureAccountBanner(mustEnrolMfa, pathname)) return null;
  return (
    <div className="px-4 pt-3 print:hidden">
      <Callout tone="attention" title="Secure your account">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm">
            Team, Payroll, Billing and firm settings stay locked until you set up an authenticator app.
          </p>
          <Link
            href={MFA_SETUP_HREF}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark"
          >
            <ShieldCheck size={13} aria-hidden /> Set up authenticator
          </Link>
        </div>
      </Callout>
    </div>
  );
}
