import Link from "next/link";
import { Logo } from "./Logo";
import { appLinks, CONTACT } from "@/lib/site";

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
    title: "Resources",
    links: [
      { label: "Guides", href: "/resources" },
      { label: "Compliance calendar", href: "/resources#calendar" },
      { label: "Help centre", href: "/support" },
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

export function SiteFooter() {
  return (
    <footer className="relative overflow-hidden bg-brand-dark text-slate-400">
      <div className="bg-grid absolute inset-0 opacity-60" />
      <div className="relative mx-auto max-w-content px-[clamp(20px,6vw,72px)] py-14">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr_1fr]">
          <div className="max-w-xs">
            <Logo theme="dark" />
            <p className="mt-4 text-[13px] leading-relaxed text-slate-400">
              The AI-first operating system for Indian CA practices — compliance,
              accounting, payroll and clients in one place.
            </p>
          </div>

          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h4 className="text-[12px] font-semibold uppercase tracking-wider text-slate-500">
                {col.title}
              </h4>
              <ul className="mt-4 space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    {link.external ? (
                      <a
                        href={link.href}
                        className="text-[14px] text-slate-400 transition-colors hover:text-white"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        href={link.href}
                        className="text-[14px] text-slate-400 transition-colors hover:text-white"
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-start justify-between gap-4 border-t border-white/10 pt-6 sm:flex-row sm:items-center">
          <p className="text-[13px] text-slate-500">
            © 2026 PracticeSync. Built for Indian Chartered Accountants.
          </p>
          <div className="flex items-center gap-5 text-[13px] text-slate-500">
            <Link href="/support" className="hover:text-white">
              Privacy
            </Link>
            <Link href="/support" className="hover:text-white">
              Terms
            </Link>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Data hosted in India
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
