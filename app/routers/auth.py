from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_jwt, encrypt_token, get_current_user
from app.config import settings
from app.constants import DEFAULT_CATEGORIES
from app.database import get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "openid", "email", "profile"]


def _create_flow(redirect_uri: str) -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


@router.get("/login")
async def login(request: Request):
    redirect_uri = str(request.url_for("auth_callback"))
    flow = _create_flow(redirect_uri)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return RedirectResponse(auth_url)


@router.get("/callback", name="auth_callback")
async def callback(request: Request, code: str, db: AsyncSession = Depends(get_db)):
    redirect_uri = str(request.url_for("auth_callback"))
    flow = _create_flow(redirect_uri)
    flow.fetch_token(code=code)

    credentials = flow.credentials
    id_info = id_token.verify_oauth2_token(
        credentials.id_token,
        google_requests.Request(),
        settings.google_client_id,
    )

    google_id = id_info["sub"]
    email = id_info.get("email", "")
    name = id_info.get("name")

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    is_new_user = user is None
    if is_new_user:
        user = User(google_id=google_id, email=email, name=name)
        db.add(user)

    user.access_token = encrypt_token(credentials.token)
    if credentials.refresh_token:
        user.refresh_token = encrypt_token(credentials.refresh_token)
    if credentials.expiry:
        user.token_expiry = credentials.expiry.replace(tzinfo=timezone.utc)
    user.email = email
    user.name = name

    await db.flush()

    if is_new_user:
        for cat in DEFAULT_CATEGORIES:
            db.add(Category(user_id=user.id, name=cat["name"], description=cat["description"]))

    await db.commit()

    token = create_jwt(user.id)
    return RedirectResponse(f"{settings.frontend_url}?token={token}")


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user
