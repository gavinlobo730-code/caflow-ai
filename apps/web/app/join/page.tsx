"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase/client";

export default function JoinPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const firmId = searchParams.get("firm") ?? "";
  const role = searchParams.get("role") ?? "Staff";
  const name = searchParams.get("name") ?? "";
  const jobTitle = searchParams.get("jobTitle") ?? "";

  const [status, setStatus] = useState<"checking" | "linking" | "done" | "error">("checking");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    async function link() {
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
        const email = session.user.email ?? "";
        const authUserId = session.user.id;

        // Try to update the pre-created invited row
        const { data: existingRow } = await supabase
          .from("users")
          .select("id, auth_user_id")
          .eq("email", email)
          .eq("firm_id", firmId)
          .maybeSingle();

        if (existingRow) {
          if (!existingRow.auth_user_id) {
            await supabase
              .from("users")
              .update({ auth_user_id: authUserId, status: "active", is_active: true })
              .eq("id", existingRow.id);
          }
        } else {
          // No pre-created row — insert one
          await supabase.from("users").insert({
            auth_user_id: authUserId,
            firm_id: firmId,
            full_name: name || email,
            email,
            role,
            job_title: jobTitle || null,
            is_active: true,
            status: "active",
          });
        }
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
    <div className="min-h-screen bg-gradient-to-br from-indigo-950 via-indigo-900 to-violet-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-white/10 border border-white/20 flex items-center justify-center mx-auto mb-4">
            <span className="text-white font-bold text-lg">CA</span>
          </div>
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
              <p className="text-sm text-gray-500">
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
              <h2 className="text-lg font-semibold text-gray-900">
                Welcome to the team{name ? `, ${name}` : ""}!
              </h2>
              {role && (
                <p className="text-sm text-gray-500">
                  You&apos;ve been added as <strong>{role}</strong>
                  {jobTitle ? ` — ${jobTitle}` : ""}.
                </p>
              )}
              <button
                onClick={() => router.replace("/")}
                className="w-full bg-indigo-600 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-indigo-700 transition-colors"
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
              <h2 className="text-lg font-semibold text-gray-900">Something went wrong</h2>
              <p className="text-sm text-gray-500">{errorMsg}</p>
              <p className="text-xs text-gray-400">Please contact your CA to resend the invite.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
