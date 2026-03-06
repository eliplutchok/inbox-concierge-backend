import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import BatchHttpRequest

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


def _parse_thread(thread: dict) -> dict | None:
    messages = thread.get("messages", [])
    if not messages:
        return None

    first_message = messages[0]
    latest_message = messages[-1]
    headers = first_message.get("payload", {}).get("headers", [])

    date_str = _extract_header(headers, "Date")
    parsed_date = None
    if date_str:
        try:
            parsed_date = parsedate_to_datetime(date_str)
        except Exception:
            logger.debug("Failed to parse date: %r", date_str)

    return {
        "gmail_thread_id": thread["id"],
        "gmail_message_id": latest_message["id"],
        "subject": _extract_header(headers, "Subject"),
        "sender": _extract_header(headers, "From"),
        "snippet": thread.get("snippet", ""),
        "date": parsed_date,
    }


def fetch_threads(
    access_token: str, refresh_token: str, max_results: int = 200
) -> tuple[list[dict], str | None, datetime | None]:
    """Fetch the latest threads from Gmail using batch requests.

    Returns (threads, refreshed_access_token, new_expiry).
    If the token was refreshed, the new token and expiry are returned so the
    caller can persist them. Otherwise they are None.
    """
    service, creds = _build_gmail_service(access_token, refresh_token)

    threads_response = (
        service.users().threads().list(userId="me", maxResults=max_results).execute()
    )
    thread_ids = [t["id"] for t in threads_response.get("threads", [])]

    if not thread_ids:
        return [], None, None

    results: dict[str, dict] = {}
    failed_ids: list[str] = []

    def _handle_thread_response(request_id: str, response: dict, exception: Exception | None):
        if exception:
            failed_ids.append(request_id)
            logger.warning("Failed to fetch thread %s: %s", request_id, exception)
            return
        parsed = _parse_thread(response)
        if parsed:
            results[request_id] = parsed

    batch_size = 25
    max_retries = 2

    remaining_ids = list(thread_ids)
    for attempt in range(1 + max_retries):
        if not remaining_ids:
            break

        if attempt > 0:
            time.sleep(1 * attempt)
            logger.info("Retrying %d failed threads (attempt %d)", len(remaining_ids), attempt + 1)

        failed_ids = []
        for i in range(0, len(remaining_ids), batch_size):
            batch: BatchHttpRequest = service.new_batch_http_request(callback=_handle_thread_response)
            for thread_id in remaining_ids[i : i + batch_size]:
                batch.add(
                    service.users().threads().get(
                        userId="me",
                        id=thread_id,
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    ),
                    request_id=thread_id,
                )
            batch.execute()

        remaining_ids = failed_ids

    ordered_results = [results[tid] for tid in thread_ids if tid in results]

    new_token = None
    new_expiry = None
    if creds.token != access_token:
        new_token = creds.token
        new_expiry = creds.expiry
        if new_expiry and new_expiry.tzinfo is None:
            new_expiry = new_expiry.replace(tzinfo=timezone.utc)

    logger.info("Fetched %d threads in %d batch(es)", len(ordered_results), -(-len(thread_ids) // batch_size))
    return ordered_results, new_token, new_expiry


def build_gmail_link(gmail_thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{gmail_thread_id}"
