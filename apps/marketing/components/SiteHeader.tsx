"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Logo } from "./Logo";
import { Menu, X, ArrowRight } from "./icons";
import { NAV, appLinks } from "@/lib/site";

export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  // Header condenses and gains depth once the page scrolls.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`sticky top-0 z-50 border-b transition-all duration-500 ${
        scrolled
          ? "border-ps-border/80 bg-white/90 shadow-[0_8px_30px_rgba(24,35,80,0.08)] backdrop-blur-xl"
          : "border-transparent bg-white/70 backdrop-blur-md"
      }`}
    >
      <div
        className={`container-ps flex items-center justify-between gap-4 transition-all duration-500 ${
          scrolled ? "h-14" : "h-[72px]"
        }`}
      >
        <Logo />

        {/* Desktop nav */}
        <nav className="hidden items-center gap-7 lg:flex">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="group relative text-[14px] font-medium text-slate-600 transition-colors hover:text-brand"
            >
              {item.label}
              <span className="absolute -bottom-1 left-0 h-px w-0 bg-brand transition-all duration-300 group-hover:w-full" />
            </Link>
          ))}
        </nav>

        {/* Desktop actions */}
        <div className="hidden items-center gap-2 lg:flex">
          <Link
            href="/access"
            className="rounded-lg px-4 py-2 text-[14px] font-semibold text-brand transition-colors hover:bg-ps-muted"
          >
            Login
          </Link>
          <a
            href={appLinks.signup}
            className="btn-shine inline-flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-[14px] font-semibold text-white shadow-sm transition-all duration-300 hover:bg-brand-hover hover:shadow-[0_6px_20px_rgba(24,35,80,0.25)]"
          >
            Start free trial
            <ArrowRight size={15} />
          </a>
        </div>

        {/* Mobile toggle */}
        <button
          onClick={() => setOpen((v) => !v)}
          className="rounded-lg p-2 text-brand hover:bg-ps-muted lg:hidden"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {/* Mobile panel */}
      {open && (
        <div className="border-t border-ps-border bg-white lg:hidden">
          <div className="container-ps flex flex-col gap-1 py-4">
            {NAV.map((item, i) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="fade-up rounded-lg px-3 py-2.5 text-[15px] font-medium text-slate-700 hover:bg-ps-muted"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                {item.label}
              </Link>
            ))}
            <div className="mt-2 flex flex-col gap-2 border-t border-ps-border pt-4">
              <Link
                href="/access"
                onClick={() => setOpen(false)}
                className="rounded-lg border border-ps-border px-4 py-2.5 text-center text-[15px] font-semibold text-brand"
              >
                Login
              </Link>
              <a
                href={appLinks.signup}
                className="rounded-lg bg-brand px-4 py-2.5 text-center text-[15px] font-semibold text-white"
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
