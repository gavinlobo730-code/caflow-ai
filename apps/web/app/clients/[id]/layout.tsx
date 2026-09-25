/**
 * The client workspace's layout is now only its static param.
 *
 * It used to render `ClientWorkspaceShell`, which rendered `ClientHeader`.
 * Both are gone: the header became `ClientTopBar` and moved up into
 * `AppShell`, beside the firm rail it replaces, so ONE component decides which
 * chrome a screen gets. A layout that rendered half the chrome meant the
 * decision was taken in two places, and only one of them could see the path.
 */
export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
