"use client";

/**
 * Where a person lands when the server says their account is closed (POST-A-482).
 *
 * A platform administrator suspends or deletes a firm, or a Partner removes a person, and the API then refuses that
 * person's requests. `lib/api` signs them out at once and sends them here, so they are not left on a screen that can
 * load nothing with no word why. Public (the "/auth" prefix, lib/auth/public-paths.ts): they are signed out.
 *
 * The reason is in the address (`?why=`) and every sentence is `lib/auth/closedAccount`'s, which blames nobody and
 * names no address, because the product shows no contact until a business mailbox exists.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { FrontDoor } from "@/components/FrontDoor";
import { closedAccountWords } from "@/lib/auth/closedAccount";

export default function AccountClosedPage() {
  const [why, setWhy] = useState<string | null>(null);
  // Read in an effect, never during render: this app is a static export and `window` is not there at build time.
  useEffect(() => {
    setWhy(new URLSearchParams(window.location.search).get("why"));
  }, []);
  const words = closedAccountWords(why);
  return (
    <FrontDoor width="wide">
      <div data-account-closed="" className="text-center space-y-4">
        <h2 className="text-lg font-semibold text-ps-ink">{words.heading}</h2>
        <p className="text-sm text-ps-label">{words.body}</p>
        <Link
          href="/login"
          className="inline-flex items-center justify-center w-full bg-brand text-white text-sm font-medium py-2.5 rounded-lg hover:bg-brand-dark transition-colors"
        >
          Go to sign in
        </Link>
      </div>
    </FrontDoor>
  );
}
