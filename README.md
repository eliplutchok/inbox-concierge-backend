# Inbox Concierge — Backend

FastAPI backend for the Inbox Concierge email classification app. Handles Google OAuth authentication, Gmail thread fetching, LLM-powered email classification, and a feedback learning system that improves classification accuracy from user corrections.

## Quick Start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in your values
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `OPENAI_API_KEY` | OpenAI API key |
| `JWT_SECRET` | Secret for signing JWTs |
| `ENCRYPTION_KEY` | Fernet key for encrypting stored tokens |
| `FRONTEND_URL` | Frontend URL for CORS and redirects (default: `http://localhost:5173`) |
| `DEMO_USER_GOOGLE_ID` | (Optional) Google ID for one-click demo login |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/auth/login` | Start Google OAuth flow |
| GET | `/api/auth/callback` | OAuth callback |
| GET | `/api/auth/demo` | Get a demo account JWT |
| GET | `/api/auth/me` | Current user info |
| GET | `/api/emails` | Fetch, classify, and return email threads |
| PATCH | `/api/emails/{id}/category` | Reclassify a single email (triggers feedback learning) |
| POST | `/api/emails/reclassify` | Re-run classification on all emails (synchronous, returns results) |
| GET | `/api/categories` | List categories |
| PUT | `/api/categories` | Bulk update categories |
| POST | `/api/categories/reset` | Reset to default categories |
| GET | `/api/categories/notes` | Get AI preference notes |
| PUT | `/api/categories/notes` | Update preference notes |

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed technical documentation.
