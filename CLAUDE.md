PracticeSync (formerly CAflow AI) — AI-powered practice management platform for Indian Chartered Accountants.
Replaces Tally + ClearTax + Winman + WhatsApp with one unified AI-first platform.

Tech stack:
- Frontend: Next.js 14, TypeScript, Tailwind CSS, shadcn/ui
- Backend: FastAPI (Python 3.11)
- Database: Supabase (Postgres)
- AI: Groq API (llama-3.3-70b-versatile) for chat/text features — requires GROQ_API_KEY in apps/api/.env ONLY. Every AI key is backend-only: apps/web builds as a static export (`output: "export"` in next.config.js), so it has no server and can read nothing but NEXT_PUBLIC_* values, which are inlined into the browser bundle. An AI key in the frontend environment is at best ignored and at worst published. Gemini API (gemini-2.5-flash) for image-based invoice extraction only (routers/document_intelligence_v1.py) — requires GEMINI_API_KEY in apps/api/.env; Groq's vision models were unavailable on this account (live 404 model_not_found), Gemini's free tier is multimodal-native and already provisioned for this project. PDF invoice extraction still uses Groq (text-only, works fine).
- Package manager: pnpm for frontend, pip for backend

Indian tax domain rules — never violate these:
- GSTIN format: 2-digit state code + PAN (10 chars) + 1 digit entity number + Z + 1 check digit
- PAN format: AAAAA9999A (5 uppercase letters + 4 digits + 1 uppercase letter)
- Financial year: April 1 to March 31
- GSTR-1 due date: 11th of the following month
- GSTR-3B due date: 20th of the following month
- GSTR-9 (annual): 31st December
- TDS return (24Q/26Q): Q1 31 Jul, Q2 31 Oct, Q3 31 Jan, Q4 31 May. Q4 is the exception — it is NOT the end of the month following quarter end (that would be 30 Apr). services/compliance_engine.py::tds_return_due_date is the authority; keep any prose in step with it.
- Advance tax due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
- Never auto-submit anything to any government portal — always require explicit CA confirmation click
- Every rupee calculation must use integer paise arithmetic, never floating point

Code rules — always follow:
- Never hardcode API keys — always use .env files
- Every financial calculation must have a corresponding unit test
- All GST/ITR logic must have a comment citing the relevant section of the CGST Act or IT Act
- Before any government API call, add comment: # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
- Frontend and backend are completely separate — zero business logic in the frontend
- All API responses must follow: { success: bool, data: any, error: string | null }

Current phase: MVP Phase 1 only. Do not build anything outside this scope.

Bug fixing:
- When the user reports a bug, don't just patch the one instance. Identify the underlying pattern (wrong column name, missing null check, stale label, unapplied migration, etc.) and grep/search the rest of the codebase for the same pattern before calling the fix done. Report what else was found, even if you decide not to touch it.
