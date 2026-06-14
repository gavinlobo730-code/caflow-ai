# PracticeSync AI

AI-powered practice management platform for Indian Chartered Accountants.

## Setup

### Prerequisites
- Node.js 18+
- pnpm 8+
- Python 3.11+
- pip

### Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Frontend (Next.js)

```bash
cd apps/web
pnpm install
pnpm dev
```

Runs at http://localhost:3000

### Backend (FastAPI)

```bash
cd apps/api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Runs at http://localhost:8000

### API Docs

FastAPI auto-generates docs at http://localhost:8000/docs

## Project Structure

```
caflow-ai/
├── apps/
│   ├── web/          # Next.js 14 frontend
│   └── api/          # FastAPI backend
├── .env.example
├── .gitignore
├── CLAUDE.md
└── README.md
```

## Test PDFs

Place test PDF files in `apps/web/public/` for the document parser.
See `apps/web/public/demo-form16.pdf` for instructions.
