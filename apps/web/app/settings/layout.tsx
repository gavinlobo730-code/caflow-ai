import { Suspense, type ReactNode } from "react";
import { SettingsTabs } from "@/components/settings/SettingsTabs";

// Every Settings page opens under the same row of tabs (PRE-A-023): the groups are lib/settings/groups.ts, and a
// tab is the Settings home with ?tab=, so no page moves and no route is added. The row reads the address's query,
// which a static export may only do inside a Suspense boundary; until it can, nothing is drawn in its place
// rather than a row with the wrong tab lit.
export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <div className="sticky top-0 z-10">
        <Suspense fallback={null}>
          <SettingsTabs />
        </Suspense>
      </div>
      {children}
    </>
  );
}
