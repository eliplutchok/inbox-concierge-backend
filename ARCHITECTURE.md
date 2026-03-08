# Inbox Concierge — Backend Architecture

> **Keep this document up to date.** When you add, remove, or change models, endpoints, services, schemas, or configuration, update the relevant sections here so this file stays accurate for future development.

## Overview

A FastAPI backend that authenticates users via Google OAuth, fetches their Gmail threads, classifies emails into categories using an LLM, and learns from user corrections to improve over time. All data is persisted in PostgreSQL.

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 (async with asyncpg), Alembic, OpenAI API (Responses API), Google Gmail API, PostgreSQL.

## Core Features

- **Google OAuth 2.0** — PKCE-secured authentication with `gmail.readonly` scope
- **Gmail integration** — batch-fetched threads (up to 200) with retry logic for rate limits
- **LLM classification** — GPT-4o-mini classifies emails into user-defined categories
- **Feedback learning** — GPT-5.4 analyzes user corrections to generate preference notes that improve future classifications
- **Synchronous reclassification** — dedicated endpoint reclassifies all emails and returns results directly (no background polling)
- **Category management** — CRUD for categories; reclassification is explicitly triggered by the user
- **Notes adaptation** — when reclassification runs, preference notes are automatically adapted to the current category set by an LLM
- **Token management** — encrypted storage of Google tokens, automatic refresh persistence

## Project Structure

```
app/
├── main.py                    # FastAPI app, CORS, router registration
├── config.py                  # Pydantic settings from .env
├── database.py                # SQLAlchemy engine + session factory
├── auth.py                    # JWT creation/decoding, Fernet encryption, get_current_user
├── constants.py               # Default category definitions
├── models/
│   ├── base.py                # Declarative base with UUID primary key + created_at
│   ├── user.py                # User model (google_id, tokens, prompt_notes)
│   ├── category.py            # Category model (name, description, per-user)
│   └── email_thread.py        # EmailThread model (gmail data + classification fields)
├── schemas/
│   ├── auth.py                # UserResponse
│   ├── category.py            # CategoryResponse, CategoryUpdate, CategoriesBulkUpdate
│   └── email.py               # EmailThreadResponse, EmailsResponse, EmailCategoryUpdate
├── routers/
│   ├── auth.py                # /api/auth — OAuth login/callback, /me
│   ├── emails.py              # /api/emails — fetch, classify, reclassify
│   └── categories.py          # /api/categories — CRUD, reset, notes
└── services/
    ├── gmail.py               # Gmail API integration (batch fetch, parsing)
    ├── classifier.py          # LLM classification (GPT-4o-mini)
    └── feedback.py            # Feedback learning + notes adaptation (GPT-5.4)
```

## Database Schema

All tables use UUID primary keys and `created_at` timestamps (from `Base`).

### users

| Column | Type | Notes |
|---|---|---|
| google_id | String | Unique, from Google OAuth |
| email | String | User's email address |
| name | String? | Display name |
| access_token | Text? | Fernet-encrypted Google access token |
| refresh_token | Text? | Fernet-encrypted Google refresh token |
| token_expiry | DateTime? | Token expiration time |
| prompt_notes | Text? | AI-generated preference notes from user feedback |
| updated_at | DateTime | Auto-updated on every change |

### categories

| Column | Type | Notes |
|---|---|---|
| user_id | UUID (FK → users) | CASCADE on delete |
| name | String | Unique per user |
| description | Text? | Guides the classifier |

### email_threads

| Column | Type | Notes |
|---|---|---|
| user_id | UUID (FK → users) | CASCADE on delete |
| gmail_thread_id | String | Unique per user |
| gmail_message_id | String? | Latest message ID |
| subject | String? | From first message headers |
| sender | String? | From first message headers |
| snippet | Text? | Gmail snippet preview |
| date | DateTime? | Parsed from headers |
| category_id | UUID? (FK → categories) | SET NULL on delete |
| is_user_corrected | Boolean | True if user manually reclassified |
| classified_at | DateTime? | When the email was last classified |

## API Endpoints

### Auth (`/api/auth`)

| Method | Path | Description |
|---|---|---|
| GET | `/login` | Initiates Google OAuth flow (redirects to Google) |
| GET | `/callback` | OAuth callback, exchanges code for tokens, creates/updates user, returns JWT via redirect |
| GET | `/demo` | Returns a JWT for the pre-configured demo user (no OAuth required) |
| GET | `/me` | Returns authenticated user info |

### Emails (`/api/emails`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Fetches Gmail threads (up to 200), upserts to DB, classifies unclassified ones, returns all |
| PATCH | `/{email_id}/category` | Reclassifies an email, marks as user-corrected, triggers background feedback learning |
| POST | `/reclassify` | Reclassifies the 200 most recent emails synchronously, returns full `EmailsResponse` |

### Categories (`/api/categories`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Lists user's categories (alphabetical) |
| PUT | `/` | Bulk update categories (add/edit/delete) |
| POST | `/reset` | Resets to default categories |
| GET | `/notes` | Returns user's AI preference notes |
| PUT | `/notes` | Updates user's preference notes |

## Authentication Flow

1. Frontend redirects to `GET /api/auth/login`
2. Backend creates a Google OAuth `Flow` with PKCE, stores `code_verifier` in an HTTP-only cookie, redirects to Google consent screen
3. User consents → Google redirects to `GET /api/auth/callback` with auth code
4. Backend retrieves `code_verifier` from cookie, exchanges code for tokens
5. Verifies the ID token, creates or updates the user, encrypts and stores Google tokens
6. Creates a JWT (1-week expiry) and redirects to frontend with `?token=...`
7. Subsequent requests use `Authorization: Bearer <jwt>` header

### Security

- **PKCE** — `code_verifier` stored in HTTP-only cookie, prevents authorization code interception
- **Fernet encryption** — Google access/refresh tokens encrypted at rest in the database
- **JWT** — session tokens with 1-week expiry, signed with `JWT_SECRET`
- **Scope relaxation** — `OAUTHLIB_RELAX_TOKEN_SCOPE=1` handles Google's scope normalization

## Services

### gmail.py — Gmail API Integration

**`fetch_threads(access_token, refresh_token, max_results=200)`**

Fetches the user's latest email threads using the Gmail API:

1. Lists thread IDs via `threads.list`
2. Batch-fetches full thread metadata in groups of 25 (to stay under rate limits)
3. Retries failed requests up to 2 times with backoff for `429` errors
4. Parses Subject, From, Date headers from the first message in each thread
5. Detects token refresh and returns the new token/expiry so the caller can persist them

**`build_gmail_link(thread_id)`** — constructs a direct Gmail URL for a thread.

### classifier.py — LLM Classification

Uses **GPT-4o-mini** via the OpenAI Responses API.

**Three-part prompt structure:**
1. **Instructions** — system-level context about Inbox Concierge and the classification task
2. **Categories** — user's categories with descriptions
3. **User preference notes** — learned from past corrections, override general intuition

**`classify_emails(emails, categories, user_notes, max_concurrent=20)`** — classifies multiple emails concurrently with a semaphore to limit parallelism. Returns a `{thread_id: category_name}` mapping.

**`apply_classifications(threads, classification_map, categories)`** — sets `category_id` and `classified_at` on ORM objects from the classification map.

**Helper functions:**
- `build_category_dicts(orm_categories)` — converts ORM Category objects to dicts
- `build_emails_for_llm(orm_threads)` — converts ORM EmailThread objects to dicts

### feedback.py — Feedback Learning

Uses **GPT-5.4** (more capable model needed for nuanced reasoning about user intent).

**`learn_from_feedback(email, old_category, new_category, current_notes)`**

When a user reclassifies an email:
1. Provides the email details and the correction to GPT-5.4
2. Prompts the LLM to reason about *why* the email belongs in the new category (topic, content type, purpose) rather than just memorizing the sender
3. Generates updated preference notes that replace the previous ones entirely
4. Notes prefer thematic rules over per-sender rules

**`adapt_notes_for_categories(current_notes, new_categories)`**

Called during reclassification when preference notes exist:
1. Provides the current category set and existing notes to GPT-5.4
2. LLM removes notes referencing deleted categories, adapts notes to renamed categories
3. Returns `None` if no notes remain relevant

## Router Details

### emails.py — `GET /api/emails`

The main data-loading endpoint. Orchestrates:

1. Decrypts Google tokens from DB
2. Fetches Gmail threads (runs in `asyncio.to_thread` since the Google client is synchronous)
3. Persists any refreshed tokens back to DB
4. Upserts email threads (existing = skip, new = insert)
5. Identifies unclassified emails (`category_id IS NULL`)
6. Classifies unclassified emails via the LLM
7. Commits everything and returns the full email list with category names

### emails.py — `PATCH /{email_id}/category`

Handles user reclassification of a single email:

1. Updates `category_id` and sets `is_user_corrected = True`
2. Fires `_run_feedback` as a background task (does not block the response)
3. Background task loads user, calls `learn_from_feedback`, saves updated notes

### emails.py — `POST /api/emails/reclassify`

Reclassifies all emails synchronously and returns the results:

1. Calls `reclassify_all()` which adapts preference notes (if any) and reclassifies the 200 most recent threads
2. Queries the reclassified emails from the DB
3. Returns a full `EmailsResponse` — the frontend updates immediately with no polling

### categories.py — `reclassify_all(user_id, db)`

Shared reclassification logic used by `POST /api/emails/reclassify`:

1. Adapts preference notes to the current category set (if notes exist)
2. Loads the 200 most recent email threads
3. Resets all classifications (`category_id = NULL`, `is_user_corrected = False`)
4. Classifies all threads with the LLM using updated categories and notes
5. Commits the new classifications

### categories.py — `PUT /api/categories`

Saves category changes (add/edit/delete) without triggering reclassification. The frontend decides whether to follow up with a `POST /api/emails/reclassify` call based on the user's action ("Save" vs "Save & Recategorize").

### categories.py — `POST /api/categories/reset`

Resets to default categories without triggering reclassification. The frontend follows up with `POST /api/emails/reclassify` to reclassify all emails.

## Configuration

All settings loaded from `.env` via Pydantic:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (asyncpg) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `OPENAI_API_KEY` | OpenAI API key |
| `JWT_SECRET` | Secret for signing JWTs |
| `ENCRYPTION_KEY` | Fernet key for encrypting stored tokens |
| `FRONTEND_URL` | Frontend URL for CORS and redirects (default: `http://localhost:5173`) |
| `DEMO_USER_GOOGLE_ID` | (Optional) Google ID of the demo user for one-click demo login |

## Key Design Decisions

- **Merged classifications into email_threads** — classification is 1:1 with threads, so a separate table added complexity without benefit. `category_id`, `is_user_corrected`, and `classified_at` live directly on the email thread.
- **Synchronous reclassification** — `POST /api/emails/reclassify` awaits the full reclassification and returns results directly. This eliminates the need for polling or WebSocket push and keeps the frontend simple. Classification of 200 emails takes only a few seconds.
- **Background tasks only for feedback learning** — feedback learning (when a user corrects a single email) still uses `BackgroundTasks` since the user doesn't need to wait for the AI to update preference notes.
- **`asyncio.to_thread` for Gmail API** — the Google client library is synchronous, so it's wrapped in `to_thread` to avoid blocking the event loop.
- **Batch Gmail requests with retries** — batch size of 25 with up to 2 retries and backoff handles Google's per-user rate limits.
- **Two-tier LLM models** — GPT-4o-mini for fast/cheap classification, GPT-5.4 for the harder feedback reasoning task.
- **OpenAI Responses API** — uses the newer `client.responses.create` API with `instructions` and `input` parameters instead of the older chat completions format.
- **`store=False`** — explicitly opts out of OpenAI storing request data.
- **200-thread limit** — reclassification is capped at the 200 most recent threads, matching the Gmail fetch limit, to keep response times reasonable.
