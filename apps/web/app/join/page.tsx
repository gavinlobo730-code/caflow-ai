"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase/client";
import { LogoIcon } from "@/components/LogoIcon";
import { api } from "@/lib/api";

export default function JoinPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const token = searchParams.get("token") ?? "";

  const [status, setStatus] = useState<"checking" | "linking" | "done" | "error">("checking");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [result, setResult] = useState<{ role?: string; full_name?: string } | null>(null);

  useEffect(() => {
    async function link() {
      if (!token) {
        setErrorMsg("This invite link is missing its token.");
        setStatus("error");
        return;
      }
      const supabase = getSupabaseClient();
      const { data: sessionData } = await supabase.auth.getSession();
      const session = sessionData?.session;
      if (!session) {
        // Magic link auth happens automatically — wait a moment and retry
        setTimeout(() => link(), 1500);
        return;
      }
      setStatus("linking");
      try {
        // F21 fix: the ONLY way an auth identity can be linked to a firm's
        // users row — server verifies the token, its expiry, and that the
        // caller's verified JWT email matches the invited email. firm_id and
        // role always come from the server-created invite row, never the URL.
        const res = await api.identity.acceptInvite(token);
        if (!res.success) throw new Error(res.error ?? "This invite is invalid or has expired.");
        setResult({ role: res.data.role, full_name: res.data.full_name });
        setStatus("done");
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : "Failed to link account");
        setStatus("error");
      }
    }
    link();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-600 via-indigo-900 to-blue-400 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <LogoIcon size="xl" />
          <h1 className="text-white text-2xl font-bold">PracticeSync AI</h1>
        </div>

        <div className="bg-white rounded-2xl shadow-2xl p-8 text-center space-y-4">
          {(status === "checking" || status === "linking") && (
            <>
              <div className="flex items-center justify-center gap-1.5 py-4">
                <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:0ms]" />
                <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:150ms]" />
                <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:300ms]" />
              </div>
              <p className="text-sm text-[#64748B]">
                {status === "checking" ? "Verifying your invite…" : "Setting up your account…"}
              </p>
            </>
          )}

          {status === "done" && (
            <>
              <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mx-auto">
                <svg className="w-6 h-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-[#0F172A]">
                Welcome to the team{result?.full_name ? `, ${result.full_name}` : ""}!
              </h2>
              {result?.role && (
                <p className="text-sm text-[#64748B]">
                  You&apos;ve been added as <strong>{result.role}</strong>.
                </p>
              )}
              <button
                onClick={() => router.replace("/")}
                className="w-full bg-blue-500 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-blue-600 transition-colors"
              >
                Go to Dashboard →
              </button>
            </>
          )}

          {status === "error" && (
            <>
              <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto">
                <svg className="w-6 h-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-[#0F172A]">Something went wrong</h2>
              <p className="text-sm text-[#64748B]">{errorMsg}</p>
              <p className="text-xs text-[#94A3B8]">Please contact your CA to resend the invite.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
