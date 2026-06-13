"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import {
  Send, Plus, Archive, ChevronRight, Sparkles, ThumbsUp, ThumbsDown,
  BarChart2, Users, Shield, Zap, GitBranch, RefreshCw, X,
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

const CONTEXT_ICONS: Record<string, React.ReactNode> = {
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
            ? "bg-[#182350] text-white rounded-tr-sm"
            : "bg-white border border-[#E2E8F0] text-[#1E293B] rounded-tl-sm shadow-sm"
        }`}>
          {msg.content.split("\n").map((line, i) => (
            <p key={i} className={line.startsWith("##") ? "font-semibold mt-2" : line.startsWith("- ") ? "pl-3" : ""}>{
              line.startsWith("## ") ? line.replace("## ", "") : line
            }</p>
          ))}
        </div>
        {!isUser && (
          <div className="flex items-center gap-2 mt-1.5 px-1">
            <span className="text-[10px] text-[#94A3B8]">{fmtTime(msg.created_at)}</span>
            {msg.tokens_used && (
              <span className="text-[10px] text-[#CBD5E1]">{msg.tokens_used} tokens</span>
            )}
            <div className="flex gap-1 ml-auto">
              <button
                onClick={() => onRate(msg.id, 5)}
                className={`p-1 rounded hover:bg-green-50 transition-colors ${msg.feedback_rating === 5 ? "text-green-600" : "text-[#CBD5E1] hover:text-green-500"}`}
              >
                <ThumbsUp size={11} />
              </button>
              <button
                onClick={() => onRate(msg.id, 1)}
                className={`p-1 rounded hover:bg-red-50 transition-colors ${msg.feedback_rating === 1 ? "text-red-500" : "text-[#CBD5E1] hover:text-red-400"}`}
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

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });

  const loadConversations = useCallback(async () => {
    try {
      const res = await api.copilotV2.listConversations() as any;
      setConversations(res.data?.conversations || []);
    } catch {}
  }, []);

  const loadRecommendations = useCallback(async () => {
    try {
      const res = await api.copilotV2.listRecommendations({ status: "pending" }) as any;
      setRecommendations(res.data?.recommendations || []);
    } catch {}
  }, []);

  const loadSuggestions = useCallback(async () => {
    try {
      const res = await api.copilotV2.suggestions(contextType) as any;
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
    setActiveConv(convId);
    try {
      const res = await api.copilotV2.getConversation(convId) as any;
      setMessages(res.data?.messages || []);
    } catch {}
  };

  const newConversation = async () => {
    try {
      const res = await api.copilotV2.createConversation({ context_type: contextType }) as any;
      const conv = res.data;
      setConversations(prev => [conv, ...prev]);
      setActiveConv(conv.id);
      setMessages([]);
    } catch {}
  };

  const sendMessage = async (content?: string) => {
    const text = content || input.trim();
    if (!text || sending) return;

    let convId = activeConv;
    if (!convId) {
      const res = await api.copilotV2.createConversation({ context_type: contextType }) as any;
      convId = res.data.id;
      setConversations(prev => [res.data, ...prev]);
      setActiveConv(convId);
    }

    const optimistic: Message = {
      id: `opt-${Date.now()}`,
      conversation_id: convId!,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, optimistic]);
    setInput("");
    setSending(true);

    try {
      const res = await api.copilotV2.sendMessage(convId!, { content: text, context_type: contextType }) as any;
      const { message: assistantMsg, suggested_questions } = res.data;
      setMessages(prev => [...prev.filter(m => m.id !== optimistic.id), optimistic, assistantMsg]);
      if (suggested_questions?.length) setSuggestions(suggested_questions);
      loadConversations();
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== optimistic.id));
    } finally {
      setSending(false);
    }
  };

  const rateMessage = async (messageId: string, rating: number) => {
    setMessages(prev => prev.map(m => m.id === messageId ? { ...m, feedback_rating: rating } : m));
    try {
      await api.copilotV2.rateMessage(messageId, { rating });
    } catch {}
  };

  const actOnRecommendation = async (recId: string, action: "accept" | "dismiss" | "snooze") => {
    setActingRec(recId);
    try {
      await api.copilotV2.actRecommendation(recId, { action });
      setRecommendations(prev => prev.filter(r => r.id !== recId));
    } finally {
      setActingRec(null);
    }
  };

  return (
    <div className="h-screen flex flex-col bg-[#F8FAFC]">
      {/* Header */}
      <div className="bg-white border-b border-[#E2E8F0] px-6 py-4 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: "#182350" }}>
              <Sparkles size={16} className="text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-[#182350]">AI Copilot</h1>
              <p className="text-xs text-[#64748B]">Intelligent assistant for your CA practice</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Context type selector */}
            <select
              value={contextType}
              onChange={e => setContextType(e.target.value)}
              className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg bg-white text-[#475569]"
            >
              <option value="global">Global</option>
              <option value="compliance">Compliance</option>
              <option value="workflow">Workflows</option>
              <option value="executive">Executive</option>
              <option value="relationship">Relationships</option>
            </select>
            <div className="flex gap-1 border border-[#E2E8F0] rounded-lg p-0.5 bg-white">
              <button
                onClick={() => setTab("chat")}
                className={`px-3 py-1.5 text-xs rounded-md font-medium transition-colors ${tab === "chat" ? "bg-[#182350] text-white" : "text-[#64748B] hover:text-[#334155]"}`}
              >
                Chat
              </button>
              <button
                onClick={() => setTab("recommendations")}
                className={`px-3 py-1.5 text-xs rounded-md font-medium transition-colors relative ${tab === "recommendations" ? "bg-[#182350] text-white" : "text-[#64748B] hover:text-[#334155]"}`}
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
        <div className="w-64 bg-white border-r border-[#E2E8F0] flex flex-col flex-shrink-0">
          <div className="p-3 border-b border-[#F1F5F9]">
            <button
              onClick={newConversation}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg text-white transition-colors"
              style={{ backgroundColor: "#182350" }}
            >
              <Plus size={14} />
              New Conversation
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {conversations.length === 0 ? (
              <p className="text-xs text-[#94A3B8] text-center py-6">No conversations yet</p>
            ) : (
              conversations.map(conv => (
                <button
                  key={conv.id}
                  onClick={() => openConversation(conv.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors ${
                    activeConv === conv.id
                      ? "bg-[#EFF6FF] text-[#182350]"
                      : "hover:bg-[#F8FAFC] text-[#334155]"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 text-[#94A3B8] flex-shrink-0">
                      {CONTEXT_ICONS[conv.context_type] || <MessageSquare size={14} />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium line-clamp-2">{conv.title}</p>
                      <div className="flex items-center gap-1 mt-0.5">
                        <Clock size={9} className="text-[#CBD5E1]" />
                        <span className="text-[10px] text-[#CBD5E1]">
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
                    <h2 className="text-lg font-semibold text-[#182350] mb-1">Ask your Copilot</h2>
                    <p className="text-sm text-[#64748B] mb-6 max-w-sm">
                      Get instant answers about clients, compliance, GST, TDS, and more.
                    </p>
                    <div className="grid grid-cols-2 gap-2 max-w-lg">
                      {suggestions.slice(0, 6).map((q, i) => (
                        <button
                          key={i}
                          onClick={() => sendMessage(q)}
                          className="text-left text-xs px-3 py-2.5 rounded-xl border border-[#E2E8F0] bg-white hover:border-[#AFD2FA] hover:bg-[#EFF6FF] text-[#475569] transition-colors"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="max-w-3xl mx-auto">
                    {messages.map(msg => (
                      <MessageBubble key={msg.id} msg={msg} onRate={rateMessage} />
                    ))}
                    {sending && (
                      <div className="flex justify-start mb-4">
                        <div className="w-7 h-7 rounded-full flex items-center justify-center mr-2 flex-shrink-0"
                          style={{ backgroundColor: "#182350" }}>
                          <Sparkles size={13} className="text-white" />
                        </div>
                        <div className="bg-white border border-[#E2E8F0] rounded-2xl rounded-tl-sm px-4 py-3">
                          <div className="flex gap-1">
                            {[0,1,2].map(i => (
                              <div key={i} className="w-2 h-2 rounded-full bg-[#AFD2FA] animate-bounce"
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
                <div className="px-6 py-2 border-t border-[#F1F5F9] bg-white">
                  <div className="flex gap-2 overflow-x-auto pb-1 max-w-3xl mx-auto">
                    {suggestions.slice(0,4).map((q, i) => (
                      <button
                        key={i}
                        onClick={() => sendMessage(q)}
                        className="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] hover:bg-[#EFF6FF] hover:border-[#AFD2FA] text-[#475569] transition-colors whitespace-nowrap"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Input */}
              <div className="px-6 py-4 border-t border-[#E2E8F0] bg-white flex-shrink-0">
                <div className="max-w-3xl mx-auto flex items-end gap-3">
                  <div className="flex-1 relative">
                    <textarea
                      value={input}
                      onChange={e => setInput(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                      placeholder="Ask anything about your clients, compliance, GST, TDS..."
                      rows={1}
                      className="w-full px-4 py-3 text-sm border border-[#E2E8F0] rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-[#182350]/20 focus:border-[#AFD2FA] leading-relaxed"
                      style={{ minHeight: "48px", maxHeight: "140px" }}
                    />
                  </div>
                  <button
                    onClick={() => sendMessage()}
                    disabled={!input.trim() || sending}
                    className="flex-shrink-0 w-11 h-11 rounded-xl flex items-center justify-center disabled:opacity-40 transition-all"
                    style={{ backgroundColor: input.trim() ? "#182350" : "#E2E8F0" }}
                  >
                    <Send size={15} className={input.trim() ? "text-white" : "text-[#94A3B8]"} />
                  </button>
                </div>
                <p className="text-center text-[10px] text-[#CBD5E1] mt-2">
                  AI responses are advisory — always verify with source documents. Never auto-submit to government portals.
                </p>
              </div>
            </>
          )}

          {tab === "recommendations" && (
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <div className="max-w-2xl mx-auto">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-semibold text-[#182350]">AI Recommendations</h2>
                  <button onClick={loadRecommendations} className="text-xs text-[#64748B] flex items-center gap-1 hover:text-[#182350]">
                    <RefreshCw size={12} /> Refresh
                  </button>
                </div>

                {recommendations.length === 0 ? (
                  <div className="text-center py-16">
                    <Star size={40} className="mx-auto text-[#CBD5E1] mb-3" />
                    <p className="text-[#64748B]">No pending recommendations</p>
                    <p className="text-sm text-[#94A3B8] mt-1">All insights have been actioned</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {recommendations.map(rec => (
                      <div key={rec.id} className="bg-white border border-[#E2E8F0] rounded-xl p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border ${PRIORITY_STYLES[rec.priority]}`}>
                                {rec.priority.toUpperCase()}
                              </span>
                              <span className="text-[10px] bg-[#F1F5F9] text-[#64748B] px-2 py-0.5 rounded-full">
                                {REC_TYPE_LABELS[rec.recommendation_type] || rec.recommendation_type}
                              </span>
                              {rec.client_name && (
                                <span className="text-[10px] text-[#94A3B8]">{rec.client_name}</span>
                              )}
                            </div>
                            <p className="font-medium text-[#182350] text-sm">{rec.title}</p>
                            <p className="text-xs text-[#64748B] mt-1">{rec.description}</p>
                            {rec.rationale && (
                              <p className="text-[11px] text-[#94A3B8] mt-1 italic">{rec.rationale}</p>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 mt-3 pt-3 border-t border-[#F1F5F9]">
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
                            className="text-xs px-3 py-1.5 rounded-lg font-medium border border-[#E2E8F0] text-[#475569] hover:bg-[#F8FAFC] disabled:opacity-50"
                          >
                            Snooze
                          </button>
                          <button
                            onClick={() => actOnRecommendation(rec.id, "dismiss")}
                            disabled={actingRec === rec.id}
                            className="text-xs text-[#94A3B8] hover:text-[#64748B] px-2 py-1.5 disabled:opacity-50"
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
