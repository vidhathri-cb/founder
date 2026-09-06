"""
Google Drive download client -- fetches a voucher PDF by its Drive file id
(sales.invoices.drive_file_id) for the monthly CA export. Kept as its own
standalone file, independent of mail_service.py.

Uses the same user-OAuth Credentials pattern pdfservice already uses (not a
service account).

Env vars (falls back to GOOGLE_OAUTH_* if DRIVE_-prefixed ones aren't set):
    GOOGLE_OAUTH_CLIENT_ID / DRIVE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET / DRIVE_OAUTH_CLIENT_SECRET
    GOOGLE_OAUTH_REFRESH_TOKEN / DRIVE_OAUTH_REFRESH_TOKEN
"""

import os

from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from common.env import env as _env


def _get_credentials() -> UserCredentials:
    client_id = _env("DRIVE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_ID")
    client_secret = _env("DRIVE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = _env("DRIVE_OAUTH_REFRESH_TOKEN", "GOOGLE_OAUTH_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("Drive OAuth credentials not configured (need client id/secret/refresh token).")

    return UserCredentials(
        None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def download_drive_file(drive_file_id: str) -> bytes:
    creds = _get_credentials()
    drive = build("drive", "v3", credentials=creds)
    return drive.files().get_media(fileId=drive_file_id).execute()
