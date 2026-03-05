# Inbox Concierge — Backend

FastAPI backend for the Inbox Concierge email classification app.

## Quick Start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in your values
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

See [SETUP.md](SETUP.md) for detailed setup instructions including Google Cloud and OpenAI configuration.

## API

- `GET /api/auth/login` — Start Google OAuth flow
- `GET /api/auth/me` — Current user info
- `GET /api/emails` — Fetch and classify email threads
- `GET /api/categories` — List categories
- `PUT /api/categories` — Bulk update categories
- `POST /api/categories/reset` — Reset to defaults
- `PATCH /api/classifications/{id}` — Update a classification (drag-and-drop)
