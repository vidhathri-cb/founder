import io
import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = FastAPI(title="Vidhathri Invoice PDF Service")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REFRESH_TOKEN = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", "")
DRIVE_ACCOUNTING_FOLDER_ID = os.environ.get("DRIVE_ACCOUNTING_FOLDER_ID", "")

NAVY = colors.HexColor("#1F3B57")
GREY = colors.HexColor("#F2F2F2")

# Fixed seller details -- same on every invoice, per the confirmed template
# (Invoice_Generation_Prompt.md, matching sample invoice VFPO/194/2026-27).
SELLER = {
    "name": "Vidhathri Farmers Producer Company Ltd",
    "address_lines": [
        "Raithara Yekathe Kendra, Apmc Yard, Gandhi Maidan,",
        "Kota, Brahmavara Taluk, Udupi Dist",
    ],
    "gstin": "29AAJCV2495A1Z5",
    "state_name": "Karnataka",
    "state_code": "29",
    "contact": "9731247844, 7760377444",
    "email": "vidhathrifpo@gmail.com",
    "bank_account_holder": "Vidhathri Farmers Producer Company Ltd",
    "bank_name": "SBI",
    "bank_account_no": "42785852176",
    "bank_branch_ifsc": "SBI SALIGRAMA & SBIN0014506",
}


# ---------------------------------------------------------------------------
# Amount-in-words (Indian numbering: crore/lakh/thousand/hundred)
# ---------------------------------------------------------------------------

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
]


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")).strip()


def _three_digit_words(n: int) -> str:
    if n >= 100:
        rest = n % 100
        return f"{_ONES[n // 100]} Hundred" + (f" {_two_digit_words(rest)}" if rest else "")
    return _two_digit_words(n)


def _int_to_words_indian(n: int) -> str:
    """Converts a non-negative integer to words using the Indian numbering
    system (crore/lakh/thousand/hundred), e.g. 184029 -> 'One Lakh Eighty
    Four Thousand Twenty Nine'."""
    if n == 0:
        return "Zero"

    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    hundred = n

    if crore:
        parts.append(f"{_three_digit_words(crore)} Crore")
    if lakh:
        parts.append(f"{_two_digit_words(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two_digit_words(thousand)} Thousand")
    if hundred:
        parts.append(_three_digit_words(hundred))

    return " ".join(parts)


def amount_in_words_inr(amount: float) -> str:
    """e.g. 1900.00 -> 'One Thousand Nine Hundred Rupees Only'
    e.g. 1900.50 -> 'One Thousand Nine Hundred Rupees And Fifty Paise Only'"""
    rupees = int(amount)
    paise = round((amount - rupees) * 100)

    words = f"{_int_to_words_indian(rupees)} Rupees"
    if paise:
        words += f" And {_int_to_words_indian(paise)} Paise"
    return words + " Only"


# ---------------------------------------------------------------------------
# Request/response schema
# ---------------------------------------------------------------------------

class LineItem(BaseModel):
    sku: str
    name: str               # invoice description, e.g. "Cold Pressed Coconut Oil 1 litre Bottle"
    hsnCode: str
    quantity: float
    unitPrice: float         # tax-inclusive rate per unit
    gstRate: float           # e.g. 5 for 5%
    taxableValue: float
    cgstAmount: float
    sgstAmount: float
    lineTotal: float         # tax-inclusive
    lineType: str = "NORMAL"


class BillTo(BaseModel):
    name: str
    place: Optional[str] = None
    gstin: Optional[str] = None
    stateName: str = "Karnataka"
    stateCode: str = "29"


class InvoiceRequest(BaseModel):
    saleId: str
    invoiceNumber: str
    invoiceDate: str          # ISO YYYY-MM-DD
    voucherType: str
    billTo: BillTo
    lineItems: List[LineItem]
    subtotal: float           # sum of taxableValue
    cgstTotal: float
    sgstTotal: float
    grandTotal: float


class InvoiceResponse(BaseModel):
    invoiceNumber: str
    fileUrl: str
    driveFileId: str


# ---------------------------------------------------------------------------
# PDF rendering -- matches Invoice_Generation_Prompt.md layout (sample
# invoice VFPO/194/2026-27): header -> seller block -> Tax Invoice title ->
# party block -> line items (with Output CGST/SGST sub-rows) -> amount in
# words -> HSN-wise tax summary -> tax in words -> bank details ->
# declaration -> footer.
# ---------------------------------------------------------------------------

def render_invoice_pdf(inv: InvoiceRequest) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    bold = ParagraphStyle("Bold", parent=normal, fontName="Helvetica-Bold")
    center = ParagraphStyle("Center", parent=normal, alignment=TA_CENTER)
    center_bold = ParagraphStyle("CenterBold", parent=bold, alignment=TA_CENTER)
    right = ParagraphStyle("Right", parent=normal, alignment=TA_RIGHT)
    title_style = ParagraphStyle("Title", parent=styles["Heading2"], alignment=TA_CENTER, textColor=NAVY)

    try:
        invoice_date_display = datetime.strptime(inv.invoiceDate, "%Y-%m-%d").strftime("%d-%b-%y")
    except ValueError:
        invoice_date_display = inv.invoiceDate  # already display-formatted

    story = []

    # 1. Header: Invoice No. / Dated, Ref. No. blank line below
    header_table = Table(
        [["Invoice No.", inv.invoiceNumber, "Dated", invoice_date_display]],
        colWidths=[28 * mm, 62 * mm, 18 * mm, None],
    )
    header_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
        ("ALIGN", (3, 0), (3, 0), "RIGHT"),
    ]))
    story.append(header_table)
    story.append(Paragraph("Ref. No.", ParagraphStyle("Ref", parent=normal, fontSize=9)))
    story.append(Spacer(1, 4 * mm))

    # 2. Seller block (centered)
    story.append(Paragraph(f"<b>{SELLER['name']}</b>", center_bold))
    for line in SELLER["address_lines"]:
        story.append(Paragraph(line, center))
    story.append(Paragraph(f"GSTIN/UIN: {SELLER['gstin']}", center))
    story.append(Paragraph(f"State Name: {SELLER['state_name']}, Code: {SELLER['state_code']}", center))
    story.append(Paragraph(f"Contact: {SELLER['contact']}", center))
    story.append(Paragraph(f"E-Mail: {SELLER['email']}", center))
    story.append(Spacer(1, 3 * mm))

    # 3. Tax Invoice title
    story.append(Paragraph("Tax Invoice", title_style))
    story.append(Spacer(1, 3 * mm))

    # 4. Party block
    party_place = f", {inv.billTo.place}" if inv.billTo.place else ""
    story.append(Paragraph(f"<b>Party : {inv.billTo.name}{party_place}</b>", normal))
    if inv.billTo.gstin:
        story.append(Paragraph(f"GSTIN/UIN : {inv.billTo.gstin}", normal))
    story.append(Paragraph(f"State Name : {inv.billTo.stateName}, Code : {inv.billTo.stateCode}", normal))
    story.append(Spacer(1, 4 * mm))

    # 5. Line items table
    header = ["Sl No.", "Description of Goods", "HSN/SAC", "Quantity", "Rate\n(Incl. of Tax)", "Rate per", "Amount"]
    rows = [header]
    for i, li in enumerate(inv.lineItems, start=1):
        desc = li.name if li.lineType == "NORMAL" else f"{li.name} ({li.lineType})"
        rows.append([
            str(i), desc, li.hsnCode, f"{li.quantity:.2f} Bottles",
            f"{li.unitPrice:,.2f}", "1 Bottle", f"{li.lineTotal:,.2f}",
        ])

    total_cgst = sum(li.cgstAmount for li in inv.lineItems)
    total_sgst = sum(li.sgstAmount for li in inv.lineItems)
    rows.append(["", "", "", "", "", "Output CGST", f"{total_cgst:,.2f}"])
    rows.append(["", "", "", "", "", "Output SGST", f"{total_sgst:,.2f}"])
    total_qty = sum(li.quantity for li in inv.lineItems)
    # Helvetica (base PDF font) has no Rupee-sign glyph -- "Rs." avoids a
    # missing-glyph box rendering in place of "₹".
    rows.append(["", "Total", "", f"{total_qty:.2f} Bottles", "", "", f"Rs. {inv.grandTotal:,.2f}"])

    items_table = Table(rows, colWidths=[12 * mm, 55 * mm, 18 * mm, 22 * mm, 24 * mm, 22 * mm, 25 * mm])
    n_lines = len(inv.lineItems)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, n_lines), 0.5, colors.grey),
        ("LINEBELOW", (0, -1), (-1, -1), 0.75, colors.black),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4 * mm))

    # 6. Amount chargeable in words
    story.append(Table(
        [[Paragraph("<b>Amount Chargeable (in words)</b>", normal), Paragraph("E. & O.E", right)]],
        colWidths=[140 * mm, None],
    ))
    story.append(Paragraph(f"<b>INR {amount_in_words_inr(inv.grandTotal)}</b>", normal))
    story.append(Spacer(1, 4 * mm))

    # 7. HSN-wise tax summary
    by_hsn = {}
    for li in inv.lineItems:
        agg = by_hsn.setdefault(li.hsnCode, {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "rate": li.gstRate})
        agg["taxable"] += li.taxableValue
        agg["cgst"] += li.cgstAmount
        agg["sgst"] += li.sgstAmount

    tax_header = ["HSN/SAC", "Taxable Value", "CGST Rate", "CGST Amount", "SGST/UTGST Rate", "SGST Amount", "Total Tax Amount"]
    tax_rows = [tax_header]
    total_taxable = total_cgst_2 = total_sgst_2 = total_tax = 0.0
    for hsn, agg in by_hsn.items():
        half_rate = agg["rate"] / 2
        line_tax = agg["cgst"] + agg["sgst"]
        tax_rows.append([
            hsn, f"{agg['taxable']:,.2f}", f"{half_rate:g}%", f"{agg['cgst']:,.2f}",
            f"{half_rate:g}%", f"{agg['sgst']:,.2f}", f"{line_tax:,.2f}",
        ])
        total_taxable += agg["taxable"]
        total_cgst_2 += agg["cgst"]
        total_sgst_2 += agg["sgst"]
        total_tax += line_tax
    tax_rows.append(["Total", f"{total_taxable:,.2f}", "", f"{total_cgst_2:,.2f}", "", f"{total_sgst_2:,.2f}", f"{total_tax:,.2f}"])

    tax_table = Table(tax_rows, colWidths=[20 * mm, 26 * mm, 18 * mm, 24 * mm, 22 * mm, 22 * mm, 26 * mm])
    tax_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tax_table)
    story.append(Spacer(1, 3 * mm))

    # 8. Tax amount in words
    story.append(Paragraph(f"<b>Tax Amount (in words) : INR {amount_in_words_inr(total_tax)}</b>", normal))
    story.append(Spacer(1, 5 * mm))

    # 9. Bank details
    story.append(Paragraph("<b>Company's Bank Details</b>", normal))
    story.append(Paragraph(f"A/c Holder's Name: {SELLER['bank_account_holder']}", normal))
    story.append(Paragraph(f"Bank Name: {SELLER['bank_name']}", normal))
    story.append(Paragraph(f"A/c No.: {SELLER['bank_account_no']}", normal))
    story.append(Paragraph(f"Branch & IFS Code: {SELLER['bank_branch_ifsc']}", normal))
    story.append(Spacer(1, 5 * mm))

    # 10. Declaration
    decl_table = Table([[
        Paragraph(
            "<b>Declaration</b><br/>We declare that this invoice shows the actual price of the goods "
            "described and that all particulars are true and correct.",
            normal,
        ),
        Paragraph(f"for {SELLER['name']}<br/><br/><br/>Authorised Signatory", right),
    ]], colWidths=[110 * mm, None])
    story.append(decl_table)
    story.append(Spacer(1, 6 * mm))

    # 11. Footer
    story.append(Paragraph("This is a Computer Generated Invoice", ParagraphStyle("Footer", parent=center, fontSize=8, textColor=colors.grey)))

    doc.build(story)
    return buf.getvalue()


def find_or_create_folder(drive, name: str, parent_id: str) -> str:
    query = (
        f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    resp = drive.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    created = drive.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
        fields="id",
    ).execute()
    return created["id"]


def get_voucher_month_folder(drive, voucher_type: str, invoice_date: str) -> str:
    dt = datetime.strptime(invoice_date, "%Y-%m-%d")
    voucher_folder_id = find_or_create_folder(drive, voucher_type, DRIVE_ACCOUNTING_FOLDER_ID)
    year_folder_id = find_or_create_folder(drive, f"{dt.year:04d}", voucher_folder_id)
    month_folder_id = find_or_create_folder(drive, f"{dt.month:02d}", year_folder_id)
    return month_folder_id


def upload_to_drive(pdf_bytes: bytes, filename: str, voucher_type: str, invoice_date: str) -> tuple[str, str]:
    if not (GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REFRESH_TOKEN and DRIVE_ACCOUNTING_FOLDER_ID):
        raise RuntimeError("Google OAuth credentials / DRIVE_ACCOUNTING_FOLDER_ID not configured")

    creds = UserCredentials(
        None,
        refresh_token=GOOGLE_OAUTH_REFRESH_TOKEN,
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    drive = build("drive", "v3", credentials=creds)

    target_folder_id = get_voucher_month_folder(drive, voucher_type, invoice_date)

    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf", resumable=False)
    file_metadata = {"name": filename, "parents": [target_folder_id]}
    created = drive.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    return created["id"], created["webViewLink"]


@app.post("/generate-invoice", response_model=InvoiceResponse)
def generate_invoice(inv: InvoiceRequest):
    try:
        pdf_bytes = render_invoice_pdf(inv)
        filename = f"{inv.invoiceNumber.replace('/', '_')}.pdf"
        file_id, url = upload_to_drive(pdf_bytes, filename, inv.voucherType, inv.invoiceDate)
        return InvoiceResponse(invoiceNumber=inv.invoiceNumber, fileUrl=url, driveFileId=file_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
