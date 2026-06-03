import { NextRequest, NextResponse } from "next/server";

const SYSTEM_PROMPT = `You are an AI assistant for Indian Chartered Accountants using PracticeSync AI. You help with GST (CGST Act), Income Tax (IT Act), TDS, ROC/MCA filings, accounting, and practice management. Always cite relevant sections when giving tax advice. For compliance deadlines, be precise about Indian financial year (April-March). Never provide advice that could be construed as filing on behalf of the CA — always recommend CA review.`;

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

    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      return NextResponse.json(
        { success: false, data: null, error: "GEMINI_API_KEY is not configured" },
        { status: 500 }
      );
    }

    // Build Gemini contents array from history + new message
    const contents = [
      ...(Array.isArray(history)
        ? history
            .filter(
              (h) =>
                h &&
                (h.role === "user" || h.role === "assistant") &&
                typeof h.content === "string"
            )
            .map((h) => ({
              role: h.role === "assistant" ? "model" : "user",
              parts: [{ text: h.content }],
            }))
        : []),
      { role: "user", parts: [{ text: message.trim() }] },
    ];

    // Call Google Gemini API (gemini-1.5-flash — free tier)
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
          contents,
          generationConfig: { maxOutputTokens: 2048 },
        }),
      }
    );

    if (!response.ok) {
      const errText = await response.text();
      console.error("Gemini API error:", errText);
      return NextResponse.json(
        { success: false, data: null, error: "AI service error. Please try again." },
        { status: 502 }
      );
    }

    const result = await response.json();
    const reply: string =
      result?.candidates?.[0]?.content?.parts?.[0]?.text ?? "";

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
