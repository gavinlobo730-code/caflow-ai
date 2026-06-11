"use client";

import { useState, useRef, ChangeEvent } from "react";
import { Upload, FileText, CheckCircle, AlertCircle, X } from "lucide-react";

const DOCUMENT_TYPES = [
  { value: "AIS", label: "AIS (Annual Information Statement)" },
  { value: "FORM26AS", label: "Form 26AS" },
  { value: "GST_INVOICE", label: "GST Invoice" },
  { value: "BANK_STATEMENT", label: "Bank Statement" },
  { value: "FORM16", label: "Form 16" },
  { value: "TDS_CERTIFICATE", label: "TDS Certificate" },
  { value: "OTHER", label: "Other" },
];

interface Props {
  clientId: string;
  onSuccess?: (doc: Record<string, unknown>) => void;
}

type UploadState = "idle" | "uploading" | "success" | "error";

export function DocumentUploader({ clientId, onSuccess }: Props) {
  const [documentType, setDocumentType] = useState("OTHER");
  const [state, setState] = useState<UploadState>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setState("uploading");
    setMessage(null);

    const form = new FormData();
    form.append("file", file);
    form.append("document_type", documentType);
    form.append("client_id", clientId);

    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    try {
      const res = await fetch(`${apiUrl}/api/documents/upload`, {
        method: "POST",
        body: form,
      });
      const json = await res.json();
      if (json.success) {
        setState("success");
        setMessage(`${file.name} uploaded successfully.`);
        onSuccess?.(json.data.document);
      } else {
        throw new Error(json.error ?? "Upload failed");
      }
    } catch (err) {
      setState("error");
      setMessage(err instanceof Error ? err.message : "Upload failed");
    }
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) upload(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) upload(file);
  }

  function reset() {
    setState("idle");
    setMessage(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-sm font-medium text-[#334155] mb-1">
          Document Type
        </label>
        <select
          value={documentType}
          onChange={(e) => setDocumentType(e.target.value)}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
          disabled={state === "uploading"}
        >
          {DOCUMENT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => state !== "uploading" && fileRef.current?.click()}
        className={`
          relative flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed
          p-8 cursor-pointer transition-colors
          ${dragOver ? "border-blue-400 bg-blue-50" : "border-[#E2E8F0] hover:border-blue-300 hover:bg-[#F8FAFC]"}
          ${state === "uploading" ? "pointer-events-none opacity-70" : ""}
        `}
      >
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          onChange={handleFileChange}
          accept=".pdf,.png,.jpg,.jpeg,.xlsx,.csv"
        />

        {state === "idle" && (
          <>
            <Upload className="h-8 w-8 text-[#94A3B8]" />
            <p className="text-sm font-medium text-[#334155]">
              Drop file here or click to browse
            </p>
            <p className="text-xs text-[#94A3B8]">PDF, PNG, JPG, XLSX, CSV</p>
          </>
        )}

        {state === "uploading" && (
          <>
            <FileText className="h-8 w-8 text-blue-500 animate-pulse" />
            <p className="text-sm font-medium text-blue-700">Uploading…</p>
          </>
        )}

        {state === "success" && (
          <>
            <CheckCircle className="h-8 w-8 text-green-500" />
            <p className="text-sm font-medium text-green-700">{message}</p>
            <button
              onClick={(e) => { e.stopPropagation(); reset(); }}
              className="mt-1 text-xs text-[#64748B] hover:text-[#334155] flex items-center gap-1"
            >
              <X size={12} /> Upload another
            </button>
          </>
        )}

        {state === "error" && (
          <>
            <AlertCircle className="h-8 w-8 text-red-500" />
            <p className="text-sm font-medium text-red-700">{message}</p>
            <button
              onClick={(e) => { e.stopPropagation(); reset(); }}
              className="mt-1 text-xs text-[#64748B] hover:text-[#334155] flex items-center gap-1"
            >
              <X size={12} /> Try again
            </button>
          </>
        )}
      </div>
    </div>
  );
}
