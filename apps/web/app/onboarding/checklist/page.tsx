"use client";

// sweep-auth-and-public-05: this URL used to BE the client-onboarding
// workflow tracker, and it shared the /onboarding/* prefix with the firm
// SIGNUP wizard at /onboarding — confusing enough that even a route-grouping
// sweep treated it as step 2 of firm signup, although it is an authenticated
// staff screen tracking a CLIENT's onboarding, unrelated to the wizard.
//
// The real screen moved to /clients/onboarding, alongside the rest of the
// Clients workspace it belongs to (see ClientsPanel.tsx). This file stays as
// a redirect — not deleted — so an already-bookmarked or previously-linked
// /onboarding/checklist URL still lands somewhere functional. `output: export`
// serves this app with no server, so there is no server-side redirect to
// issue instead; see app/portal/page.tsx for the same pattern.
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function OnboardingChecklistRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/clients/onboarding");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
