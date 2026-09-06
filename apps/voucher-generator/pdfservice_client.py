"""
HTTP client for the pdfservice (founder-panel/src/pdfservice) that turns an
InvoiceRequest payload into a PDF and returns its Drive file URL.

Requires env var:
    PDFSERVICE_URL -- defaults to the live founder-panel Render service.
"""

import os
import requests

PDFSERVICE_URL = os.environ.get("PDFSERVICE_URL", "https://founder-panel.onrender.com")


class PdfServiceError(Exception):
    """Raised on a non-2xx response or network failure -- caller should
    flag/escrow this sale's invoice generation rather than retry blindly."""


def generate_invoice_pdf(payload: dict, timeout: int = 30) -> dict:
    """POSTs to /generate-invoice. Returns the response dict
    ({invoiceNumber, fileUrl, driveFileId}) on success."""
    url = f"{PDFSERVICE_URL.rstrip('/')}/generate-invoice"
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise PdfServiceError(f"Could not reach pdfservice at {url}: {e}") from e

    if not response.ok:
        raise PdfServiceError(f"pdfservice returned {response.status_code}: {response.text}")

    return response.json()
