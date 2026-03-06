import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings

logger = logging.getLogger(__name__)


def _build_gmail_service(access_token: str, refresh_token: str) -> tuple[Any, Credentials]:
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    service = build("gmail", "v1", credentials=creds)
    return service, creds


def _extract_header(headers: list[dict], name: str) -> str | None:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def fetch_threads(
    access_token: str, refresh_token: str, max_results: int = 200
) -> tuple[list[dict], str | None, datetime | None]:
    """Fetch the latest threads from Gmail.

    Returns (threads, refreshed_access_token, new_expiry).
    If the token was refreshed, the new token and expiry are returned so the
    caller can persist them. Otherwise they are None.
    """
    service, creds = _build_gmail_service(access_token, refresh_token)

    threads_response = (
        service.users().threads().list(userId="me", maxResults=max_results).execute()
    )
    thread_ids = [t["id"] for t in threads_response.get("threads", [])]

    results = []
    for thread_id in thread_ids:
        try:
            thread = (
                service.users()
                .threads()
                .get(
                    userId="me",
                    id=thread_id,
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                )
                .execute()
            )
        except Exception:
            logger.warning("Failed to fetch thread %s, skipping", thread_id)
            continue

        messages = thread.get("messages", [])
        if not messages:
            continue

        first_message = messages[0]
        latest_message = messages[-1]
        headers = first_message.get("payload", {}).get("headers", [])

        date_str = _extract_header(headers, "Date")
        parsed_date = None
        if date_str:
            try:
                parsed_date = parsedate_to_datetime(date_str)
            except Exception:
                pass

        results.append(
            {
                "gmail_thread_id": thread["id"],
                "gmail_message_id": latest_message["id"],
                "subject": _extract_header(headers, "Subject"),
                "sender": _extract_header(headers, "From"),
                "snippet": thread.get("snippet", ""),
                "date": parsed_date,
            }
        )

    # Check if the token was refreshed during API calls
    new_token = None
    new_expiry = None
    if creds.token != access_token:
        new_token = creds.token
        new_expiry = creds.expiry
        if new_expiry and new_expiry.tzinfo is None:
            new_expiry = new_expiry.replace(tzinfo=timezone.utc)

    return results, new_token, new_expiry


def build_gmail_link(gmail_thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{gmail_thread_id}"
