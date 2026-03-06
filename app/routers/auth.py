import asyncio
import logging
import os
from datetime import datetime, timezone

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import APIRouter, Depends, HTTPException, Request
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

logger = logging.getLogger(__name__)

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
    response = RedirectResponse(auth_url)
    if flow.code_verifier:
        response.set_cookie(
            "code_verifier", flow.code_verifier, httponly=True, max_age=600, samesite="lax"
        )
    return response


@router.get("/callback", name="auth_callback")
async def callback(request: Request, code: str, db: AsyncSession = Depends(get_db)):
    redirect_uri = str(request.url_for("auth_callback"))
    flow = _create_flow(redirect_uri)

    code_verifier = request.cookies.get("code_verifier")
    flow.code_verifier = code_verifier

    try:
        await asyncio.to_thread(flow.fetch_token, code=code)
    except Exception:
        logger.exception("OAuth token exchange failed")
        return RedirectResponse(f"{settings.frontend_url}?error=auth_failed")

    credentials = flow.credentials

    try:
        id_info = await asyncio.to_thread(
            id_token.verify_oauth2_token,
            credentials.id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception:
        logger.exception("ID token verification failed")
        return RedirectResponse(f"{settings.frontend_url}?error=auth_failed")

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
    response = RedirectResponse(f"{settings.frontend_url}?token={token}")
    response.delete_cookie("code_verifier")
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user
