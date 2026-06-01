"use client";
export const runtime = "edge";

import { useState, useRef } from "react";
import { Upload, Copy, FileText, Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const MOCK_FORM16: Record<string, string> = {
  "Employee Name": "Rajesh Kumar Sharma",
  "PAN": "ABCRS1234D",
  "Employer Name": "TechCorp India Pvt Ltd",
  "Assessment Year": "2024-25",
  "Gross Salary": "₹12,00,000",
  "Total TDS": "₹1,85,000",
};

const MOCK_GST_INVOICE: Record<string, string> = {
  "Supplier Name": "Hindustan Goods Suppliers Pvt Ltd",
  "GSTIN": "27AABCH1234B1ZA",
  "Invoice Number": "HGS/2024-25/001234",
  "Invoice Date": "15-03-2024",
  "Taxable Value": "₹1,00,000",
  "CGST (9%)": "₹9,000",
  "SGST (9%)": "₹9,000",
  "IGST": "₹0",
  "Total Amount": "₹1,18,000",
  "HSN Code": "8471",
};

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button onClick={copy} className="text-gray-400 hover:text-blue-600 transition-colors">
      {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
    </button>
  );
}

function ExtractedFields({ fields }: { fields: Record<string, string> }) {
  return (
    <Card className="mt-4">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <FileText size={16} className="text-blue-600" />
          Extracted Fields
          <Badge variant="secondary" className="ml-auto text-xs">Mock Data</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {Object.entries(fields).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0">
              <span className="text-xs text-gray-500 w-36 shrink-0">{key}</span>
              <span className="text-sm text-gray-900 font-medium flex-1">{value}</span>
              <CopyButton value={value} />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function ParserPage() {
  const [activeTab, setActiveTab] = useState("form16");
  const [dragging, setDragging] = useState(false);
  const [uploaded, setUploaded] = useState(false);
  const [fileName, setFileName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      setFileName(file.name);
      setUploaded(true);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setFileName(file.name);
      setUploaded(true);
    }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Document Parser</h1>
        <p className="text-gray-500 text-sm mt-1">Upload Form 16 or GST invoices for AI-powered extraction</p>
      </div>

      <Tabs value={activeTab} onValueChange={(v) => { setActiveTab(v); setUploaded(false); setFileName(""); }}>
        <TabsList>
          <TabsTrigger value="form16">Form 16</TabsTrigger>
          <TabsTrigger value="gst_invoice">GST Invoice</TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} className="mt-4">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            className={`
              border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors
              ${dragging ? "border-blue-500 bg-blue-50" : "border-gray-300 hover:border-blue-400 hover:bg-gray-50"}
            `}
          >
            <input ref={inputRef} type="file" accept=".pdf" className="hidden" onChange={handleFileChange} />
            <Upload className="mx-auto text-gray-400 mb-3" size={36} />
            {uploaded ? (
              <>
                <p className="text-sm font-medium text-blue-700">{fileName}</p>
                <p className="text-xs text-green-600 mt-1">File ready — showing extracted data below</p>
              </>
            ) : (
              <>
                <p className="text-sm text-gray-600">Drag & drop a PDF here, or click to browse</p>
                <p className="text-xs text-gray-400 mt-1">Supports: PDF files only</p>
              </>
            )}
          </div>
        </TabsContent>
      </Tabs>

      {uploaded && (
        <ExtractedFields fields={activeTab === "form16" ? MOCK_FORM16 : MOCK_GST_INVOICE} />
      )}
    </div>
  );
}
