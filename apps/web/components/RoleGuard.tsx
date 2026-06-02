"use client";

import { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { hasRole, UserRole } from "@/lib/auth/permissions";

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
  const { userRole, loading } = useAuth();
  const router = useRouter();

  const permitted = hasRole(userRole, allowed);

  useEffect(() => {
    if (!loading && !permitted && redirect) {
      router.replace("/");
    }
  }, [loading, permitted, redirect, router]);

  // While auth is loading, render nothing to avoid flicker.
  if (loading) return null;

  // If redirect=false (section guard), simply hide the section.
  if (!permitted) return null;

  return <>{children}</>;
}
