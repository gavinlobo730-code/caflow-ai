import YearEndWorkspace from "./_workspace";

export function generateStaticParams() {
  return [{ id: "_placeholder", engagementId: "_placeholder" }];
}

export default function YearEndEngagementPage() {
  return <YearEndWorkspace />;
}
