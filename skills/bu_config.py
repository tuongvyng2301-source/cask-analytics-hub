"""
Business Unit (BU) configuration.

3 BUs, 8 khoá:
- BU1: AOP, Finance, Brand
- BU2: Trade, RTM, Data
- BU3: KAM, Ecom
"""
from __future__ import annotations

BU_CONFIG = {
    "BU1": {"label": "BU1 — AOP / Finance / Brand", "khoa": ["AOP", "Finance", "Brand"]},
    "BU2": {"label": "BU2 — Trade / RTM / Trade Data", "khoa": ["Trade", "RTM", "Data"]},
    "BU3": {"label": "BU3 — KAM / Ecom", "khoa": ["KAM", "Ecom"]},
}

KHOA_TO_BU = {k: bu for bu, cfg in BU_CONFIG.items() for k in cfg["khoa"]}

ALL_KHOA = list(KHOA_TO_BU.keys())

# Color code per khoá (HEX) — apply cho section headers, cards, funnel stage 1
KHOA_COLORS = {
    "Brand":   "#c0392b",  # đỏ
    "KAM":     "#2c7be5",  # xanh dương sáng
    "Ecom":    "#8e44ad",  # tím
    "Trade":   "#2e7d32",  # xanh lá
    "Data":    "#1565c0",  # xanh dương đậm (Trade Data)
    "RTM":     "#f59f00",  # vàng cam
    "Finance": "#5e35b1",  # tím xanh đậm (deep purple)
    "AOP":     "#1a237e",  # xanh dương navy đen
}


def khoa_color(khoa: str, default: str = "#2d5a3d") -> str:
    return KHOA_COLORS.get(khoa, default)


# Product (in lead tracking) → Khoá mapping (substring match, case insensitive)
# Order matters: more specific first
PRODUCT_TO_KHOA = [
    # Data (more specific than Trade)
    ("data trade", "Data"),
    ("trade data", "Data"),
    # Trade variants
    ("trade long", "Trade"),
    ("trade short", "Trade"),
    ("impactful trade", "Trade"),
    ("trade marketing", "Trade"),
    # RTM
    ("rtm", "RTM"),
    # BU3
    ("kam", "KAM"),
    ("key account", "KAM"),
    ("ecom", "Ecom"),
    ("ecommerce", "Ecom"),
    ("e-commerce", "Ecom"),
    # BU1
    ("aop", "AOP"),
    ("annual operating", "AOP"),
    ("finance", "Finance"),
    ("non-finance", "Finance"),
    ("brand", "Brand"),
    ("branding", "Brand"),
    # Fallback for generic "Trade" — keep at end so specific variants match first
    ("trade", "Trade"),
]


def product_to_khoa(product: str) -> str | None:
    """Map free-text Product column to standard khoá."""
    if not product:
        return None
    text = str(product).lower().strip()
    if not text:
        return None
    for kw, khoa in PRODUCT_TO_KHOA:
        if kw in text:
            return khoa
    return None


def filter_khoa_by_bu(bu: str) -> list[str]:
    """Return list of khoá belonging to a BU."""
    return BU_CONFIG.get(bu, {}).get("khoa", [])
