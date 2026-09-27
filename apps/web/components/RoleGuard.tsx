"use client";

import { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { hasRole, UserRole } from "@/lib/auth/permissions";
import { roleGuardDecision } from "@/lib/auth/guardDecision";

interface RoleGuardProps {
  /** Roles that are allowed to access the wrapped content. */
  allowed: UserRole[];
  /** Content to render when role check passes. */
  children: ReactNode;
  /**
   * When true (default), redirects to "/" if the user doesn't have the required role.
   * When false, renders nothing instead of redirecting (useful for wrapping sections).
   */
  redirect?: boolean;
}

/**
 * Wraps a page or section, redirecting to "/" (or hiding content) if the user
 * doesn't have one of the required roles.
 * Defaults role to "Partner" when null so existing users are never locked out.
 */
export function RoleGuard({ allowed, children, redirect = true }: RoleGuardProps) {
  const { userRole, loading, roleLoading } = useAuth();
  const router = useRouter();

  // Not decided until BOTH the session and this user's role are known: with
  // the role still in flight, userRole is null and hasRole() answers "no".
  const decision = roleGuardDecision({
    loading, roleLoading, permitted: hasRole(userRole, allowed),
  });

  useEffect(() => {
    if (decision === "deny" && redirect) {
      router.replace("/");
    }
  }, [decision, redirect, router]);

  // Waiting renders nothing (no flicker); a refusal hides the section, and
  // redirects too when this guards a whole page.
  if (decision !== "allow") return null;

  return <>{children}</>;
}
