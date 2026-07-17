"use client";

import { useState } from "react";
import Link from "next/link";
import { Logo } from "./Logo";
import { Magnetic } from "./Cursor";
import { Menu, X, ArrowRight } from "./icons";
import { NAV, appLinks } from "@/lib/site";

// Fixed frosted-light nav, styled to match the homepage's own nav bar exactly
// (same light-grey translucent background, blur, constant height and link
// treatment) so it never visibly changes when navigating between the homepage
// and the inner pages. Deliberately constant — the earlier scroll-condense
// (shrinking height + shadow on scroll) is what made the bar look different
// from the homepage's, so it's gone.
export function SiteHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-transparent bg-[#f3f4f6]/70 backdrop-blur-[10px]">
      <div className="container-ps flex h-[68px] items-center justify-between gap-4">
        <Logo />

        {/* Desktop nav */}
        <nav className="hidden items-center gap-[clamp(14px,2vw,30px)] lg:flex">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-[13px] font-medium text-brand-dark/70 transition-colors hover:text-brand-dark"
            >
              {item.label}
            </Link>
          ))}
          <Link
            href="/access"
            className="text-[13px] font-medium text-brand-dark/70 transition-colors hover:text-brand-dark"
          >
            Login
          </Link>
          <Magnetic max={10}>
            <a
              href={appLinks.signup}
              className="inline-flex items-center gap-1.5 rounded-md bg-[#4f71cc] px-[18px] py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-[#4463bd]"
            >
              Start free trial
              <ArrowRight size={14} />
            </a>
          </Magnetic>
        </nav>

        {/* Mobile toggle */}
        <button
          onClick={() => setOpen((v) => !v)}
          className="rounded-lg p-2 text-brand hover:bg-black/[0.04] lg:hidden"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {/* Mobile panel */}
      {open && (
        <div className="border-t border-black/[0.06] bg-[#f3f4f6]/95 backdrop-blur-[10px] lg:hidden">
          <div className="container-ps flex flex-col gap-1 py-4">
            {NAV.map((item, i) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="fade-up rounded-lg px-3 py-2.5 text-[15px] font-medium text-brand-dark/80 hover:bg-black/[0.04]"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                {item.label}
              </Link>
            ))}
            <div className="mt-2 flex flex-col gap-2 border-t border-black/[0.06] pt-4">
              <Link
                href="/access"
                onClick={() => setOpen(false)}
                className="rounded-lg border border-black/10 px-4 py-2.5 text-center text-[15px] font-semibold text-brand"
              >
                Login
              </Link>
              <a
                href={appLinks.signup}
                className="rounded-lg bg-[#4f71cc] px-4 py-2.5 text-center text-[15px] font-semibold text-white"
              >
                Start free trial
              </a>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
