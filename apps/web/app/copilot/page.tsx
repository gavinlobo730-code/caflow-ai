"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import {
  Send, Plus, Sparkles, ThumbsUp, ThumbsDown,
  BarChart2, Users, Shield, Zap, GitBranch, RefreshCw,
  MessageSquare, Clock, Star,
} from "lucide-react";
import { api } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Conversation {
  id: string;
  title: string;
  context_type: string;
  message_count: number;
  last_message_at?: string;
  is_archived: boolean;
  created_at: string;
}

interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  tokens_used?: number;
  feedback_rating?: number;
  created_at: string;
}

interface Recommendation {
  id: string;
  recommendation_type: string;
  priority: string;
  title: string;
  description: string;
  rationale?: string;
  action_label?: string;
  status: string;
  client_name?: string;
  created_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const CONTEXT_ICONS: Record<string, JSX.Element> = {
  global: <Sparkles size={14} />,
  client: <Users size={14} />,
  compliance: <Shield size={14} />,
  workflow: <Zap size={14} />,
  executive: <BarChart2 size={14} />,
  relationship: <GitBranch size={14} />,
};

const PRIORITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-700 border-red-200",
  high:     "bg-orange-100 text-orange-700 border-orange-200",
  medium:   "bg-amber-100 text-amber-700 border-amber-200",
  low:      "bg-gray-100 text-gray-600 border-gray-200",
};

const REC_TYPE_LABELS: Record<string, string> = {
  risk: "Risk", opportunity: "Opportunity", compliance: "Compliance",
  workflow: "Workflow", relationship: "Relationship", health: "Health",
};

function fmtTime(s: string) {
  const d = new Date(s);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg, onRate }: { msg: Message; onRate: (id: string, rating: number) => void }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mr-2 mt-1"
          style={{ backgroundColor: "#182350" }}>
          <Sparkles size={13} className="text-white" />
        </div>
      )}
      <div className={`max-w-[85%] ${isUser ? "order-first" : ""}`}>
        <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-brand text-white rounded-tr-sm"
            : "bg-white border border-ps-border text-ps-ink rounded-tl-sm shadow-sm"
        }`}>
          {msg.content.split("\n").map((line, i) => (
            <p key={i} className={line.startsWith("##") ? "font-semibold mt-2" : line.startsWith("- ") ? "pl-3" : ""}>{
              line.startsWith("## ") ? line.replace("## ", "") : line
            }</p>
          ))}
        </div>
        {!isUser && (
          <div className="flex items-center gap-2 mt-1.5 px-1">
            <span className="text-3xs text-ps-hint">{fmtTime(msg.created_at)}</span>
            {msg.tokens_used && (
              <span className="text-3xs text-ps-disabled">{msg.tokens_used} tokens</span>
            )}
            <div className="flex gap-1 ml-auto">
              <button
                onClick={() => onRate(msg.id, 5)}
                className={`p-1 rounded hover:bg-green-50 transition-colors ${msg.feedback_rating === 5 ? "text-green-600" : "text-ps-disabled hover:text-green-500"}`}
              >
                <ThumbsUp size={11} />
              </button>
              <button
                onClick={() => onRate(msg.id, 1)}
                className={`p-1 rounded hover:bg-red-50 transition-colors ${msg.feedback_rating === 1 ? "text-red-500" : "text-ps-disabled hover:text-red-400"}`}
              >
                <ThumbsDown size={11} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CopilotPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [contextType, setContextType] = useState("global");
  const [tab, setTab] = useState<"chat" | "recommendations">("chat");
  const [actingRec, setActingRec] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Distinguish "fetch failed" from "genuinely none yet" — a masked failure
  // here used to render as "No conversations yet" / "All insights have been
  // actioned", the worst version of this bug class (an active false-positive
  // congratulatory message, not just an empty list).
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [recommendationsError, setRecommendationsError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  // This row's request is in flight. These handlers had no loading state at
  // all, so the button was never disabled and a second click sent it again.
  const [rowBusy, setRowBusy] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = rowBusy || sending;

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });

  const loadConversations = useCallback(async () => {
    try {
      const res = (await api.copilotV2.listConversations()) as { data: { conversations: Conversation[] } };
      setConversations(res.data?.conversations || []);
      setConversationsError(null);
    } catch (e) {
      setConversations([]);
      setConversationsError(e instanceof Error ? e.message : "Couldn't load conversations.");
    }
  }, []);

  const loadRecommendations = useCallback(async () => {
    try {
      const res = (await api.copilotV2.listRecommendations({ status: "pending" })) as { data: { recommendations: Recommendation[] } };
      setRecommendations(res.data?.recommendations || []);
      setRecommendationsError(null);
    } catch (e) {
      setRecommendations([]);
      setRecommendationsError(e instanceof Error ? e.message : "Couldn't load recommendations.");
    }
  }, []);

  const loadSuggestions = useCallback(async () => {
    try {
      const res = (await api.copilotV2.suggestions(contextType)) as { data: { suggestions: string[] } };
      setSuggestions(res.data?.suggestions || []);
    } catch {}
  }, [contextType]);

  useEffect(() => {
    loadConversations();
    loadRecommendations();
    loadSuggestions();
  }, [loadConversations, loadRecommendations, loadSuggestions]);

  useEffect(() => { scrollToBottom(); }, [messages]);

  const openConversation = async (convId: string) => {
    setRowBusy(true);
    try {
    setActiveConv(convId);
    try {
      const res = (await api.copilotV2.getConversation(convId)) as { data: Conversation & { messages: Message[] } };
      setMessages(res.data?.messages || []);
      setChatError(null);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : "Couldn't open conversation.");
    }
  } finally { setRowBusy(false); }
  };

  const newConversation = async () => {
    setRowBusy(true);
    try {
    try {
      const res = (await api.copilotV2.createConversation({ context_type: contextType })) as { data: Conversation };
      const conv = res.data;
      setConversations((prev: Conversation[]) => [conv, ...prev]);
      setActiveConv(conv.id);
      setMessages([]);
      setChatError(null);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : "Couldn't start a new conversation.");
    }
  } finally { setRowBusy(false); }
  };

  const sendMessage = async (content?: string) => {
    const text = content || input.trim();
    if (!text || sending) return;

    let convId = activeConv;
    if (!convId) {
      const res = (await api.copilotV2.createConversation({ context_type: contextType })) as { data: Conversation };
      convId = res.data.id;
      setConversations((prev: Conversation[]) => [res.data, ...prev]);
      setActiveConv(convId);
    }

    const optimistic: Message = {
      id: `opt-${Date.now()}`,
      conversation_id: convId!,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev: Message[]) => [...prev, optimistic]);
    setInput("");
    setSending(true);

    try {
      const res = (await api.copilotV2.sendMessage(convId!, { content: text, context_type: contextType })) as { data: { message: Message; suggested_questions: string[] } };
      const { message: assistantMsg, suggested_questions } = res.data;
      setMessages((prev: Message[]) => [...prev.filter((m: Message) => m.id !== optimistic.id), optimistic, assistantMsg]);
      if (suggested_questions?.length) setSuggestions(suggested_questions);
      setChatError(null);
      loadConversations();
    } catch (e) {
      setMessages((prev: Message[]) => prev.filter((m: Message) => m.id !== optimistic.id));
      setInput(text);
      setChatError(e instanceof Error ? e.message : "Couldn't send message.");
    } finally {
      setSending(false);
    }
  };

  const rateMessage = async (messageId: string, rating: number) => {
    setMessages((prev: Message[]) => prev.map((m: Message) => m.id === messageId ? { ...m, feedback_rating: rating } : m));
    try {
      await api.copilotV2.rateMessage(messageId, { rating });
    } catch {}
  };

  const actOnRecommendation = async (recId: string, action: "accept" | "dismiss" | "snooze") => {
    setActingRec(recId);
    try {
      await api.copilotV2.actRecommendation(recId, { action });
      setRecommendations((prev: Recommendation[]) => prev.filter((r: Recommendation) => r.id !== recId));
    } finally {
      setActingRec(null);
    }
  };

  return (
    <div className="h-screen flex flex-col bg-ps-bg">
      {/* Header */}
      <div className="bg-white border-b border-ps-border px-6 py-4 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: "#182350" }}>
              <Sparkles size={16} className="text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-brand">AI Copilot</h1>
              <p className="text-xs text-ps-label">Intelligent assistant for your CA practice</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Context type selector */}
            <select
              value={contextType}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setContextType(e.target.value)}
              className="text-xs px-3 py-1.5 border border-ps-border rounded-lg bg-white text-ps-label"
            >
              <option value="global">Global</option>
              <option value="compliance">Compliance</option>
              <option value="workflow">Workflows</option>
              <option value="executive">Executive</option>
              <option value="relationship">Relationships</option>
            </select>
            <div className="flex gap-1 border border-ps-border rounded-lg p-0.5 bg-white">
              <button
                onClick={() => setTab("chat")}
                className={`px-3 py-1.5 text-xs rounded-md font-medium transition-colors ${tab === "chat" ? "bg-brand text-white" : "text-ps-label hover:text-ps-body"}`}
              >
                Chat
              </button>
              <button
                onClick={() => setTab("recommendations")}
                className={`px-3 py-1.5 text-xs rounded-md font-medium transition-colors relative ${tab === "recommendations" ? "bg-brand text-white" : "text-ps-label hover:text-ps-body"}`}
              >
                Insights
                {recommendations.length > 0 && (
                  <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-[9px] rounded-full flex items-center justify-center font-bold">
                    {recommendations.length > 9 ? "9+" : recommendations.length}
                  </span>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">

        {/* Sidebar — conversation history */}
        <div className="w-64 bg-white border-r border-ps-border flex flex-col flex-shrink-0">
          <div className="p-3 border-b border-ps-muted">
            <button disabled={actionInFlight}
              onClick={newConversation}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg text-white transition-colors"
              style={{ backgroundColor: "#182350" }}
            >
              <Plus size={14} />
              New Conversation
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {conversationsError ? (
              <div className="text-center py-6 space-y-2">
                <p className="text-xs text-red-600 font-medium px-2">{conversationsError}</p>
                <button onClick={loadConversations} className="text-2xs px-2.5 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-body">Retry</button>
              </div>
            ) : conversations.length === 0 ? (
              <p className="text-xs text-ps-hint text-center py-6">No conversations yet</p>
            ) : (
              conversations.map((conv: Conversation) => (
                <button disabled={actionInFlight}
                  key={conv.id}
                  onClick={() => openConversation(conv.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors ${
                    activeConv === conv.id
                      ? "bg-[#EFF6FF] text-brand"
                      : "hover:bg-ps-bg text-ps-body"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 text-ps-hint flex-shrink-0">
                      {CONTEXT_ICONS[conv.context_type] || <MessageSquare size={14} />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium line-clamp-2">{conv.title}</p>
                      <div className="flex items-center gap-1 mt-0.5">
                        <Clock size={9} className="text-ps-disabled" />
                        <span className="text-3xs text-ps-disabled">
                          {conv.last_message_at ? fmtTime(conv.last_message_at) : "new"}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {tab === "chat" && (
            <>
              {/* Messages area */}
              <div className="flex-1 overflow-y-auto px-6 py-4">
                {messages.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-center">
                    <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4"
                      style={{ backgroundColor: "#EFF6FF" }}>
                      <Sparkles size={28} style={{ color: "#182350" }} />
                    </div>
                    <h2 className="text-lg font-semibold text-brand mb-1">Ask your Copilot</h2>
                    <p className="text-sm text-ps-label mb-6 max-w-sm">
                      Get instant answers about clients, compliance, GST, TDS, and more.
                    </p>
                    <div className="grid grid-cols-2 gap-2 max-w-lg">
                      {suggestions.slice(0, 6).map((q: string, i: number) => (
                        <button disabled={actionInFlight}
                          key={i}
                          onClick={() => sendMessage(q)}
                          className="text-left text-xs px-3 py-2.5 rounded-xl border border-ps-border bg-white hover:border-brand-light hover:bg-[#EFF6FF] text-ps-label transition-colors"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="max-w-3xl mx-auto">
                    {messages.map((msg: Message) => (
                      <MessageBubble key={msg.id} msg={msg} onRate={(id, rating) => { void rateMessage(id, rating); }} />
                    ))}
                    {sending && (
                      <div className="flex justify-start mb-4">
                        <div className="w-7 h-7 rounded-full flex items-center justify-center mr-2 flex-shrink-0"
                          style={{ backgroundColor: "#182350" }}>
                          <Sparkles size={13} className="text-white" />
                        </div>
                        <div className="bg-white border border-ps-border rounded-2xl rounded-tl-sm px-4 py-3">
                          <div className="flex gap-1">
                            {[0,1,2].map(i => (
                              <div key={i} className="w-2 h-2 rounded-full bg-brand-light animate-bounce"
                                style={{ animationDelay: `${i * 150}ms` }} />
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                )}
              </div>

              {/* Suggested questions (contextual) */}
              {messages.length > 0 && suggestions.length > 0 && (
                <div className="px-6 py-2 border-t border-ps-muted bg-white">
                  <div className="flex gap-2 overflow-x-auto pb-1 max-w-3xl mx-auto">
                    {suggestions.slice(0,4).map((q: string, i: number) => (
                      <button disabled={actionInFlight}
                        key={i}
                        onClick={() => sendMessage(q)}
                        className="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg border border-ps-border bg-ps-bg hover:bg-[#EFF6FF] hover:border-brand-light text-ps-label transition-colors whitespace-nowrap"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Input */}
              <div className="px-6 py-4 border-t border-ps-border bg-white flex-shrink-0">
                {chatError && (
                  <div role="alert" className="max-w-3xl mx-auto mb-2 flex items-center justify-between gap-3 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                    <p className="text-xs text-red-700">{chatError}</p>
                    <button onClick={() => setChatError(null)} className="text-red-400 hover:text-red-600 shrink-0">✕</button>
                  </div>
                )}
                <div className="max-w-3xl mx-auto flex items-end gap-3">
                  <div className="flex-1 relative">
                    <textarea
                      value={input}
                      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInput(e.target.value)}
                      onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                      placeholder="Ask anything about your clients, compliance, GST, TDS..."
                      rows={1}
                      className="w-full px-4 py-3 text-sm border border-ps-border rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand-light leading-relaxed"
                      style={{ minHeight: "48px", maxHeight: "140px" }}
                    />
                  </div>
                  <button
                    onClick={() => sendMessage()}
                    disabled={actionInFlight || !input.trim()}
                    className="flex-shrink-0 w-11 h-11 rounded-xl flex items-center justify-center disabled:opacity-40 transition-all"
                    style={{ backgroundColor: input.trim() ? "#182350" : "#E2E8F0" }}
                  >
                    <Send size={15} className={input.trim() ? "text-white" : "text-ps-hint"} />
                  </button>
                </div>
                <p className="text-center text-3xs text-ps-disabled mt-2">
                  AI responses are advisory — always verify with source documents. Never auto-submit to government portals.
                </p>
              </div>
            </>
          )}

          {tab === "recommendations" && (
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <div className="max-w-2xl mx-auto">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-semibold text-brand">AI Recommendations</h2>
                  <button onClick={loadRecommendations} className="text-xs text-ps-label flex items-center gap-1 hover:text-brand">
                    <RefreshCw size={12} /> Refresh
                  </button>
                </div>

                {recommendationsError ? (
                  <div className="text-center py-16">
                    <Star size={40} className="mx-auto text-red-300 mb-3" />
                    <p className="text-sm text-red-600 font-medium">{recommendationsError}</p>
                    <button onClick={loadRecommendations} className="mt-3 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">Retry</button>
                  </div>
                ) : recommendations.length === 0 ? (
                  <div className="text-center py-16">
                    <Star size={40} className="mx-auto text-ps-disabled mb-3" />
                    <p className="text-ps-label">No pending recommendations</p>
                    <p className="text-sm text-ps-hint mt-1">All insights have been actioned</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {recommendations.map((rec: Recommendation) => (
                      <div key={rec.id} className="bg-white border border-ps-border rounded-xl p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <span className={`text-3xs px-2 py-0.5 rounded-full font-semibold border ${PRIORITY_STYLES[rec.priority]}`}>
                                {rec.priority.toUpperCase()}
                              </span>
                              <span className="text-3xs bg-ps-muted text-ps-label px-2 py-0.5 rounded-full">
                                {REC_TYPE_LABELS[rec.recommendation_type] || rec.recommendation_type}
                              </span>
                              {rec.client_name && (
                                <span className="text-3xs text-ps-hint">{rec.client_name}</span>
                              )}
                            </div>
                            <p className="font-medium text-brand text-sm">{rec.title}</p>
                            <p className="text-xs text-ps-label mt-1">{rec.description}</p>
                            {rec.rationale && (
                              <p className="text-2xs text-ps-hint mt-1 italic">{rec.rationale}</p>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 mt-3 pt-3 border-t border-ps-muted">
                          {rec.action_label && (
                            <button
                              onClick={() => actOnRecommendation(rec.id, "accept")}
                              disabled={actingRec === rec.id}
                              className="text-xs px-3 py-1.5 rounded-lg font-medium text-white disabled:opacity-50"
                              style={{ backgroundColor: "#182350" }}
                            >
                              {rec.action_label}
                            </button>
                          )}
                          <button
                            onClick={() => actOnRecommendation(rec.id, "snooze")}
                            disabled={actingRec === rec.id}
                            className="text-xs px-3 py-1.5 rounded-lg font-medium border border-ps-border text-ps-label hover:bg-ps-bg disabled:opacity-50"
                          >
                            Snooze
                          </button>
                          <button
                            onClick={() => actOnRecommendation(rec.id, "dismiss")}
                            disabled={actingRec === rec.id}
                            className="text-xs text-ps-hint hover:text-ps-label px-2 py-1.5 disabled:opacity-50"
                          >
                            Dismiss
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
