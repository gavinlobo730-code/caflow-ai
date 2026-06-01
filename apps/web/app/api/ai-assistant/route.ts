import { NextRequest, NextResponse } from "next/server";

// System prompt for Indian CA assistant
const SYSTEM_PROMPT = `You are an AI assistant for Indian Chartered Accountants using CAflow AI. You help with GST (CGST Act), Income Tax (IT Act), TDS, ROC/MCA filings, accounting, and practice management. Always cite relevant sections when giving tax advice. For compliance deadlines, be precise about Indian financial year (April-March). Never provide advice that could be construed as filing on behalf of the CA — always recommend CA review.`;

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

    // Build message list: prior history + new user message
    const messages: { role: "user" | "assistant"; content: string }[] = [
      ...(Array.isArray(history)
        ? history
            .filter(
              (h) =>
                h &&
                (h.role === "user" || h.role === "assistant") &&
                typeof h.content === "string"
            )
            .map((h) => ({ role: h.role, content: h.content }))
        : []),
      { role: "user", content: message.trim() },
    ];

    // Call Anthropic Claude API (claude-sonnet-4-6)
    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-6",
        max_tokens: 2048,
        system: SYSTEM_PROMPT,
        messages,
      }),
    });

    if (!response.ok) {
      const errText = await response.text();
      console.error("Anthropic API error:", errText);
      return NextResponse.json(
        { success: false, data: null, error: "AI service error. Please try again." },
        { status: 502 }
      );
    }

    const result = await response.json();
    const reply: string =
      result?.content?.[0]?.type === "text" ? result.content[0].text : "";

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
