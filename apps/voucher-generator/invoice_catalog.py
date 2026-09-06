"""
SKU -> invoice-specific description/HSN mapping.

sales.products.name holds a short internal name (e.g. "Cold Pressed Oil
Bottle 1 litre") that's different from the exact wording confirmed for the
printed invoice (e.g. "Cold Pressed Coconut Oil 1 litre Bottle"), and HSN/SAC
isn't stored in sales.products at all yet. Kept as its own hardcoded table
here -- same "hardcoded for now" pattern as distribution-order-ingest's old
SKU_ALIASES and sales-ingest's LINE_TYPE_TO_MOVEMENT -- until there's reason
to move this into the database itself.
"""

INVOICE_LINE_INFO = {
    "CP-1000ML": {"description": "Cold Pressed Coconut Oil 1 litre Bottle", "hsn_code": "15131900"},
    "CP-500ML": {"description": "Cold Pressed Coconut Oil 500 ml Bottle", "hsn_code": "15131900"},
    "HCW-250ML": {"description": "Health Care and Wellness Oil 250 ml Bottle", "hsn_code": "15131900"},
    "HO-100ML": {"description": "Hair Oil 100 ml Bottle", "hsn_code": "15131900"},
}


class UnknownSkuForInvoiceError(Exception):
    """Raised when a sale_item's SKU has no invoice description/HSN mapping
    -- flag and escrow rather than guess at legally-required invoice text."""


def get_invoice_line_info(sku: str) -> dict:
    key = sku.strip().upper()
    if key not in INVOICE_LINE_INFO:
        raise UnknownSkuForInvoiceError(
            f"SKU '{sku}' has no invoice description/HSN mapping in INVOICE_LINE_INFO -- add it before invoicing this sale."
        )
    return INVOICE_LINE_INFO[key]
