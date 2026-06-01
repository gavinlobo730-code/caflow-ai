"use client";

import { useState, useRef, useEffect } from "react";
import { Sparkles, Bot, Send } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { CopilotMessage } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SUGGESTED_QUERIES: { category: string; queries: string[] }[] = [
  {
    category: "Client Intelligence",
    queries: [
      "Show high-risk clients",
      "Which clients have overdue filings?",
      "Summarize client health scores",
    ],
  },
  {
    category: "Compliance",
    queries: [
      "Which GST filings are overdue?",
      "Show compliance due this week",
      "List all critical compliance records",
    ],
  },
  {
    category: "Documents & Risk",
    queries: [
      "Show documents pending review",
      "List all critical risks",
      "Which clients have AIS mismatches?",
    ],
  },
  {
    category: "Tax Law",
    queries: [
      "Penalty for late GSTR-3B filing?",
      "Explain reverse charge mechanism",
      "TDS rates under section 194C",
    ],
  },
];

const CONTEXT_BUTTONS = [
  { id: "general", label: "General" },
  { id: "compliance", label: "Compliance" },
  { id: "accounting", label: "Accounting" },
  { id: "risk", label: "Risk" },
];

export default function AIAssistantPage() {
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [context, setContext] = useState("general");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return;

    const userMsg: CopilotMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${BASE_URL}/api/ai-copilot/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          conversation_history: messages,
          context,
        }),
      });
      const data = await res.json();
      if (data.success && data.data) {
        const assistantMsg: CopilotMessage = {
          role: "assistant",
          content: data.data.content ?? data.data.message ?? JSON.stringify(data.data),
          suggested_actions: data.data.suggested_actions,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Sorry, I encountered an error. Please try again." },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Network error. Please check your connection and try again." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  return (
    <div className="flex h-[calc(100vh-0px)] overflow-hidden">
      {/* Left panel */}
      <div className="w-72 shrink-0 border-r border-gray-100 bg-white flex flex-col overflow-y-auto">
        <div className="p-4 border-b border-gray-100">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles size={18} className="text-blue-600" />
            <h2 className="font-semibold text-gray-900">AI Copilot</h2>
          </div>
          <Badge variant="outline" className="text-xs text-blue-700 border-blue-200 bg-blue-50">
            Powered by Claude
          </Badge>
        </div>

        {/* Context selector */}
        <div className="p-4 border-b border-gray-100">
          <p className="text-xs text-gray-500 font-medium mb-2 uppercase tracking-wide">Context</p>
          <div className="grid grid-cols-2 gap-1.5">
            {CONTEXT_BUTTONS.map((btn) => (
              <button
                key={btn.id}
                onClick={() => setContext(btn.id)}
                className={`text-xs px-3 py-2 rounded-lg font-medium transition-colors ${
                  context === btn.id
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {btn.label}
              </button>
            ))}
          </div>
        </div>

        {/* Suggested queries */}
        <div className="p-4 space-y-4 flex-1">
          {SUGGESTED_QUERIES.map((group) => (
            <div key={group.category}>
              <p className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-2">
                {group.category}
              </p>
              <div className="space-y-1">
                {group.queries.map((q) => (
                  <button
                    key={q}
                    onClick={() => sendMessage(q)}
                    className="w-full text-left text-xs text-gray-600 px-3 py-2 rounded-lg hover:bg-blue-50 hover:text-blue-700 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex flex-col min-w-0 bg-gray-50">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-14 h-14 rounded-2xl bg-blue-50 flex items-center justify-center mb-4">
                <Sparkles size={28} className="text-blue-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">How can I help?</h3>
              <p className="text-sm text-gray-500 mt-1 max-w-sm">
                Ask me about clients, compliance deadlines, documents, risks, or Indian tax law.
              </p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              {msg.role === "assistant" && (
                <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center mr-2 shrink-0 mt-0.5">
                  <Bot size={14} className="text-blue-700" />
                </div>
              )}
              <div className={`max-w-[70%] ${msg.role === "user" ? "order-1" : ""}`}>
                <div
                  className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                    msg.role === "user"
                      ? "bg-blue-600 text-white rounded-br-sm"
                      : "bg-white text-gray-800 shadow-sm border border-gray-100 rounded-bl-sm"
                  }`}
                >
                  {msg.content}
                </div>
                {msg.role === "assistant" && msg.suggested_actions && msg.suggested_actions.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {msg.suggested_actions.map((action, j) => (
                      <button
                        key={j}
                        onClick={() => sendMessage(action)}
                        className="text-xs px-3 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 transition-colors"
                      >
                        {action}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
                <Bot size={14} className="text-blue-700" />
              </div>
              <div className="bg-white border border-gray-100 shadow-sm rounded-2xl rounded-bl-sm px-4 py-3 text-sm text-gray-500 flex items-center gap-2">
                <span>Analyzing firm data</span>
                <span className="flex gap-0.5">
                  <span className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                </span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="outline" className="text-xs text-blue-700 border-blue-200 bg-blue-50">
              Context: {context}
            </Badge>
          </div>
          <div className="flex gap-3 items-end">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about clients, compliance, risks, or tax law… (Enter to send)"
              rows={2}
              className="flex-1 resize-none text-sm border border-gray-200 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || loading}
              className="p-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
