import { ClientWorkspaceShell } from "@/components/ClientWorkspaceShell";

export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return <ClientWorkspaceShell>{children}</ClientWorkspaceShell>;
}
