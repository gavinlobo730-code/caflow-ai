"use client";

/**
 * "WHERE IS…?": ASK WHERE SOMETHING IS, AND BE TOLD WITH A BUTTON THAT OPENS IT (POST-A-538, the owner's decision of 21-11-2026).
 *
 * It replaced the guided tips. The owner tried the tips on the live Test Firm and asked for something a person can ASK: a new
 * CA types "where do I record a TDS challan?" and is shown the screen. `lib/guide/whereIs.ts` holds the rules and says what
 * they guarantee; this draws them.
 *
 * WHAT IS ON THE SCREEN IS THE PRODUCT'S OWN WORDS. The server answers with the ids of screens and nothing else, and each
 * answer here is the screen's own name, a sentence saying where it is, and a link. No word of a model's is drawn.
 *
 * BEFORE IT IS SENT the box says who reads the question and that it leaves India (`AiDisclosure`, the one notice every screen
 * that sends to a model shows), and the input points at that sentence, so a screen reader reads it on the way in.
 *
 * WHEN THE AI CANNOT ANSWER (it is not set up, the firm's allowance is used, the rate limit, an outage) the same box does a
 * plain search of the same list and SAYS that it did, with the server's own sentence as the reason. A person is never left
 * with nothing, and never mistakes a word match for an understanding of the question.
 *
 * THREE ANSWERS ARE KEPT APART: screens were found; the AI looked and no screen matches; the AI could not be asked and the
 * plain search found some or none. "No screen matches" is said only by whichever of the two actually looked.
 */
import { useId, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Compass } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { AiDisclosure } from "@/components/ai/AiDisclosure";
import { useAuth, usePermissions } from "@/lib/auth/AuthContext";
import { sectionsOffered, useClientNav } from "@/lib/workspace/ClientNavContext";
import { api } from "@/lib/api";
import { WORKSPACE_CONFIGS } from "@/lib/workspace/workspaceConfig";
import { workspaceTileOffered } from "@/lib/workspace/tileOffered";
import { canAccessWorkspace } from "@/lib/auth/permissions";
import {
  MAX_QUESTION, answersFor, offeredIds, plainSearch, sentenceFor, type GuideAnswer, type Places,
} from "@/lib/guide/whereIs";

type Outcome =
  | { by: "ai"; answers: GuideAnswer[] }
  | { by: "plain"; answers: GuideAnswer[]; reason: string };

/** The ids out of the server's answer, or null when it is not the shape the route sends. */
function idsOf(res: unknown): unknown[] | null {
  const body = res && typeof res === "object" ? (res as { success?: unknown; data?: unknown }) : null;
  const data = body?.success === true && body.data && typeof body.data === "object" ? (body.data as { screens?: unknown }) : null;
  return data && Array.isArray(data.screens) ? data.screens : null;
}

export function WhereIsGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return <GuideDialog onClose={onClose} />;
}

function GuideDialog({ onClose }: { onClose: () => void }) {
  const { userRole } = useAuth();
  const { can, resolved } = usePermissions();
  const { clientId, client } = useClientNav();
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const noticeId = useId();
  const inputId = useId();
  const answers = outcome?.answers ?? [];

  // The open client, when this is a client's workspace and its row has been read; otherwise none.
  const openClient = client && clientId && client.id === clientId ? clientId : null;
  const offered = useMemo(() => {
    const sections = new Set<string>(sectionsOffered(can, resolved).map((s) => s.id));
    return new Set(offeredIds({ role: userRole, can, resolved, clientSectionOffered: (id) => sections.has(id) }));
  }, [userRole, can, resolved]);
  // The areas on this person's firm menu, worked out the way the menu works them out, so the sentence under an answer names
  // the entry they will actually see ("under More, then Accounting"; "under Team" for a Manager).
  const places: Places = useMemo(() => ({
    areas: WORKSPACE_CONFIGS
      .filter((ws) => canAccessWorkspace(ws.id, userRole) && workspaceTileOffered(ws, can, resolved))
      .map((ws) => ws.id),
  }), [userRole, can, resolved]);

  async function ask() {
    const asked = question.trim().slice(0, MAX_QUESTION);
    if (!asked || asking) return;
    setAsking(true);
    setOutcome(null);
    try {
      const ids = idsOf(await api.guide.where(asked, [...offered]));
      if (ids === null) throw new Error("PracticeSync AI answered in a form this screen could not read.");
      setOutcome({ by: "ai", answers: answersFor(ids, offered, openClient, places) });
    } catch (e) {
      const reason = e instanceof Error && e.message ? e.message : "PracticeSync AI could not be reached.";
      setOutcome({ by: "plain", answers: answersFor(plainSearch(asked, offered), offered, openClient, places), reason });
    } finally {
      setAsking(false);
    }
  }

  return (
    <Modal title="Where is…?" onClose={onClose} maxWidthClass="max-w-lg">
      <form
        onSubmit={(e) => { e.preventDefault(); void ask(); }}
        className="space-y-2"
        data-where-is
      >
        <label htmlFor={inputId} className="block text-xs font-medium text-ps-ink">
          What are you looking for?
        </label>
        <div className="flex gap-2">
          <input
            id={inputId}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={MAX_QUESTION}
            placeholder="For example: where do I record a TDS challan?"
            aria-describedby={noticeId}
            autoComplete="off"
            className="min-w-0 flex-1 rounded-lg border border-ps-border px-3 py-2 text-sm text-ps-ink placeholder:text-ps-hint focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          />
          <Button type="submit" disabled={asking || !question.trim()} className="gap-1.5">
            <Compass size={14} />
            {asking ? "Looking…" : "Find it"}
          </Button>
        </div>
        <AiDisclosure surface="guide" id={noticeId} />
      </form>

      <div aria-live="polite" data-where-is-answer={outcome ? outcome.by : asking ? "asking" : "none"}>
        {outcome?.by === "plain" && (
          <p role="status" className="mb-2 rounded-lg border border-state-attention-border bg-state-attention-surface px-3 py-2 text-xs text-state-attention">
            PracticeSync AI could not be asked, so this is a plain search of the screens&apos; names. {outcome.reason}
          </p>
        )}
        {answers.length > 0 && (
          <ul className="space-y-2">
            {answers.map((a) => (
              <li key={a.id} className="flex items-center gap-3 rounded-lg border border-ps-border px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ps-ink">{a.name}</p>
                  <p className="text-xs text-ps-label">{sentenceFor(a)}</p>
                </div>
                {a.href ? (
                  <Link
                    href={a.href}
                    onClick={onClose}
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                  >
                    Open <span className="sr-only">{a.name}</span> <ArrowRight size={12} />
                  </Link>
                ) : (
                  <Link
                    href="/clients/"
                    onClick={onClose}
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-ps-border px-3 py-1.5 text-xs font-medium text-ps-ink hover:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                  >
                    Choose a client <ArrowRight size={12} />
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
        {outcome && answers.length === 0 && (
          <p className="text-sm text-ps-body">
            {outcome.by === "ai"
              ? "No screen in PracticeSync matches that."
              : "The plain search found no screen with those words."}{" "}
            Try the form number or the section, for example 26Q or 43B(h). For a question about tax or law, ask{" "}
            <Link href="/ai-assistant/" onClick={onClose} className="font-medium text-brand underline underline-offset-2">PracticeSync AI</Link>.
          </p>
        )}
      </div>
    </Modal>
  );
}
