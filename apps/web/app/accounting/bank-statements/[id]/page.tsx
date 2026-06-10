import StatementDetailClient from "./StatementDetailClient";

export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default function Page() {
  return <StatementDetailClient />;
}
