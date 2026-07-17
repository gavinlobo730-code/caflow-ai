import EditDebitNotePageClient from "./_page";

// Static-export requires generateStaticParams for the dynamic [dnId] segment;
// the real id comes from the URL at runtime (client-rendered SPA + _redirects).
export function generateStaticParams() {
  return [{ id: "_placeholder", dnId: "_placeholder" }];
}

export default function EditDebitNotePage() {
  return <EditDebitNotePageClient />;
}
