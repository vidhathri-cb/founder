"""
Static marketing/template copy for the B2C ad-campaign flow (v1), matching
the flow the user specified directly. Fixed for now -- not campaign-specific
except Combo Details, since there's only one test campaign; if copy needs to
vary per campaign later, this is the first place that would need to become
data-driven instead of hardcoded.
"""

WELCOME_MESSAGE = (
    "Namaste! Welcome to Vidhathri Farmers Producer Company \U0001F965\n"
    "Thank you for choosing pure, farm-gate direct Coconut Oil. "
    "How can we help you today?"
)
WELCOME_BUTTONS = ["Order Now", "Combo Details", "Contact Us"]

ORDER_NOW_STEP1 = (
    "We are not \"white-labelers who can't control mineral oil adulteration\""
    "—that’s why our product is 100% safe and pure! \U0001F6E1️\n\n"
    "Please share your details to reserve your combo:\n"
    "• Full Name:\n"
    "• Shipping Address (House/Door No, Street, Landmark):\n"
    "• Pincode:\n"
    "• Shipping Phone Number:"
)

ORDER_NOW_STEP2 = (
    "We are not \"manufacturers who source copra from traders to process via "
    "expellers\"—that’s why our production is 100% organic and "
    "farm-gate direct! \U0001F33F"
)

ORDER_NOW_STEP3 = (
    "We are not \"traders who procure from unknown farms using chemical "
    "fertilizers\"—that’s why you get 100% natural produce direct "
    "from our farmer-owned groves. \U0001F331\n\n"
    "We will confirm your order shortly! Our team is verifying your delivery "
    "details and will message you here with the payment link and shipping "
    "timeline. \U0001F69A"
)

CONTACT_US_MESSAGE = (
    "We're here to help! \U0001F4DE\n"
    "You can ask us any questions about our extraction methods, sourcing, or "
    "bulk orders right here.\n"
    "A team member from Vidhathri Farmers Producer Company will respond to "
    "this chat within a few minutes!"
)

COMBO_DETAILS_BUTTONS = ["Order Now", "Contact Us"]


def combo_details_card(campaign: dict) -> str:
    """
    Built from campaign data (campaigns.description, campaigns.display_price)
    rather than hardcoded copy, so this can never drift from what an order
    for this campaign will actually contain (campaign_combo_items).
    """
    lines = ["Vidhathri Pure Coconut Oil Combo Pack \U0001F965", ""]

    if campaign.get("description"):
        lines.append(campaign["description"])
    else:
        for item in campaign.get("campaign_combo_items", []):
            product = item.get("products", {})
            lines.append(f"• {item['quantity']}x {product.get('name', product.get('sku', '?'))}")

    lines.append("")
    if campaign.get("display_price") is not None:
        lines.append(
            f"\U0001F4B3 Special Direct-from-Farmer Price: ₹{float(campaign['display_price']):.0f} "
            "(Incl. taxes & delivery)"
        )

    return "\n".join(lines)
