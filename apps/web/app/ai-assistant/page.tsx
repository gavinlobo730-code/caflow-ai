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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[#F1F5F9] shrink-0">
        <Link
          href="/"
          className="text-xs text-[#94A3B8] hover:text-[#475569] transition-colors mr-1"
        >
          &larr; Dashboard
        </Link>
        <div className="h-4 w-px bg-white/[0.08]" />
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-blue-500" />
          <h1 className="text-sm font-semibold text-[#0F172A]">AI Assistant</h1>
        </div>
        <span className="text-xs text-[#94A3B8] hidden sm:block">
          Ask about GST, Income Tax, TDS, and practice management
        </span>
        {messages.length > 0 && (
          <button
            onClick={startNewChat}
            title="Start a new chat (clears this conversation)"
            className="ml-auto flex items-center gap-1.5 text-xs font-medium text-[#64748B] hover:text-[#0F172A] border border-[#E2E8F0] hover:border-[#CBD5E1] rounded-lg px-2.5 py-1.5 transition-colors shrink-0"
          >
            <Plus size={13} />
            New chat
          </button>
        )}
      </div>

      {/* ── Message area ────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-6 py-16">
            <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-50 border border-blue-100">
              <Bot size={28} className="text-blue-500" />
            </div>
            <div>
              <p className="text-sm font-semibold text-[#1E293B] mb-1">
                Ask me anything about Indian tax &amp; compliance
              </p>
              <p className="text-xs text-[#94A3B8]">
                I cite relevant sections of CGST Act and IT Act in every answer.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => sendMessage(prompt)}
                  className="text-left text-xs text-[#475569] bg-[#F8FAFC] hover:bg-blue-50 hover:text-blue-700 border border-[#E2E8F0] hover:border-blue-200 rounded-lg px-4 py-3 transition-colors"
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
                  ? "bg-blue-600 text-white"
                  : "bg-[#F1F5F9] text-[#64748B] border border-[#E2E8F0]"
              }`}
            >
              {msg.role === "user" ? <User size={13} /> : <Bot size={13} />}
            </div>

            {/* Bubble */}
            <div
              className={`max-w-[75%] text-sm rounded-xl px-4 py-3 whitespace-pre-wrap leading-relaxed ${
                msg.role === "user"
                  ? "bg-blue-600 text-white rounded-tr-sm"
                  : "bg-[#F8FAFC] text-[#1E293B] border border-[#F1F5F9] rounded-tl-sm"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="shrink-0 flex items-center justify-center w-7 h-7 rounded-full bg-[#F1F5F9] border border-[#E2E8F0]">
              <Bot size={13} className="text-[#64748B]" />
            </div>
            <div className="bg-[#F8FAFC] border border-[#F1F5F9] rounded-xl rounded-tl-sm px-4 py-3">
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
            <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-2">
              {error}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ───────────────────────────────────────────────────────── */}
      <div className="shrink-0 px-6 py-4 border-t border-[#F1F5F9] bg-white">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about GST, Income Tax, TDS, MCA filings..."
            rows={1}
            disabled={loading}
            className="flex-1 text-sm text-[#0F172A] border border-[#E2E8F0] rounded-xl px-4 py-2.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC] disabled:opacity-60 placeholder:text-[#94A3B8] max-h-32 overflow-y-auto"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading}
            className="flex items-center justify-center w-9 h-9 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            <Send size={15} />
          </button>
        </div>
        <p className="text-center text-xs text-[#CBD5E1] mt-2">
          AI responses are for guidance only &mdash; always apply CA professional judgement before filing.
        </p>
      </div>
    </div>
  );
}
