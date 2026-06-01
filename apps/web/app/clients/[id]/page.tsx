import ClientWorkspacePage from "./ClientWorkspacePage";

// Pre-render the known mock client IDs for static export
export function generateStaticParams() {
  return [
    { id: "c-001" },
    { id: "c-002" },
    { id: "c-003" },
    { id: "c-004" },
    { id: "c-005" },
  ];
}

export default function Page() {
  return <ClientWorkspacePage />;
}
