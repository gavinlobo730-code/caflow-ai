"use client";

import { useState, useEffect, useRef, useCallback, ChangeEvent, DragEvent } from "react";
import {
  FileText,
  Upload,
  Brain,
  Loader2,
  AlertCircle,
  CheckCircle,
  Clock,
  Save,
  ChevronDown,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ExtractedData {
  name?: string;
  pan?: string;
  gstin?: string;
  period?: string;
  amounts?: Record<string, string | number>;
  dates?: Record<string, string>;
  [key: string]: unknown;
}

interface AnalysisHistory {
  id: string;
  fileName: string;
  docType: string;
  analyzedAt: string;
  extractedData: ExtractedData;
  clientId?: string;
  clientName?: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const DOCUMENT_TYPES = [
  { value: "Form 16", label: "Form 16" },
  { value: "ITR Acknowledgement", label: "ITR Acknowledgement" },
  { value: "GST Certificate", label: "GST Certificate" },
  { value: "PAN Card", label: "PAN Card" },
  { value: "Aadhaar", label: "Aadhaar" },
  { value: "Bank Statement", label: "Bank Statement" },
  { value: "Form 26AS", label: "Form 26AS" },
  { value: "Incorporation Certificate", label: "Incorporation Certificate" },
] as const;

type DocTypeValue = (typeof DOCUMENT_TYPES)[number]["value"];

const HISTORY_KEY = "doc_intelligence_history";
const MAX_HISTORY = 5;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function loadHistory(): AnalysisHistory[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as AnalysisHistory[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(items: AnalysisHistory[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip data:…;base64, prefix
      const base64 = result.split(",")[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ─── Document Text Extraction ────────────────────────────────────────────────
// For PDFs: uses PDF.js (loaded from CDN) to extract text from each page
// For images: converts to base64 and sends as data URL in the prompt
// Then sends extracted content to Groq (already configured in the app)

type PdfjsLib = {
  getDocument: (src: { data: ArrayBuffer }) => {
    promise: Promise<{
      numPages: number;
      getPage: (n: number) => Promise<{
        getTextContent: () => Promise<{ items: Array<{ str?: string }> }>;
      }>;
    }>;
  };
  GlobalWorkerOptions: { workerSrc: string };
};

function loadPdfJs(): Promise<PdfjsLib> {
  return new Promise((resolve, reject) => {
    if ((window as unknown as Record<string, unknown>).pdfjsLib) {
      resolve((window as unknown as Record<string, PdfjsLib>).pdfjsLib);
      return;
    }
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js";
    script.onload = () => {
      const lib = (window as unknown as Record<string, PdfjsLib>).pdfjsLib;
      lib.GlobalWorkerOptions.workerSrc =
        "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
      resolve(lib);
    };
    script.onerror = () => reject(new Error("Failed to load PDF.js"));
    document.head.appendChild(script);
  });
}

async function extractTextFromPdf(file: File): Promise<string> {
  const pdfjsLib = await loadPdfJs();
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  const pages: string[] = [];
  for (let i = 1; i <= Math.min(pdf.numPages, 10); i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const text = content.items.map((item) => item.str ?? "").join(" ");
    pages.push(text);
  }
  return pages.join("\n\n");
}

// Uses Groq (llama-3.1-8b-instant, free) — already configured in the app
async function extractWithClaude(file: File, docType: DocTypeValue): Promise<ExtractedData> {
  const apiKey = process.env.NEXT_PUBLIC_GROQ_API_KEY;
  if (!apiKey) throw new Error("NEXT_PUBLIC_GROQ_API_KEY is not configured");

  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");

  let documentContent: string;
  if (isPdf) {
    try {
      const fullText = await extractTextFromPdf(file);
      if (!fullText.trim()) throw new Error("No text found in PDF");
      documentContent = fullText;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (msg === "No text found in PDF") throw new Error("This PDF has no extractable text. It may be a scanned image. Please use a digitally-generated PDF.");
      throw new Error("Could not read this PDF. Please try again or use a different file.");
    }
  } else {
    const base64 = await fileToBase64(file);
    documentContent = `[Image file: ${file.name}, size: ${Math.round(file.size / 1024)}KB]\nExtract any PAN, GSTIN, names, monetary amounts and dates visible.`;
    void base64;
  }

  // Split into 4000-char chunks so each request stays within token limits.
  // Process all chunks in parallel and merge results.
  const CHUNK_SIZE = 4000;
  const chunks: string[] = [];
  for (let i = 0; i < documentContent.length; i += CHUNK_SIZE) {
    chunks.push(documentContent.slice(i, i + CHUNK_SIZE));
  }

  async function callGroq(prompt: string, retries = 4): Promise<string> {
    const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${apiKey}` },
      body: JSON.stringify({
        model: "llama-3.1-8b-instant",
        messages: [{ role: "user", content: prompt }],
        max_tokens: 1024,
        temperature: 0,
      }),
    });

    if (res.status === 429 && retries > 0) {
      // Parse retry delay from Groq error message e.g. "Please try again in 8.37s"
      const errBody = await res.json().catch(() => ({})) as { error?: { message?: string } };
      const msg = errBody?.error?.message ?? "";
      const match = msg.match(/try again in ([\d.]+)s/);
      const waitMs = match ? Math.ceil(parseFloat(match[1]) * 1000) + 500 : 15000;
      await new Promise(r => setTimeout(r, waitMs));
      return callGroq(prompt, retries - 1);
    }

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({})) as { error?: { message?: string } };
      throw new Error(`AI extraction failed: ${errBody?.error?.message ?? res.statusText}`);
    }

    const json = await res.json() as { choices: Array<{ message: { content: string } }> };
    return json.choices?.[0]?.message?.content ?? "{}";
  }

  async function extractChunk(chunk: string, chunkIndex: number): Promise<ExtractedData> {
    const prompt = `You are an expert Indian CA document parser. Extract key information from this ${docType} document (part ${chunkIndex + 1} of ${chunks.length}).

DOCUMENT TEXT:
${chunk}

Return ONLY a valid JSON object. Include only fields actually present in this text:
- name: full name of individual or company
- pan: PAN number (format AAAAA9999A)
- gstin: GSTIN (15-char alphanumeric)
- assessment_year: e.g. "2024-25"
- financial_year: e.g. "2023-24"
- period: period covered
- employer_name: employer or deductor name
- employer_tan: TAN number
- amounts: object of {label: rupee_value} for ALL monetary amounts
- dates: object of {label: date_string} for ALL dates

Return ONLY the JSON. No markdown, no explanation.`;

    const content = await callGroq(prompt);
    const cleaned = content.replace(/```json\s*/gi, "").replace(/```\s*/g, "").trim();
    try { return JSON.parse(cleaned) as ExtractedData; } catch { return {}; }
  }

  // Process chunks sequentially with auto-retry on rate limits
  const results: ExtractedData[] = [];
  for (let i = 0; i < chunks.length; i++) {
    const result = await extractChunk(chunks[i], i);
    results.push(result);
  }

  // Merge all chunk results — later chunks override earlier for scalars, amounts/dates are merged
  const merged: ExtractedData = {};
  for (const r of results) {
    for (const [k, v] of Object.entries(r)) {
      if (!v) continue;
      if (typeof v === "object" && !Array.isArray(v)) {
        merged[k] = { ...(merged[k] as Record<string, unknown> ?? {}), ...(v as Record<string, unknown>) };
      } else if (!merged[k]) {
        merged[k] = v;
      }
    }
  }
  return Object.keys(merged).length > 0 ? merged : { raw_response: "No data could be extracted from this document." };
}

// ─── Extracted Data Display ───────────────────────────────────────────────────

function ExtractedDataCard({ data }: { data: ExtractedData }) {
  const simple: [string, string][] = [];
  const nested: [string, Record<string, string | number>][] = [];

  for (const [key, value] of Object.entries(data)) {
    if (value === null || value === undefined || value === "") continue;
    if (typeof value === "object" && !Array.isArray(value)) {
      nested.push([key, value as Record<string, string | number>]);
    } else {
      simple.push([key, String(value)]);
    }
  }

  function label(key: string) {
    return key
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  return (
    <div className="space-y-4">
      {simple.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {simple.map(([k, v]) => (
            <div key={k} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-0.5">
                {label(k)}
              </p>
              <p className="text-sm font-medium text-gray-800 break-all">{v}</p>
            </div>
          ))}
        </div>
      )}

      {nested.map(([k, obj]) => (
        <div key={k}>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            {label(k)}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {Object.entries(obj).map(([sk, sv]) => (
              <div key={sk} className="rounded-lg border border-gray-100 bg-blue-50 p-3">
                <p className="text-xs font-medium text-blue-500 mb-0.5">{label(sk)}</p>
                <p className="text-sm font-semibold text-blue-900">{String(sv)}</p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── History Item ─────────────────────────────────────────────────────────────

function HistoryItem({
  item,
  onRestore,
}: {
  item: AnalysisHistory;
  onRestore: (item: AnalysisHistory) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-3">
          <FileText size={15} className="shrink-0 text-gray-400" />
          <div>
            <p className="text-sm font-medium text-gray-800">{item.fileName}</p>
            <p className="text-xs text-gray-500">
              {item.docType} · {formatDateTime(item.analyzedAt)}
              {item.clientName && ` · ${item.clientName}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRestore(item);
            }}
            className="text-xs text-blue-600 hover:underline"
          >
            Restore
          </button>
          <ChevronDown
            size={14}
            className={`text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`}
          />
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-100">
          <ExtractedDataCard data={item.extractedData} />
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function DocIntelligencePage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState<DocTypeValue>("Form 16");
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [extracted, setExtracted] = useState<ExtractedData | null>(null);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [saved, setSaved] = useState(false);
  const [history, setHistory] = useState<AnalysisHistory[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setHistory(loadHistory());
    getClients()
      .then(setClients)
      .catch(() => {});
  }, []);

  function handleFileSelect(selected: File) {
    setFile(selected);
    setExtracted(null);
    setError(null);
    setSaved(false);
  }

  function handleInputChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) handleFileSelect(f);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleFileSelect(f);
  }

  const handleAnalyze = useCallback(async () => {
    if (!file) return;
    setAnalyzing(true);
    setError(null);
    setExtracted(null);
    setSaved(false);

    try {
      const data = await extractWithClaude(file, docType);
      setExtracted(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }, [file, docType]);

  function handleSave() {
    if (!extracted || !file) return;
    const client = clients.find((c) => c.id === selectedClientId);
    const item: AnalysisHistory = {
      id: crypto.randomUUID(),
      fileName: file.name,
      docType,
      analyzedAt: new Date().toISOString(),
      extractedData: extracted,
      clientId: selectedClientId || undefined,
      clientName: client?.client_name,
    };
    const updated = [item, ...history].slice(0, MAX_HISTORY);
    setHistory(updated);
    saveHistory(updated);
    setSaved(true);
  }

  function handleRestore(item: AnalysisHistory) {
    setExtracted(item.extractedData);
    setDocType(item.docType as DocTypeValue);
    setSelectedClientId(item.clientId ?? "");
    setSaved(true);
    // Clear file so user knows this is from history
    setFile(null);
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Doc Intelligence</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          AI-powered document analysis — extract key data from Indian tax documents
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* ── Left panel — Upload & Analyze ── */}
        <div className="lg:col-span-3 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Upload size={16} className="text-blue-500" />
                Upload Document
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Document type selector */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Document Type
                </label>
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value as DocTypeValue)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
                >
                  {DOCUMENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Drag & Drop zone */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  File (PDF or Image)
                </label>
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={handleDrop}
                  onClick={() => fileRef.current?.click()}
                  className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-8 transition-colors ${
                    dragging
                      ? "border-blue-400 bg-blue-50"
                      : file
                      ? "border-green-400 bg-green-50"
                      : "border-gray-200 hover:border-blue-300 hover:bg-gray-50"
                  }`}
                >
                  <input
                    ref={fileRef}
                    type="file"
                    className="hidden"
                    accept=".pdf,.png,.jpg,.jpeg,.webp"
                    onChange={handleInputChange}
                  />
                  {file ? (
                    <>
                      <CheckCircle className="h-8 w-8 text-green-500" />
                      <p className="text-sm font-medium text-green-700">{file.name}</p>
                      <p className="text-xs text-gray-500">
                        {(file.size / 1024).toFixed(1)} KB — click to change
                      </p>
                    </>
                  ) : (
                    <>
                      <Upload className="h-8 w-8 text-gray-400" />
                      <p className="text-sm font-medium text-gray-600">
                        Drag & drop or click to browse
                      </p>
                      <p className="text-xs text-gray-400">PDF, PNG, JPG, WEBP</p>
                    </>
                  )}
                </div>
              </div>

              {/* Error */}
              {error && (
                <div className="flex items-start gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
                  <AlertCircle size={16} className="mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Analyze button */}
              <button
                onClick={handleAnalyze}
                disabled={!file || analyzing}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {analyzing ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    Analyzing with AI…
                  </>
                ) : (
                  <>
                    <Brain size={15} />
                    Extract Data with AI
                  </>
                )}
              </button>
            </CardContent>
          </Card>

          {/* ── Extracted results ── */}
          {extracted && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <CheckCircle size={16} className="text-green-500" />
                  Extracted Data
                  <span className="ml-auto text-xs font-normal text-gray-400">
                    {docType}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <ExtractedDataCard data={extracted} />

                {/* Save to client */}
                <div className="border-t border-gray-100 pt-4 space-y-3">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">
                      Associate with Client (optional)
                    </label>
                    <select
                      value={selectedClientId}
                      onChange={(e) => setSelectedClientId(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
                    >
                      <option value="">Select client…</option>
                      {clients.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.client_name}
                        </option>
                      ))}
                    </select>
                  </div>

                  <button
                    onClick={handleSave}
                    disabled={saved}
                    className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    {saved ? (
                      <>
                        <CheckCircle size={14} className="text-green-500" />
                        Saved to History
                      </>
                    ) : (
                      <>
                        <Save size={14} />
                        Save to History
                      </>
                    )}
                  </button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── Right panel — History ── */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Clock size={16} className="text-gray-400" />
                Recent Analyses
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 min-h-[120px]">
              {history.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <FileText className="h-8 w-8 text-gray-300 mb-2" />
                  <p className="text-sm text-gray-500">No documents analyzed yet.</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Upload and analyze a document to see history here.
                  </p>
                </div>
              ) : (
                history.map((item) => (
                  <HistoryItem key={item.id} item={item} onRestore={handleRestore} />
                ))
              )}
            </CardContent>
          </Card>

          {/* Tips */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-gray-600">Tips</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1.5 text-xs text-gray-500">
                <li className="flex items-start gap-1.5">
                  <span className="text-blue-400 font-bold mt-0.5">·</span>
                  Upload clear, high-resolution scans for best results
                </li>
                <li className="flex items-start gap-1.5">
                  <span className="text-blue-400 font-bold mt-0.5">·</span>
                  Select the correct document type before analyzing
                </li>
                <li className="flex items-start gap-1.5">
                  <span className="text-blue-400 font-bold mt-0.5">·</span>
                  Always verify extracted PAN/GSTIN against originals
                </li>
                <li className="flex items-start gap-1.5">
                  <span className="text-blue-400 font-bold mt-0.5">·</span>
                  Last {MAX_HISTORY} analyses are stored in your browser
                </li>
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
