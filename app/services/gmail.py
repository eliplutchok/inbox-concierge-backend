import base64
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings


def _build_gmail_service(access_token: str, refresh_token: str) -> any:
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    return build("gmail", "v1", credentials=creds)


def _extract_header(headers: list[dict], name: str) -> str | None:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def fetch_threads(access_token: str, refresh_token: str, max_results: int = 200) -> list[dict]:
    """Fetch the latest threads from Gmail and return normalized metadata."""
    service = _build_gmail_service(access_token, refresh_token)

    threads_response = (
        service.users().threads().list(userId="me", maxResults=max_results).execute()
    )
    thread_ids = [t["id"] for t in threads_response.get("threads", [])]

    results = []
    for thread_id in thread_ids:
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="metadata", metadataHeaders=["Subject", "From", "Date"])
            .execute()
        )

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
                from email.utils import parsedate_to_datetime
                parsed_date = parsedate_to_datetime(date_str)
            except Exception:
                pass

        results.append({
            "gmail_thread_id": thread["id"],
            "gmail_message_id": latest_message["id"],
            "subject": _extract_header(headers, "Subject"),
            "sender": _extract_header(headers, "From"),
            "snippet": thread.get("snippet", ""),
            "date": parsed_date,
        })

    return results


def build_gmail_link(gmail_thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{gmail_thread_id}"
