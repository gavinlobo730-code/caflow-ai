import { ClientWorkspaceShell } from "@/components/ClientWorkspaceShell";

export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

interface ClientLayoutProps {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}

export default async function ClientLayout({ children, params }: ClientLayoutProps) {
  const { id } = await params;
  return (
    <ClientWorkspaceShell clientId={id}>
      {children}
    </ClientWorkspaceShell>
  );
}
