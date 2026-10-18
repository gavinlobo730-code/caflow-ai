"use client";

/** A Partner asks for a member's lost authenticator to be reset (POST-A-006). A different Partner approves it under
 *  Approvals (the firm's only Partner, themself); the server refuses in words when there is nobody who could. */
import Link from "next/link";
import { Modal } from "@/components/ui/modal";
import AuthenticatorResetRequest from "@/components/auth/AuthenticatorResetRequest";

export default function ResetAuthenticatorModal({
  member, onClose,
}: {
  member: { id: string; full_name: string; email: string };
  onClose: () => void;
}) {
  return (
    <Modal
      title="Reset authenticator app"
      note={`${member.full_name} · ${member.email}`}
      onClose={onClose}
      maxWidthClass="max-w-md"
    >
      <p className="text-xs text-ps-label">
        This removes their authenticator app. The next time they sign in they use their password and are asked to set up a new
        app; a sign-in they already have open may carry on until it expires. A Partner other than you approves it first; if
        you are the firm&apos;s only Partner, you approve it yourself.
      </p>
      <AuthenticatorResetRequest
        target={{ kind: "member", userId: member.id }}
        sentMessage={
          <>
            Request sent. It is decided under{" "}
            <Link href="/approvals" className="underline">Approvals</Link>, by a Partner other than you (or by you, if you
            are the firm&apos;s only Partner); until then nothing changes for {member.full_name}.
          </>
        }
      />
    </Modal>
  );
}
