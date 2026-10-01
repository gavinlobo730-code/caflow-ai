"use client";

// practice_management-24: Work Allocation is merged into Team Workload.
//
// This URL used to be a SECOND answer to "how loaded is this person", and a
// guess by job title: it divided a count of open tasks by a per-role constant
// held in the browser, read every task straight over PostgREST, and wrote a
// reassignment straight back over it — so `rbac()` never saw the write, the new
// assignee was told nothing, and only one of the task's two assignee columns
// moved. `/team/workload` is the real model (configured weekly hours, logged
// time, a thirteen-week forecast, and now each person's estimated open work), and
// the allocate-and-reassign flow lives there, on the same payload.
//
// This file stays as a redirect — not deleted — so a bookmark, an emailed link or
// a `#unassigned-tasks` deep link still lands somewhere functional.
// `output: export` serves this app with no server, so there is no server-side
// redirect to issue instead; app/onboarding/checklist/page.tsx is the same
// pattern. IT FETCHES NOTHING AND DECIDES NOTHING, and a guard says so.
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function WorkAllocationRedirect() {
  const router = useRouter();

  useEffect(() => {
    // `window` is read inside an effect, never during render: this is a static
    // export and the page is pre-rendered with no browser.
    const hash = typeof window !== "undefined" ? window.location.hash : "";
    router.replace(`/team/workload${hash}`);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
