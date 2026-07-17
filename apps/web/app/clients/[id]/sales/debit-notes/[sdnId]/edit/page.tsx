import EditSalesDebitNotePageClient from "./_page";

// Static-export requires generateStaticParams for the dynamic [sdnId] segment;
// the real id comes from the URL at runtime (client-rendered SPA + _redirects).
export function generateStaticParams() {
  return [{ id: "_placeholder", sdnId: "_placeholder" }];
}

export default function EditSalesDebitNotePage() {
  return <EditSalesDebitNotePageClient />;
}
