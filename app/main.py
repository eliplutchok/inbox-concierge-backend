from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, categories, classifications, emails

app = FastAPI(title="Inbox Concierge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(emails.router)
app.include_router(categories.router)
app.include_router(classifications.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
