"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Check, ArrowRight, Lock } from "./icons";
import { CONTACT } from "@/lib/site";

/**
 * The "Book a demo" form.
 *
 * Posts to POST /api/public/demo-request on apps/api, because apps/marketing is
 * a static export with no server of its own to send mail from. An owner
 * decision of 16-09-2026 made a demo the site's primary call to action and
 * ruled out every third-party scheduler — a booking widget is a third party
 * that sees every visitor who reaches the page, whether or not they book.
 *
 * THE FAILURE PATH IS THE POINT. A form that says "thanks" over a request that
 * never arrived loses the lead AND the knowledge that it was lost, which is why
 * the endpoint answers a dropped send with a 503 rather than a cheerful 200 —
 * and why this checks `success` rather than merely `res.ok`. Nothing here
 * reports a send it did not get confirmation of; a failure shows the email
 * address instead, with what the visitor typed still in the fields so they can
 * copy it rather than write it again.
 *
 * The honeypot is a real input, positioned off-screen rather than
 * `display:none` — some bots skip hidden inputs and fill everything else.
 * `tabIndex={-1}` and `aria-hidden` keep it away from keyboard and screen
 * reader users, who are the people a `display:none` would have protected.
 */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Matches routers/demo_request.py::FIRM_SIZES; replaced at runtime by the
 *  server's own list, which is the authority. Kept here only so the select is
 *  populated during the redeploy window and if the options call fails. */
const FALLBACK_SIZES = [
  "Solo practitioner",
  "2–5 people",
  "6–20 people",
  "21–50 people",
  "More than 50",
];

const GENERIC_FAILURE =
  "We couldn't send that just now. Please email us instead and we'll come straight back to you.";

type Status = "idle" | "sending" | "sent" | "failed";

const field =
  "w-full rounded-lg border border-white/15 bg-white/[0.04] px-3.5 py-3 text-[15px] text-white placeholder:text-white/35 outline-none transition-colors focus:border-brand-light/60 focus:bg-white/[0.07]";
const label = "block text-[12px] font-semibold uppercase tracking-[0.14em] text-white/50";

export function DemoForm() {
  const [sizes, setSizes] = useState<string[]>(FALLBACK_SIZES);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/api/public/demo-request/options`)
      .then((r) => r.json())
      .then((res) => {
        const list = res?.data?.firm_sizes;
        if (!cancelled && Array.isArray(list) && list.length) setSizes(list);
      })
      .catch(() => {
        /* the fallback list is already rendered */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (status === "sending") return;
    setStatus("sending");
    setError(null);

    const form = new FormData(e.currentTarget);
    const payload = {
      name: String(form.get("name") ?? "").trim(),
      firm_name: String(form.get("firm_name") ?? "").trim(),
      email: String(form.get("email") ?? "").trim(),
      phone: String(form.get("phone") ?? "").trim() || null,
      firm_size: String(form.get("firm_size") ?? "").trim() || null,
      message: String(form.get("message") ?? "").trim() || null,
      website: String(form.get("website") ?? ""),
    };

    try {
      const res = await fetch(`${API}/api/public/demo-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      // Two shapes are possible and both must be handled: this API's own
      // {success, data, error} envelope, and FastAPI's {detail: …} for a
      // request its validators reject before the handler runs. Reading only
      // `res.ok` would call the first kind of failure a success.
      let body: { success?: boolean; error?: string } | null = null;
      try {
        body = await res.json();
      } catch {
        body = null;
      }
      if (res.ok && body?.success) {
        setStatus("sent");
        return;
      }
      setError(body?.error || GENERIC_FAILURE);
      setStatus("failed");
    } catch {
      // A network error, a CORS refusal, or the API asleep on Render's free
      // tier. The visitor does not need to know which.
      setError(GENERIC_FAILURE);
      setStatus("failed");
    }
  }

  if (status === "sent") {
    return (
      <div className="rounded-2xl border border-brand-light/25 bg-white/[0.05] p-8 text-center">
        <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-brand-light/15 text-brand-light ring-1 ring-white/10">
          <Check size={26} />
        </span>
        <h2 className="mt-5 font-display text-[26px] italic text-white">Thank you.</h2>
        <p className="mt-3 text-[15px] leading-relaxed text-slate-300">
          We have your request and someone from the team will be in touch to arrange a
          time. If it is urgent, email{" "}
          <a
            href={`mailto:${CONTACT.email}`}
            className="font-semibold text-brand-light underline-offset-4 hover:underline"
          >
            {CONTACT.email}
          </a>
          .
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 md:p-8"
      noValidate
    >
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="sm:col-span-1">
          <label className={label} htmlFor="demo-name">
            Your name
          </label>
          <input
            id="demo-name"
            name="name"
            required
            maxLength={120}
            autoComplete="name"
            placeholder="CA Priya Raghavan"
            className={`mt-2 ${field}`}
          />
        </div>
        <div className="sm:col-span-1">
          <label className={label} htmlFor="demo-firm">
            Firm name
          </label>
          <input
            id="demo-firm"
            name="firm_name"
            required
            maxLength={160}
            autoComplete="organization"
            placeholder="Raghavan &amp; Associates"
            className={`mt-2 ${field}`}
          />
        </div>
        <div className="sm:col-span-1">
          <label className={label} htmlFor="demo-email">
            Email
          </label>
          <input
            id="demo-email"
            name="email"
            type="email"
            required
            maxLength={254}
            autoComplete="email"
            placeholder="you@yourfirm.in"
            className={`mt-2 ${field}`}
          />
        </div>
        <div className="sm:col-span-1">
          <label className={label} htmlFor="demo-phone">
            Phone <span className="font-normal normal-case tracking-normal text-white/30">(optional)</span>
          </label>
          <input
            id="demo-phone"
            name="phone"
            type="tel"
            maxLength={32}
            autoComplete="tel"
            placeholder="+91 98765 43210"
            className={`mt-2 ${field}`}
          />
        </div>
        <div className="sm:col-span-2">
          <label className={label} htmlFor="demo-size">
            How big is the practice?
          </label>
          <select id="demo-size" name="firm_size" defaultValue="" className={`mt-2 ${field}`}>
            <option value="" className="bg-brand-dark">
              Select one
            </option>
            {sizes.map((s) => (
              <option key={s} value={s} className="bg-brand-dark">
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label className={label} htmlFor="demo-message">
            What would you like to see?{" "}
            <span className="font-normal normal-case tracking-normal text-white/30">(optional)</span>
          </label>
          <textarea
            id="demo-message"
            name="message"
            rows={4}
            maxLength={2000}
            placeholder="What you run today, what is painful, what you would want to see working."
            className={`mt-2 resize-y ${field}`}
          />
        </div>
      </div>

      {/* Honeypot — off-screen rather than hidden, and out of the tab order. */}
      <div aria-hidden="true" className="absolute left-[-9999px] top-auto h-px w-px overflow-hidden">
        <label htmlFor="demo-website">Leave this empty</label>
        <input id="demo-website" name="website" tabIndex={-1} autoComplete="off" />
      </div>

      {status === "failed" && error ? (
        <div
          role="alert"
          className="mt-6 rounded-xl border border-red-400/30 bg-red-500/[0.08] px-4 py-3.5 text-[14px] leading-relaxed text-red-100"
        >
          {error}{" "}
          <a
            href={`mailto:${CONTACT.email}?subject=${encodeURIComponent("Demo request")}`}
            className="font-semibold text-white underline underline-offset-4"
          >
            {CONTACT.email}
          </a>
          <span className="mt-1.5 block text-red-200/70">
            What you typed is still here — nothing was lost.
          </span>
        </div>
      ) : null}

      <button
        type="submit"
        disabled={status === "sending"}
        className="btn-shine mt-7 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#5876c7] px-7 py-[15px] text-[15px] font-semibold text-white transition-colors hover:bg-[#4d68af] disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
      >
        {status === "sending" ? "Sending…" : "Request a demo"}
        {status === "sending" ? null : <ArrowRight size={16} />}
      </button>

      <p className="mt-5 inline-flex items-center gap-2 text-[12.5px] text-white/40">
        <Lock size={13} />
        We use this to arrange your demo. Nothing else, and no marketing list.
      </p>
    </form>
  );
}
