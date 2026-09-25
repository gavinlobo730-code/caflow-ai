import { ClientResolutionGate } from "@/components/client/ClientResolutionGate";

/**
 * The client workspace's layout is its static param and one gate.
 *
 * It used to render `ClientWorkspaceShell`, which rendered `ClientHeader`.
 * Both are gone: the header became `ClientTopBar` and moved up into
 * `AppShell`, beside the firm rail it replaces, so ONE component decides which
 * chrome a screen gets. A layout that rendered half the chrome meant the
 * decision was taken in two places, and only one of them could see the path.
 *
 * What it does render is `ClientResolutionGate`, and the reason it is HERE is
 * that every route under this layout has the same defect and the same fix: a
 * client id that resolves to nothing leaves the screen holding its skeleton
 * for ever, because each page's loader returns early inside a `useEffect` and
 * never clears `loading`. Forty screens, one shared layout, one gate — rather
 * than forty empty states that would then have to be kept in step.
 *
 * ⚠️ IT HAS TO BE A SEPARATE `"use client"` COMPONENT. `generateStaticParams`
 * is a server export and a file carrying `"use client"` may not have one, so
 * the layout stays a server component and the gate is its child.
 */
export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return <ClientResolutionGate>{children}</ClientResolutionGate>;
}
