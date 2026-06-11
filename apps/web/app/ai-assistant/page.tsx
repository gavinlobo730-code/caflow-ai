"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, Sparkles } from "lucide-react";
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

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return;

    const userMessage: Message = { role: "user", content: text.trim() };
    const newHistory = [...messages, userMessage];
    setMessages(newHistory);
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

      setMessages([...newHistory, { role: "assistant", content: reply }]);
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

  return (
    <div className="flex flex-col h-screen max-h-screen bg-[#131620]">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-white/[0.05] shrink-0">
        <Link
          href="/"
          className="text-xs text-white/30 hover:text-white/55 transition-colors mr-1"
        >
          &larr; Dashboard
        </Link>
        <div className="h-4 w-px bg-white/[0.08]" />
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-blue-500" />
          <h1 className="text-sm font-semibold text-white/85">AI Assistant</h1>
        </div>
        <span className="text-xs text-white/30 hidden sm:block">
          Powered by AI &mdash; ask about GST, Income Tax, TDS, and practice management
        </span>
      </div>

      {/* ── Message area ────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-6 py-16">
            <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-50 border border-blue-100">
              <Bot size={28} className="text-blue-500" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white/75 mb-1">
                Ask me anything about Indian tax &amp; compliance
              </p>
              <p className="text-xs text-white/30">
                I cite relevant sections of CGST Act and IT Act in every answer.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => sendMessage(prompt)}
                  className="text-left text-xs text-white/55 bg-[#0e1017] hover:bg-blue-50 hover:text-blue-700 border border-white/[0.07] hover:border-blue-200 rounded-lg px-4 py-3 transition-colors"
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
                  : "bg-white/[0.06] text-white/40 border border-white/[0.07]"
              }`}
            >
              {msg.role === "user" ? <User size={13} /> : <Bot size={13} />}
            </div>

            {/* Bubble */}
            <div
              className={`max-w-[75%] text-sm rounded-xl px-4 py-3 whitespace-pre-wrap leading-relaxed ${
                msg.role === "user"
                  ? "bg-blue-600 text-white rounded-tr-sm"
                  : "bg-[#0e1017] text-white/75 border border-white/[0.05] rounded-tl-sm"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="shrink-0 flex items-center justify-center w-7 h-7 rounded-full bg-white/[0.06] border border-white/[0.07]">
              <Bot size={13} className="text-white/40" />
            </div>
            <div className="bg-[#0e1017] border border-white/[0.05] rounded-xl rounded-tl-sm px-4 py-3">
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
      <div className="shrink-0 px-6 py-4 border-t border-white/[0.05] bg-[#131620]">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about GST, Income Tax, TDS, MCA filings..."
            rows={1}
            disabled={loading}
            className="flex-1 text-sm text-white/85 border border-white/[0.07] rounded-xl px-4 py-2.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#0e1017] disabled:opacity-60 placeholder:text-white/30 max-h-32 overflow-y-auto"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading}
            className="flex items-center justify-center w-9 h-9 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            <Send size={15} />
          </button>
        </div>
        <p className="text-center text-xs text-white/20 mt-2">
          AI responses are for guidance only &mdash; always apply CA professional judgement before filing.
        </p>
      </div>
    </div>
  );
}
