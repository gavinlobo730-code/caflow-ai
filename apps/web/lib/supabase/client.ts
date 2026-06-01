import { createClient, SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

  // Provide a no-op client at build time so static generation doesn't crash.
  // Real auth calls only happen in the browser where env vars are populated.
  _client = createClient(url || "https://placeholder.supabase.co", key || "placeholder");
  return _client;
}

// Convenience singleton — used by AuthContext and api client
export const supabase = {
  auth: {
    getSession: () => getSupabaseClient().auth.getSession(),
    onAuthStateChange: (...args: Parameters<SupabaseClient["auth"]["onAuthStateChange"]>) =>
      getSupabaseClient().auth.onAuthStateChange(...args),
    signInWithPassword: (creds: { email: string; password: string }) =>
      getSupabaseClient().auth.signInWithPassword(creds),
    signOut: () => getSupabaseClient().auth.signOut(),
  },
  storage: {
    from: (bucket: string) => getSupabaseClient().storage.from(bucket),
  },
};
