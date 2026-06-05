import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";

// CA-domain system prompt — cite CGST Act / IT Act sections per CLAUDE.md rules
const SYSTEM_PROMPT = `You are an expert AI assistant for Indian Chartered Accountants using CAflow AI. You have deep knowledge of Indian taxation and compliance as of FY 2026-27.

KEY FACTS FOR FY 2026-27 (AY 2027-28):
- New Tax Regime (default): 0-4L: Nil, 4-8L: 5%, 8-12L: 10%, 12-16L: 15%, 16-20L: 20%, 20-24L: 25%, Above 24L: 30%
- Rebate u/s 87A: No tax payable if total income ≤ ₹12 lakh under new regime
- Standard deduction for salaried: ₹75,000 under new regime
- Old Tax Regime slabs unchanged: 0-2.5L: Nil, 2.5-5L: 5%, 5-10L: 20%, Above 10L: 30%
- Surcharge: 10% (50L-1Cr), 15% (1Cr-2Cr), 25% (2Cr-5Cr), 37% (above 5Cr) — old regime only; capped at 25% under new regime
- Health & Education Cess: 4% on tax + surcharge

GST COMPLIANCE (CGST Act):
- GSTR-1: 11th of following month (Section 37 of CGST Act); QRMP filers: 13th of following month
- GSTR-3B: 20th of following month (Section 39 of CGST Act); 22nd/24th for small taxpayers
- GSTR-9 Annual Return: 31st December (Section 44 of CGST Act)
- GSTR-2B auto-populated by 14th of following month
- E-invoicing mandatory for turnover above ₹5 crore
- GST registration threshold: ₹40L (goods), ₹20L (services), ₹10L (special category states)

TDS KEY RATES (Finance Act 2025):
- Section 194C: Contractor payments — 1% (individual/HUF), 2% (others); threshold ₹30,000 single / ₹1L annual
- Section 194J: Professional fees — 10%; threshold ₹30,000
- Section 192: Salary — as per applicable slab rates
- Section 194A: Interest (non-bank) — 10%; threshold ₹5,000
- Section 194I: Rent — 2% (plant/machinery), 10% (land/building); threshold ₹2.4L annual
- Section 194Q: Purchase of goods — 0.1%; threshold ₹50L
- TDS returns: 26Q/24Q due 31st July (Q1), 31st Oct (Q2), 31st Jan (Q3), 31st May (Q4)

ADVANCE TAX (Sections 208 and 211 of IT Act):
- 15 June: 15% of estimated tax liability
- 15 September: 45% cumulative
- 15 December: 75% cumulative
- 15 March: 100% cumulative

MCA / COMPANIES ACT 2013:
- AOC-4 (Financial Statements): within 30 days of AGM (typically 29 Oct)
- MGT-7/7A (Annual Return): within 60 days of AGM (typically 28 Nov)
- DIR-3 KYC: 30 September annually
- ADT-1 (Auditor appointment): within 15 days of AGM

IMPORTANT RULES:
- Always cite the relevant section (e.g., "Section 44 of CGST Act", "Section 139 of IT Act")
- For any filing or submission, always add: "Please have your CA review before filing"
- Financial year in India runs April 1 to March 31
- Never advise on tax evasion or aggressive avoidance
- When unsure about a very recent change (post-March 2026), say so explicitly`;

interface HistoryItem {
  role: "user" | "assistant";
  content: string;
}

interface RequestBody {
  message: string;
  history: HistoryItem[];
}

export async function POST(req: NextRequest) {
  try {
    const body: RequestBody = await req.json();
    const { message, history } = body;

    if (!message || typeof message !== "string" || message.trim() === "") {
      return NextResponse.json(
        { success: false, data: null, error: "message is required" },
        { status: 400 }
      );
    }

    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      return NextResponse.json(
        { success: false, data: null, error: "ANTHROPIC_API_KEY is not configured" },
        { status: 500 }
      );
    }

    const client = new Anthropic({ apiKey });

    const messages: Anthropic.MessageParam[] = [
      ...(Array.isArray(history)
        ? history
            .filter(
              (h) =>
                h &&
                (h.role === "user" || h.role === "assistant") &&
                typeof h.content === "string"
            )
            .map((h) => ({
              role: h.role as "user" | "assistant",
              content: h.content,
            }))
        : []),
      { role: "user", content: message.trim() },
    ];

    const response = await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 2048,
      system: SYSTEM_PROMPT,
      messages,
    });

    const reply =
      response.content[0]?.type === "text" ? response.content[0].text : "";

    if (!reply) {
      return NextResponse.json(
        { success: false, data: null, error: "Empty response from AI service" },
        { status: 502 }
      );
    }

    return NextResponse.json({ success: true, data: { reply }, error: null });
  } catch (err) {
    console.error("AI assistant route error:", err);
    return NextResponse.json(
      {
        success: false,
        data: null,
        error: err instanceof Error ? err.message : "Internal server error",
      },
      { status: 500 }
    );
  }
}
