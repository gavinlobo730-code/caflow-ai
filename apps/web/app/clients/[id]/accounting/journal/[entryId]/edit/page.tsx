import JournalEntryPageClient from "./_page";

// Static-export requires generateStaticParams for the dynamic [entryId] segment;
// the real ids come from the URL at runtime (client-rendered SPA + _redirects).
export function generateStaticParams() {
  return [{ id: "_placeholder", entryId: "_placeholder" }];
}

export default function JournalEntryPage() {
  return <JournalEntryPageClient />;
}
