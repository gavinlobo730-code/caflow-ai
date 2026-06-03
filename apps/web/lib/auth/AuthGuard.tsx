"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "./AuthContext";
import { LogoIcon } from "@/components/LogoIcon";

const PUBLIC_PREFIXES = ["/login", "/signup", "/onboarding", "/join", "/auth", "/portal"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"));
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (loading) return;
    const isPublic = isPublicPath(pathname);
    if (!session && !isPublic) {
      router.replace("/login");
    }
    if (session && (pathname === "/login" || pathname.startsWith("/login/"))) {
      router.replace("/");
    }
  }, [session, loading, pathname, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gradient-to-br from-indigo-950 via-indigo-900 to-violet-900">
        <div className="text-center space-y-4">
          <LogoIcon size="xl" />
          <div className="flex items-center justify-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:0ms]" />
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:150ms]" />
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:300ms]" />
          </div>
          <p className="text-indigo-300 text-sm font-medium">PracticeSync AI</p>
        </div>
      </div>
    );
  }

  const isPublic = isPublicPath(pathname);
  if (!session && !isPublic) return null;

  return <>{children}</>;
}
