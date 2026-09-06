"""
Mail-sending service -- sends the monthly CA export email (and, if a future
use case needs it, any other outbound mail) via the Gmail API, from
vidhathrifpo@gmail.com. Kept as its own standalone file, independent of
drive_client.py, so the two can be read/tested/replaced separately.

Uses the same user-OAuth Credentials pattern pdfservice already uses (not a
service account) -- see "Generating the OAuth refresh token" in the README
for how to actually produce GOOGLE_OAUTH_REFRESH_TOKEN.

IMPORTANT -- scope gap, not yet resolved: pdfservice's existing OAuth
consent only requested the Drive scope (drive.file), for uploading
invoices it creates. Sending Gmail needs the separate gmail.send scope,
which that existing refresh token almost certainly does NOT carry -- scopes
are fixed at consent time, so reusing GOOGLE_OAUTH_REFRESH_TOKEN as-is will
likely fail with an insufficient-scope error until a fresh OAuth consent is
done covering BOTH scopes together. See the README for the full walkthrough.

Env vars (falls back to the same GOOGLE_OAUTH_* pdfservice already uses if
the GMAIL_-prefixed ones aren't set, since it's typically the same OAuth
client either way):
    GOOGLE_OAUTH_CLIENT_ID / GMAIL_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET / GMAIL_OAUTH_CLIENT_SECRET
    GOOGLE_OAUTH_REFRESH_TOKEN / GMAIL_OAUTH_REFRESH_TOKEN
"""

import os
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.env import env as _env


def _get_credentials() -> UserCredentials:
    client_id = _env("GMAIL_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_ID")
    client_secret = _env("GMAIL_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = _env("GMAIL_OAUTH_REFRESH_TOKEN", "GOOGLE_OAUTH_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("Gmail OAuth credentials not configured (need client id/secret/refresh token).")

    return UserCredentials(
        None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def send_email_with_attachments(to: str, subject: str, body_text: str, attachments: list[tuple[str, bytes]], sender: str = "me") -> dict:
    """attachments: list of (filename, pdf_bytes). Sends from the
    authenticated Gmail account (the account behind the OAuth credentials
    above -- vidhathrifpo@gmail.com)."""
    creds = _get_credentials()
    gmail = build("gmail", "v1", credentials=creds)

    message = MIMEMultipart()
    message["to"] = to
    message["subject"] = subject
    message.attach(MIMEText(body_text))

    for filename, pdf_bytes in attachments:
        part = MIMEApplication(pdf_bytes, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(part)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return gmail.users().messages().send(userId=sender, body={"raw": raw}).execute()
