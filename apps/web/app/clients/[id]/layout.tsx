import { ClientWorkspaceShell } from "@/components/ClientWorkspaceShell";

export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

interface ClientLayoutProps {
  children: React.ReactNode;
  params: { id: string };
}

export default function ClientLayout({ children, params }: ClientLayoutProps) {
  return (
    <ClientWorkspaceShell clientId={params.id}>
      {children}
    </ClientWorkspaceShell>
  );
}
