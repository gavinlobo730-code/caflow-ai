import type { CSSProperties } from "react";
import Link from "next/link";
import { Logo } from "./Logo";
import { DiagonalSection } from "./DiagonalSection";
import { appLinks, CONTACT } from "@/lib/site";

// Home-page-only footer, distinct from the shared `SiteFooter` used on every
// other marketing route (/products, /pricing, /support, /resources, /access
// all keep that one, untouched). The design reference specifies exactly 4
// columns; the shared footer has 5 (an extra "Resources" column) and isn't
// meant to change — so this is its own component rather than a variant prop
// on the shared one, keeping the two fully independent.

type FooterLink = { label: string; href: string; external?: boolean };

const COLUMNS: { title: string; links: FooterLink[] }[] = [
  {
    title: "Product",
    links: [
      { label: "Products", href: "/products" },
      { label: "Pricing", href: "/pricing" },
      { label: "Security", href: "/products#security" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "Our Story", href: "/#story" },
      { label: "Support", href: "/support" },
      { label: "Contact", href: `mailto:${CONTACT.email}`, external: true },
    ],
  },
  {
    title: "Get started",
    links: [
      { label: "Start free trial", href: appLinks.signup, external: true },
      { label: "Firm login", href: "/access" },
      { label: "Client portal", href: appLinks.clientPortal, external: true },
    ],
  },
];

const VIGNETTE: CSSProperties = { boxShadow: "inset 0 0 140px rgba(0,0,0,0.5)" };

export function HomeFooter() {
  return (
    <DiagonalSection seam="rising-right" className="bg-brand-dark text-white" style={VIGNETTE}>
      <footer className="relative overflow-hidden">
        <div
          className="relative mx-auto max-w-[1100px] px-[clamp(20px,6vw,72px)] pb-[34px]"
          style={{ paddingTop: "calc(70px + 64px)" }}
        >
          <div className="grid gap-9 sm:grid-cols-2 lg:grid-cols-[1.6fr_1fr_1fr_1fr]" style={{ gap: "36px" }}>
            <div className="max-w-[32ch]">
              <Logo theme="dark" />
              <p className="mt-3.5 text-[13px] leading-[1.6] text-white/60">
                The AI-first operating system for Indian CA practices — compliance,
                accounting, payroll and clients in one place.
              </p>
            </div>

            {COLUMNS.map((col) => (
              <div key={col.title}>
                <h4 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.1em] text-white/45">
                  {col.title}
                </h4>
                <ul className="flex flex-col gap-2.5">
                  {col.links.map((link) => (
                    <li key={link.label}>
                      {link.external ? (
                        <a href={link.href} className="text-[13px] text-white/70 transition-colors hover:text-white">
                          {link.label}
                        </a>
                      ) : (
                        <Link href={link.href} className="text-[13px] text-white/70 transition-colors hover:text-white">
                          {link.label}
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-[50px] flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-[22px] text-[12px] text-white/45">
            <span>© 2026 PracticeSync. Built for Indian Chartered Accountants.</span>
            <div className="flex items-center gap-5">
              <Link href="/support" className="hover:text-white">
                Privacy
              </Link>
              <Link href="/support" className="hover:text-white">
                Terms
              </Link>
              <span>Data hosted in India</span>
            </div>
          </div>
        </div>
      </footer>
    </DiagonalSection>
  );
}
