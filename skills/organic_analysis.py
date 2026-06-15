"""
Skill: Organic Content Analysis (Facebook Page posts)
Input: Facebook Page Insights CSV export
Output: dict with per-khoa metrics + funnel + top/bottom + V/R proxy

Categorization keywords (priority: KAM > RTM > Trade)
"""
from __future__ import annotations
import re
import statistics
import pandas as pd


KHOA_KEYWORDS = {
    # BU3 — more specific so check first
    "KAM": [
        "kam", "key account", "buyer→", "buyer ->", "gmroi", "jbp",
        "ebook kam", "7 nghiệp vụ kam", "vòng quay", "lợi nhuận trên mét kệ",
        "cask x orion", "orion kam", "modern trade channel capability",
    ],
    "Ecom": [
        "ecommerce", "ecom", "e-commerce", "tmđt", "tmdt",
        "design winning ecommerce", "ecom16", "shopee", "lazada", "tiktok shop",
        "gian hàng", "sàn tmđt", "flash sale", "campaign sàn",
    ],
    # BU2
    "Data": [
        "trade data", "data analytics", "trade data analytics",
        "phân tích dữ liệu thương mại", "sell-out từ điển", "data dashboard",
    ],
    "RTM": [
        "rtm", "route to market", "route plan", "sales sup",
        " asm ", " rsm ", "coverage plan", "sales sup → asm",
        "tuyến bán hàng", "phân phối",
    ],
    "Trade": [
        "trade marketing", "trade mkter", "trade marketer", "posm",
        "shopper", "shelfzone", "modern trade", "availability", "visibility",
        "sampling", "distribution", "sell-out", "đẩy hàng",
        "thị trường bán lẻ", "channel mt", "impactfultrade", "tradek3",
        "ms thấp", "sos cao", "33% bán lẻ",
        "stock khi tung", "tung sản phẩm mới",
    ],
    # BU1
    "AOP": [
        "aop", "annual operating plan", "annual operating",
        "kế hoạch hoạt động kinh doanh hằng năm", "p&l framework",
        "revenue forecast", "scenario 3 cấp", "alignment",
    ],
    "Finance": [
        "finance for non-finance", "finance 3", "non-finance manager",
        "tài chính cho ceo", "đọc p&l", "đọc báo cáo tài chính",
    ],
    "Brand": [
        "brand building", "journey of brand", "thương hiệu",
        "brand plan", "brand identity", "brand positioning",
        "marketing manager", "the journey of brand", "tốt nghiệp brand",
        "brand 33", "ngày brand", "brand mkt",
    ],
}

# Priority order: most specific first
KHOA_PRIORITY = ["KAM", "Ecom", "Data", "RTM", "AOP", "Finance", "Brand", "Trade"]


def _safe_num(val) -> float:
    try:
        v = pd.to_numeric(val, errors="coerce")
        if pd.isna(v):
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def categorize_post(title: str, description: str) -> str | None:
    text = (str(title or "") + " " + str(description or "")).lower()
    if not text.strip():
        return None
    for khoa in KHOA_PRIORITY:
        if any(kw in text for kw in KHOA_KEYWORDS[khoa]):
            return khoa
    return None


def categorize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Add __category column to dataframe (in place returns new df)."""
    df = df.copy()
    cols = {c.lower(): c for c in df.columns}
    c_title = cols.get("title")
    c_desc = cols.get("description")
    df["__category"] = df.apply(
        lambda r: categorize_post(
            r.get(c_title) if c_title else "",
            r.get(c_desc) if c_desc else "",
        ),
        axis=1,
    )
    return df


def find_ambiguous_posts(df: pd.DataFrame, focus_khoa: list[str] | None = None) -> list[dict]:
    """Return list of posts that didn't categorize automatically.

    If focus_khoa provided, also flag posts categorized OUT of focus list (BU mismatch).
    """
    df = categorize_dataframe(df)
    cols = {c.lower(): c for c in df.columns}
    c_desc = cols.get("description")
    c_date = cols.get("publish time") or cols.get("date")
    c_type = cols.get("post type")
    c_permalink = cols.get("permalink")
    c_reach = cols.get("reach")

    ambiguous = []
    for idx, r in df.iterrows():
        cat = r.get("__category")
        is_uncategorized = cat is None or (isinstance(cat, float) and pd.isna(cat))
        if is_uncategorized:
            desc = str(r.get(c_desc, "") if c_desc else "")
            first_line = desc.split("\n")[0].strip()[:120] or "(no description)"
            ambiguous.append({
                "row_index": int(idx),
                "date": str(r.get(c_date, "") if c_date else "")[:10],
                "post_type": str(r.get(c_type, "") if c_type else ""),
                "title_short": first_line,
                "reach": int(_safe_num(r.get(c_reach)) if c_reach else 0),
                "permalink": str(r.get(c_permalink, "") if c_permalink else ""),
                "suggested_khoa": None,
            })
    return ambiguous


def list_all_posts_with_category(df: pd.DataFrame, focus_khoa: list[str] | None = None) -> list[dict]:
    """Return ALL posts with auto-categorized khoá (user can override).

    Returns:
        [{
            "row_index": int,
            "date": str,
            "post_type": str,
            "title_short": str,
            "reach": int,
            "permalink": str,
            "auto_khoa": str | None,       # what categorizer assigned
            "is_in_focus": bool,           # khoá thuộc BU đang chọn
            "is_uncategorized": bool,      # categorizer failed
        }, ...]
    """
    from .bu_config import ALL_KHOA
    if focus_khoa is None:
        focus_khoa = ALL_KHOA

    df = categorize_dataframe(df)
    cols = {c.lower(): c for c in df.columns}
    c_desc = cols.get("description")
    c_date = cols.get("publish time") or cols.get("date")
    c_type = cols.get("post type")
    c_permalink = cols.get("permalink")
    c_reach = cols.get("reach")

    out = []
    for idx, r in df.iterrows():
        cat = r.get("__category")
        is_uncategorized = cat is None or (isinstance(cat, float) and pd.isna(cat))
        cat_val = None if is_uncategorized else str(cat)
        desc = str(r.get(c_desc, "") if c_desc else "")
        first_line = desc.split("\n")[0].strip()[:120] or "(no description)"
        out.append({
            "row_index": int(idx),
            "date": str(r.get(c_date, "") if c_date else "")[:10],
            "post_type": str(r.get(c_type, "") if c_type else ""),
            "title_short": first_line,
            "reach": int(_safe_num(r.get(c_reach)) if c_reach else 0),
            "permalink": str(r.get(c_permalink, "") if c_permalink else ""),
            "auto_khoa": cat_val,
            "is_in_focus": (cat_val in focus_khoa) if cat_val else False,
            "is_uncategorized": is_uncategorized,
        })
    return out


def analyze_organic(df: pd.DataFrame, focus_khoa: list[str] | None = None, manual_labels: dict[int, str] | None = None) -> dict:
    """Analyze Facebook Page Insights CSV.

    Args:
        df: raw DataFrame from CSV
        focus_khoa: list of khoá to include (filter for BU). None = all 8 khoá.
        manual_labels: {row_index: khoá} for ambiguous posts the user manually assigned.

    Returns dict with khoa breakdown.
    """
    df = df.copy()
    manual_labels = manual_labels or {}

    # Normalize column lookups (case-insensitive partial match)
    def col(name):
        for c in df.columns:
            if c.lower().strip() == name.lower().strip():
                return c
        return None

    c_title = col("Title")
    c_desc = col("Description")
    c_date = col("Publish time") or col("Date")
    c_reach = col("Reach")
    c_views = col("Views")
    c_rcs = col("Reactions, Comments and Shares")
    c_react = col("Reactions")
    c_cmts = col("Comments")
    c_shares = col("Shares")
    c_link_clicks = col("Link Clicks") or col("Link clicks")
    c_total_clicks = col("Total clicks") or col("Total Clicks")
    c_other_clicks = col("Other Clicks") or col("Other clicks")
    c_post_type = col("Post type") or col("Post Type")
    c_permalink = col("Permalink")

    if not c_desc and not c_title:
        raise ValueError("CSV không có cột 'Description' hoặc 'Title' để categorize")

    df["__category"] = df.apply(
        lambda r: categorize_post(
            r.get(c_title) if c_title else "",
            r.get(c_desc) if c_desc else "",
        ),
        axis=1,
    )

    # Apply manual labels: override khoá OR skip (__SKIP__)
    for row_idx, khoa in manual_labels.items():
        if not khoa or not (0 <= row_idx < len(df)):
            continue
        if khoa == "__SKIP__":
            df.at[df.index[row_idx], "__category"] = None
        else:
            df.at[df.index[row_idx], "__category"] = khoa

    in_scope = df[df["__category"].notna()].copy()

    # Determine which khoá to include
    if focus_khoa is None:
        from .bu_config import ALL_KHOA
        focus_khoa = ALL_KHOA

    khoa_data = {}
    for k in focus_khoa:
        sub = in_scope[in_scope["__category"] == k]
        posts = []
        for _, r in sub.iterrows():
            reach = int(_safe_num(r.get(c_reach)) if c_reach else 0)
            rcs = int(_safe_num(r.get(c_rcs)) if c_rcs else 0)
            link_clicks = int(_safe_num(r.get(c_link_clicks)) if c_link_clicks else 0)
            desc = str(r.get(c_desc, "") if c_desc else "")
            first_line = desc.split("\n")[0].strip()[:90] or "(no description)"

            posts.append({
                "date": str(r.get(c_date, "") if c_date else ""),
                "title_short": first_line,
                "post_type": str(r.get(c_post_type, "") if c_post_type else ""),
                "reach": reach,
                "views": int(_safe_num(r.get(c_views)) if c_views else 0),
                "reactions": int(_safe_num(r.get(c_react)) if c_react else 0),
                "comments": int(_safe_num(r.get(c_cmts)) if c_cmts else 0),
                "shares": int(_safe_num(r.get(c_shares)) if c_shares else 0),
                "rcs": rcs,
                "link_clicks": link_clicks,
                "total_clicks": int(_safe_num(r.get(c_total_clicks)) if c_total_clicks else 0),
                "other_clicks": int(_safe_num(r.get(c_other_clicks)) if c_other_clicks else 0),
                "er": (rcs / reach * 100) if reach else 0,
                "permalink": str(r.get(c_permalink, "") if c_permalink else ""),
            })

        posts.sort(key=lambda p: -p["er"])

        total_reach = sum(p["reach"] for p in posts)
        total_views = sum(p["views"] for p in posts)
        total_rcs = sum(p["rcs"] for p in posts)
        total_link_clicks = sum(p["link_clicks"] for p in posts)
        total_shares = sum(p["shares"] for p in posts)

        khoa_data[k] = {
            "posts": posts,
            "n_posts": len(posts),
            "total_reach": total_reach,
            "total_views": total_views,
            "total_engagement": total_rcs,
            "total_link_clicks": total_link_clicks,
            "total_shares": total_shares,
            "er": (total_rcs / total_reach * 100) if total_reach else 0,
            "organic_ctr": (total_link_clicks / total_reach * 100) if total_reach else 0,
            "share_rate": (total_shares / total_reach * 100) if total_reach else 0,
        }

    return {
        "khoa": khoa_data,
        "total_in_scope": len(in_scope),
        "total_out_of_scope": len(df) - len(in_scope),
    }
