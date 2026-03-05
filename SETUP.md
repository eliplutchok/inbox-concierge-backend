# Inbox Concierge — Setup Instructions

## Prerequisites

- Python 3.13+
- Node.js 20+
- PostgreSQL (local or hosted)
- A Google Cloud project with Gmail API enabled
- An OpenAI API key

---

## 1. Google Cloud Setup

This is the most involved setup step. You need a Google Cloud project with OAuth credentials.

### Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Name it (e.g., "Inbox Concierge") and create it

### Enable the Gmail API

1. In your project, go to **APIs & Services → Library**
2. Search for "Gmail API" and click **Enable**

### Configure OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Choose **External** user type
3. Fill in the app name ("Inbox Concierge"), user support email, and developer contact email
4. On the **Scopes** step, click "Add or Remove Scopes" and add:
   - `https://www.googleapis.com/auth/gmail.readonly`
5. On the **Test users** step, add your own Gmail address (required while app is in "Testing" mode)
6. Save and continue

### Create OAuth Credentials

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Web application**
4. Name: "Inbox Concierge"
5. **Authorized redirect URIs**: Add your backend callback URL:
   - For local development: `http://localhost:8000/api/auth/callback`
   - For production: `https://your-backend-url.railway.app/api/auth/callback`
6. Click **Create**
7. Copy the **Client ID** and **Client Secret** — you'll need these for `.env`

---

## 2. OpenAI API Key

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Create an account or sign in
3. Go to **API Keys** and create a new key
4. Copy the key — you'll need it for `.env`

---

## 3. Backend Setup

```bash
cd inbox-concierge-backend

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy the example env file and fill in your values
cp .env.example .env
```

### Configure `.env`

Edit `.env` with your actual values:

```
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/inbox_concierge
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
OPENAI_API_KEY=sk-your-openai-api-key
JWT_SECRET=any-random-string-here
ENCRYPTION_KEY=  # Generated below
FRONTEND_URL=http://localhost:5173
```

### Generate an Encryption Key

Run this in Python to generate a Fernet key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output into `ENCRYPTION_KEY` in your `.env`.

### Set Up the Database

```bash
# Create the database (if using local PostgreSQL)
createdb inbox_concierge

# Run migrations
alembic upgrade head
```

### Run the Backend

```bash
uvicorn app.main:app --reload --port 8000
```

---

## 4. Frontend Setup

```bash
cd inbox-concierge-frontend

# Install dependencies
npm install

# Copy the example env file
cp .env.example .env
```

### Configure `.env`

```
VITE_API_URL=http://localhost:8000
```

### Run the Frontend

```bash
npm run dev
```

The app will be available at `http://localhost:5173`.

---

## 5. Railway Deployment

### Create a Railway Project

1. Go to [Railway](https://railway.app/) and sign up / sign in
2. Create a new project

### Add PostgreSQL

1. In your Railway project, click **+ New** → **Database** → **PostgreSQL**
2. Railway will provision a Postgres instance and provide a `DATABASE_URL`

### Deploy the Backend

1. Click **+ New** → **GitHub Repo** → select `inbox-concierge-backend`
2. Railway will auto-detect Python and deploy
3. Add environment variables in the **Variables** tab:
   - `DATABASE_URL` — use the Railway-provided Postgres URL (change the scheme to `postgresql+asyncpg://`)
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
   - `OPENAI_API_KEY`
   - `JWT_SECRET`
   - `ENCRYPTION_KEY`
   - `FRONTEND_URL` — your frontend's Railway URL
4. Update your Google Cloud OAuth **Authorized redirect URIs** to include the Railway backend URL

### Deploy the Frontend

1. Click **+ New** → **GitHub Repo** → select `inbox-concierge-frontend`
2. Add environment variable: `VITE_API_URL` = your backend's Railway URL
3. Railway will build and serve the Vite app

---

## Summary of Required Accounts & Keys

| Item | Where to get it |
|------|----------------|
| Google Cloud Project | [console.cloud.google.com](https://console.cloud.google.com/) |
| Gmail API | Enable in Google Cloud Console |
| OAuth Client ID & Secret | Google Cloud → APIs & Services → Credentials |
| OpenAI API Key | [platform.openai.com](https://platform.openai.com/) |
| Railway Account | [railway.app](https://railway.app/) |
| PostgreSQL | Local install or Railway add-on |
