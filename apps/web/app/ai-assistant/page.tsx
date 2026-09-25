"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, Sparkles, Plus } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const SUGGESTED_PROMPTS = [
  "What are the GSTR-1 filing deadlines?",
  "Explain Section 194C TDS rates",
  "What documents are needed for ITR-3?",
  "How to reconcile GSTR-2B with purchase register?",
];

// Chat history is kept ONLY in this browser (localStorage) — it is never sent to
// or stored on our servers, since conversations can contain client PII/financials.
// It auto-expires 24h after the last message; "New chat" clears it immediately.
const HISTORY_KEY = "ps-ai-assistant-history-v1";
const HISTORY_TTL_MS = 24 * 60 * 60 * 1000; // 1 day

/**
 * ⚠️ THE CLIENT IS CHOSEN PER CONVERSATION AND IS NOT REMEMBERED.
 * Unlike the chat history above, the chosen client is NOT persisted: a CA who
 * comes back tomorrow to ask a general question should not silently be sending
 * yesterday's client's figures to Groq. It resets to "no client" on every load,
 * which is the direction that cannot leak by omission.
 */
const NO_CLIENT = "";

function isValidMessage(m: unknown): m is Message {
  if (!m || typeof m !== "object") return false;
  const role = (m as Message).role;
  const content = (m as Message).content;
  return (role === "user" || role === "assistant") && typeof content === "string";
}

function loadHistory(): Message[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { savedAt?: number; messages?: unknown };
    if (!parsed?.savedAt || Date.now() - parsed.savedAt > HISTORY_TTL_MS) {
      window.localStorage.removeItem(HISTORY_KEY); // expired — purge
      return [];
    }
    return Array.isArray(parsed.messages)
      ? (parsed.messages.filter(isValidMessage) as Message[])
      : [];
  } catch {
    try {
      window.localStorage.removeItem(HISTORY_KEY);
    } catch {
      /* ignore */
    }
    return [];
  }
}

function saveHistory(messages: Message[]) {
  if (typeof window === "undefined") return;
  try {
    if (messages.length === 0) {
      window.localStorage.removeItem(HISTORY_KEY);
    } else {
      window.localStorage.setItem(
        HISTORY_KEY,
        JSON.stringify({ savedAt: Date.now(), messages })
      );
    }
  } catch {
    /* storage full or blocked — non-fatal, history just won't persist */
  }
}

export default function AIAssistantPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [clients, setClients] = useState<{ id: string; client_name?: string }[]>([]);
  const [clientId, setClientId] = useState<string>(NO_CLIENT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.clients
      .list()
      .then((res) => {
        if (!live) return;
        // `arrayOrEmpty`'s job done inline — the picker degrades to "no client",
        // which is the safe state, so a failed list must not blank the screen.
        const rows = (res as { data?: { clients?: unknown } } | null)?.data?.clients;
        setClients(Array.isArray(rows) ? (rows as { id: string; client_name?: string }[]) : []);
      })
      .catch(() => live && setClients([]));
    return () => {
      live = false;
    };
  }, []);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Restore any conversation saved in this browser (auto-purged after 24h).
  useEffect(() => {
    const saved = loadHistory();
    if (saved.length > 0) setMessages(saved);
  }, []);

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return;

    const userMessage: Message = { role: "user", content: text.trim() };
    const newHistory = [...messages, userMessage];
    setMessages(newHistory);
    saveHistory(newHistory);
    setInput("");
    setError(null);
    setLoading(true);

    try {
      const json = await api.assistant.ask({
        question: text.trim(),
        conversation_history: messages.map((m) => ({ role: m.role, content: m.content })),
        // Omitted entirely when no client is chosen, rather than sent empty:
        // the server branches on truthiness and an empty string would take the
        // scoped path with nothing to scope.
        ...(clientId ? { client_id: clientId } : {}),
      }) as { success: boolean; data: { answer?: string; reply?: string } | null; error: string | null };

      if (!json.success || !json.data) {
        throw new Error(json.error ?? "Request failed");
      }

      // FastAPI backend returns `answer`; fallback to `reply` for compatibility
      const reply: string = json.data.answer ?? json.data.reply ?? "";
      if (!reply) throw new Error("Empty response from AI service");

      const finalHistory: Message[] = [...newHistory, { role: "assistant", content: reply }];
      setMessages(finalHistory);
      saveHistory(finalHistory);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  function startNewChat() {
    setMessages([]);
    setInput("");
    setError(null);
    saveHistory([]); // clears the saved copy in this browser too
    textareaRef.current?.focus();
  }

  return (
    <div className="flex flex-col h-screen max-h-screen bg-white">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-ps-muted shrink-0">
        <Link
          href="/"
          className="text-xs text-ps-hint hover:text-ps-label transition-colors mr-1"
        >
          &larr; Dashboard
        </Link>
        <div className="h-4 w-px bg-white/[0.08]" />
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-blue-500" />
          <h1 className="text-sm font-semibold text-ps-ink">AI Assistant</h1>
        </div>
        <span className="text-xs text-ps-hint hidden lg:block">
          Ask about GST, Income Tax, TDS, and practice management
        </span>
        {clients.length > 0 && (
          <label className="flex items-center gap-1.5 text-xs text-ps-hint shrink-0">
            <span className="hidden sm:inline">About</span>
            <select
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="text-xs border border-ps-border rounded-lg px-2 py-1 bg-white text-ps-body outline-none focus:border-brand max-w-[14rem]"
            >
              <option value={NO_CLIENT}>No client — general question</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>{c.client_name ?? c.id}</option>
              ))}
            </select>
          </label>
        )}
        {messages.length > 0 && (
          <button
            onClick={startNewChat}
            title="Start a new chat (clears this conversation)"
            className="ml-auto flex items-center gap-1.5 text-xs font-medium text-ps-label hover:text-ps-ink border border-ps-border hover:border-ps-border-strong rounded-lg px-2.5 py-1.5 transition-colors shrink-0"
          >
            <Plus size={13} />
            New chat
          </button>
        )}
      </div>

      {/* ⚠️ THE CA IS TOLD WHAT LEAVES THE BUILDING. The note above about chat
          history says it never reaches our servers; choosing a client changes
          what is sent to the MODEL, which is a different fact and one the
          person doing it is entitled to know before they do it. It says WHAT
          goes (the hub's outstanding-work figures) and, as importantly, what
          does not. */}
      {clientId && (
        <div className="px-6 py-2 border-b border-ps-muted bg-ps-bg shrink-0">
          <p className="text-3xs text-ps-hint">
            Answers for this client are given the figures the hub computes —
            how much is outstanding in each module. No document, no ledger
            line, no employee record and no GSTIN or PAN is sent.
          </p>
        </div>
      )}

      {/* ── Message area ────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-6 py-16">
            <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-50 border border-blue-100">
              <Bot size={28} className="text-blue-500" />
            </div>
            <div>
              <p className="text-sm font-semibold text-ps-ink mb-1">
                Ask me anything about Indian tax &amp; compliance
              </p>
              <p className="text-xs text-ps-hint">
                I cite relevant sections of CGST Act and IT Act in every answer.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button disabled={loading}
                  key={prompt}
                  onClick={() => sendMessage(prompt)}
                  className="disabled:opacity-40 text-left text-xs text-ps-label bg-ps-bg hover:bg-blue-50 hover:text-blue-700 border border-ps-border hover:border-blue-200 rounded-lg px-4 py-3 transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}
          >
            {/* Avatar */}
            <div
              className={`shrink-0 flex items-center justify-center w-7 h-7 rounded-full mt-0.5 ${
                msg.role === "user"
                  ? "bg-brand text-white"
                  : "bg-ps-muted text-ps-label border border-ps-border"
              }`}
            >
              {msg.role === "user" ? <User size={13} /> : <Bot size={13} />}
            </div>

            {/* Bubble */}
            <div
              className={`max-w-[75%] text-sm rounded-xl px-4 py-3 whitespace-pre-wrap leading-relaxed ${
                msg.role === "user"
                  ? "bg-brand text-white rounded-tr-sm"
                  : "bg-ps-bg text-ps-ink border border-ps-muted rounded-tl-sm"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="shrink-0 flex items-center justify-center w-7 h-7 rounded-full bg-ps-muted border border-ps-border">
              <Bot size={13} className="text-ps-label" />
            </div>
            <div className="bg-ps-bg border border-ps-muted rounded-xl rounded-tl-sm px-4 py-3">
              <div className="flex gap-1 items-center h-4">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="flex justify-center">
            <div className="text-xs text-red-600 bg-state-problem-surface border border-red-100 rounded-lg px-4 py-2">
              {error}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ───────────────────────────────────────────────────────── */}
      <div className="shrink-0 px-6 py-4 border-t border-ps-muted bg-white">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about GST, Income Tax, TDS, MCA filings..."
            rows={1}
            disabled={loading}
            className="flex-1 text-sm text-ps-ink border border-ps-border rounded-xl px-4 py-2.5 resize-none focus:outline-none focus:ring-2 focus:ring-brand bg-ps-bg disabled:opacity-60 placeholder:text-ps-hint max-h-32 overflow-y-auto"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading}
            className="flex items-center justify-center w-9 h-9 bg-brand text-white rounded-xl hover:bg-brand-dark transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            <Send size={15} />
          </button>
        </div>
        <p className="text-center text-xs text-ps-disabled mt-2">
          AI responses are for guidance only &mdash; always apply CA professional judgement before filing.
        </p>
      </div>
    </div>
  );
}
