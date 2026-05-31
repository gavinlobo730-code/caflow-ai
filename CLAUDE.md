CAflow AI — AI-powered practice management platform for Indian Chartered Accountants.
Replaces Tally + ClearTax + Winman + WhatsApp with one unified AI-first platform.

Tech stack:
- Frontend: Next.js 14, TypeScript, Tailwind CSS, shadcn/ui
- Backend: FastAPI (Python 3.11)
- Database: Supabase (Postgres)
- AI: Anthropic Claude API (claude-sonnet-4-6)
- Package manager: pnpm for frontend, pip for backend

Indian tax domain rules — never violate these:
- GSTIN format: 2-digit state code + PAN (10 chars) + 1 digit entity number + Z + 1 check digit
- PAN format: AAAAA9999A (5 uppercase letters + 4 digits + 1 uppercase letter)
- Financial year: April 1 to March 31
- GSTR-1 due date: 11th of the following month
- GSTR-3B due date: 20th of the following month
- GSTR-9 (annual): 31st December
- TDS return (24Q/26Q): 31st of month following quarter end
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
