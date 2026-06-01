import ClientWorkspacePage from "./ClientWorkspacePage";

// Single placeholder — Cloudflare _redirects serves this for any /clients/ANYTHING
export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default function Page() {
  return <ClientWorkspacePage />;
}
