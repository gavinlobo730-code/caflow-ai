import EditPurchaseBillPageClient from "./_page";

// Static-export requires generateStaticParams for the dynamic [billId] segment;
// the real id comes from the URL at runtime (client-rendered SPA + _redirects).
export function generateStaticParams() {
  return [{ id: "_placeholder", billId: "_placeholder" }];
}

export default function EditPurchaseBillPage() {
  return <EditPurchaseBillPageClient />;
}
