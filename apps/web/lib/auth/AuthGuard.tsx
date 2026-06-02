"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "./AuthContext";

const PUBLIC_PATHS = ["/login", "/login/"];

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (loading) return;
    const isPublic = PUBLIC_PATHS.includes(pathname);
    if (!session && !isPublic) {
      router.replace("/login");
    }
    if (session && (pathname === "/login" || pathname === "/login/")) {
      router.replace("/");
    }
  }, [session, loading, pathname, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gradient-to-br from-indigo-950 via-indigo-900 to-violet-900">
        <div className="text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-white/10 border border-white/20 flex items-center justify-center mx-auto backdrop-blur-sm">
            <span className="text-white font-bold text-lg">CA</span>
          </div>
          <div className="flex items-center justify-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:0ms]" />
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:150ms]" />
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:300ms]" />
          </div>
          <p className="text-indigo-300 text-sm font-medium">CAflow AI</p>
        </div>
      </div>
    );
  }

  const isPublic = PUBLIC_PATHS.includes(pathname);
  if (!session && !isPublic) return null;

  return <>{children}</>;
}
