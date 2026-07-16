import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { CustomCursor } from "@/components/Cursor";

// Shared chrome for the public marketing pages. The login gateway (/access)
// lives OUTSIDE this group so it renders as a clean, standalone chooser without
// the full site header/footer — mirroring account.capium.com/Account/Login.
// CustomCursor is mounted once here so it's live across every page in the
// group without each page needing to remember to include it.
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <CustomCursor />
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </>
  );
}
