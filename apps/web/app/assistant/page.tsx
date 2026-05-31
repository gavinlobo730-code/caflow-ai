"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import axios from "axios";

interface Message {
  role: "user" | "assistant";
  content: string;
  source?: string;
}

const SUGGESTED_QUESTIONS = [
  "What is the due date for GSTR-3B?",
  "Can I claim ITC on motor vehicle purchase?",
  "What is the penalty for late GST filing?",
  "What is the turnover limit for GST registration?",
  "How is reverse charge mechanism applied?",
];

export default function AssistantPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (question: string) => {
    if (!question.trim() || loading) return;
    const userMsg: Message = { role: "user", content: question };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }));
      const res = await axios.post("http://localhost:8000/api/assistant", {
        question,
        conversation_history: history,
      });
      const { answer, source } = res.data.data;
      setMessages((prev) => [...prev, { role: "assistant", content: answer, source }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Unable to reach the assistant. Please ensure the backend server is running at localhost:8000.",
          source: "",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full p-6 max-w-3xl mx-auto">
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-gray-900">GST Knowledge Assistant</h1>
        <p className="text-gray-500 text-sm mt-1">Ask anything about GST, ITR, or compliance</p>
      </div>

      {messages.length === 0 && (
        <div className="mb-4">
          <p className="text-xs text-gray-500 uppercase tracking-wide font-semibold mb-2">Suggested Questions</p>
          <div className="flex flex-wrap gap-2">
            {SUGGESTED_QUESTIONS.map((q) => (
              <button
                key={q}
                onClick={() => sendMessage(q)}
                className="px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-full text-gray-700 hover:border-blue-400 hover:text-blue-700 transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <Card className="flex-1 overflow-auto p-4 space-y-4 bg-gray-50 mb-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 py-12">
            <Bot size={40} className="mx-auto mb-3 opacity-40" />
            <p className="text-sm">Ask a question to get started</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "assistant" && (
              <div className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center shrink-0">
                <Bot size={16} />
              </div>
            )}
            <div className={`max-w-[80%] ${msg.role === "user" ? "items-end" : "items-start"} flex flex-col gap-1`}>
              <div
                className={`px-4 py-3 rounded-2xl text-sm ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : "bg-white text-gray-800 border border-gray-100 rounded-bl-sm"
                }`}
              >
                {msg.content}
              </div>
              {msg.source && (
                <Badge variant="outline" className="text-xs text-blue-700 border-blue-200 bg-blue-50">
                  {msg.source}
                </Badge>
              )}
            </div>
            {msg.role === "user" && (
              <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-600 flex items-center justify-center shrink-0">
                <User size={16} />
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center shrink-0">
              <Bot size={16} />
            </div>
            <div className="bg-white border border-gray-100 rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </Card>

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
          placeholder="Ask anything about GST, ITR, or compliance..."
          className="flex-1 px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
          disabled={loading}
        />
        <button
          onClick={() => sendMessage(input)}
          disabled={loading || !input.trim()}
          className="px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
