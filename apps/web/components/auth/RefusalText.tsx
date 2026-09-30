"use client";

import Link from "next/link";
import {
  MFA_SETUP_HREF,
  MFA_SETUP_LEAD,
  MFA_SETUP_PLACE,
  isMfaRefusal,
} from "@/lib/auth/mfaRefusal";

/** A refusal as text, with the MFA one turned into a way to fix it.
 *  lib/api has already translated the backend's sentence; this adds the link
 *  where a screen can render one. Anything else renders as written. */
export function RefusalText({ message }: { message: string }) {
  if (!isMfaRefusal(message)) return <>{message}</>;
  return (
    <>
      {MFA_SETUP_LEAD} —{" "}
      <Link href={MFA_SETUP_HREF} className="font-medium underline underline-offset-2">
        {MFA_SETUP_PLACE}
      </Link>
    </>
  );
}
